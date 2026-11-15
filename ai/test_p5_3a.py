"""
P5-3A tests: Multiple-object detection and baseline storage.

Verifies:
  - Multiple chairs can be detected and stored (multi-instance same class).
  - Couch and potted plant are now in MONITORED_CLASSES and trigger change events.
  - All pre-existing MONITORED_CLASSES still work.
  - Baselines are room-specific (different rooms don't share data).
  - couch and potted plant moving/appearing produce change events after
    CHANGE_CONFIRMATION_FRAMES.

These tests use FakeModel + temporary SQLite databases (never touch the
production database) and run from the ai/ directory.
"""

import base64
import json
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from server import create_app


# ---------------------------------------------------------------------------
# Fake YOLO model helpers
# ---------------------------------------------------------------------------

class FakeBox:
    def __init__(self, class_id, confidence, bounds):
        self.cls = [class_id]
        self.conf = [confidence]
        self.xyxy = [bounds]


class FakeResult:
    def __init__(self, boxes):
        self.boxes = boxes


def _encoded_image():
    """Return a base64 JPEG data-URL of a blank 64×48 image."""
    success, encoded = cv2.imencode(".jpg", np.zeros((48, 64, 3), dtype=np.uint8))
    assert success
    return "data:image/jpeg;base64," + base64.b64encode(encoded.tobytes()).decode("ascii")


def _make_app(model, tmp_dir):
    db_path = Path(tmp_dir) / "layout.sqlite3"
    app = create_app(db_path, detector=model)
    app.config["TESTING"] = True
    return app


# ---------------------------------------------------------------------------
# Test: MONITORED_CLASSES membership
# ---------------------------------------------------------------------------

class TestMonitoredClasses(unittest.TestCase):
    """Config-level checks — no HTTP calls needed."""

    def test_couch_in_monitored_classes(self):
        from config import MONITORED_CLASSES
        self.assertIn("couch", MONITORED_CLASSES)

    def test_potted_plant_in_monitored_classes(self):
        from config import MONITORED_CLASSES
        self.assertIn("potted plant", MONITORED_CLASSES)

    def test_all_original_classes_still_present(self):
        from config import MONITORED_CLASSES
        original = {
            "backpack", "bottle", "cell phone", "chair",
            "dining table", "handbag", "suitcase", "teddy bear",
        }
        self.assertTrue(original.issubset(MONITORED_CLASSES),
                        f"Missing: {original - MONITORED_CLASSES}")

    def test_monitored_classes_subset_of_supported(self):
        from config import MONITORED_CLASSES, SUPPORTED_CLASSES
        self.assertTrue(
            MONITORED_CLASSES.issubset(SUPPORTED_CLASSES),
            f"In MONITORED but not SUPPORTED: {MONITORED_CLASSES - SUPPORTED_CLASSES}",
        )


# ---------------------------------------------------------------------------
# Test: Multiple chairs detected and stored in baseline
# ---------------------------------------------------------------------------

class FakeModelTwoChairs:
    """Two chairs side by side — tests multi-instance same-class storage."""
    names = {0: "chair"}

    def __call__(self, frame, conf, verbose):
        return [FakeResult([
            FakeBox(0, 0.90, [4,  4, 20, 24]),   # chair 1 — left of frame
            FakeBox(0, 0.85, [42, 4, 58, 24]),   # chair 2 — right of frame
        ])]


