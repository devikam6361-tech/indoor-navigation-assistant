"""
Tests for camera stability validation and monitoring resilience under minor vibration.

Verifies:
  1. Minor camera vibration / typing jitter (dx=12, dy=18, rot=1.5 deg) is classified as 'stable'.
  2. Genuine camera movement (dx=50, dy=35, rot=4.5 deg) is classified as 'moved'.
  3. Excessive rotation (> 3.5 deg) or scale distortion (> 6%) is classified as 'moved'.
  4. Featureless, corrupted, or blank frame is classified as 'unknown'.
  5. Monitoring loop pauses alerts when camera moves genuinely, but continues without
     false alerts during minor vibration.
"""

import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from config import CAMERA_ID, CHANGE_CONFIRMATION_FRAMES
from server import camera_view_status, create_app


def _textured_image(seed=42, width=640, height=480):
    """Generate a rich, repeatable textured image suitable for ORB keypoint detection."""
    rng = np.random.default_rng(seed)
    noise = rng.integers(0, 256, (height, width), dtype=np.uint8)
    blurred = cv2.GaussianBlur(noise, (5, 5), 0)
    color = cv2.cvtColor(blurred, cv2.COLOR_GRAY2BGR)
    # Add high-contrast geometric landmarks to guarantee plentiful ORB features
    for x in range(40, width - 40, 50):
        for y in range(40, height - 40, 50):
            cv2.rectangle(color, (x, y), (x + 20, y + 20), (0, 255, 0), -1)
            cv2.circle(color, (x + 35, y + 35), 10, (255, 0, 0), -1)
    return color


def _apply_affine_transform(image, dx, dy, angle_degrees, scale=1.0):
    """Applies a 2D affine transformation simulating camera shake or relocation."""
    h, w = image.shape[:2]
    center = (w / 2.0, h / 2.0)
    matrix = cv2.getRotationMatrix2D(center, angle_degrees, scale)
    matrix[0, 2] += dx
    matrix[1, 2] += dy
    return cv2.warpAffine(image, matrix, (w, h), borderMode=cv2.BORDER_REFLECT)


class FakeBox:
    def __init__(self, class_id, confidence, bounds):
        self.cls = [class_id]
        self.conf = [confidence]
        self.xyxy = [bounds]


class FakeResult:
    def __init__(self, boxes):
        self.boxes = boxes


class FakeDetector:
    names = {0: "chair", 1: "bottle", 2: "laptop"}

    def __init__(self, boxes=None):
        self.boxes = boxes if boxes is not None else [
            FakeBox(0, 0.92, [8, 8, 24, 28]),
        ]

    def __call__(self, frame, conf, verbose):
        return [FakeResult(self.boxes)]


class TestCameraStabilityValidation(unittest.TestCase):
    """Tests for camera_view_status under various optical and motion conditions."""

    @classmethod
    def setUpClass(cls):
        cls.ref_image = _textured_image(seed=101, width=640, height=480)
        ok, encoded = cv2.imencode(".jpg", cls.ref_image)
        assert ok
        cls.ref_bytes = encoded.tobytes()

    def test_identical_frame_is_stable(self):
        status = camera_view_status(self.ref_bytes, self.ref_image.copy())
        self.assertEqual(status, "stable")

    def test_minor_vibration_typing_shake_is_stable(self):
        """Simulate realistic webcam vibration: dx=10px, dy=14px, 1.2 deg rotation on 640x480."""
        vibrated_frame = _apply_affine_transform(
            self.ref_image, dx=10, dy=14, angle_degrees=1.2
        )
        status = camera_view_status(self.ref_bytes, vibrated_frame)
        self.assertEqual(status, "stable")

    def test_moderate_desk_nudge_is_stable(self):
        """Simulate a desk bump: dx=12px, dy=18px, 1.5 deg rotation on 640x480."""
        nudged_frame = _apply_affine_transform(
            self.ref_image, dx=12, dy=18, angle_degrees=1.5
        )
        status = camera_view_status(self.ref_bytes, nudged_frame)
        self.assertEqual(status, "stable")

    def test_genuine_camera_translation_is_moved(self):
        """Simulate moving the webcam across the desk: dx=55px, dy=35px on 640x480."""
        moved_frame = _apply_affine_transform(
            self.ref_image, dx=55, dy=35, angle_degrees=0.5
        )
        status = camera_view_status(self.ref_bytes, moved_frame)
        self.assertEqual(status, "moved")

    def test_genuine_camera_rotation_is_moved(self):
        """Simulate rotating the webcam viewpoint by 4.5 degrees."""
        rotated_frame = _apply_affine_transform(
            self.ref_image, dx=5, dy=5, angle_degrees=4.5
        )
        status = camera_view_status(self.ref_bytes, rotated_frame)
        self.assertEqual(status, "moved")

    def test_genuine_zoom_or_distance_change_is_moved(self):
        """Simulate significant viewpoint distance change: scale 1.10."""
        zoomed_frame = _apply_affine_transform(
            self.ref_image, dx=0, dy=0, angle_degrees=0.0, scale=1.10
        )
        status = camera_view_status(self.ref_bytes, zoomed_frame)
        self.assertEqual(status, "moved")

    def test_blank_or_occluded_frame_is_unknown(self):
        """A featureless dark image has insufficient ORB matches -> 'unknown'."""
        blank_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        status = camera_view_status(self.ref_bytes, blank_frame)
        self.assertEqual(status, "unknown")


