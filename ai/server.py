import base64
import binascii
import json
import math
import re
import sqlite3
import threading
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
from flask import Flask, jsonify, request
from werkzeug.exceptions import RequestEntityTooLarge


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = PROJECT_ROOT / "yolo11n.pt"
DATABASE_PATH = Path(__file__).resolve().parent / "instance" / "home_layout.sqlite3"
CAMERA_ID = "default-webcam"
MAX_IMAGE_BYTES = 8 * 1024 * 1024
CONFIDENCE_THRESHOLD = 0.5
CHANGE_CONFIRMATION_FRAMES = 3
MOVE_DISTANCE_THRESHOLD = 0.14
OBJECT_COOLDOWN_SECONDS = 60
MONITORED_CLASSES = {
    "backpack",
    "bottle",
    "chair",
    "couch",
    "dining table",
    "handbag",
    "suitcase",
}
SUPPORTED_CLASSES = {
    "backpack",
    "bed",
    "bottle",
    "bowl",
    "book",
    "chair",
    "clock",
    "couch",
    "cup",
    "dining table",
    "hair drier",
    "handbag",
    "keyboard",
    "laptop",
    "microwave",
    "mouse",
    "oven",
    "potted plant",
    "refrigerator",
    "remote",
    "scissors",
    "sink",
    "suitcase",
    "toaster",
    "toothbrush",
    "tv",
    "vase",
}


def connect_database(database_path):
    connection = sqlite3.connect(database_path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database(database_path):
    Path(database_path).parent.mkdir(parents=True, exist_ok=True)
    with closing(connect_database(database_path)) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_key TEXT NOT NULL,
                room_name TEXT NOT NULL,
                camera_id TEXT NOT NULL,
                captured_at TEXT NOT NULL,
                image BLOB NOT NULL,
                image_width INTEGER NOT NULL,
                image_height INTEGER NOT NULL,
                is_baseline INTEGER NOT NULL DEFAULT 1
            );
            CREATE UNIQUE INDEX IF NOT EXISTS one_baseline_per_room_camera
                ON observations (room_key, camera_id)
                WHERE is_baseline = 1;
            CREATE TABLE IF NOT EXISTS detections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                observation_id INTEGER NOT NULL
                    REFERENCES observations(id) ON DELETE CASCADE,
                class_name TEXT NOT NULL,
                instance_number INTEGER NOT NULL,
                confidence REAL NOT NULL,
                center_x REAL NOT NULL,
                center_y REAL NOT NULL,
                x1 REAL NOT NULL,
                y1 REAL NOT NULL,
                x2 REAL NOT NULL,
                y2 REAL NOT NULL,
                zone TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS latest_observations (
                room_key TEXT PRIMARY KEY,
                room_name TEXT NOT NULL,
                camera_id TEXT NOT NULL,
                captured_at TEXT NOT NULL,
                image BLOB NOT NULL,
                image_width INTEGER NOT NULL,
                image_height INTEGER NOT NULL,
                detections_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS change_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_key TEXT NOT NULL,
                baseline_id INTEGER NOT NULL REFERENCES observations(id),
                event_signature TEXT NOT NULL,
                class_name TEXT NOT NULL,
                change_type TEXT NOT NULL,
                original_zone TEXT,
                current_zone TEXT,
                confidence REAL NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL,
                speech_status TEXT NOT NULL DEFAULT 'pending',
                speech_error TEXT
            );
            CREATE INDEX IF NOT EXISTS change_events_by_room
                ON change_events (room_key, created_at DESC);
            CREATE TABLE IF NOT EXISTS room_monitor_status (
                room_key TEXT PRIMARY KEY,
                camera_id TEXT NOT NULL,
                view_status TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )


def room_key(room_name):
    return room_name.strip().casefold()


def image_zone(center_x, center_y):
    horizontal = "left" if center_x < 1 / 3 else "right" if center_x >= 2 / 3 else "center"
    vertical = "upper" if center_y < 1 / 3 else "lower" if center_y >= 2 / 3 else "middle"
    return f"{vertical}-{horizontal}"


def zone_label(zone):
    return zone.replace("-", " ")


