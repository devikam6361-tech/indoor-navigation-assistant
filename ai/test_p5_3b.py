"""
P5-3B tests: Object matching and position comparison validation.

Verifies:
  - Two chairs: one stays, one moves → only the moved chair triggers an alert.
  - Sofa (couch) unchanged → no alert produced.
  - New object (bag/backpack) appears → newly_observed event after confirmation.
  - MOVE_DISTANCE_THRESHOLD (0.14) correctly separates moved from stationary objects.
  - instance_number is preserved correctly through the matching pipeline.
  - Greedy nearest-neighbour matching correctly pairs objects across frames.

All tests use FakeModel + temporary SQLite databases (never touch the production
database) and must be run from the ai/ directory:

    python -m pytest test_p5_3b.py -v
"""

import math
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np
import base64

from config import CHANGE_CONFIRMATION_FRAMES, MOVE_DISTANCE_THRESHOLD
from services.change_detection import compare_detections, event_message


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _det(class_name, cx, cy, instance_number=1, confidence=0.90):
    """Build a minimal detection dict as compare_detections() expects."""
    from utils.formatting import image_zone
    return {
        "class_name": class_name,
        "center_x": cx,
        "center_y": cy,
        "instance_number": instance_number,
        "zone": image_zone(cx, cy),
        "confidence": confidence,
    }


def _encoded_image():
    """Return a base64 JPEG data-URL of a blank 64×48 image."""
    success, encoded = cv2.imencode(".jpg", np.zeros((48, 64, 3), dtype=np.uint8))
    assert success
    return "data:image/jpeg;base64," + base64.b64encode(encoded.tobytes()).decode("ascii")


# ---------------------------------------------------------------------------
# FakeBox / FakeResult — reused from P5-3A pattern
# ---------------------------------------------------------------------------

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
# 1. MOVE_DISTANCE_THRESHOLD unit tests (pure logic, no Flask)
# ---------------------------------------------------------------------------

class TestMoveDistanceThreshold(unittest.TestCase):
    """
    Verify that MOVE_DISTANCE_THRESHOLD is exactly 0.14 and that
    compare_detections() uses it as the boundary between 'stationary' and 'moved'.
    """

    def test_threshold_value(self):
        self.assertAlmostEqual(MOVE_DISTANCE_THRESHOLD, 0.14, places=4)

    def test_object_below_threshold_is_not_moved(self):
        """An object that moves less than the threshold should produce no candidate."""
        small_shift = MOVE_DISTANCE_THRESHOLD * 0.5   # 0.07 — clearly below
        baseline = [_det("chair", 0.50, 0.50)]
        current  = [_det("chair", 0.50 + small_shift, 0.50)]
        candidates = compare_detections(baseline, current)
        moved = [c for c in candidates if c["change_type"] == "moved"]
        self.assertEqual(len(moved), 0,
                         f"Sub-threshold shift should not be 'moved'; got {moved}")

    def test_object_exactly_at_threshold_is_not_moved(self):
        """
        Distance == threshold: greedy match absorbs the pair as 'close enough',
        so the second pass (moved pairs) skips it because distance <= threshold.
        """
        baseline = [_det("chair", 0.50, 0.50)]
        # Move only in X so distance == MOVE_DISTANCE_THRESHOLD exactly
        current  = [_det("chair", 0.50 + MOVE_DISTANCE_THRESHOLD, 0.50)]
        candidates = compare_detections(baseline, current)
        moved = [c for c in candidates if c["change_type"] == "moved"]
        self.assertEqual(len(moved), 0,
                         "Object at exactly the threshold should not be flagged as moved")

    def test_object_above_threshold_is_moved(self):
        """An object that moves more than the threshold should produce a 'moved' candidate."""
        large_shift = MOVE_DISTANCE_THRESHOLD * 2.0   # 0.28 — clearly above
        baseline = [_det("chair", 0.20, 0.50)]
        current  = [_det("chair", 0.20 + large_shift, 0.50)]
        candidates = compare_detections(baseline, current)
        moved = [c for c in candidates if c["change_type"] == "moved"]
        self.assertEqual(len(moved), 1,
                         f"Object above threshold should be 'moved'; got {candidates}")


# ---------------------------------------------------------------------------
# 2. Two chairs: one stays, one moves
# ---------------------------------------------------------------------------

