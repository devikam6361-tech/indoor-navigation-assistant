from contextlib import closing

from flask import Blueprint, jsonify

from database.connection import connect_database

room_bp = Blueprint("rooms", __name__)


@room_bp.get("/api/rooms")
def list_rooms():
    from flask import current_app

    with closing(connect_database(current_app.config["DATABASE_PATH"])) as connection:
        rows = connection.execute(
            """
            SELECT o.room_name, o.room_key, o.captured_at,
                   COUNT(d.id) AS detection_count
            FROM observations o
            LEFT JOIN detections d ON d.observation_id = o.id
            WHERE o.is_baseline = 1
            GROUP BY o.room_key
            ORDER BY o.room_name COLLATE NOCASE
            """
        ).fetchall()
    return jsonify(
        {
            "rooms": [
                {
                    "room_name": row["room_name"],
                    "room_key": row["room_key"],
                    "captured_at": row["captured_at"],
                    "detection_count": row["detection_count"],
                }
                for row in rows
            ]
        }
    )
