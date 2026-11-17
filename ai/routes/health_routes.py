from flask import Blueprint, jsonify, current_app

from config import MODEL_PATH

health_bp = Blueprint("health", __name__)


@health_bp.get("/api/health")
def health():
    return jsonify(
        {
            "status": "ok",
            "model_available": current_app.config["DETECTOR"] is not None
            or MODEL_PATH.is_file(),
        }
    )
