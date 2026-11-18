def room_key(room_name):
    return room_name.strip().casefold()


def image_zone(center_x, center_y):
    horizontal = "left" if center_x < 1 / 3 else "right" if center_x >= 2 / 3 else "center"
    vertical = "upper" if center_y < 1 / 3 else "lower" if center_y >= 2 / 3 else "middle"
    return f"{vertical}-{horizontal}"


def zone_label(zone):
    return zone.replace("-", " ")


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
