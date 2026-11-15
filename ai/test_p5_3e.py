"""
P5-3E tests: Hall scenario end-to-end integration.

Simulates the full multi-object workflow:

  Baseline (call 1):
    chair       → middle-right
    dining table → middle-center
    couch        → middle-left    (unchanged in monitoring)
    potted plant → upper-center   (unchanged in monitoring)
    backpack     → absent

  Monitoring (calls 2+, same frame repeated):
    chair        → middle-LEFT    (moved, distance 0.672 >> 0.14)
    dining table → middle-RIGHT   (moved, distance 0.328 >> 0.14)
    couch        → middle-left    (unchanged, distance 0.000)
    potted plant → upper-center   (unchanged, distance 0.000)
    backpack     → lower-center   (new, obstacle warning)

  After CHANGE_CONFIRMATION_FRAMES (3) consecutive monitoring scans,
  exactly three events must fire:
    1. chair       moved    middle-right → middle-left
    2. dining table moved    middle-center → middle-right
    3. backpack    newly_observed in lower-center (obstacle warning)

  No events for couch or potted plant.
  Baseline row and detections must be unchanged after monitoring.

No production files are modified. Run from the ai/ directory:

    python -m pytest test_p5_3e.py -v
"""

import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _encoded_image():
    """Return a base64 JPEG data-URL of a blank 64×48 image."""
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


# ---------------------------------------------------------------------------
# Hall scenario FakeModel
#
# Frame: 64 × 48 pixels (normalised coordinates verified below)
#
# Class ID map:
#   0 = chair         1 = dining table
#   2 = couch         3 = potted plant    4 = backpack
#
# Baseline zones (call 1):
#   chair        [44,16,62,32]  cx=0.828 cy=0.500  middle-right
#   dining table [22,20,42,36]  cx=0.500 cy=0.583  middle-center
#   couch        [ 2,20,18,36]  cx=0.156 cy=0.583  middle-left
#   potted plant [22, 2,42,14]  cx=0.500 cy=0.167  upper-center
#
# Monitoring zones (calls 2+):
#   chair        [ 2,16,18,32]  cx=0.156 cy=0.500  middle-left   Δ=0.672
#   dining table [44,20,62,36]  cx=0.828 cy=0.583  middle-right  Δ=0.328
#   couch        [ 2,20,18,36]  cx=0.156 cy=0.583  middle-left   Δ=0.000
#   potted plant [22, 2,42,14]  cx=0.500 cy=0.167  upper-center  Δ=0.000
#   backpack     [22,34,42,46]  cx=0.500 cy=0.833  lower-center  NEW
# ---------------------------------------------------------------------------

class FakeModelHall:
    names = {
        0: "chair",
        1: "dining table",
        2: "couch",
        3: "potted plant",
        4: "backpack",
    }
    _call_count = 0

    def __call__(self, frame, conf, verbose):
        self._call_count += 1
        if self._call_count == 1:
            # Baseline: 4 objects, no backpack
            return [FakeResult([
                FakeBox(0, 0.90, [44, 16, 62, 32]),  # chair       middle-right
                FakeBox(1, 0.88, [22, 20, 42, 36]),  # dining table middle-center
                FakeBox(2, 0.85, [ 2, 20, 18, 36]),  # couch        middle-left
                FakeBox(3, 0.82, [22,  2, 42, 14]),  # potted plant upper-center
            ])]
        # Monitoring: chair moved left, table moved right, couch/plant unchanged, bag new
        return [FakeResult([
            FakeBox(0, 0.89, [ 2, 16, 18, 32]),  # chair        middle-left   (moved)
            FakeBox(1, 0.87, [44, 20, 62, 36]),  # dining table middle-right  (moved)
            FakeBox(2, 0.84, [ 2, 20, 18, 36]),  # couch        middle-left   (unchanged)
            FakeBox(3, 0.81, [22,  2, 42, 14]),  # potted plant upper-center  (unchanged)
            FakeBox(4, 0.78, [22, 34, 42, 46]),  # backpack     lower-center  (new)
        ])]


# ---------------------------------------------------------------------------
# Base test class: sets up the Hall app, runs baseline + N monitoring scans
# ---------------------------------------------------------------------------

