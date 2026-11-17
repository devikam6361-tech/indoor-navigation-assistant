"""
Comprehensive regression test suite for Indoor Room Change Detection.

Tests all 10 mandatory scenarios:
1. Objects visible in both images (stationary).
2. A moved chair or table.
3. A missing bottle or doll (actual room observation scenario).
4. A newly introduced bag or object.
5. Different indoor object categories (furniture, containers, toys, decor).
6. Different lighting and exposure (illumination normalization).
7. Minor camera vibration (typing jitter / desk nudge).
8. Genuine camera movement (viewpoint relocation / tilt).
9. Zero detections (empty scene vs unexplained visual change).
10. Incorrect or mismatched BEFORE/AFTER images (scope mismatch, scene mismatch).
"""

import base64
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from config import CAMERA_ID, CONFIDENCE_THRESHOLD, MOVE_DISTANCE_THRESHOLD
from server import camera_view_status, create_app
from services.camera_validation import align_frames_if_needed, validate_camera_view
from services.change_detection import (
    categorize_room_comparison,
    compare_detections,
)
from services.visual_change import (
    compute_overall_visual_change_ratio,
    extract_changed_regions,
    verify_object_visibility_change,
)
from services.visual_recognition import (
    detect_dominant_color,
    measure_region_difference,
    refine_object_label,
)


def _make_test_image(seed=42, width=640, height=480, brightness=1.0):
    """Generate a reproducible indoor room scene with distinct landmarks."""
    rng = np.random.default_rng(seed)
    base = rng.integers(80, 180, (height, width), dtype=np.uint8)
    base = cv2.GaussianBlur(base, (7, 7), 0)
    color = cv2.cvtColor(base, cv2.COLOR_GRAY2BGR)

    # Add furniture-like rectangular landmarks
    cv2.rectangle(color, (60, 120), (220, 360), (40, 80, 160), -1)    # couch / table
    cv2.rectangle(color, (340, 180), (460, 320), (80, 140, 60), -1)   # chair
    cv2.circle(color, (520, 140), 45, (180, 100, 200), -1)            # plant / plush

    if brightness != 1.0:
        color = np.clip(color.astype(np.float32) * brightness, 0, 255).astype(np.uint8)

    return color


def _encode_image(image):
    ok, buf = cv2.imencode(".jpg", image)
    assert ok
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode("ascii"), buf.tobytes()


class FakeBox:
    def __init__(self, class_id, confidence, bounds):
        self.cls = [class_id]
        self.conf = [confidence]
        self.xyxy = [bounds]


class FakeResult:
    def __init__(self, boxes):
        self.boxes = boxes


class MockYOLOModel:
    names = {
        0: "chair",
        1: "dining table",
        2: "couch",
        3: "bottle",
        4: "backpack",
        5: "potted plant",
        6: "teddy bear",
    }

    def __init__(self, boxes=None):
        self.boxes = boxes if boxes is not None else []

    def __call__(self, frame, conf=0.15, verbose=False, **kwargs):
        return [FakeResult(self.boxes)]