class TestTwoChairsOneMovesOnestays(unittest.TestCase):
    """
    Baseline has two chairs.  In the current frame one stays put and the other
    moves well beyond the threshold.  Only the moved chair should produce a
    'moved' candidate; the stationary one should produce nothing.
    """

    def _run(self, baseline, current):
        return compare_detections(baseline, current)

    def test_only_moved_chair_produces_candidate(self):
        """Chair-1 stays; chair-2 moves far right."""
        baseline = [
            _det("chair", 0.17, 0.50, instance_number=1),   # left zone
            _det("chair", 0.83, 0.50, instance_number=2),   # right zone
        ]
        # Chair-1 stays; chair-2 moves to center
        current = [
            _det("chair", 0.17, 0.50, instance_number=1),   # same as baseline
            _det("chair", 0.50, 0.50, instance_number=2),   # moved from right to center
        ]
        candidates = self._run(baseline, current)
        moved = [c for c in candidates if c["change_type"] == "moved"]
        self.assertEqual(len(moved), 1,
                         f"Only one chair should have moved; candidates: {candidates}")

    def test_moved_chair_original_zone_is_correct(self):
        """The 'moved' candidate should record the baseline zone, not the current zone."""
        baseline = [
            _det("chair", 0.17, 0.50, instance_number=1),
            _det("chair", 0.83, 0.50, instance_number=2),
        ]
        current = [
            _det("chair", 0.17, 0.50, instance_number=1),
            _det("chair", 0.50, 0.50, instance_number=2),
        ]
        candidates = self._run(baseline, current)
        moved = [c for c in candidates if c["change_type"] == "moved"]
        self.assertEqual(len(moved), 1)
        # Chair-2 was in middle-right → moved to middle-center
        self.assertIn("right", moved[0]["original_zone"],
                      f"original_zone should be right; got {moved[0]['original_zone']}")

    def test_moved_chair_current_zone_is_correct(self):
        baseline = [
            _det("chair", 0.17, 0.50, instance_number=1),
            _det("chair", 0.83, 0.50, instance_number=2),
        ]
        current = [
            _det("chair", 0.17, 0.50, instance_number=1),
            _det("chair", 0.50, 0.50, instance_number=2),
        ]
        candidates = self._run(baseline, current)
        moved = [c for c in candidates if c["change_type"] == "moved"]
        self.assertEqual(len(moved), 1)
        self.assertIn("center", moved[0]["current_zone"],
                      f"current_zone should be center; got {moved[0]['current_zone']}")

    def test_stationary_chair_produces_no_candidate(self):
        """Chair-1 (stationary) should not appear in candidates at all."""
        baseline = [
            _det("chair", 0.17, 0.50, instance_number=1),
            _det("chair", 0.83, 0.50, instance_number=2),
        ]
        current = [
            _det("chair", 0.17, 0.50, instance_number=1),
            _det("chair", 0.50, 0.50, instance_number=2),
        ]
        candidates = self._run(baseline, current)
        # Stationary chair-1 is matched and within threshold → no candidate
        chair1_candidates = [
            c for c in candidates
            if c["change_type"] == "moved" and "right" not in c["original_zone"]
        ]
        self.assertEqual(len(chair1_candidates), 0,
                         f"Stationary chair should produce no candidate; got {chair1_candidates}")


# ---------------------------------------------------------------------------
# 3. Unchanged couch produces no candidate
# ---------------------------------------------------------------------------

class TestUnchangedCouchNoEvent(unittest.TestCase):
    """
    A couch that does not move should produce zero candidates.
    """

    def test_unchanged_couch_produces_no_candidates(self):
        baseline = [_det("couch", 0.50, 0.50)]
        current  = [_det("couch", 0.50, 0.50)]
        candidates = compare_detections(baseline, current)
        self.assertEqual(candidates, [],
                         f"Unchanged couch should produce no candidates; got {candidates}")

    def test_unchanged_couch_with_tiny_jitter_produces_no_candidates(self):
        """Sub-threshold jitter (e.g. JPEG noise) must not trigger a 'moved' event."""
        baseline = [_det("couch", 0.50, 0.50)]
        current  = [_det("couch", 0.505, 0.502)]   # < 0.14 distance
        candidates = compare_detections(baseline, current)
        moved = [c for c in candidates if c["change_type"] == "moved"]
        self.assertEqual(moved, [],
                         f"Jitter below threshold should not produce 'moved'; got {moved}")