class _HallBase(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._model = FakeModelHall()
        self._app = _make_app(self._model, self._tmp.name)
        self._client = self._app.test_client()
        self._image = _encoded_image()
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

    def _observe(self):
        resp = self._client.post("/api/observe", json={
            "room_name": "Hall",
            "image": self._image,
        })
        self.assertEqual(resp.status_code, 200)
        return resp.get_json()

    def _run_hall_scenario(self):
        """
        Saves baseline, runs CHANGE_CONFIRMATION_FRAMES monitoring scans,
        and returns the final observe response.
        """
        from config import CHANGE_CONFIRMATION_FRAMES
        self._save_baseline()
        result = None
        for _ in range(CHANGE_CONFIRMATION_FRAMES):
            result = self._observe()
        return result

    def _all_object_history(self, result):
        """Return history entries that are not camera-status events."""
        return [
            e for e in result["history"]
            if not e["change_type"].startswith("camera_view_")
        ]


# ---------------------------------------------------------------------------
# 1. TestHallScenarioEvents — event count and types (5 tests)
# ---------------------------------------------------------------------------

class TestHallScenarioEvents(_HallBase):
    """
    After CHANGE_CONFIRMATION_FRAMES monitoring scans:
    - exactly 3 object-change events (chair moved, table moved, backpack new)
    - no couch or potted plant events
    """

    def test_exactly_three_events_after_confirmation(self):
        """Total object-change events in history must be exactly 3."""
        result = self._run_hall_scenario()
        events = self._all_object_history(result)
        self.assertEqual(
            len(events), 3,
            f"Expected exactly 3 events; got {len(events)}: "
            f"{[(e['object_name'], e['change_type']) for e in events]}",
        )

    def test_chair_moved_event_present(self):
        """A 'moved' event for 'chair' must appear in the alert history."""
        result = self._run_hall_scenario()
        chair_events = [
            e for e in result["history"]
            if e["object_name"] == "chair" and e["change_type"] == "moved"
        ]
        self.assertEqual(
            len(chair_events), 1,
            f"Expected 1 chair-moved event; history: {result['history']}",
        )

    def test_dining_table_moved_event_present(self):
        """A 'moved' event for 'dining table' must appear in the alert history."""
        result = self._run_hall_scenario()
        table_events = [
            e for e in result["history"]
            if e["object_name"] == "dining table" and e["change_type"] == "moved"
        ]
        self.assertEqual(
            len(table_events), 1,
            f"Expected 1 dining-table-moved event; history: {result['history']}",
        )

    def test_backpack_newly_observed_event_present(self):
        """A 'newly_observed' event for 'backpack' must appear in the alert history."""
        result = self._run_hall_scenario()
        bag_events = [
            e for e in result["history"]
            if e["object_name"] == "backpack" and e["change_type"] == "newly_observed"
        ]
        self.assertEqual(
            len(bag_events), 1,
            f"Expected 1 backpack-newly_observed event; history: {result['history']}",
        )

    def test_couch_and_plant_produce_no_events(self):
        """
        Unchanged couch and potted plant must produce zero events across
        all monitoring scans — including frames beyond the confirmation window.
        """
        from config import CHANGE_CONFIRMATION_FRAMES
        self._save_baseline()
        for _ in range(CHANGE_CONFIRMATION_FRAMES + 2):   # extra scans to be sure
            result = self._observe()
        silent = [
            e for e in result["history"]
            if e["object_name"] in {"couch", "potted plant"}
        ]
        self.assertEqual(
            silent, [],
            f"Couch and potted plant must produce no events; got {silent}",
        )


# ---------------------------------------------------------------------------
# 2. TestHallScenarioMessages — voice message text (3 tests)
# ---------------------------------------------------------------------------

class TestHallScenarioMessages(_HallBase):
    """
    Verify the voice-announcement text for the three Hall events.
    """

    def _get_event(self, result, object_name, change_type):
        matches = [
            e for e in result["history"]
            if e["object_name"] == object_name and e["change_type"] == change_type
        ]
        self.assertEqual(
            len(matches), 1,
            f"Expected 1 {change_type} event for {object_name!r}; "
            f"history: {[(e['object_name'], e['change_type']) for e in result['history']]}",
        )
        return matches[0]

    def test_chair_moved_message_text(self):
        """
        Chair moved from middle-right → middle-left.
        Message must reference the object name and both zone labels.
        """
        result = self._run_hall_scenario()
        event = self._get_event(result, "chair", "moved")
        msg = event["message"].lower()
        self.assertIn("chair", msg)
        self.assertIn("right", msg,
                      f"Original zone 'right' missing from chair message: {event['message']!r}")
        self.assertIn("left", msg,
                      f"Current zone 'left' missing from chair message: {event['message']!r}")

    def test_dining_table_moved_message_text(self):
        """
        Dining table moved from middle-center → middle-right.
        Message must reference the object name and both zone labels.
        """
        result = self._run_hall_scenario()
        event = self._get_event(result, "dining table", "moved")
        msg = event["message"].lower()
        self.assertIn("dining table", msg)
        self.assertIn("center", msg,
                      f"Original zone 'center' missing from table message: {event['message']!r}")
        self.assertIn("right", msg,
                      f"Current zone 'right' missing from table message: {event['message']!r}")

    def test_backpack_obstacle_warning_message(self):
        """
        Backpack newly observed in lower-center must trigger the obstacle warning.
        Message must contain 'obstacle'.
        """
        result = self._run_hall_scenario()
        event = self._get_event(result, "backpack", "newly_observed")
        self.assertIn(
            "obstacle", event["message"].lower(),
            f"Obstacle warning missing from backpack message: {event['message']!r}",
        )


# ---------------------------------------------------------------------------
# 3. TestHallScenarioBagAlongsideMoved — obstacle warning alongside other events (2 tests)
# ---------------------------------------------------------------------------

class TestHallScenarioBagAlongsideMoved(_HallBase):
    """
    When a bag appears simultaneously with moved objects, the obstacle warning
    must still be present on the bag event and the moved-object events must
    be unaffected.
    """

    def test_obstacle_warning_present_even_alongside_moved_events(self):
        """
        Obstacle warning on backpack event is not suppressed by co-occurring
        chair and table moved events in the same observe response.
        """
        result = self._run_hall_scenario()
        bag_events = [
            e for e in result["history"]
            if e["object_name"] == "backpack"
        ]
        self.assertEqual(len(bag_events), 1)
        self.assertIn(
            "obstacle", bag_events[0]["message"].lower(),
            f"Obstacle warning missing: {bag_events[0]['message']!r}",
        )

    def test_moved_events_unaffected_when_bag_present(self):
        """
        Chair and dining table moved events are present regardless of the
        simultaneously appearing backpack.
        """
        result = self._run_hall_scenario()
        moved = [
            e for e in result["history"]
            if e["change_type"] == "moved"
        ]
        moved_names = {e["object_name"] for e in moved}
        self.assertIn("chair", moved_names,
                      f"Chair moved event missing; history: {result['history']}")
        self.assertIn("dining table", moved_names,
                      f"Dining table moved event missing; history: {result['history']}")


# ---------------------------------------------------------------------------
# 4. TestHallScenarioBaselinePreserved — baseline unchanged after monitoring (2 tests)
# ---------------------------------------------------------------------------

class TestHallScenarioBaselinePreserved(_HallBase):
    """
    Monitoring scans must never modify the stored baseline.
    After N observe calls the baseline row must still reflect the original
    4-object capture (chair, dining table, couch, potted plant) with no
    backpack and the same baseline ID.
    """

    def test_baseline_id_unchanged_after_monitoring(self):
        """
        The baseline row ID returned by GET /api/baseline must be the same
        before and after three monitoring scans.
        """
        from config import CHANGE_CONFIRMATION_FRAMES
        baseline_before = self._save_baseline()["baseline"]
        for _ in range(CHANGE_CONFIRMATION_FRAMES):
            self._observe()
        resp = self._client.get("/api/baseline?room_name=Hall")
        self.assertEqual(resp.status_code, 200)
        baseline_after = resp.get_json()["baseline"]
        self.assertEqual(
            baseline_before["id"], baseline_after["id"],
            "Baseline row ID changed after monitoring — baseline was overwritten.",
        )

    def test_baseline_detections_do_not_include_backpack(self):
        """
        The baseline was captured before the backpack appeared.
        After monitoring, GET /api/baseline must still return exactly the
        4 original objects: chair, dining table, couch, potted plant.
        The backpack (a monitoring-only object) must not appear in the baseline.
        """
        from config import CHANGE_CONFIRMATION_FRAMES
        self._save_baseline()
        for _ in range(CHANGE_CONFIRMATION_FRAMES):
            self._observe()
        resp = self._client.get("/api/baseline?room_name=Hall")
        baseline = resp.get_json()["baseline"]
        detection_names = {d["class_name"] for d in baseline["detections"]}

        self.assertNotIn(
            "backpack", detection_names,
            f"Backpack must not appear in the baseline; detections: {detection_names}",
        )
        expected_names = {"chair", "dining table", "couch", "potted plant"}
        self.assertEqual(
            detection_names, expected_names,
            f"Baseline detections mismatch.\n"
            f"  Expected: {expected_names}\n"
            f"  Got:      {detection_names}",
        )


if __name__ == "__main__":
    unittest.main()