def camera_view_status(reference_bytes, current_frame):
    reference_frame = cv2.imdecode(
        np.frombuffer(reference_bytes, dtype=np.uint8), cv2.IMREAD_GRAYSCALE
    )
    current_gray = cv2.cvtColor(current_frame, cv2.COLOR_BGR2GRAY)
    if reference_frame is None:
        return "unknown"
    reference_aspect = reference_frame.shape[1] / reference_frame.shape[0]
    current_aspect = current_gray.shape[1] / current_gray.shape[0]
    if abs(reference_aspect - current_aspect) > 0.01:
        return "unknown"
    reference_frame = cv2.resize(
        reference_frame, (current_gray.shape[1], current_gray.shape[0])
    )

    orb = cv2.ORB_create(nfeatures=1000, fastThreshold=12)
    reference_points, reference_descriptors = orb.detectAndCompute(
        reference_frame, None
    )
    current_points, current_descriptors = orb.detectAndCompute(current_gray, None)
    if (
        reference_descriptors is None
        or current_descriptors is None
        or len(reference_points) < 12
        or len(current_points) < 12
    ):
        return "unknown"

    matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
    matches = matcher.knnMatch(reference_descriptors, current_descriptors, k=2)
    good_matches = [
        best
        for pair in matches
        if len(pair) == 2
        for best, second in [pair]
        if best.distance < 0.75 * second.distance
    ]
    if len(good_matches) < 12:
        return "unknown"

    source_points = np.float32(
        [reference_points[match.queryIdx].pt for match in good_matches]
    )
    target_points = np.float32(
        [current_points[match.trainIdx].pt for match in good_matches]
    )
    transform, inlier_mask = cv2.estimateAffinePartial2D(
        source_points,
        target_points,
        method=cv2.RANSAC,
        ransacReprojThreshold=3.0,
        maxIters=2000,
        confidence=0.99,
    )
    if transform is None or inlier_mask is None:
        return "unknown"
    inlier_ratio = float(inlier_mask.mean())
    if inlier_ratio < 0.35:
        return "unknown"

    scale = math.hypot(transform[0, 0], transform[1, 0])
    rotation = abs(math.degrees(math.atan2(transform[1, 0], transform[0, 0])))
    width, height = reference_frame.shape[1], reference_frame.shape[0]
    moved = (
        abs(transform[0, 2]) > width * 0.04
        or abs(transform[1, 2]) > height * 0.04
        or rotation > 3
        or abs(scale - 1) > 0.05
    )
    return "moved" if moved else "stable"


def compare_detections(baseline, current):
    candidates = []
    classes = {
        item["class_name"]
        for item in baseline + current
        if item["class_name"] in MONITORED_CLASSES
    }

    for name in classes:
        matched_baseline = set()
        matched_current = set()
        original = sorted(
            (item for item in baseline if item["class_name"] == name),
            key=lambda item: item["instance_number"],
        )
        observed = sorted(
            (item for item in current if item["class_name"] == name),
            key=lambda item: (item["center_y"], item["center_x"]),
        )
        distances = sorted(
            (
                math.hypot(
                    old["center_x"] - new["center_x"],
                    old["center_y"] - new["center_y"],
                ),
                old_index,
                new_index,
            )
            for old_index, old in enumerate(original)
            for new_index, new in enumerate(observed)
        )
        pairs = []
        for distance, old_index, new_index in distances:
            if old_index in matched_baseline or new_index in matched_current:
                continue
            if distance <= MOVE_DISTANCE_THRESHOLD:
                matched_baseline.add(old_index)
                matched_current.add(new_index)
                pairs.append((old_index, new_index, distance))

        remaining_original = [
            index for index in range(len(original)) if index not in matched_baseline
        ]
        remaining_observed = [
            index for index in range(len(observed)) if index not in matched_current
        ]
        remaining_pairs = sorted(
            (
                math.hypot(
                    original[old_index]["center_x"] - observed[new_index]["center_x"],
                    original[old_index]["center_y"] - observed[new_index]["center_y"],
                ),
                old_index,
                new_index,
            )
            for old_index in remaining_original
            for new_index in remaining_observed
        )
        for distance, old_index, new_index in remaining_pairs:
            if old_index in matched_baseline or new_index in matched_current:
                continue
            matched_baseline.add(old_index)
            matched_current.add(new_index)
            pairs.append((old_index, new_index, distance))

        for old_index, new_index, distance in pairs:
            old = original[old_index]
            new = observed[new_index]
            if distance <= MOVE_DISTANCE_THRESHOLD:
                continue
            x_bucket = round(new["center_x"] * 10)
            y_bucket = round(new["center_y"] * 10)
            key = (
                f"moved:{name}:{old['instance_number']}:{new['zone']}:"
                f"{x_bucket}:{y_bucket}"
            )
            candidates.append(
                {
                    "key": key,
                    "class_name": name,
                    "change_type": "moved",
                    "original_zone": old["zone"],
                    "current_zone": new["zone"],
                    "confidence": min(old["confidence"], new["confidence"]),
                }
            )

        for index, old in enumerate(original):
            if index in matched_baseline:
                continue
            instance = old["instance_number"]
            key = f"missing:{name}:{instance}"
            candidates.append(
                {
                    "key": key,
                    "class_name": name,
                    "change_type": "not_currently_visible",
                    "original_zone": old["zone"],
                    "current_zone": None,
                    "confidence": old["confidence"],
                }
            )
        new_counts = {}
        for index, new in enumerate(observed):
            if index in matched_current:
                continue
            zone = new["zone"]
            new_counts[zone] = new_counts.get(zone, 0) + 1
            instance = new_counts[zone]
            x_bucket = round(new["center_x"] * 10)
            y_bucket = round(new["center_y"] * 10)
            key = f"new:{name}:{zone}:{instance}:{x_bucket}:{y_bucket}"
            candidates.append(
                {
                    "key": key,
                    "class_name": name,
                    "change_type": "newly_observed",
                    "original_zone": None,
                    "current_zone": zone,
                    "confidence": new["confidence"],
                }
            )

    return candidates


