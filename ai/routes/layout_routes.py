import re
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime, timezone

import cv2
import numpy as np
from flask import Blueprint, current_app, jsonify, request

from config import CAMERA_ID
from database.connection import connect_database
from database.queries import baseline_response
from services.camera_validation import (
    align_frames_if_needed,
    camera_view_status,
    validate_camera_view,
)
from services.change_detection import categorize_room_comparison
from services.image_processing import image_from_payload
from services.open_vocabulary_service import (
    get_open_vocabulary_detector,
    hybrid_detections,
)
from services.yolo_service import detections_from_model, get_or_load_detector
from utils.formatting import room_key


layout_bp = Blueprint("layouts", __name__)


@contextmanager
def _monitor_transaction(connection):
    with current_app.config["MONITOR_LOCK"]:
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield
        finally:
            if connection.in_transaction:
                connection.rollback()


def _scope(room_name, camera_id):
    if not isinstance(room_name, str) or not room_name.strip() or len(room_name.strip()) > 80:
        return None, (jsonify({"error": "Room name must contain 1 to 80 characters."}), 400)
    if not isinstance(camera_id, str) or not camera_id.strip():
        return None, (jsonify({"error": "A camera_id is required."}), 400)
    if camera_id.strip() != CAMERA_ID:
        return None, (jsonify({"error": "The camera_id is not configured for this service."}), 400)
    name = room_name.strip()
    return (name, room_key(name), CAMERA_ID), None


def _positive_id(raw_id):
    if not isinstance(raw_id, str) or re.fullmatch(r"[0-9]+", raw_id) is None:
        return None
    value = int(raw_id)
    return value if value > 0 else None


def _payload_positive_id(raw_id):
    if isinstance(raw_id, bool):
        return None
    if isinstance(raw_id, int):
        return raw_id if raw_id > 0 else None
    if isinstance(raw_id, str):
        return _positive_id(raw_id)
    return None


def _history_schema_ready(connection):
    version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    columns = {
        row[1] for row in connection.execute("PRAGMA table_info('observations')")
    }
    indexes = {
        row[1]: row
        for row in connection.execute("PRAGMA index_list('observations')")
    }
    active_index = indexes.get("one_baseline_per_room_camera")
    return (
        version >= 1
        and {"layout_name", "deleted_at"}.issubset(columns)
        and active_index is not None
        and int(active_index[2]) == 1
        and int(active_index[4]) == 1
    )


def _migration_required():
    return jsonify(
        {"error": "Saved layout history is unavailable until database migration version 1 is applied."}
    ), 503


def _layout_response(connection, observation):
    response = baseline_response(connection, observation)
    response.update(
        {
            "layout_name": observation["layout_name"],
            "is_active": bool(observation["is_baseline"]),
            "deleted_at": observation["deleted_at"],
        }
    )
    return response


def _insert_detections(connection, observation_id, detections):
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
            {"observation_id": observation_id, **detection}
            for detection in detections
        ],
    )


def _mark_view_unknown(connection, scope, timestamp):
    _, scope_key, camera_id = scope
    connection.execute(
        """
        INSERT INTO room_monitor_status (
            room_key, camera_id, view_status, updated_at
        ) VALUES (?, ?, 'unknown', ?)
        ON CONFLICT(room_key) DO UPDATE SET
            camera_id = excluded.camera_id,
            view_status = excluded.view_status,
            updated_at = excluded.updated_at
        """,
        (scope_key, camera_id, timestamp),
    )


def _reset_room_trackers(scope_key):
    trackers = current_app.config["TRACKERS"]
    for tracker_key in list(trackers):
        if isinstance(tracker_key, tuple) and tracker_key and tracker_key[0] == scope_key:
            trackers.pop(tracker_key, None)


def _timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


@layout_bp.get("/api/layouts")
def list_layouts():
    scope, error_response = _scope(
        request.args.get("room_name"), request.args.get("camera_id")
    )
    if error_response:
        return error_response

    with closing(connect_database(current_app.config["DATABASE_PATH"])) as connection:
        if not _history_schema_ready(connection):
            return _migration_required()
        _, scope_key, camera_id = scope
        observations = connection.execute(
            """
            SELECT *
            FROM observations
            WHERE room_key = ? AND camera_id = ?
            ORDER BY captured_at DESC, id DESC
            """,
            (scope_key, camera_id),
        ).fetchall()
        layouts = [
            _layout_response(connection, observation)
            for observation in observations
        ]
    return jsonify({"layouts": layouts})


