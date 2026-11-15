"""
Focused tests for Fix 1: Before-and-After Comparison Pipeline.

Verifies:
  1. categorize_room_comparison returns all four categories:
     - unchanged: objects that remained within MOVE_DISTANCE_THRESHOLD
     - moved: objects that moved beyond MOVE_DISTANCE_THRESHOLD
     - new: newly observed objects not in baseline
     - missing: baseline objects not observed in latest scan
  2. Multi-instance matching for same-class objects (e.g., 2 chairs, 1 moved, 1 stayed).
  3. Moved objects include both previous_position and current_position.
  4. Integration with GET /api/comparison returning 'comparison' diff object.
  5. Original baseline is preserved and not mutated by comparison.
"""

import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from config import MOVE_DISTANCE_THRESHOLD
from services.change_detection import categorize_room_comparison


def _encoded_image():
    success, encoded = cv2.imencode(".jpg", np.zeros((48, 64, 3), dtype=np.uint8))
    assert success
    return "data:image/jpeg;base64," + base64.b64encode(encoded.tobytes()).decode("ascii")


class FakeBox:
    def __init__(self, class_id, confidence, bounds):
        self.cls = [class_id]
        self.conf = [confidence]
        self.xyxy = [bounds]


class FakeResult:
    def __init__(self, boxes):
        self.boxes = boxes


def _make_app(model, tmp_dir):
    from server import create_app
    db_path = Path(tmp_dir) / "layout.sqlite3"
    app = create_app(db_path, detector=model)
    app.config["TESTING"] = True
    return app


class TestCategorizeRoomComparisonUnit(unittest.TestCase):
    """Unit tests for categorize_room_comparison algorithm."""

    def test_four_categories_all_present(self):
        """
        Baseline:
          - Chair 1 at (0.20, 0.50) [left]
          - Chair 2 at (0.80, 0.50) [right]
          - Couch at (0.50, 0.20) [center-top]
        Current:
          - Chair 1 at (0.20, 0.50) -> UNCHANGED (dist = 0.0)
          - Chair 2 at (0.50, 0.50) -> MOVED (dist = 0.30 > 0.14)
          - Backpack at (0.50, 0.80) -> NEW
          - (Couch is absent) -> MISSING
        """
        baseline = [
            {"class_name": "chair", "instance_number": 1, "center_x": 0.20, "center_y": 0.50, "zone": "middle-left", "confidence": 0.90},
            {"class_name": "chair", "instance_number": 2, "center_x": 0.80, "center_y": 0.50, "zone": "middle-right", "confidence": 0.88},
            {"class_name": "couch", "instance_number": 1, "center_x": 0.50, "center_y": 0.20, "zone": "upper-center", "confidence": 0.85},
        ]
        current = [
            {"class_name": "chair", "center_x": 0.20, "center_y": 0.50, "zone": "middle-left", "confidence": 0.91},
            {"class_name": "chair", "center_x": 0.50, "center_y": 0.50, "zone": "middle-center", "confidence": 0.87},
            {"class_name": "backpack", "center_x": 0.50, "center_y": 0.80, "zone": "lower-center", "confidence": 0.82},
        ]

        result = categorize_room_comparison(baseline, current)

        # 1. Check summary counts
        summary = result["summary"]
        self.assertEqual(summary["unchanged"], 1)
        self.assertEqual(summary["moved"], 1)
        self.assertEqual(summary["missing"], 1)
        self.assertEqual(summary["new"], 1)
        self.assertEqual(summary["total_baseline"], 3)
        self.assertEqual(summary["total_latest"], 3)

        # 2. Check Unchanged
        self.assertEqual(len(result["unchanged"]), 1)
        self.assertEqual(result["unchanged"][0]["class_name"], "chair")
        self.assertEqual(result["unchanged"][0]["instance_number"], 1)
        self.assertEqual(result["unchanged"][0]["zone"], "middle-left")

        # 3. Check Moved (with previous and current positions)
        self.assertEqual(len(result["moved"]), 1)
        moved_chair = result["moved"][0]
        self.assertEqual(moved_chair["class_name"], "chair")
        self.assertEqual(moved_chair["instance_number"], 2)
        self.assertEqual(moved_chair["original_zone"], "middle-right")
        self.assertEqual(moved_chair["current_zone"], "middle-center")
        self.assertIn("previous_position", moved_chair)
        self.assertIn("current_position", moved_chair)
        self.assertAlmostEqual(moved_chair["previous_position"]["center_x"], 0.80, places=2)
        self.assertAlmostEqual(moved_chair["current_position"]["center_x"], 0.50, places=2)

        # 4. Check Missing
        self.assertEqual(len(result["missing"]), 1)
        self.assertEqual(result["missing"][0]["class_name"], "couch")
        self.assertEqual(result["missing"][0]["zone"], "upper-center")

        # 5. Check New
        self.assertEqual(len(result["new"]), 1)
        self.assertEqual(result["new"][0]["class_name"], "backpack")
        self.assertEqual(result["new"][0]["zone"], "lower-center")

    def test_multi_instance_same_class_stationary_and_moved(self):
        """
        Three chairs in baseline, two chairs in current:
          - Chair 1 stays -> UNCHANGED
          - Chair 2 moves -> MOVED
          - Chair 3 absent -> MISSING
          - Plus a new bottle -> NEW
        """
        baseline = [
            {"class_name": "chair", "instance_number": 1, "center_x": 0.10, "center_y": 0.50, "zone": "middle-left", "confidence": 0.90},
            {"class_name": "chair", "instance_number": 2, "center_x": 0.50, "center_y": 0.50, "zone": "middle-center", "confidence": 0.88},
            {"class_name": "chair", "instance_number": 3, "center_x": 0.90, "center_y": 0.50, "zone": "middle-right", "confidence": 0.85},
        ]
        current = [
            {"class_name": "chair", "center_x": 0.10, "center_y": 0.50, "zone": "middle-left", "confidence": 0.90},   # stays
            {"class_name": "chair", "center_x": 0.75, "center_y": 0.50, "zone": "middle-right", "confidence": 0.86},  # chair 2 moved (dist 0.25 to chair 2, 0.15 to chair 3)
            {"class_name": "bottle", "center_x": 0.30, "center_y": 0.20, "zone": "upper-center", "confidence": 0.80},  # new bottle
        ]

        result = categorize_room_comparison(baseline, current)
        self.assertEqual(result["summary"]["unchanged"], 1)
        self.assertEqual(result["summary"]["moved"], 1)
        self.assertEqual(result["summary"]["missing"], 1)
        self.assertEqual(result["summary"]["new"], 1)

        self.assertEqual(result["unchanged"][0]["instance_number"], 1)
        self.assertEqual(len(result["moved"]), 1)
        self.assertEqual(len(result["missing"]), 1)
        self.assertEqual(len(result["new"]), 1)
        self.assertEqual(result["new"][0]["class_name"], "bottle")