class TestMultipleChairsBaseline(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._app = _make_app(FakeModelTwoChairs(), self._tmp.name)
        self._client = self._app.test_client()
        self._image = _encoded_image()

    def tearDown(self):
        self._tmp.cleanup()

    def test_two_chairs_stored_in_baseline(self):
        resp = self._client.post("/api/baseline", json={
            "room_name": "Hall",
            "image": self._image,
        })
        self.assertEqual(resp.status_code, 201)
        data = resp.get_json()
        detections = data["baseline"]["detections"]
        chairs = [d for d in detections if d["class_name"] == "chair"]
        self.assertEqual(len(chairs), 2, f"Expected 2 chairs, got {len(chairs)}: {chairs}")

    def test_two_chairs_have_distinct_instance_numbers(self):
        resp = self._client.post("/api/baseline", json={
            "room_name": "Hall",
            "image": self._image,
        })
        detections = resp.get_json()["baseline"]["detections"]
        chairs = sorted(
            [d for d in detections if d["class_name"] == "chair"],
            key=lambda d: d["instance_number"],
        )
        self.assertEqual(chairs[0]["instance_number"], 1)
        self.assertEqual(chairs[1]["instance_number"], 2)

    def test_two_chairs_have_different_zones(self):
        resp = self._client.post("/api/baseline", json={
            "room_name": "Hall",
            "image": self._image,
        })
        detections = resp.get_json()["baseline"]["detections"]
        chairs = [d for d in detections if d["class_name"] == "chair"]
        zones = {d["zone"] for d in chairs}
        self.assertGreater(len(zones), 1, f"Expected distinct zones, got {zones}")


# ---------------------------------------------------------------------------
# Test: Couch detected, stored, and triggers change events
# ---------------------------------------------------------------------------

class FakeModelCouch:
    """Baseline: couch in middle-center. Current: couch moved to middle-right."""
    names = {0: "couch"}
    _call_count = 0

    def __call__(self, frame, conf, verbose):
        self._call_count += 1
        if self._call_count == 1:
            # Baseline capture — couch in center
            return [FakeResult([FakeBox(0, 0.88, [20, 10, 44, 38])])]
        # Monitoring frame — couch shifted significantly to the right
        return [FakeResult([FakeBox(0, 0.86, [48, 10, 62, 38])])]


class TestCouchMonitoring(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._model = FakeModelCouch()
        self._app = _make_app(self._model, self._tmp.name)
        self._app.config["TESTING"] = True
        self._client = self._app.test_client()
        self._image = _encoded_image()

        from unittest.mock import patch
        self._view_patch = patch("server.camera_view_status", return_value="stable")
        self._view_patch.start()

    def tearDown(self):
        self._view_patch.stop()
        self._tmp.cleanup()

    def _save_baseline(self):
        resp = self._client.post("/api/baseline", json={
            "room_name": "Hall",
            "image": self._image,
        })
        self.assertEqual(resp.status_code, 201)
        data = resp.get_json()
        couches = [d for d in data["baseline"]["detections"] if d["class_name"] == "couch"]
        self.assertEqual(len(couches), 1, "Couch should be in baseline detections")
        return data

    def _observe(self):
        resp = self._client.post("/api/observe", json={
            "room_name": "Hall",
            "image": self._image,
        })
        self.assertEqual(resp.status_code, 200)
        return resp.get_json()

    def test_couch_in_baseline_detections(self):
        data = self._save_baseline()
        names = {d["class_name"] for d in data["baseline"]["detections"]}
        self.assertIn("couch", names)

    def test_couch_move_produces_event_after_confirmation(self):
        self._save_baseline()
        from config import CHANGE_CONFIRMATION_FRAMES
        result = None
        for _ in range(CHANGE_CONFIRMATION_FRAMES + 1):
            result = self._observe()
        # After confirmation frames, a moved-couch event should appear
        all_events = result["history"]
        couch_events = [e for e in all_events if e["object_name"] == "couch"]
        self.assertTrue(
            len(couch_events) > 0,
            f"Expected couch change event after {CHANGE_CONFIRMATION_FRAMES} frames. "
            f"History: {[e['object_name'] for e in all_events]}",
        )


# ---------------------------------------------------------------------------
# Test: Potted plant detected, stored, and triggers change events
# ---------------------------------------------------------------------------

class FakeModelPlant:
    """Baseline: plant at top-left. Current: plant moved to top-right."""
    names = {0: "potted plant"}
    _call_count = 0

    def __call__(self, frame, conf, verbose):
        self._call_count += 1
        if self._call_count == 1:
            return [FakeResult([FakeBox(0, 0.82, [2, 2, 14, 14])])]   # top-left
        return [FakeResult([FakeBox(0, 0.80, [50, 2, 62, 14])])]       # top-right


class TestPottedPlantMonitoring(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._model = FakeModelPlant()
        self._app = _make_app(self._model, self._tmp.name)
        self._app.config["TESTING"] = True
        self._client = self._app.test_client()
        self._image = _encoded_image()

        from unittest.mock import patch
        self._view_patch = patch("server.camera_view_status", return_value="stable")
        self._view_patch.start()

    def tearDown(self):
        self._view_patch.stop()
        self._tmp.cleanup()

    def _save_baseline(self):
        resp = self._client.post("/api/baseline", json={
            "room_name": "Hall",
            "image": self._image,
        })
        self.assertEqual(resp.status_code, 201)
        return resp.get_json()

    def test_potted_plant_in_baseline_detections(self):
        data = self._save_baseline()
        names = {d["class_name"] for d in data["baseline"]["detections"]}
        self.assertIn("potted plant", names)

    def test_potted_plant_move_produces_event_after_confirmation(self):
        self._save_baseline()
        from config import CHANGE_CONFIRMATION_FRAMES
        result = None
        for _ in range(CHANGE_CONFIRMATION_FRAMES + 1):
            result = self._client.post("/api/observe", json={
                "room_name": "Hall",
                "image": self._image,
            }).get_json()
        plant_events = [e for e in result["history"] if e["object_name"] == "potted plant"]
        self.assertTrue(
            len(plant_events) > 0,
            f"Expected potted plant change event after {CHANGE_CONFIRMATION_FRAMES} frames. "
            f"History: {[e['object_name'] for e in result['history']]}",
        )


# ---------------------------------------------------------------------------
# Test: Room isolation — baselines do not bleed between rooms
# ---------------------------------------------------------------------------

class FakeModelChairAndBottle:
    """Returns a chair for Hall, a bottle for Bedroom."""
    names = {0: "chair", 1: "bottle"}
    _room_sequence = []

    def __call__(self, frame, conf, verbose):
        # Alternate: odd calls = chair, even calls = bottle
        # (simpler: rely on call order per test method)
        return [FakeResult(self._boxes)]

    def set_boxes(self, boxes):
        self._boxes = boxes


class TestRoomIsolation(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._model = FakeModelChairAndBottle()
        self._model._boxes = []
        self._app = _make_app(self._model, self._tmp.name)
        self._app.config["TESTING"] = True
        self._client = self._app.test_client()
        self._image = _encoded_image()

    def tearDown(self):
        self._tmp.cleanup()

    def test_baselines_are_room_specific(self):
        # Capture Hall baseline with a chair
        self._model.set_boxes([FakeBox(0, 0.90, [4, 4, 20, 24])])
        resp_hall = self._client.post("/api/baseline", json={
            "room_name": "Hall",
            "image": self._image,
        })
        self.assertEqual(resp_hall.status_code, 201)

        # Capture Bedroom baseline with a bottle
        self._model.set_boxes([FakeBox(1, 0.80, [30, 10, 50, 30])])
        resp_bed = self._client.post("/api/baseline", json={
            "room_name": "Bedroom",
            "image": self._image,
        })
        self.assertEqual(resp_bed.status_code, 201)

        # Verify Hall baseline has chair, not bottle
        hall = self._client.get("/api/baseline?room_name=Hall").get_json()
        hall_classes = {d["class_name"] for d in hall["baseline"]["detections"]}
        self.assertIn("chair", hall_classes)
        self.assertNotIn("bottle", hall_classes)

        # Verify Bedroom baseline has bottle, not chair
        bed = self._client.get("/api/baseline?room_name=Bedroom").get_json()
        bed_classes = {d["class_name"] for d in bed["baseline"]["detections"]}
        self.assertIn("bottle", bed_classes)
        self.assertNotIn("chair", bed_classes)

    def test_room_names_are_case_insensitive(self):
        """room_key normalises to strip().casefold() — 'Hall' and 'hall' share one baseline."""
        self._model.set_boxes([FakeBox(0, 0.88, [4, 4, 20, 24])])
        self._client.post("/api/baseline", json={"room_name": "Hall", "image": self._image})

        resp = self._client.get("/api/baseline?room_name=HALL").get_json()
        self.assertIsNotNone(resp["baseline"], "HALL should return the same baseline as Hall")


if __name__ == "__main__":
    unittest.main()
