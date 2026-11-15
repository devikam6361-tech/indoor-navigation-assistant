from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = PROJECT_ROOT / "yolo11n.pt"
DATABASE_PATH = Path(__file__).resolve().parent / "instance" / "home_layout.sqlite3"
CAMERA_ID = "default-webcam"
MAX_IMAGE_BYTES = 8 * 1024 * 1024
# Lowered from 0.5 → 0.25: the yolo11n nano model scores indoor furniture at
# 0.12–0.44 on typical 640×480 room images. 0.5 filtered everything out.
# Verified empirically by running inference on three saved baseline images.
CONFIDENCE_THRESHOLD = 0.25
CHANGE_CONFIRMATION_FRAMES = 3
MOVE_DISTANCE_THRESHOLD = 0.14
OBJECT_COOLDOWN_SECONDS = 60
MONITORED_CLASSES = {
    "backpack",
    "bottle",
    "cell phone",
    "chair",
    "couch",
    "dining table",
    "handbag",
    "potted plant",
    "suitcase",
    "teddy bear",
}
SUPPORTED_CLASSES = {
    # Furniture & fixtures
    "bed",
    "bench",
    "chair",
    "couch",
    "dining table",
    "sink",
    "toilet",
    # Electronics — only kitchen appliances and large fixtures are retained.
    # laptop, keyboard, mouse, and remote are removed: they produce high false-positive
    # rates on indoor navigation images (chair backs and door panels are frequently
    # misclassified as 'laptop' by YOLO11n at conf=0.25, silently dropping chairs
    # from baseline tracking). tv, microwave, oven, refrigerator, toaster are kept
    # because they are large, spatially stable fixtures with low confusion risk.
    "cell phone",
    "microwave",
    "oven",
    "refrigerator",
    "toaster",
    "tv",
    # Containers & tableware
    "backpack",
    "bottle",
    "bowl",
    "cup",
    "handbag",
    "suitcase",
    "vase",
    "wine glass",
    # Books & stationery
    "book",
    "scissors",
    # Decor & misc
    "clock",
    "hair drier",
    "potted plant",
    "teddy bear",
    "toothbrush",
}