class TestComparisonApiIntegration(unittest.TestCase):
    """Integration tests for GET /api/comparison returning diff object."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._image = _encoded_image()

    def tearDown(self):
        self._tmp.cleanup()

    def test_api_comparison_returns_diff_when_both_baseline_and_latest_exist(self):
        """
        Baseline has 1 chair (left) and 1 table (center).
        Observation has 1 chair (left -> unchanged) and 1 table (moved right) and 1 bag (new).
        """
        class ModelSeq:
            names = {0: "chair", 1: "dining table", 2: "backpack"}
            calls = 0
            def __call__(self, frame, conf, verbose):
                self.calls += 1
                if self.calls == 1:
                    # Baseline: chair at left [0, 10, 20, 30], table at center [22, 20, 42, 40]
                    return [FakeResult([
                        FakeBox(0, 0.90, [0, 10, 20, 30]),
                        FakeBox(1, 0.88, [22, 20, 42, 40]),
                    ])]
                # Observation: chair at left (unchanged), table moved right [44, 20, 62, 40], backpack [22, 34, 42, 46]
                return [FakeResult([
                    FakeBox(0, 0.90, [0, 10, 20, 30]),
                    FakeBox(1, 0.86, [44, 20, 62, 40]),
                    FakeBox(2, 0.80, [22, 34, 42, 46]),
                ])]

        app = _make_app(ModelSeq(), self._tmp.name)
        client = app.test_client()

        with patch("server.camera_view_status", return_value="stable"):
            client.post("/api/baseline", json={"room_name": "Living room", "image": self._image})
            client.post("/api/observe", json={"room_name": "Living room", "image": self._image})

            resp = client.get("/api/comparison?room_name=Living%20room")
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()

            # Backwards compatibility checks
            self.assertIsNotNone(data.get("baseline"))
            self.assertIsNotNone(data.get("latest"))

            # New comparison diff check
            self.assertIn("comparison", data)
            diff = data["comparison"]
            self.assertIsNotNone(diff)
            self.assertEqual(diff["summary"]["unchanged"], 1)
            self.assertEqual(diff["summary"]["moved"], 1)
            self.assertEqual(diff["summary"]["new"], 1)
            self.assertEqual(diff["summary"]["missing"], 0)

            # Details
            self.assertEqual(diff["unchanged"][0]["class_name"], "chair")
            self.assertEqual(diff["moved"][0]["class_name"], "dining table")
            self.assertIn("previous_position", diff["moved"][0])
            self.assertIn("current_position", diff["moved"][0])
            self.assertEqual(diff["new"][0]["class_name"], "backpack")


if __name__ == "__main__":
    unittest.main()