@layout_bp.post("/api/layouts")
def save_layout():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Send a JSON object with room_name, camera_id, layout_name, and image fields."}), 400

    scope, error_response = _scope(payload.get("room_name"), payload.get("camera_id"))
    if error_response:
        return error_response

    layout_name = payload.get("layout_name")
    if (
        not isinstance(layout_name, str)
        or not layout_name.strip()
        or len(layout_name.strip()) > 80
    ):
        return jsonify({"error": "Layout name must contain 1 to 80 characters."}), 400
    layout_name = layout_name.strip()
    activate = payload.get("activate", True)
    if not isinstance(activate, bool):
        return jsonify({"error": "activate must be a boolean."}), 400

    try:
        image_bytes, frame, width, height = image_from_payload(payload)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    try:
        with current_app.config["DETECTOR_LOCK"]:
            model = get_or_load_detector()
            detections = detections_from_model(model, frame, width, height)
    except Exception as error:
        current_app.logger.exception("Could not run local YOLO inference for saved layout")
        return jsonify({"error": f"YOLO could not process the image: {error}"}), 503

    captured_at = _timestamp()
    connection = connect_database(current_app.config["DATABASE_PATH"])
    scope_name, scope_key, camera_id = scope
    try:
        with _monitor_transaction(connection):
            if not _history_schema_ready(connection):
                connection.rollback()
                return _migration_required()

            if activate:
                connection.execute(
                    """
                    UPDATE observations
                    SET is_baseline = 0
                    WHERE room_key = ? AND camera_id = ? AND is_baseline = 1
                    """,
                    (scope_key, camera_id),
                )
            cursor = connection.execute(
                """
                INSERT INTO observations (
                    room_key, room_name, camera_id, captured_at, image,
                    image_width, image_height, is_baseline, layout_name
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    scope_key,
                    scope_name,
                    camera_id,
                    captured_at,
                    image_bytes,
                    width,
                    height,
                    int(activate),
                    layout_name,
                ),
            )
            _insert_detections(connection, cursor.lastrowid, detections)
            if activate:
                _mark_view_unknown(connection, scope, captured_at)
            observation = connection.execute(
                "SELECT * FROM observations WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
            response = _layout_response(connection, observation)
            connection.commit()
            if activate:
                _reset_room_trackers(scope_key)
    except sqlite3.Error as error:
        if connection.in_transaction:
            connection.rollback()
        current_app.logger.exception("Could not save room layout")
        return jsonify({"error": f"Could not save room layout: {error}"}), 500
    finally:
        if connection.in_transaction:
            connection.rollback()
        connection.close()

    return jsonify({"layout": response}), 201


@layout_bp.post("/api/layouts/compare")
def compare_saved_layouts():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Send a JSON object with room_name, camera_id, before_layout_id, and after_layout_id."}), 400

    scope, error_response = _scope(payload.get("room_name"), payload.get("camera_id"))
    if error_response:
        return error_response

    before_id = _payload_positive_id(payload.get("before_layout_id"))
    after_id = _payload_positive_id(payload.get("after_layout_id"))
    if before_id is None or after_id is None:
        return jsonify({"error": "Layout IDs must be positive integers."}), 400
    if before_id == after_id:
        return jsonify({"error": "Choose two different saved layouts to compare."}), 400

    _, scope_key, camera_id = scope
    with closing(connect_database(current_app.config["DATABASE_PATH"])) as connection:
        if not _history_schema_ready(connection):
            return _migration_required()
        before_observation = connection.execute(
            """
            SELECT *
            FROM observations
            WHERE id = ? AND room_key = ? AND camera_id = ?
            """,
            (before_id, scope_key, camera_id),
        ).fetchone()
        after_observation = connection.execute(
            """
            SELECT *
            FROM observations
            WHERE id = ? AND room_key = ? AND camera_id = ?
            """,
            (after_id, scope_key, camera_id),
        ).fetchone()
        if before_observation is None or after_observation is None:
            return jsonify({"error": "Both layouts must belong to this room and camera."}), 404
        if before_observation["deleted_at"] is not None or after_observation["deleted_at"] is not None:
            return jsonify({"error": "Deleted layouts cannot be compared."}), 409

        before_layout = _layout_response(connection, before_observation)
        after_layout = _layout_response(connection, after_observation)

    status = "uncertain"
    comparison_diff = None
    try:
        before_frame = cv2.imdecode(
            np.frombuffer(before_observation["image"], dtype=np.uint8),
            cv2.IMREAD_COLOR,
        )
        after_frame = cv2.imdecode(
            np.frombuffer(after_observation["image"], dtype=np.uint8),
            cv2.IMREAD_COLOR,
        )

        view_status = camera_view_status(before_observation["image"], after_frame)

        if after_frame is not None and view_status == "stable":
            view_analysis = validate_camera_view(
                before_observation["image"], after_frame
            )
            aligned_after = align_frames_if_needed(
                before_frame, after_frame, view_analysis.get("transform")
            )

            # Check if production detector is available to refresh detections
            detector = current_app.config.get("DETECTOR")
            if detector is None:
                try:
                    detector = get_or_load_detector()
                except Exception:
                    detector = None
            if detector is not None and not hasattr(detector, "boxes"):
                custom_prompts = payload.get("prompts") or payload.get("custom_classes")
                with current_app.config["DETECTOR_LOCK"]:
                    fresh_before = detections_from_model(
                        detector,
                        before_frame,
                        before_observation["image_width"],
                        before_observation["image_height"],
                    )
                    fresh_after = detections_from_model(
                        detector,
                        aligned_after,
                        after_observation["image_width"],
                        after_observation["image_height"],
                    )

                    # Secondary open-vocabulary detection for unfamiliar/non-COCO objects
                    ov_detector = get_open_vocabulary_detector()
                    if ov_detector is not None:
                        fresh_before = hybrid_detections(
                            fresh_before,
                            ov_detector,
                            before_frame,
                            before_observation["image_width"],
                            before_observation["image_height"],
                            custom_prompts=custom_prompts,
                        )
                        fresh_after = hybrid_detections(
                            fresh_after,
                            ov_detector,
                            aligned_after,
                            after_observation["image_width"],
                            after_observation["image_height"],
                            custom_prompts=custom_prompts,
                        )

                    if fresh_before or not before_layout["detections"]:
                        before_layout["detections"] = fresh_before
                    if fresh_after or not after_layout["detections"]:
                        after_layout["detections"] = fresh_after

            comparison = categorize_room_comparison(
                before_layout["detections"],
                after_layout["detections"],
                before_frame=before_frame,
                after_frame=aligned_after,
            )
            summary = comparison["summary"]
            if summary["uncertain"]:
                status = "uncertain"
            elif summary["moved"] or summary["new"] or summary["missing"]:
                status = "changed"
            else:
                status = "unchanged"

            comparison_diff = {
                "summary": {
                    key: summary[key]
                    for key in (
                        "unchanged",
                        "moved",
                        "new",
                        "missing",
                        "total_baseline",
                        "total_latest",
                    )
                },
                "unchanged": comparison["unchanged"],
                "moved": comparison["moved"],
                "new": comparison["new"],
                "missing": comparison["missing"],
                "uncertain": comparison.get("uncertain", []),
                "camera_stability": {
                    "status": view_status,
                    "illumination_changed": (
                        view_analysis.get("illumination_changed", False)
                        if isinstance(view_analysis, dict)
                        else False
                    ),
                    "rotation_deg": (
                        view_analysis.get("rotation_deg", 0.0)
                        if isinstance(view_analysis, dict)
                        else 0.0
                    ),
                    "translation_norm": (
                        view_analysis.get("translation_norm", 0.0)
                        if isinstance(view_analysis, dict)
                        else 0.0
                    ),
                },
            }
        else:
            status = "uncertain"
            comparison_diff = {
                "summary": {
                    "unchanged": 0,
                    "moved": 0,
                    "new": 0,
                    "missing": 0,
                    "total_baseline": len(before_layout.get("detections", [])),
                    "total_latest": len(after_layout.get("detections", [])),
                },
                "unchanged": [],
                "moved": [],
                "new": [],
                "missing": [],
                "uncertain": [
                    {
                        "class_name": None,
                        "reason": f"camera_view_{view_status}",
                        "message": f"Camera viewpoint or room lighting changed.",
                    }
                ],
                "camera_stability": {
                    "status": view_status,
                },
            }
    except (cv2.error, KeyError, TypeError, ValueError) as error:
        current_app.logger.exception("Could not compare saved room layouts")
        return jsonify({"error": f"Could not compare saved layouts: {error}"}), 500

    response_data = {
        "status": status,
        "before": before_layout,
        "after": after_layout,
    }
    if comparison_diff is not None:
        response_data["comparison"] = comparison_diff
    return jsonify(response_data)


@layout_bp.post("/api/layouts/<layout_id>/activate")
def activate_layout(layout_id):
    parsed_id = _positive_id(layout_id)
    if parsed_id is None:
        return jsonify({"error": "Layout ID must be a positive integer."}), 400
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Send a JSON object with room_name and camera_id."}), 400
    scope, error_response = _scope(payload.get("room_name"), payload.get("camera_id"))
    if error_response:
        return error_response

    captured_at = _timestamp()
    connection = connect_database(current_app.config["DATABASE_PATH"])
    _, scope_key, camera_id = scope
    try:
        with _monitor_transaction(connection):
            if not _history_schema_ready(connection):
                connection.rollback()
                return _migration_required()
            observation = connection.execute(
                """
                SELECT *
                FROM observations
                WHERE id = ? AND room_key = ? AND camera_id = ?
                """,
                (parsed_id, scope_key, camera_id),
            ).fetchone()
            if observation is None:
                connection.rollback()
                return jsonify({"error": "Layout was not found for this room and camera."}), 404
            if observation["deleted_at"] is not None:
                connection.rollback()
                return jsonify({"error": "A deleted layout cannot be activated."}), 409

            connection.execute(
                """
                UPDATE observations
                SET is_baseline = 0
                WHERE room_key = ? AND camera_id = ? AND is_baseline = 1
                """,
                (scope_key, camera_id),
            )
            connection.execute(
                "UPDATE observations SET is_baseline = 1 WHERE id = ?",
                (parsed_id,),
            )
            _mark_view_unknown(connection, scope, captured_at)
            observation = connection.execute(
                "SELECT * FROM observations WHERE id = ?", (parsed_id,)
            ).fetchone()
            response = _layout_response(connection, observation)
            connection.commit()
            _reset_room_trackers(scope_key)
    except sqlite3.Error as error:
        if connection.in_transaction:
            connection.rollback()
        current_app.logger.exception("Could not activate room layout")
        return jsonify({"error": f"Could not activate room layout: {error}"}), 500
    finally:
        if connection.in_transaction:
            connection.rollback()
        connection.close()

    return jsonify({"layout": response}), 200


@layout_bp.delete("/api/layouts/<layout_id>")
def delete_layout(layout_id):
    parsed_id = _positive_id(layout_id)
    if parsed_id is None:
        return jsonify({"error": "Layout ID must be a positive integer."}), 400
    scope, error_response = _scope(
        request.args.get("room_name"), request.args.get("camera_id")
    )
    if error_response:
        return error_response

    deleted_at = _timestamp()
    connection = connect_database(current_app.config["DATABASE_PATH"])
    _, scope_key, camera_id = scope
    try:
        with _monitor_transaction(connection):
            if not _history_schema_ready(connection):
                connection.rollback()
                return _migration_required()
            observation = connection.execute(
                """
                SELECT id, is_baseline, deleted_at
                FROM observations
                WHERE id = ? AND room_key = ? AND camera_id = ?
                """,
                (parsed_id, scope_key, camera_id),
            ).fetchone()
            if observation is None:
                connection.rollback()
                return jsonify({"error": "Layout was not found for this room and camera."}), 404
            if observation["deleted_at"] is not None:
                connection.rollback()
                return jsonify({"error": "Layout is already deleted."}), 409
            if observation["is_baseline"]:
                connection.rollback()
                return jsonify({"error": "The active layout cannot be deleted."}), 409

            available_count = connection.execute(
                """
                SELECT COUNT(*)
                FROM observations
                WHERE room_key = ? AND camera_id = ? AND deleted_at IS NULL
                """,
                (scope_key, camera_id),
            ).fetchone()[0]
            if available_count <= 1:
                connection.rollback()
                return jsonify({"error": "The last available layout cannot be deleted."}), 409

            connection.execute(
                "UPDATE observations SET deleted_at = ? WHERE id = ?",
                (deleted_at, parsed_id),
            )
            connection.commit()
    except sqlite3.Error as error:
        if connection.in_transaction:
            connection.rollback()
        current_app.logger.exception("Could not delete room layout")
        return jsonify({"error": f"Could not delete room layout: {error}"}), 500
    finally:
        if connection.in_transaction:
            connection.rollback()
        connection.close()

    return jsonify({"status": "deleted", "layout_id": parsed_id, "deleted_at": deleted_at})
