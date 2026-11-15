import base64
import json
import threading
from contextlib import closing
from datetime import datetime, timezone

from flask import Flask, jsonify, request
from werkzeug.exceptions import RequestEntityTooLarge

from config import (
    CAMERA_ID,
    CHANGE_CONFIRMATION_FRAMES,
    DATABASE_PATH,
    MAX_IMAGE_BYTES,
    OBJECT_COOLDOWN_SECONDS,
)
from database.connection import connect_database, initialize_database
from database.queries import read_recent_events
from services.camera_validation import camera_view_status
from services.change_detection import compare_detections, event_message, event_response
from services.image_processing import image_from_payload
from services.yolo_service import detections_from_model, get_or_load_detector
from utils.formatting import room_key

from routes.health_routes import health_bp
from routes.room_routes import room_bp
from routes.baseline_routes import baseline_bp
from routes.monitoring_routes import monitoring_bp
from routes.alert_routes import alert_bp
from routes.object_finder_routes import object_finder_bp


def create_app(database_path=DATABASE_PATH, detector=None):
    app = Flask(__name__)
    app.config["DATABASE_PATH"] = str(database_path)
    app.config["DETECTOR"] = detector
    app.config["DETECTOR_LOCK"] = threading.Lock()
    app.config["MONITOR_LOCK"] = threading.Lock()
    app.config["TRACKERS"] = {}
    app.config["MAX_CONTENT_LENGTH"] = MAX_IMAGE_BYTES * 2
    initialize_database(app.config["DATABASE_PATH"])

    # Enable INFO-level logging so YOLO detection debug lines appear in the console
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Register blueprints
    app.register_blueprint(health_bp)
    app.register_blueprint(room_bp)
    app.register_blueprint(baseline_bp)
    app.register_blueprint(monitoring_bp)
    app.register_blueprint(alert_bp)
    app.register_blueprint(object_finder_bp)

    @app.errorhandler(RequestEntityTooLarge)
    def request_too_large(_error):
        return jsonify({"error": "The camera image request is too large."}), 413

    # /api/observe is kept here so that patch("server.camera_view_status") in
    # test_server.py correctly intercepts the call made by this route.
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
                model = get_or_load_detector()
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

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