def event_message(candidate):
    name = candidate["class_name"]
    change_type = candidate["change_type"]
    if change_type == "moved":
        original_zone = zone_label(candidate["original_zone"])
        current_zone = zone_label(candidate["current_zone"])
        if original_zone == current_zone:
            message = (
                f"A {name} appears to have shifted within the {current_zone} "
                "of the camera view."
            )
        else:
            message = (
                f"A {name} appears to have moved from {original_zone} to "
                f"{current_zone} in the camera view."
            )
        if candidate["current_zone"].startswith("lower-center") and name in {
            "chair",
            "dining table",
            "suitcase",
            "backpack",
            "handbag",
        }:
            message += (
                " It may be an obstacle. Please proceed carefully; the camera "
                "cannot confirm that a walkway is blocked."
            )
        return message
    if change_type == "not_currently_visible":
        return (
            f"The {name} usually seen in the "
            f"{zone_label(candidate['original_zone'])} is not currently visible. "
            "This does not confirm it was removed."
        )

    current_zone = zone_label(candidate["current_zone"])
    if candidate["current_zone"].startswith("lower-center") and name in {
        "chair",
        "dining table",
        "suitcase",
        "backpack",
        "handbag",
    }:
        return (
            f"A newly detected {name} is in the {current_zone} of the camera view. "
            "It may be an obstacle. Please proceed carefully; the camera cannot "
            "confirm that a walkway is blocked."
        )
    return f"A new {name} is visible in the {current_zone} of the camera view."


def event_response(event):
    return {
        "id": event["id"],
        "object_name": event["class_name"],
        "change_type": event["change_type"],
        "original_zone": event["original_zone"],
        "current_zone": event["current_zone"],
        "confidence": (
            None if event["change_type"].startswith("camera_view_") else event["confidence"]
        ),
        "message": event["message"],
        "created_at": event["created_at"],
        "speech_status": event["speech_status"],
        "speech_error": event["speech_error"],
    }


