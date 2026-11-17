import os
import sys
import time
from pathlib import Path

# Add project root and ai dir to path
ai_dir = Path(__file__).resolve().parent
project_root = ai_dir.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(ai_dir))

import cv2
import numpy as np
import sqlite3

print("=" * 70)
print("PHASE 2 VERIFICATION: YOLO-WORLD & HYBRID DETECTION PIPELINE")
print("=" * 70)

# -------------------------------------------------------------
# 1. Verify YOLO-World Checkpoint & CLIP dependencies
# -------------------------------------------------------------
checkpoint_path = project_root / "yolov8s-worldv2.pt"
print(f"\n[1] Checking YOLO-World Checkpoint at: {checkpoint_path}")
if checkpoint_path.is_file():
    size_mb = checkpoint_path.stat().st_size / (1024 * 1024)
    print(f"    SUCCESS: Checkpoint exists! Size = {size_mb:.2f} MB")
else:
    print("    ERROR: Checkpoint does not exist!")
    sys.exit(1)

print("\n[2] Checking CLIP dependency and cache...")
try:
    import clip
    import ftfy
    import regex
    print("    SUCCESS: clip, ftfy, regex imported successfully.")
except ImportError as e:
    print(f"    ERROR: CLIP import failed: {e}")
    sys.exit(1)

cache_dir = Path(os.path.expanduser("~/.cache/clip"))
cached_vit = cache_dir / "ViT-B-32.pt"
print(f"    Checking CLIP ViT-B/32 cache at {cached_vit}...")
if cached_vit.is_file():
    print(f"    SUCCESS: Cached ViT-B-32.pt exists ({cached_vit.stat().st_size / (1024*1024):.1f} MB).")
else:
    print(f"    WARNING: {cached_vit} not found in ~/.cache/clip. Let us check clip availability.")

# -------------------------------------------------------------
# 2. Load YOLO-World Model & Set Dynamic Vocabulary
# -------------------------------------------------------------
print("\n[3] Loading YOLO-World detector via open_vocabulary_service...")
from services.open_vocabulary_service import (
    get_open_vocabulary_detector,
    detect_open_vocabulary,
    hybrid_detections,
)
from services.yolo_service import get_or_load_detector, detections_from_model

t0 = time.time()
ov_model = get_open_vocabulary_detector()
load_time = time.time() - t0
if ov_model is not None:
    print(f"    SUCCESS: YOLO-World model loaded in {load_time:.2f}s!")
else:
    print("    ERROR: Failed to load YOLO-World model!")
    sys.exit(1)

# Dynamic test prompts required by prompt:
# "doll", "pink plush toy", "calculator", "microscope", "notebook", "test tube"
test_prompts = [
    "doll",
    "pink plush toy",
    "calculator",
    "microscope",
    "notebook",
    "test tube",
    "bed",
    "table",
    "chair",
]
print(f"\n[4] Initializing dynamic vocabulary with custom prompts:\n    {test_prompts}")
ov_model.set_classes(test_prompts)
print(f"    SUCCESS: Active classes set in model: {ov_model.names}")

# -------------------------------------------------------------
# 3. Retrieve Observation 86 (BEFORE) & 87 (AFTER) from SQLite
# -------------------------------------------------------------
print("\n[5] Retrieving Observations 86 and 87 from SQLite database...")
db_path = ai_dir / "instance" / "home_layout.sqlite3"
con = sqlite3.connect(str(db_path))
cur = con.cursor()

cur.execute("SELECT id, room_key, image, image_width, image_height, layout_name FROM observations WHERE id = 86")
row_86 = cur.fetchone()
cur.execute("SELECT id, room_key, image, image_width, image_height, layout_name FROM observations WHERE id = 87")
row_87 = cur.fetchone()
con.close()

if not row_86 or not row_87:
    print("    ERROR: Observations 86 or 87 not found in DB!")
    sys.exit(1)

print(f"    Observation 86: {row_86[5]} ({row_86[3]}x{row_86[4]}), image bytes={len(row_86[2])}")
print(f"    Observation 87: {row_87[5]} ({row_87[3]}x{row_87[4]}), image bytes={len(row_87[2])}")

# Decode images to BGR numpy arrays
nparr_86 = np.frombuffer(row_86[2], np.uint8)
img_86 = cv2.imdecode(nparr_86, cv2.IMREAD_COLOR)

nparr_87 = np.frombuffer(row_87[2], np.uint8)
img_87 = cv2.imdecode(nparr_87, cv2.IMREAD_COLOR)