# ---------------------------------------------------------------------------
# 4. New object (bag/backpack) → newly_observed candidate
# ---------------------------------------------------------------------------

class TestNewObjectAppearsNewlyObserved(unittest.TestCase):
    """
    A backpack not present in baseline but present in current should produce
    a 'newly_observed' candidate.
    """

    def test_new_backpack_produces_newly_observed(self):
        baseline = [_det("chair", 0.17, 0.50)]
        current  = [_det("chair", 0.17, 0.50),
                    _det("backpack", 0.50, 0.80)]  # new object
        candidates = compare_detections(baseline, current)
        new_obj = [c for c in candidates if c["change_type"] == "newly_observed"]
        self.assertEqual(len(new_obj), 1,
                         f"Expected 1 newly_observed; got {candidates}")
        self.assertEqual(new_obj[0]["class_name"], "backpack")

    def test_new_backpack_current_zone_is_set(self):
        baseline = [_det("chair", 0.17, 0.50)]
        current  = [_det("chair", 0.17, 0.50),
                    _det("backpack", 0.50, 0.80)]
        candidates = compare_detections(baseline, current)
        new_obj = [c for c in candidates if c["class_name"] == "backpack"]
        self.assertEqual(len(new_obj), 1)
        self.assertIsNotNone(new_obj[0]["current_zone"])
        self.assertIsNone(new_obj[0]["original_zone"])

    def test_new_backpack_on_floor_message(self):
        """A backpack in lower-center should trigger the obstacle warning."""
        baseline = []
        # lower-center zone: cx in [1/3, 2/3), cy >= 2/3
        current  = [_det("backpack", 0.50, 0.75)]
        candidates = compare_detections(baseline, current)
        self.assertEqual(len(candidates), 1)
        msg = event_message(candidates[0])
        self.assertIn("obstacle", msg.lower(),
                      f"Lower-center backpack should warn about obstacle; got: {msg!r}")

    def test_unmonitored_class_not_in_candidates(self):
        """'keyboard' is not in MONITORED_CLASSES — it should be silently ignored."""
        baseline = []
        current  = [_det("keyboard", 0.50, 0.50)]
        candidates = compare_detections(baseline, current)
        self.assertEqual(candidates, [],
                         f"Unmonitored class should produce no candidates; got {candidates}")


# ---------------------------------------------------------------------------
# 5. Greedy nearest-neighbour matching — instance_number preservation
# ---------------------------------------------------------------------------

class TestGreedyMatchingInstanceNumbers(unittest.TestCase):
    """
    Verify that the greedy matching algorithm correctly pairs the nearest
    baseline object to the nearest current object so that instance_number
    information is preserved in the 'moved' candidate key.
    """

    def test_nearest_pair_matched_first(self):
        """
        Baseline: chair at 0.20 and 0.80 (x).
        Current:  chair at 0.21 and 0.78.
        Both should match to their nearest counterpart (sub-threshold), no moved events.
        """
        baseline = [
            _det("chair", 0.20, 0.50, instance_number=1),
            _det("chair", 0.80, 0.50, instance_number=2),
        ]
        current = [
            _det("chair", 0.21, 0.50),
            _det("chair", 0.78, 0.50),
        ]
        candidates = compare_detections(baseline, current)
        self.assertEqual(candidates, [],
                         f"Both chairs sub-threshold → no candidates; got {candidates}")

    def test_moved_candidate_key_contains_instance_number(self):
        """
        A moved object's key should embed the baseline instance_number so that
        the tracker can deduplicate across frames.
        """
        baseline = [_det("chair", 0.17, 0.50, instance_number=3)]
        # Move far enough to exceed the threshold
        current  = [_det("chair", 0.17 + MOVE_DISTANCE_THRESHOLD * 2, 0.50)]
        candidates = compare_detections(baseline, current)
        moved = [c for c in candidates if c["change_type"] == "moved"]
        self.assertEqual(len(moved), 1)
        # Key format: "moved:{name}:{instance_number}:{zone}:{x_bucket}:{y_bucket}"
        self.assertIn(":3:", moved[0]["key"],
                      f"instance_number 3 should appear in key; got {moved[0]['key']}")

    def test_cross_match_not_swapped(self):
        """
        When two chairs are on opposite sides and both move a little (sub-threshold),
        the greedy algorithm should NOT swap them (which would create spurious moved events).
        Chair-A at 0.10 stays near 0.11; chair-B at 0.90 stays near 0.89.
        """
        baseline = [
            _det("chair", 0.10, 0.50, instance_number=1),
            _det("chair", 0.90, 0.50, instance_number=2),
        ]
        current = [
            _det("chair", 0.11, 0.50),
            _det("chair", 0.89, 0.50),
        ]
        candidates = compare_detections(baseline, current)
        self.assertEqual(candidates, [],
                         f"Sub-threshold non-swapped chairs → no events; got {candidates}")