class TestMonitoringResilienceWithCameraStability(unittest.TestCase):
    """Integration tests verifying monitoring alerts under stability changes."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_stability.sqlite3"
        self.detector = FakeDetector()
        self.app = create_app(self.db_path, detector=self.detector)
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

        # Build valid base64 image (48, 64, 3)
        room_img = np.zeros((48, 64, 3), dtype=np.uint8)
        ok, enc = cv2.imencode(".jpg", room_img)
        assert ok
        self.b64_image = "data:image/jpeg;base64," + base64.b64encode(enc.tobytes()).decode("ascii")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_monitoring_pauses_alerts_on_camera_moved(self):
        """When camera_view_status returns 'moved', alerts are paused and status is camera_moved."""
        with patch("server.camera_view_status", return_value="stable"):
            res = self.client.post("/api/baseline", json={"room_name": "Living room", "image": self.b64_image})
            self.assertEqual(res.status_code, 201)

        with patch("server.camera_view_status", return_value="moved"):
            # Move the chair
            self.detector.boxes = [FakeBox(0, 0.92, [35, 15, 55, 38])]
            for _ in range(CHANGE_CONFIRMATION_FRAMES + 1):
                obs_res = self.client.post("/api/observe", json={"room_name": "Living room", "image": self.b64_image})
                self.assertEqual(obs_res.status_code, 200)
                data = obs_res.get_json()
                self.assertEqual(data["status"], "camera_moved")
                # Object alerts must NOT fire when camera is moved
                object_alerts = [
                    a for a in data["alerts"]
                    if (a.get("class_name") or a.get("object_name")) != "camera"
                ]
                self.assertEqual(len(object_alerts), 0)

    def test_monitoring_resumes_and_confirms_changes_when_stable(self):
        """When camera is stable, moved object confirms after 3 consecutive frames."""
        with patch("server.camera_view_status", return_value="stable"):
            self.client.post("/api/baseline", json={"room_name": "Living room", "image": self.b64_image})

            # Move the chair to a distinctly different zone
            self.detector.boxes = [FakeBox(0, 0.92, [38, 20, 58, 42])]
            data = None
            for frame_idx in range(CHANGE_CONFIRMATION_FRAMES):
                obs_res = self.client.post("/api/observe", json={"room_name": "Living room", "image": self.b64_image})
                self.assertEqual(obs_res.status_code, 200)
                data = obs_res.get_json()
                self.assertEqual(data["status"], "monitoring")
                if frame_idx < CHANGE_CONFIRMATION_FRAMES - 1:
                    self.assertEqual(len(data["alerts"]), 0)

            # At frame 3, confirmation threshold reached -> alert emitted!
            self.assertGreaterEqual(len(data["alerts"]), 1)
            alert = data["alerts"][0]
            name = alert.get("class_name") or alert.get("object_name")
            self.assertEqual(name, "chair")
            self.assertIn("chair", alert["message"].lower())


if __name__ == "__main__":
    unittest.main()