# -------------------------------------------------------------
# 4. Open-Vocabulary Inference on Observation 86 & 87
# -------------------------------------------------------------
print("\n[6] Running Open-Vocabulary Inference on Observation 86 (BEFORE)...")
t0 = time.time()
detections_ov_86 = detect_open_vocabulary(
    ov_model, img_86, row_86[3], row_86[4], prompts=test_prompts, confidence_threshold=0.10
)
inf_time_86 = time.time() - t0
print(f"    Inference time: {inf_time_86*1000:.1f} ms | Detected {len(detections_ov_86)} objects:")
for idx, d in enumerate(detections_ov_86, 1):
    print(f"      {idx}. Label: '{d['class_name']}' | Conf: {d['confidence']:.3f} | Box: [{d['x1']:.3f}, {d['y1']:.3f}, {d['x2']:.3f}, {d['y2']:.3f}] | Zone: {d['zone']}")

print("\n[7] Running Open-Vocabulary Inference on Observation 87 (AFTER)...")
t0 = time.time()
detections_ov_87 = detect_open_vocabulary(
    ov_model, img_87, row_87[3], row_87[4], prompts=test_prompts, confidence_threshold=0.10
)
inf_time_87 = time.time() - t0
print(f"    Inference time: {inf_time_87*1000:.1f} ms | Detected {len(detections_ov_87)} objects:")
for idx, d in enumerate(detections_ov_87, 1):
    print(f"      {idx}. Label: '{d['class_name']}' | Conf: {d['confidence']:.3f} | Box: [{d['x1']:.3f}, {d['y1']:.3f}, {d['x2']:.3f}, {d['y2']:.3f}] | Zone: {d['zone']}")

# -------------------------------------------------------------
# 5. Verify Handling of Non-Existent Prompt Objects
# -------------------------------------------------------------
print("\n[8] Verifying that non-existent prompt objects (calculator, microscope, test tube) are NOT falsely hallucinated...")
classes_86 = [d["class_name"] for d in detections_ov_86]
classes_87 = [d["class_name"] for d in detections_ov_87]
non_present = ["calculator", "microscope", "test tube"]
for item in non_present:
    present_86 = item in classes_86
    present_87 = item in classes_87
    status = "CLEAN (Not falsely detected)" if not (present_86 or present_87) else "HALLUCINATED!"
    print(f"    Prompt '{item}': in BEFORE={present_86}, in AFTER={present_87} -> {status}")

# -------------------------------------------------------------
# 6. Verify Hybrid Pipeline (YOLO11 Primary + YOLO-World Secondary)
# -------------------------------------------------------------
print("\n[9] Running Hybrid Pipeline Verification (Primary YOLO11 + Secondary YOLO-World)...")
from server import create_app

app = create_app()
with app.app_context():
    yolo_primary = get_or_load_detector()
    prim_86 = detections_from_model(yolo_primary, img_86, row_86[3], row_86[4])
    prim_87 = detections_from_model(yolo_primary, img_87, row_87[3], row_87[4])
    print(f"    Primary YOLO11 Detections in BEFORE (86): {[d['class_name'] for d in prim_86]}")
    print(f"    Primary YOLO11 Detections in AFTER (87):  {[d['class_name'] for d in prim_87]}")

    hybrid_86 = hybrid_detections(prim_86, ov_model, img_86, row_86[3], row_86[4], custom_prompts=test_prompts)
    hybrid_87 = hybrid_detections(prim_87, ov_model, img_87, row_87[3], row_87[4], custom_prompts=test_prompts)
    print(f"    Hybrid Detections in BEFORE (86): {[(d['class_name'], round(d['confidence'], 2), d.get('detector', 'yolo11')) for d in hybrid_86]}")
    print(f"    Hybrid Detections in AFTER (87):  {[(d['class_name'], round(d['confidence'], 2), d.get('detector', 'yolo11')) for d in hybrid_87]}")

    # -------------------------------------------------------------
    # 7. Run Actual Before/After Comparison
    # -------------------------------------------------------------
    print("\n[10] Running Actual Before/After Comparison via categorize_room_comparison...")
    from services.change_detection import categorize_room_comparison

    comp = categorize_room_comparison(hybrid_86, hybrid_87, before_frame=img_86, after_frame=img_87)
    print(f"    Summary: {comp['summary']}")
    print(f"    Missing objects: {[m['class_name'] for m in comp.get('missing', [])]}")
    print(f"    New objects:     {[n['class_name'] for n in comp.get('new', [])]}")
    print(f"    Moved objects:   {[mv['class_name'] for mv in comp.get('moved', [])]}")
    print(f"    Unchanged:       {[u['class_name'] for u in comp.get('unchanged', [])]}")

print("\n" + "=" * 70)
print("VERIFICATION COMPLETE")
print("=" * 70)