# ---------------------------------------------------------------------------
# 6. event_message() text correctness
# ---------------------------------------------------------------------------

class TestEventMessageText(unittest.TestCase):
    """
    Verify the voice message text produced by event_message() for each
    change type, including zone labels and obstacle warnings.
    """

    def _candidate(self, change_type, class_name="chair",
                   original_zone=None, current_zone=None):
        return {
            "class_name": class_name,
            "change_type": change_type,
            "original_zone": original_zone,
            "current_zone": current_zone,
            "confidence": 0.85,
        }

    def test_moved_different_zones_message(self):
        c = self._candidate("moved", "chair",
                            original_zone="middle-right",
                            current_zone="middle-left")
        msg = event_message(c)
        self.assertIn("moved", msg.lower())
        self.assertIn("right", msg.lower())
        self.assertIn("left", msg.lower())

    def test_moved_same_zone_message(self):
        """When zones are identical the message says 'shifted within'."""
        c = self._candidate("moved", "chair",
                            original_zone="middle-center",
                            current_zone="middle-center")
        msg = event_message(c)
        self.assertIn("shifted", msg.lower())

    def test_not_currently_visible_message(self):
        c = self._candidate("not_currently_visible", "couch",
                            original_zone="middle-left")
        msg = event_message(c)
        self.assertIn("not currently visible", msg.lower())
        self.assertIn("couch", msg.lower())

    def test_newly_observed_non_obstacle_message(self):
        c = self._candidate("newly_observed", "potted plant",
                            current_zone="upper-right")
        msg = event_message(c)
        self.assertIn("new", msg.lower())
        self.assertIn("potted plant", msg.lower())
        self.assertNotIn("obstacle", msg.lower())

    def test_newly_observed_lower_center_obstacle_message(self):
        """Chair in lower-center → obstacle warning appended."""
        c = self._candidate("newly_observed", "chair",
                            current_zone="lower-center")
        msg = event_message(c)
        self.assertIn("obstacle", msg.lower())

    def test_couch_move_does_not_trigger_obstacle_warning(self):
        """
        'couch' is not in the obstacle-warning class set, so a couch in
        lower-center should NOT trigger the obstacle message.
        """
        c = self._candidate("moved", "couch",
                            original_zone="middle-left",
                            current_zone="lower-center")
        msg = event_message(c)
        self.assertNotIn("obstacle", msg.lower(),
                         f"couch should not trigger obstacle warning; got: {msg!r}")


# ---------------------------------------------------------------------------
# 7. Flask integration: two-chair scenario with confirmation frames
# ---------------------------------------------------------------------------

class FakeModelTwoChairsOneMoves:
    """
    Call 1  → baseline: chair-1 left, chair-2 right.
    Calls 2+ → monitoring: chair-1 stays left, chair-2 moves to center-left.
    """
    names = {0: "chair"}
    _call_count = 0

    def __call__(self, frame, conf, verbose):
        self._call_count += 1
        if self._call_count == 1:
            # Baseline: chair-1 at ~x=0.17 (left), chair-2 at ~x=0.83 (right)
            # 64px wide frame: left chair bbox [0,4,20,44], right [44,4,62,44]
            return [FakeResult([
                FakeBox(0, 0.90, [0,  4, 20, 44]),
                FakeBox(0, 0.88, [44, 4, 62, 44]),
            ])]
        # Monitoring: chair-1 stays, chair-2 moves to center
        return [FakeResult([
            FakeBox(0, 0.90, [0,  4, 20, 44]),   # chair-1 unchanged
            FakeBox(0, 0.86, [22, 4, 42, 44]),   # chair-2 moved to center
        ])]


