"""
Open-Vocabulary Object Detection Service using YOLO-World.

Enables zero-shot and open-vocabulary detection of unfamiliar indoor objects,
allowing dynamic user text prompts (e.g. 'doll', 'pink plush toy', 'geometry box',
'microscope', 'test tube', 'calculator', 'notebook', 'wardrobe', 'unfamiliar household object').
"""

import logging
from pathlib import Path

import cv2
import numpy as np

from config import PROJECT_ROOT
from utils.formatting import image_zone

log = logging.getLogger(__name__)

YOLO_WORLD_MODEL_PATH = PROJECT_ROOT / "yolov8s-worldv2.pt"

# Default extended vocabulary for indoor navigation & household objects
DEFAULT_EXTENDED_PROMPTS = [
    "doll",
    "pink plush toy",
    "geometry box",
    "microscope",
    "test tube",
    "calculator",
    "notebook",
    "wardrobe",
    "trash bin",
    "dustbin",
    "medicine bottle",
    "slippers",
    "pillow",
    "unfamiliar household object",
]

_cached_yolo_world = None


def is_open_vocab_available():
    """Checks if the YOLO-World weights are present on disk."""
    return YOLO_WORLD_MODEL_PATH.is_file()


def get_open_vocabulary_detector():
    """Lazily load and return the cached YOLO-World detector."""
    global _cached_yolo_world
    if _cached_yolo_world is not None:
        return _cached_yolo_world

    if not YOLO_WORLD_MODEL_PATH.is_file():
        log.warning("YOLO-World weights not found at %s", YOLO_WORLD_MODEL_PATH)
        return None

    try:
        from ultralytics import YOLO

        model = YOLO(str(YOLO_WORLD_MODEL_PATH))
        # Set initial indoor vocabulary
        model.set_classes(DEFAULT_EXTENDED_PROMPTS)
        _cached_yolo_world = model
        log.info("Loaded YOLO-World open-vocabulary model from %s", YOLO_WORLD_MODEL_PATH)
        return _cached_yolo_world
    except Exception as e:
        log.exception("Could not initialize YOLO-World model: %s", e)
        return None


def detect_open_vocabulary(
    model,
    frame,
    width,
    height,
    prompts=None,
    confidence_threshold=0.10,
):
    """
    Runs open-vocabulary detection on a frame with arbitrary user text prompts.
    Returns list of formatted detection dicts.
    """
    if model is None or frame is None:
        return []

    active_prompts = list(prompts) if prompts else DEFAULT_EXTENDED_PROMPTS
    try:
        model.set_classes(active_prompts)
    except Exception as e:
        log.warning("Could not set dynamic classes on YOLO-World: %s", e)

    try:
        results = model(frame, conf=0.08, verbose=False)
    except Exception as e:
        log.exception("Open-vocabulary inference failed: %s", e)
        return []

    objects = []
    for result in results:
        for box in result.boxes:
            conf = float(box.conf[0])
            cls_id = int(box.cls[0])
            name = model.names[cls_id].strip().lower()

            # Handle uncertain / unfamiliar detections
            if conf < confidence_threshold:
                if conf >= 0.08:
                    name = "unknown object"
                else:
                    continue

            x1, y1, x2, y2 = (float(v) for v in box.xyxy[0])
            cx = min(1.0, max(0.0, ((x1 + x2) / 2) / width))
            cy = min(1.0, max(0.0, ((y1 + y2) / 2) / height))

            objects.append(
                {
                    "class_name": name,
                    "confidence": conf,
                    "center_x": cx,
                    "center_y": cy,
                    "x1": min(1.0, max(0.0, x1 / width)),
                    "y1": min(1.0, max(0.0, y1 / height)),
                    "x2": min(1.0, max(0.0, x2 / width)),
                    "y2": min(1.0, max(0.0, y2 / height)),
                    "zone": image_zone(cx, cy),
                    "detector": "open_vocabulary",
                }
            )

    return objects


def _compute_box_iou(box1, box2):
    """Computes Intersection over Union between two normalized [x1, y1, x2, y2] boxes."""
    xA = max(box1[0], box2[0])
    yA = max(box1[1], box2[1])
    xB = min(box1[2], box2[2])
    yB = min(box1[3], box2[3])

    inter = max(0.0, xB - xA) * max(0.0, yB - yA)
    area1 = (box1[2] - box1[0]) * (box1[3] - box1[1])
    area2 = (box2[2] - box2[0]) * (box2[3] - box2[1])

    union = area1 + area2 - inter
    return inter / union if union > 0 else 0.0


def hybrid_detections(
    primary_detections,
    open_vocab_model,
    frame,
    width,
    height,
    custom_prompts=None,
):
    """
    Combines primary YOLO detections with secondary open-vocabulary detections.
    - Preserves high-confidence primary detections.
    - Uses open-vocabulary detections to identify objects missed by primary YOLO or
      objects outside COCO vocabulary.
    - Merges duplicate detections.
    """
    if open_vocab_model is None or frame is None:
        return primary_detections

    ov_detections = detect_open_vocabulary(
        open_vocab_model, frame, width, height, prompts=custom_prompts
    )
    if not ov_detections:
        return primary_detections

    merged = list(primary_detections)
    for ov_item in ov_detections:
        ov_box = [ov_item["x1"], ov_item["y1"], ov_item["x2"], ov_item["y2"]]
        matched_primary = None
        best_iou = 0.0

        for prim_item in merged:
            prim_box = [prim_item["x1"], prim_item["y1"], prim_item["x2"], prim_item["y2"]]
            iou = _compute_box_iou(ov_box, prim_box)
            if iou > best_iou:
                best_iou = iou
                matched_primary = prim_item

        if best_iou >= 0.40 and matched_primary is not None:
            # Overlapping detection: if open-vocab has higher specificity or confidence
            if matched_primary["class_name"] in {"person", "teddy bear"} and ov_item["class_name"] not in {"unknown object"}:
                matched_primary["class_name"] = ov_item["class_name"]
                matched_primary["confidence"] = max(matched_primary["confidence"], ov_item["confidence"])
                matched_primary["open_vocab_refined"] = True
        elif best_iou < 0.25 and ov_item["confidence"] >= 0.10:
            # Non-overlapping new object found by open-vocabulary model
            merged.append(ov_item)

    merged.sort(key=lambda d: (d["class_name"], d["center_y"], d["center_x"]))
    instance_counts = {}
    for d in merged:
        name = d["class_name"]
        instance_counts[name] = instance_counts.get(name, 0) + 1
        d["instance_number"] = instance_counts[name]

    return merged
