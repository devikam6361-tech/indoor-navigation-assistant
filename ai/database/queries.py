import base64

from utils.formatting import event_response, room_key


# ---------------------------------------------------------------------------
# Public query functions
# ---------------------------------------------------------------------------

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
