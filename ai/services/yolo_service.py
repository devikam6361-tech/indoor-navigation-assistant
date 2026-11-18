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


import logging

from flask import current_app

from config import (
    CANDIDATE_CONFIDENCE_THRESHOLD,
    CONFIDENCE_THRESHOLD,
    MODEL_PATH,
    SUPPORTED_CLASSES,
)
from services.visual_recognition import refine_object_label
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

    # Multi-scale / candidate inference for non-rigid indoor objects
    try:
        results = model(
            frame,
            conf=CANDIDATE_CONFIDENCE_THRESHOLD,
            imgsz=960,
            verbose=False,
        )
    except (TypeError, ValueError):
        try:
            results = model(
                frame,
                conf=CANDIDATE_CONFIDENCE_THRESHOLD,
                verbose=False,
            )
        except (TypeError, ValueError):
            results = model(frame)

    objects = []
    raw_count = 0
    raw_summary = []

    toy_classes = {
        "teddy bear",
        "doll",
        "pink plush doll",
        "plush doll",
        "plush toy",
        "toy",
    }

    for result in results:
        for box in result.boxes:
            raw_count += 1
            class_id = int(box.cls[0])
            raw_name = model.names[class_id].strip().lower()
            conf = float(box.conf[0])
            raw_summary.append(f"{raw_name}:{conf:.3f}")

            # Determine appropriate confidence threshold for class
            min_conf = (
                CANDIDATE_CONFIDENCE_THRESHOLD
                if raw_name in toy_classes
                else CONFIDENCE_THRESHOLD
            )
            if conf < min_conf:
                continue

            # Extract image crop for visual refinement if available
            x1, y1, x2, y2 = (float(value) for value in box.xyxy[0])
            crop = None
            if (
                frame is not None
                and hasattr(frame, "shape")
                and len(frame.shape) == 3
            ):
                ix1 = max(0, int(x1))
                iy1 = max(0, int(y1))
                ix2 = min(width, int(x2))
                iy2 = min(height, int(y2))
                if ix2 > ix1 and iy2 > iy1:
                    crop = frame[iy1:iy2, ix1:ix2]

            object_name = refine_object_label(raw_name, crop)
            if object_name not in SUPPORTED_CLASSES:
                # If refined name not supported, check if raw_name is supported
                if raw_name in SUPPORTED_CLASSES:
                    object_name = raw_name
                else:
                    continue

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
        "YOLO raw=%d frame=%dx%d raw=[%s] kept=%d [%s]",
        raw_count,
        width,
        height,
        ", ".join(raw_summary) if raw_summary else "none",
        len(objects),
        ", ".join(f"{o['class_name']}:{o['confidence']:.3f}" for o in objects)
        if objects
        else "none",
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
