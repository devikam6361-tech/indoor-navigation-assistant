import base64
import json

from contextlib import closing
from datetime import datetime

from flask import Blueprint, jsonify, request, current_app

from config import CAMERA_ID
from database.connection import connect_database
from database.queries import baseline_response
from services.change_detection import categorize_room_comparison
from services.object_finder import find_target_classes
from utils.formatting import room_key, zone_label

object_finder_bp = Blueprint("object_finder", __name__)


@object_finder_bp.get("/api/find")
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

    with closing(connect_database(current_app.config["DATABASE_PATH"])) as connection:
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


@object_finder_bp.get("/api/comparison")
def get_comparison():
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
        baseline = baseline_response(connection, observation) if observation else None
        row = connection.execute(
            "SELECT * FROM latest_observations WHERE room_key = ?",
            (room_key(name),),
        ).fetchone()
        latest = None
        if row:
            latest = {
                "room_name": row["room_name"],
                "captured_at": row["captured_at"],
                "image_data_url": "data:image/jpeg;base64,"
                + base64.b64encode(row["image"]).decode("ascii"),
                "image_width": row["image_width"],
                "image_height": row["image_height"],
                "detections": json.loads(row["detections_json"]),
            }
        comparison_diff = None
        if baseline and latest:
            analysis = categorize_room_comparison(
                baseline.get("detections", []),
                latest.get("detections", []),
            )
            comparison_diff = {
                "summary": {
                    key: analysis["summary"][key]
                    for key in (
                        "unchanged",
                        "moved",
                        "new",
                        "missing",
                        "total_baseline",
                        "total_latest",
                    )
                },
                "unchanged": analysis["unchanged"],
                "moved": analysis["moved"],
                "new": analysis["new"],
                "missing": analysis["missing"],
            }
    return jsonify({
        "baseline": baseline,
        "latest": latest,
        "comparison": comparison_diff,
    })
