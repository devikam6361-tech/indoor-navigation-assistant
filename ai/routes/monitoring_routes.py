import base64
import json

from contextlib import closing

from flask import Blueprint, jsonify, request, current_app

from database.connection import connect_database
from database.queries import read_recent_events
from utils.formatting import room_key

monitoring_bp = Blueprint("monitoring", __name__)


@monitoring_bp.get("/api/latest")
def get_latest():
    name = request.args.get("room_name", "Living room").strip()
    if not name or len(name) > 80:
        return jsonify({"error": "Room name must contain 1 to 80 characters."}), 400
    with closing(connect_database(current_app.config["DATABASE_PATH"])) as connection:
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