class TestIndoorRoomChangeDetection(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_room.sqlite3"
        self.model = MockYOLOModel()
        self.app = create_app(self.db_path, detector=self.model)
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def _post_layout(self, name, image_b64, activate=False):
        return self.client.post(
            "/api/layouts",
            json={
                "room_name": "Living room",
                "camera_id": CAMERA_ID,
                "layout_name": name,
                "image": image_b64,
                "activate": activate,
            },
        )

    def _compare(self, before_id, after_id, room_name="Living room", camera_id=CAMERA_ID):
        return self.client.post(
            "/api/layouts/compare",
            json={
                "room_name": room_name,
                "camera_id": camera_id,
                "before_layout_id": before_id,
                "after_layout_id": after_id,
            },
        )

    # -------------------------------------------------------------------------
    # Scenario 1: Objects visible in both images (stationary)
    # -------------------------------------------------------------------------
    def test_scenario_1_objects_visible_in_both_images_unchanged(self):
        img = _make_test_image(seed=1)
        b64, _ = _encode_image(img)

        self.model.boxes = [
            FakeBox(0, 0.88, [100, 100, 200, 250]),  # chair
            FakeBox(2, 0.92, [300, 150, 500, 350]),  # couch
        ]
        b_resp = self._post_layout("Before", b64)
        a_resp = self._post_layout("After", b64)

        with patch("routes.layout_routes.camera_view_status", return_value="stable"):
            res = self._compare(b_resp.get_json()["layout"]["id"], a_resp.get_json()["layout"]["id"])

        data = res.get_json()
        self.assertEqual(res.status_code, 200)
        self.assertEqual(data["status"], "unchanged")
        self.assertEqual(len(data["comparison"]["unchanged"]), 2)
        self.assertEqual(len(data["comparison"]["moved"]), 0)
        self.assertEqual(len(data["comparison"]["missing"]), 0)
        self.assertEqual(len(data["comparison"]["new"]), 0)

    # -------------------------------------------------------------------------
    # Scenario 2: Moved chair or table
    # -------------------------------------------------------------------------
    def test_scenario_2_moved_chair_detected(self):
        img_b = _make_test_image(seed=2)
        img_a = img_b.copy()
        # Visually shift chair area
        chair_crop = img_b[100:250, 100:200].copy()
        img_a[100:250, 100:200] = 120  # clear old
        img_a[100:250, 280:380] = chair_crop  # place in new spot

        b64_b, _ = _encode_image(img_b)
        b64_a, _ = _encode_image(img_a)

        self.model.boxes = [FakeBox(0, 0.89, [100, 100, 200, 250])]  # chair left
        b_resp = self._post_layout("Before", b64_b)

        self.model.boxes = [FakeBox(0, 0.87, [280, 100, 380, 250])]  # chair moved right
        a_resp = self._post_layout("After", b64_a)

        with patch("routes.layout_routes.camera_view_status", return_value="stable"):
            res = self._compare(b_resp.get_json()["layout"]["id"], a_resp.get_json()["layout"]["id"])

        data = res.get_json()
        self.assertEqual(res.status_code, 200)
        self.assertEqual(data["status"], "changed")
        self.assertEqual(len(data["comparison"]["moved"]), 1)
        self.assertEqual(data["comparison"]["moved"][0]["class_name"], "chair")
        self.assertGreater(data["comparison"]["moved"][0]["distance"], MOVE_DISTANCE_THRESHOLD)

    # -------------------------------------------------------------------------
    # Scenario 3: Missing object (e.g. bottle or pink plush doll removed)
    # -------------------------------------------------------------------------
    def test_scenario_3_missing_doll_or_bottle_confirmed_visually(self):
        img_b = _make_test_image(seed=3)
        img_a = img_b.copy()
        # Remove doll/bottle region by drawing background
        img_a[140:240, 480:580] = 130

        b64_b, _ = _encode_image(img_b)
        b64_a, _ = _encode_image(img_a)

        # Before has bottle
        self.model.boxes = [FakeBox(3, 0.82, [480, 140, 580, 240])]
        b_resp = self._post_layout("Before", b64_b)

        # After: bottle removed, 0 detections
        self.model.boxes = []
        a_resp = self._post_layout("After", b64_a)

        with patch("routes.layout_routes.camera_view_status", return_value="stable"):
            res = self._compare(b_resp.get_json()["layout"]["id"], a_resp.get_json()["layout"]["id"])

        data = res.get_json()
        self.assertEqual(res.status_code, 200)
        self.assertEqual(data["status"], "changed")
        self.assertEqual(len(data["comparison"]["missing"]), 1)
        self.assertEqual(data["comparison"]["missing"][0]["class_name"], "bottle")
        self.assertTrue(data["comparison"]["missing"][0]["visually_confirmed"])

    # -------------------------------------------------------------------------
    # Scenario 4: Newly introduced bag or other object
    # -------------------------------------------------------------------------
    def test_scenario_4_newly_introduced_backpack(self):
        img_b = _make_test_image(seed=4)
        img_a = img_b.copy()
        # Draw new backpack into scene
        cv2.rectangle(img_a, (150, 180), (260, 320), (30, 40, 200), -1)

        b64_b, _ = _encode_image(img_b)
        b64_a, _ = _encode_image(img_a)

        self.model.boxes = []
        b_resp = self._post_layout("Before", b64_b)

        self.model.boxes = [FakeBox(4, 0.85, [150, 180, 260, 320])]  # backpack
        a_resp = self._post_layout("After", b64_a)

        with patch("routes.layout_routes.camera_view_status", return_value="stable"):
            res = self._compare(b_resp.get_json()["layout"]["id"], a_resp.get_json()["layout"]["id"])

        data = res.get_json()
        self.assertEqual(res.status_code, 200)
        self.assertEqual(data["status"], "changed")
        self.assertEqual(len(data["comparison"]["new"]), 1)
        self.assertEqual(data["comparison"]["new"][0]["class_name"], "backpack")

    # -------------------------------------------------------------------------
    # Scenario 5: Different indoor object categories (label refinement)
    # -------------------------------------------------------------------------
    def test_scenario_5_indoor_object_categories_and_label_refinement(self):
        # Create pink crop
        pink_crop = np.zeros((100, 100, 3), dtype=np.uint8)
        pink_crop[:, :] = (180, 105, 230)  # BGR pink/magenta
        refined_doll = refine_object_label("teddy bear", pink_crop)
        self.assertEqual(refined_doll, "pink plush doll")

        # Create neutral crop
        gray_crop = np.zeros((100, 100, 3), dtype=np.uint8)
        gray_crop[:, :] = 120
        refined_plush = refine_object_label("teddy bear", gray_crop)
        self.assertEqual(refined_plush, "plush doll")

        # Standard furniture
        chair_label = refine_object_label("chair", gray_crop)
        self.assertEqual(chair_label, "chair")

    # -------------------------------------------------------------------------
    # Scenario 6: Different lighting and exposure (illumination normalization)
    # -------------------------------------------------------------------------
    def test_scenario_6_different_lighting_and_exposure_handled(self):
        ref = _make_test_image(seed=6)
        _, ref_bytes = _encode_image(ref)

        # 1. Darkened frame (e.g. evening / dimmed lights, 45% brightness)
        dark_frame = np.clip(ref.astype(np.float32) * 0.45, 0, 255).astype(np.uint8)
        analysis_dark = validate_camera_view(ref_bytes, dark_frame)
        self.assertEqual(analysis_dark["status"], "stable")
        self.assertTrue(analysis_dark["illumination_changed"])
        self.assertTrue(analysis_dark["can_compare"])

        # 2. Brightened frame (e.g. bright window light / switch on, 140% brightness)
        bright_frame = np.clip(ref.astype(np.float32) * 1.4 + 20, 0, 255).astype(np.uint8)
        analysis_bright = validate_camera_view(ref_bytes, bright_frame)
        self.assertEqual(analysis_bright["status"], "stable")
        self.assertTrue(analysis_bright["illumination_changed"])
        self.assertTrue(analysis_bright["can_compare"])

    # -------------------------------------------------------------------------
    # Scenario 7: Minor camera vibration (typing / desk nudge)
    # -------------------------------------------------------------------------
    def test_scenario_7_minor_camera_vibration_is_stable_and_alignable(self):
        ref = _make_test_image(seed=7)
        _, ref_bytes = _encode_image(ref)

        # Simulate typing jitter: dx=8px, dy=12px, rot=1.0 deg
        h, w = ref.shape[:2]
        M = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), 1.0, 1.0)
        M[0, 2] += 8
        M[1, 2] += 12
        vibrated = cv2.warpAffine(ref, M, (w, h), borderMode=cv2.BORDER_REFLECT)

        analysis = validate_camera_view(ref_bytes, vibrated)
        self.assertEqual(analysis["status"], "stable")
        self.assertLessEqual(analysis["rotation_deg"], 3.5)
        self.assertLessEqual(analysis["translation_norm"], 0.065)

        # Verify alignment reduces discrepancy
        aligned = align_frames_if_needed(ref, vibrated, analysis["transform"])
        raw_diff = cv2.absdiff(ref, vibrated).mean()
        aligned_diff = cv2.absdiff(ref, aligned).mean()
        self.assertLess(aligned_diff, raw_diff)

    # -------------------------------------------------------------------------
    # Scenario 8: Genuine camera movement (relocated / tilted)
    # -------------------------------------------------------------------------
    def test_scenario_8_genuine_camera_movement_detected(self):
        ref = _make_test_image(seed=8)
        _, ref_bytes = _encode_image(ref)

        # Translation dx=60px, dy=40px on 640x480
        h, w = ref.shape[:2]
        M_trans = np.float32([[1, 0, 60], [0, 1, 40]])
        moved_trans = cv2.warpAffine(ref, M_trans, (w, h), borderMode=cv2.BORDER_REFLECT)
        analysis_trans = validate_camera_view(ref_bytes, moved_trans)
        self.assertEqual(analysis_trans["status"], "moved")
        self.assertFalse(analysis_trans["can_compare"])

        # Excessive rotation: 6.0 degrees
        M_rot = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), 6.0, 1.0)
        moved_rot = cv2.warpAffine(ref, M_rot, (w, h), borderMode=cv2.BORDER_REFLECT)
        analysis_rot = validate_camera_view(ref_bytes, moved_rot)
        self.assertEqual(analysis_rot["status"], "moved")

    # -------------------------------------------------------------------------
    # Scenario 9: Zero detections (empty scene vs unexplained visual change)
    # -------------------------------------------------------------------------
    def test_scenario_9_zero_detections_clean_vs_unexplained_change(self):
        img_a = _make_test_image(seed=9)
        # 1. Clean unchanged scene with zero detections
        comp_clean = categorize_room_comparison([], [], before_frame=img_a, after_frame=img_a)
        self.assertEqual(comp_clean["summary"]["uncertain"], 0)
        self.assertEqual(comp_clean["summary"]["moved"], 0)
        self.assertEqual(comp_clean["summary"]["missing"], 0)
        self.assertEqual(comp_clean["summary"]["new"], 0)

        # 2. Scene with 15% visual difference but 0 detections (e.g. wall repainted / large banner)
        img_b = img_a.copy()
        cv2.rectangle(img_b, (50, 50), (450, 350), (0, 0, 0), -1)  # large dark area
        comp_changed = categorize_room_comparison([], [], before_frame=img_a, after_frame=img_b)
        # MUST NEVER report 0 changes!
        self.assertGreater(comp_changed["summary"]["uncertain"], 0)
        self.assertEqual(comp_changed["uncertain"][0]["reason"], "unclassified_visual_change")

    # -------------------------------------------------------------------------
    # Scenario 10: Incorrect or mismatched BEFORE/AFTER images
    # -------------------------------------------------------------------------
    def test_scenario_10_mismatched_images_rejected_safely(self):
        img_living = _make_test_image(seed=10)
        # Completely different room pattern
        img_kitchen = np.full((480, 640, 3), 40, dtype=np.uint8)
        cv2.circle(img_kitchen, (100, 100), 80, (255, 255, 255), -1)

        b64_living, _ = _encode_image(img_living)
        b64_kitchen, _ = _encode_image(img_kitchen)

        # 1. Camera validation recognizes mismatched view
        analysis = validate_camera_view(b64_living.split(",")[1].encode(), img_kitchen)
        self.assertEqual(analysis["status"], "unknown")
        self.assertFalse(analysis["can_compare"])

        # 2. Scope mismatch (wrong room or camera ID) rejected by API
        b_resp = self._post_layout("Living", b64_living)
        res_wrong_room = self._compare(b_resp.get_json()["layout"]["id"], 99999, room_name="Kitchen")
        self.assertEqual(res_wrong_room.status_code, 404)

        res_wrong_cam = self._compare(b_resp.get_json()["layout"]["id"], b_resp.get_json()["layout"]["id"], camera_id="bad-cam")
        self.assertEqual(res_wrong_cam.status_code, 400)


if __name__ == "__main__":
    unittest.main()
