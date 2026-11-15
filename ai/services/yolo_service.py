import logging

from flask import current_app

from config import CONFIDENCE_THRESHOLD, MODEL_PATH, SUPPORTED_CLASSES
from utils.formatting import image_zone


def get_or_load_detector():
    """Return the cached detector or load it lazily from disk."""
    if current_app.config["DETECTOR"] is not None:
        return current_app.config["DETECTOR"]

    if not MODEL_PATH.is_file():
        raise RuntimeError(f"YOLO model weights not found: {MODEL_PATH}")

    from ultralytics import YOLO

    current_app.config["DETECTOR"] = YOLO(str(MODEL_PATH))
    return current_app.config["DETECTOR"]


def detections_from_model(model, frame, width, height):
    log = logging.getLogger(__name__)

    results = model(frame, conf=CONFIDENCE_THRESHOLD, verbose=False)
    objects = []
    raw_count = 0
    raw_summary = []

    for result in results:
        for box in result.boxes:
            raw_count += 1
            class_id = int(box.cls[0])
            object_name = model.names[class_id].strip().lower()
            conf = float(box.conf[0])
            raw_summary.append(f"{object_name}:{conf:.3f}")

            if object_name not in SUPPORTED_CLASSES:
                continue

            x1, y1, x2, y2 = (float(value) for value in box.xyxy[0])
            center_x = min(1.0, max(0.0, ((x1 + x2) / 2) / width))
            center_y = min(1.0, max(0.0, ((y1 + y2) / 2) / height))
            objects.append(
                {
                    "class_name": object_name,
                    "confidence": conf,
                    "center_x": center_x,
                    "center_y": center_y,
                    "x1": min(1.0, max(0.0, x1 / width)),
                    "y1": min(1.0, max(0.0, y1 / height)),
                    "x2": min(1.0, max(0.0, x2 / width)),
                    "y2": min(1.0, max(0.0, y2 / height)),
                    "zone": image_zone(center_x, center_y),
                }
            )

    log.info(
        "YOLO raw=%d conf_threshold=%.2f frame=%dx%d  raw=[%s]  kept=%d [%s]",
        raw_count,
        CONFIDENCE_THRESHOLD,
        width,
        height,
        ", ".join(raw_summary) if raw_summary else "none",
        len(objects),
        ", ".join(f"{o['class_name']}:{o['confidence']:.3f}" for o in objects) if objects else "none",
    )

    objects.sort(
        key=lambda item: (
            item["class_name"],
            item["center_y"],
            item["center_x"],
        )
    )
    instance_counts = {}
    for item in objects:
        name = item["class_name"]
        instance_counts[name] = instance_counts.get(name, 0) + 1
        item["instance_number"] = instance_counts[name]

    return objects