class TestTwoChairsFlaskIntegration(unittest.TestCase):

    def setUp(self):
        from unittest.mock import patch
        self._tmp = tempfile.TemporaryDirectory()
        self._model = FakeModelTwoChairsOneMoves()
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

    def test_baseline_stores_two_chairs(self):
        data = self._save_baseline()
        chairs = [d for d in data["baseline"]["detections"] if d["class_name"] == "chair"]
        self.assertEqual(len(chairs), 2)

    def test_only_moved_chair_triggers_alert_after_confirmation(self):
        self._save_baseline()
        result = None
        for _ in range(CHANGE_CONFIRMATION_FRAMES + 1):
            result = self._observe()
        chair_events = [e for e in result["history"] if e["object_name"] == "chair"]
        # Exactly one chair event (the moved one)
        self.assertEqual(len(chair_events), 1,
                         f"Expected exactly 1 chair event; history: {result['history']}")
        self.assertEqual(chair_events[0]["change_type"], "moved")

    def test_no_spurious_events_for_stationary_chair(self):
        """The stationary chair must not appear in alerts at any point."""
        self._save_baseline()
        for _ in range(CHANGE_CONFIRMATION_FRAMES + 2):
            result = self._observe()
        # All chair events should be 'moved', never 'newly_observed' or 'not_currently_visible'
        chair_events = result["history"]
        bad = [e for e in chair_events
               if e["object_name"] == "chair" and e["change_type"] != "moved"]
        self.assertEqual(bad, [],
                         f"No spurious chair events expected; got {bad}")


# ---------------------------------------------------------------------------
# 8. Flask integration: new bag (backpack) → newly_observed after confirmation
# ---------------------------------------------------------------------------

class FakeModelChairThenBag:
    """
    Call 1   → baseline: one chair only.
    Calls 2+ → monitoring: same chair + a backpack on the floor (lower-center).
    """
    names = {0: "chair", 24: "backpack"}  # COCO id 24 = backpack
    _call_count = 0

    def __call__(self, frame, conf, verbose):
        self._call_count += 1
        if self._call_count == 1:
            return [FakeResult([FakeBox(0, 0.90, [4, 4, 20, 20])])]
        # Chair unchanged + backpack in lower-center
        return [FakeResult([
            FakeBox(0,  0.90, [4,  4,  20, 20]),
            FakeBox(24, 0.80, [22, 34, 42, 46]),  # lower-center in 48px-tall frame
        ])]


class TestNewBackpackIntegration(unittest.TestCase):

    def setUp(self):
        from unittest.mock import patch
        self._tmp = tempfile.TemporaryDirectory()
        self._model = FakeModelChairThenBag()
        self._app = _make_app(self._model, self._tmp.name)
        self._client = self._app.test_client()
        self._image = _encoded_image()
        self._view_patch = patch("server.camera_view_status", return_value="stable")
        self._view_patch.start()

    def tearDown(self):
        self._view_patch.stop()
        self._tmp.cleanup()

    def test_new_backpack_produces_newly_observed_event(self):
        self._client.post("/api/baseline", json={
            "room_name": "Hall",
            "image": self._image,
        })
        result = None
        for _ in range(CHANGE_CONFIRMATION_FRAMES + 1):
            resp = self._client.post("/api/observe", json={
                "room_name": "Hall",
                "image": self._image,
            })
            result = resp.get_json()
        bag_events = [e for e in result["history"] if e["object_name"] == "backpack"]
        self.assertTrue(len(bag_events) > 0,
                        f"Expected backpack event; history: {result['history']}")
        self.assertEqual(bag_events[0]["change_type"], "newly_observed")

    def test_chair_unchanged_no_chair_event(self):
        """The chair that does not move should produce no event."""
        self._client.post("/api/baseline", json={
            "room_name": "Hall",
            "image": self._image,
        })
        result = None
        for _ in range(CHANGE_CONFIRMATION_FRAMES + 1):
            resp = self._client.post("/api/observe", json={
                "room_name": "Hall",
                "image": self._image,
            })
            result = resp.get_json()
        chair_events = [e for e in result["history"] if e["object_name"] == "chair"]
        self.assertEqual(chair_events, [],
                         f"Stationary chair should produce no events; got {chair_events}")


if __name__ == "__main__":
    unittest.main()
