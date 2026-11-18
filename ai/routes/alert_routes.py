from contextlib import closing

from flask import Blueprint, jsonify, request, current_app

from database.connection import connect_database
from database.queries import read_recent_events
from utils.formatting import room_key

alert_bp = Blueprint("alerts", __name__)


@alert_bp.get("/api/alerts")
def get_alerts():
    name = request.args.get("room_name", "Living room").strip()
    if not name or len(name) > 80:
        return jsonify({"error": "Room name must contain 1 to 80 characters."}), 400
    with closing(connect_database(current_app.config["DATABASE_PATH"])) as connection:
        history = read_recent_events(connection, name)
    return jsonify({"history": history})


@alert_bp.post("/api/alerts/<int:event_id>/playback")
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
    with closing(connect_database(current_app.config["DATABASE_PATH"])) as connection:
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