def read_recent_events(connection, room_name, limit=50):
    rows = connection.execute(
        """
        SELECT id, class_name, change_type, original_zone, current_zone,
               confidence, message, created_at, speech_status, speech_error
        FROM change_events
        WHERE room_key = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (room_key(room_name), limit),
    ).fetchall()
    return [event_response(row) for row in rows]


def find_target_classes(query):
    normalized = re.sub(r"[^a-z0-9 ]", " ", query.lower())
    normalized = re.sub(
        r"^(where is|where are|where s|can you find|please find|find|locate|look for|search for)\s+",
        "",
        normalized.strip(),
    )
    normalized = re.sub(r"^(my|the|a|an)\s+", "", normalized).strip()
    aliases = {
        "bag": {"backpack", "handbag", "suitcase"},
        "handbag": {"handbag", "backpack"},
        "sofa": {"couch"},
        "couch": {"couch"},
        "table": {"dining table"},
        "water bottle": {"bottle"},
        "bottle": {"bottle"},
        "chair": {"chair"},
        "backpack": {"backpack"},
        "suitcase": {"suitcase"},
    }
    if normalized in aliases:
        return normalized, aliases[normalized]
    if normalized in SUPPORTED_CLASSES:
        return normalized, {normalized}
    return normalized, set()


def image_from_payload(payload):
    if not isinstance(payload, dict):
        raise ValueError("Send a JSON object with room_name and image fields.")

    image_data = payload.get("image")
    if not isinstance(image_data, str) or not image_data.startswith("data:image/jpeg;base64,"):
        raise ValueError("The camera image must be a base64-encoded JPEG.")

    encoded_image = image_data.partition(",")[2]
    try:
        image_bytes = base64.b64decode(encoded_image, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ValueError("The camera image is not valid base64 data.") from error

    if not image_bytes or len(image_bytes) > MAX_IMAGE_BYTES:
        raise ValueError("The camera image must be smaller than 8 MB.")

    frame = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError("The uploaded JPEG could not be decoded.")

    height, width = frame.shape[:2]
    if width > 4096 or height > 4096:
        raise ValueError("The camera image dimensions must not exceed 4096 by 4096.")

    return image_bytes, frame, width, height


def detections_from_model(model, frame, width, height):
    results = model(frame, conf=CONFIDENCE_THRESHOLD, verbose=False)
    objects = []

    for result in results:
        for box in result.boxes:
            class_id = int(box.cls[0])
            object_name = model.names[class_id].strip().lower()
            if object_name not in SUPPORTED_CLASSES:
                continue

            x1, y1, x2, y2 = (float(value) for value in box.xyxy[0])
            center_x = min(1.0, max(0.0, ((x1 + x2) / 2) / width))
            center_y = min(1.0, max(0.0, ((y1 + y2) / 2) / height))
            objects.append(
                {
                    "class_name": object_name,
                    "confidence": float(box.conf[0]),
                    "center_x": center_x,
                    "center_y": center_y,
                    "x1": min(1.0, max(0.0, x1 / width)),
                    "y1": min(1.0, max(0.0, y1 / height)),
                    "x2": min(1.0, max(0.0, x2 / width)),
                    "y2": min(1.0, max(0.0, y2 / height)),
                    "zone": image_zone(center_x, center_y),
                }
            )

    objects.sort(
        key=lambda item: (
            item["class_name"],
            item["center_y"],
            item["center_x"],
        )
    )
    instance_counts = {}
    for item in objects:
        name = item["class_name"]
        instance_counts[name] = instance_counts.get(name, 0) + 1
        item["instance_number"] = instance_counts[name]

    return objects


def baseline_response(connection, observation):
    detections = connection.execute(
        """
        SELECT class_name, instance_number, confidence, center_x, center_y,
               x1, y1, x2, y2, zone
        FROM detections
        WHERE observation_id = ?
        ORDER BY class_name, instance_number
        """,
        (observation["id"],),
    ).fetchall()
    image_data = base64.b64encode(observation["image"]).decode("ascii")

    return {
        "id": observation["id"],
        "room_name": observation["room_name"],
        "camera_id": observation["camera_id"],
        "captured_at": observation["captured_at"],
        "image_width": observation["image_width"],
        "image_height": observation["image_height"],
        "image_data_url": f"data:image/jpeg;base64,{image_data}",
        "detections": [dict(detection) for detection in detections],
    }


def create_app(database_path=DATABASE_PATH, detector=None):
    app = Flask(__name__)
    app.config["DATABASE_PATH"] = str(database_path)
    app.config["DETECTOR"] = detector
    app.config["DETECTOR_LOCK"] = threading.Lock()
    app.config["MONITOR_LOCK"] = threading.Lock()
    app.config["TRACKERS"] = {}
    app.config["MAX_CONTENT_LENGTH"] = MAX_IMAGE_BYTES * 2
    initialize_database(app.config["DATABASE_PATH"])

    def get_detector():
        if app.config["DETECTOR"] is not None:
            return app.config["DETECTOR"]

        if not MODEL_PATH.is_file():
            raise RuntimeError(f"YOLO model weights not found: {MODEL_PATH}")

        from ultralytics import YOLO

        app.config["DETECTOR"] = YOLO(str(MODEL_PATH))
        return app.config["DETECTOR"]

    @app.get("/api/health")
    def health():
        return jsonify(
            {
                "status": "ok",
                "model_available": app.config["DETECTOR"] is not None
                or MODEL_PATH.is_file(),
            }
        )

    @app.errorhandler(RequestEntityTooLarge)
    def request_too_large(_error):
        return jsonify({"error": "The camera image request is too large."}), 413

    @app.get("/api/baseline")
    def get_baseline():
        name = request.args.get("room_name", "Living room").strip()
        if not name or len(name) > 80:
            return jsonify({"error": "Room name must contain 1 to 80 characters."}), 400

        with closing(connect_database(app.config["DATABASE_PATH"])) as connection:
            observation = connection.execute(
                """
                SELECT * FROM observations
                WHERE room_key = ? AND camera_id = ? AND is_baseline = 1
                """,
                (room_key(name), CAMERA_ID),
            ).fetchone()
            baseline = (
                baseline_response(connection, observation) if observation else None
            )

        return jsonify({"baseline": baseline})

    @app.get("/api/latest")
    def get_latest():
        name = request.args.get("room_name", "Living room").strip()
        if not name or len(name) > 80:
            return jsonify({"error": "Room name must contain 1 to 80 characters."}), 400
        with closing(connect_database(app.config["DATABASE_PATH"])) as connection:
            row = connection.execute(
                "SELECT * FROM latest_observations WHERE room_key = ?",
                (room_key(name),),
            ).fetchone()
            latest = None
            if row:
                latest = {
                    "room_name": row["room_name"],
                    "camera_id": row["camera_id"],
                    "captured_at": row["captured_at"],
                    "image_data_url": "data:image/jpeg;base64,"
                    + base64.b64encode(row["image"]).decode("ascii"),
                    "detections": json.loads(row["detections_json"]),
                }
            status_row = connection.execute(
                "SELECT view_status FROM room_monitor_status WHERE room_key = ?",
                (room_key(name),),
            ).fetchone()
            history = read_recent_events(connection, name)
        return jsonify(
            {
                "latest": latest,
                "view_status": status_row["view_status"] if status_row else "unknown",
                "history": history,
            }
        )

    @app.get("/api/alerts")
    def get_alerts():
        name = request.args.get("room_name", "Living room").strip()
        if not name or len(name) > 80:
            return jsonify({"error": "Room name must contain 1 to 80 characters."}), 400
        with closing(connect_database(app.config["DATABASE_PATH"])) as connection:
            history = read_recent_events(connection, name)
        return jsonify({"history": history})

    @app.get("/api/find")
    def find_object():
        name = request.args.get("room_name", "Living room").strip()
        query = request.args.get("object_name", "").strip()
        if not name or len(name) > 80:
            return jsonify({"error": "Room name must contain 1 to 80 characters."}), 400
        if not query or len(query) > 80:
            return jsonify({"error": "Say or enter the name of an object to find."}), 400
        normalized, target_classes = find_target_classes(query)
        if not target_classes:
            return jsonify(
                {
                    "error": f"'{normalized}' is not a supported YOLO household-object label or alias."
                }
            ), 400

        with closing(connect_database(app.config["DATABASE_PATH"])) as connection:
            status_row = connection.execute(
                "SELECT view_status FROM room_monitor_status WHERE room_key = ?",
                (room_key(name),),
            ).fetchone()
            view_status = status_row["view_status"] if status_row else "unknown"
            latest = connection.execute(
                "SELECT captured_at, detections_json FROM latest_observations WHERE room_key = ?",
                (room_key(name),),
            ).fetchone()
            baseline = connection.execute(
                """
                SELECT id, captured_at FROM observations
                WHERE room_key = ? AND camera_id = ? AND is_baseline = 1
                """,
                (room_key(name), CAMERA_ID),
            ).fetchone()
            current_matches = []
            if latest and view_status == "stable":
                current_matches = [
                    item
                    for item in json.loads(latest["detections_json"])
                    if item["class_name"] in target_classes
                ]
            baseline_matches = []
            if baseline:
                class_placeholders = ", ".join(
                    "?" for _ in target_classes
                )
                baseline_matches = connection.execute(
                    f"""
                    SELECT class_name, instance_number, zone, confidence
                    FROM detections
                    WHERE observation_id = ? AND class_name IN ({class_placeholders})
                    ORDER BY class_name, instance_number
                    """,
                    (baseline["id"], *sorted(target_classes)),
                ).fetchall()

        if status_row and view_status != "stable":
            message = (
                "The camera view cannot currently be verified, so I cannot give "
                "a current location. Please restore the learned camera position "
                "and scan again."
            )
            return jsonify(
                {
                    "found": False,
                    "status": "view_unverified",
                    "message": message,
                }
            )
        if current_matches:
            item = max(current_matches, key=lambda detection: detection["confidence"])
            message = (
                f"The latest reliable scan saw your {normalized} in the "
                f"{zone_label(item['zone'])} of this camera view at "
                f"{datetime.fromisoformat(latest['captured_at'].replace('Z', '+00:00')).astimezone().strftime('%I:%M %p')}."
            )
            return jsonify(
                {
                    "found": True,
                    "status": "latest_observation",
                    "message": message,
                    "object": item,
                    "captured_at": latest["captured_at"],
                }
            )
        if baseline_matches:
            item = baseline_matches[0]
            message = (
                f"I last recorded your {normalized} in the "
                f"{zone_label(item['zone'])} of the original room layout. "
                "This is not a current sighting."
            )
            return jsonify(
                {
                    "found": False,
                    "status": "baseline_only",
                    "message": message,
                    "object": dict(item),
                    "captured_at": baseline["captured_at"],
                }
            )
        message = f"I could not find a {normalized} in the latest reliable scan or saved room layout."
        return jsonify({"found": False, "status": "not_found", "message": message})

    @app.post("/api/observe")
    def observe_room():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"error": "Send a JSON object with room_name and image fields."}), 400
        name = payload.get("room_name")
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 80:
            return jsonify({"error": "Room name must contain 1 to 80 characters."}), 400
        name = name.strip()
        try:
            image_bytes, frame, width, height = image_from_payload(payload)
        except ValueError as error:
            return jsonify({"error": str(error)}), 400

        try:
            with app.config["DETECTOR_LOCK"]:
                model = get_detector()
                observed = detections_from_model(model, frame, width, height)
        except Exception as error:
            app.logger.exception("Could not run local YOLO inference")
            return jsonify({"error": f"YOLO could not process the image: {error}"}), 503

        captured_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
            "+00:00", "Z"
        )
        with app.config["MONITOR_LOCK"]:
            with closing(connect_database(app.config["DATABASE_PATH"])) as connection:
                baseline = connection.execute(
                    """
                    SELECT * FROM observations
                    WHERE room_key = ? AND camera_id = ? AND is_baseline = 1
                    """,
                    (room_key(name), CAMERA_ID),
                ).fetchone()
                if baseline is None:
                    return jsonify(
                        {
                            "error": "Learn this room's home layout before starting monitoring."
                        }
                    ), 409

                view_status = camera_view_status(baseline["image"], frame)
                previous_status = connection.execute(
                    "SELECT view_status FROM room_monitor_status WHERE room_key = ?",
                    (room_key(name),),
                ).fetchone()
                connection.execute(
                    """
                    INSERT INTO room_monitor_status (
                        room_key, camera_id, view_status, updated_at
                    ) VALUES (?, ?, ?, ?)
                    ON CONFLICT(room_key) DO UPDATE SET
                        camera_id = excluded.camera_id,
                        view_status = excluded.view_status,
                        updated_at = excluded.updated_at
                    """,
                    (room_key(name), CAMERA_ID, view_status, captured_at),
                )
                camera_event = None
                previous_view_status = (
                    previous_status["view_status"] if previous_status else None
                )
                camera_message = None
                camera_change_type = None
                if view_status == "moved" and previous_view_status != "moved":
                    camera_change_type = "camera_view_changed"
                    camera_message = (
                        "The camera view has changed. Room change alerts are paused "
                        "until the saved viewpoint is restored or the room is explicitly relearned."
                    )
                elif view_status == "unknown" and previous_view_status != "unknown":
                    camera_change_type = "camera_view_unverified"
                    camera_message = (
                        "The camera view cannot be verified. Room change alerts are "
                        "paused to avoid unverified announcements."
                    )
                elif (
                    view_status == "stable"
                    and previous_view_status in {"moved", "unknown"}
                ):
                    camera_change_type = "camera_view_restored"
                    camera_message = (
                        "The saved camera view is restored. Room monitoring has resumed."
                    )

                if camera_message:
                    camera_cursor = connection.execute(
                        """
                        INSERT INTO change_events (
                            room_key, baseline_id, event_signature, class_name,
                            change_type, original_zone, current_zone, confidence,
                            message, created_at
                        ) VALUES (?, ?, ?, 'camera', ?, NULL, NULL, 1.0, ?, ?)
                        """,
                        (
                            room_key(name),
                            baseline["id"],
                            f"camera:{camera_change_type}:{captured_at}",
                            camera_change_type,
                            camera_message,
                            captured_at,
                        ),
                    )
                    camera_event = connection.execute(
                        """
                        SELECT id, class_name, change_type, original_zone,
                               current_zone, confidence, message, created_at,
                               speech_status, speech_error
                        FROM change_events WHERE id = ?
                        """,
                        (camera_cursor.lastrowid,),
                    ).fetchone()
                connection.commit()
                tracker_key = (room_key(name), baseline["id"])
                tracker = app.config["TRACKERS"].setdefault(
                    tracker_key, {"counts": {}, "announced": set()}
                )
                emitted_events = (
                    [event_response(camera_event)] if camera_event is not None else []
                )

                if view_status != "stable":
                    tracker["counts"].clear()
                    response_status = (
                        "camera_moved" if view_status == "moved" else "view_unverified"
                    )
                    latest = None
                else:
                    baseline_detections = connection.execute(
                        """
                        SELECT class_name, instance_number, confidence, center_x,
                               center_y, x1, y1, x2, y2, zone
                        FROM detections
                        WHERE observation_id = ?
                        ORDER BY class_name, instance_number
                        """,
                        (baseline["id"],),
                    ).fetchall()
                    baseline_items = [dict(item) for item in baseline_detections]
                    candidates = compare_detections(baseline_items, observed)
                    active_candidates = {candidate["key"] for candidate in candidates}
                    for old_key in set(tracker["counts"]) - active_candidates:
                        tracker["counts"].pop(old_key, None)
                    tracker["announced"].intersection_update(active_candidates)

                    for candidate in candidates:
                        key = candidate["key"]
                        tracker["counts"][key] = tracker["counts"].get(key, 0) + 1
                        if (
                            tracker["counts"][key] < CHANGE_CONFIRMATION_FRAMES
                            or key in tracker["announced"]
                        ):
                            continue

                        tracker["announced"].add(key)
                        previous = connection.execute(
                            """
                            SELECT created_at FROM change_events
                            WHERE room_key = ? AND baseline_id = ?
                                AND event_signature = ?
                            ORDER BY id DESC LIMIT 1
                            """,
                            (room_key(name), baseline["id"], key),
                        ).fetchone()
                        if previous:
                            previous_time = datetime.fromisoformat(
                                previous["created_at"].replace("Z", "+00:00")
                            )
                            age = (
                                datetime.now(timezone.utc) - previous_time
                            ).total_seconds()
                            if age < OBJECT_COOLDOWN_SECONDS:
                                continue

                        message = event_message(candidate)
                        cursor = connection.execute(
                            """
                            INSERT INTO change_events (
                                room_key, baseline_id, event_signature, class_name,
                                change_type, original_zone, current_zone, confidence,
                                message, created_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                room_key(name),
                                baseline["id"],
                                key,
                                candidate["class_name"],
                                candidate["change_type"],
                                candidate["original_zone"],
                                candidate["current_zone"],
                                candidate["confidence"],
                                message,
                                captured_at,
                            ),
                        )
                        event = connection.execute(
                            """
                            SELECT id, class_name, change_type, original_zone,
                                   current_zone, confidence, message, created_at,
                                   speech_status, speech_error
                            FROM change_events WHERE id = ?
                            """,
                            (cursor.lastrowid,),
                        ).fetchone()
                        emitted_events.append(event_response(event))

                    connection.execute(
                        """
                        INSERT INTO latest_observations (
                            room_key, room_name, camera_id, captured_at, image,
                            image_width, image_height, detections_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(room_key) DO UPDATE SET
                            room_name = excluded.room_name,
                            camera_id = excluded.camera_id,
                            captured_at = excluded.captured_at,
                            image = excluded.image,
                            image_width = excluded.image_width,
                            image_height = excluded.image_height,
                            detections_json = excluded.detections_json
                        """,
                        (
                            room_key(name),
                            name,
                            CAMERA_ID,
                            captured_at,
                            image_bytes,
                            width,
                            height,
                            json.dumps(observed),
                        ),
                    )
                    latest = {
                        "captured_at": captured_at,
                        "detections": observed,
                    }
                    response_status = "monitoring"
                    connection.commit()

                history = read_recent_events(connection, name)

        return jsonify(
            {
                "status": response_status,
                "latest": latest,
                "alerts": emitted_events,
                "history": history,
                "confirmed_after_frames": CHANGE_CONFIRMATION_FRAMES,
            }
        )

    @app.post("/api/alerts/<int:event_id>/playback")
    def record_playback(event_id):
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"error": "Send a JSON object with a playback status."}), 400
        status = payload.get("status")
        if status not in {"spoken", "failed", "unavailable"}:
            return jsonify(
                {"error": "Playback status must be spoken, failed, or unavailable."}
            ), 400
        error_message = payload.get("error")
        if error_message is not None and not isinstance(error_message, str):
            return jsonify({"error": "Playback error must be text."}), 400
        with closing(connect_database(app.config["DATABASE_PATH"])) as connection:
            cursor = connection.execute(
                """
                UPDATE change_events SET speech_status = ?, speech_error = ?
                WHERE id = ?
                """,
                (status, error_message[:200] if error_message else None, event_id),
            )
            if not cursor.rowcount:
                return jsonify({"error": "Alert history entry was not found."}), 404
            connection.commit()
        return jsonify({"status": status})

    @app.post("/api/baseline")
    def save_baseline():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"error": "Send a JSON object with room_name and image fields."}), 400

        name = payload.get("room_name")
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 80:
            return jsonify({"error": "Room name must contain 1 to 80 characters."}), 400
        name = name.strip()

        if not isinstance(payload.get("replace", False), bool):
            return jsonify({"error": "The replace field must be true or false."}), 400

        try:
            image_bytes, frame, width, height = image_from_payload(payload)
        except ValueError as error:
            return jsonify({"error": str(error)}), 400

        try:
            with app.config["DETECTOR_LOCK"]:
                model = get_detector()
                objects = detections_from_model(model, frame, width, height)
        except Exception as error:
            app.logger.exception("Could not run local YOLO inference")
            return jsonify({"error": f"YOLO could not process the image: {error}"}), 503

        captured_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
            "+00:00", "Z"
        )
        connection = connect_database(app.config["DATABASE_PATH"])
        try:
            connection.execute("BEGIN IMMEDIATE")
            previous = connection.execute(
                """
                SELECT id FROM observations
                WHERE room_key = ? AND camera_id = ? AND is_baseline = 1
                """,
                (room_key(name), CAMERA_ID),
            ).fetchone()
            if previous and not payload.get("replace", False):
                connection.rollback()
                return (
                    jsonify(
                        {
                            "error": "A baseline already exists for this room. Review it and explicitly confirm replacement."
                        }
                    ),
                    409,
                )

            if previous:
                connection.execute(
                    "UPDATE observations SET is_baseline = 0 WHERE id = ?",
                    (previous["id"],),
                )

            cursor = connection.execute(
                """
                INSERT INTO observations (
                    room_key, room_name, camera_id, captured_at, image,
                    image_width, image_height, is_baseline
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    room_key(name),
                    name,
                    CAMERA_ID,
                    captured_at,
                    image_bytes,
                    width,
                    height,
                ),
            )
            observation_id = cursor.lastrowid
            connection.executemany(
                """
                INSERT INTO detections (
                    observation_id, class_name, instance_number, confidence,
                    center_x, center_y, x1, y1, x2, y2, zone
                ) VALUES (
                    :observation_id, :class_name, :instance_number, :confidence,
                    :center_x, :center_y, :x1, :y1, :x2, :y2, :zone
                )
                """,
                [
                    {"observation_id": observation_id, **item}
                    for item in objects
                ],
            )
            observation = connection.execute(
                "SELECT * FROM observations WHERE id = ?", (observation_id,)
            ).fetchone()
            response = baseline_response(connection, observation)
            connection.commit()
        except sqlite3.Error as error:
            connection.rollback()
            app.logger.exception("Could not save the room baseline")
            return jsonify({"error": f"Could not save the room baseline: {error}"}), 500
        finally:
            connection.close()

        return jsonify({"baseline": response}), 201

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
