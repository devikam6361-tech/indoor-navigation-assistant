import sqlite3

from contextlib import closing
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request, current_app

from config import CAMERA_ID
from database.connection import connect_database
from database.queries import baseline_response
from services.yolo_service import detections_from_model, get_or_load_detector
from services.image_processing import image_from_payload
from utils.formatting import room_key

baseline_bp = Blueprint("baseline", __name__)


@baseline_bp.get("/api/baseline")
def get_baseline():
    name = request.args.get("room_name", "Living room").strip()
    if not name or len(name) > 80:
        return jsonify({"error": "Room name must contain 1 to 80 characters."}), 400

    with closing(connect_database(current_app.config["DATABASE_PATH"])) as connection:
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


@baseline_bp.post("/api/baseline")
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
        with current_app.config["DETECTOR_LOCK"]:
            model = get_or_load_detector()
            objects = detections_from_model(model, frame, width, height)
    except Exception as error:
        current_app.logger.exception("Could not run local YOLO inference")
        return jsonify({"error": f"YOLO could not process the image: {error}"}), 503

    captured_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )
    connection = connect_database(current_app.config["DATABASE_PATH"])
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
        current_app.logger.exception("Could not save the room baseline")
        return jsonify({"error": f"Could not save the room baseline: {error}"}), 500
    finally:
        connection.close()

    return jsonify({"baseline": response}), 201
