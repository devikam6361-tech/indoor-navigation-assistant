"""
P5-3C tests: Temporarily missing object detection.

Verifies:
  G1  Exactly 1 frame absent then returns  → 0 alerts throughout.
  G2  Exactly 2 frames absent then returns → 0 alerts throughout.
  G3  Counter resets after reappearance    → disappear again 2 frames still 0 alerts.
  G4  Camera moved wipes pending count     → missing count built to 2, camera moves,
                                             then 2 more absent frames → still 0 alerts.
  G5  Two chairs, one disappears           → only the missing one fires.
  G6  Missing-object tracking isolated     → room A missing object; room B unaffected.
  G7  not_currently_visible message text   → exact phrases via unit test on event_message().
  G8  Duplicate-alert suppression          → frames 4 and 5 produce no new alert.

No production files are modified.
Run from the ai/ directory:

    python -m pytest test_p5_3c.py -v
"""

import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from services.change_detection import event_message


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
# G7: not_currently_visible message wording (pure unit tests — no Flask)
# ---------------------------------------------------------------------------

class TestMissingObjectMessageText(unittest.TestCase):
    """
    Verify the exact voice-announcement text produced by event_message()
    for a not_currently_visible candidate.
    """

    def _candidate(self, class_name="chair", original_zone="middle-left"):
        return {
            "class_name": class_name,
            "change_type": "not_currently_visible",
            "original_zone": original_zone,
            "current_zone": None,
            "confidence": 0.88,
        }

    def test_message_contains_not_currently_visible(self):
        msg = event_message(self._candidate("chair", "middle-left"))
        self.assertIn(
            "not currently visible", msg.lower(),
            f"Expected 'not currently visible' in message; got: {msg!r}",
        )

    def test_message_does_not_say_removed(self):
        msg = event_message(self._candidate("couch", "upper-right"))
        self.assertIn(
            "does not confirm it was removed", msg,
            f"Expected removal disclaimer; got: {msg!r}",
        )


# ---------------------------------------------------------------------------
# Base class for Flask-based missing-object tests
# ---------------------------------------------------------------------------

class _MissingBase(unittest.TestCase):
    """Sets up a single-chair baseline and starts the camera_view_status patch."""

    # Subclasses override to supply different FakeModel classes.
    MODEL_CLASS = None

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._model = self.MODEL_CLASS()
        self._app = _make_app(self._model, self._tmp.name)
        self._client = self._app.test_client()
        self._image = _encoded_image()
        self._view_patch = patch("server.camera_view_status", return_value="stable")
        self._view_patch.start()

    def tearDown(self):
        self._view_patch.stop()
        self._tmp.cleanup()

    def _baseline(self, room="Hall"):
        resp = self._client.post("/api/baseline", json={
            "room_name": room,
            "image": self._image,
        })
        self.assertEqual(resp.status_code, 201)
        return resp.get_json()

    def _observe(self, room="Hall"):
        resp = self._client.post("/api/observe", json={
            "room_name": room,
            "image": self._image,
        })
        self.assertEqual(resp.status_code, 200)
        return resp.get_json()

    def _alerts_of_type(self, result, change_type):
        return [e for e in result["alerts"] if e["change_type"] == change_type]

    def _history_of_type(self, result, change_type):
        return [e for e in result["history"] if e["change_type"] == change_type]


# ---------------------------------------------------------------------------
# G1: Exactly 1 frame absent then returns
# ---------------------------------------------------------------------------

class _ModelChairOneThenGoneThenBack:
    """Call 1 → baseline (chair present).  Call 2 → absent.  Call 3+ → present."""
    names = {0: "chair"}
    _n = 0

    def __call__(self, frame, conf, verbose):
        self._n += 1
        if self._n == 2:  # one absent frame
            return [FakeResult([])]
        return [FakeResult([FakeBox(0, 0.90, [4, 4, 20, 24])])]


class TestOcclusionOneFrame(_MissingBase):
    MODEL_CLASS = _ModelChairOneThenGoneThenBack

    def test_one_absent_frame_produces_no_alert(self):
        """1 absent frame < CHANGE_CONFIRMATION_FRAMES → no alert."""
        self._baseline()
        result = self._observe()   # frame 2: chair absent
        self.assertEqual(result["alerts"], [],
                         f"1 absent frame should produce no alert; got {result['alerts']}")

    def test_object_returns_after_one_absent_frame_still_no_alert(self):
        """Chair returns on frame 3 → counter reset, still no alert."""
        self._baseline()
        self._observe()           # frame 2: absent
        result = self._observe()  # frame 3: back
        self.assertEqual(result["alerts"], [],
                         f"Return after 1 absent frame should produce no alert; got {result['alerts']}")


# ---------------------------------------------------------------------------
# G2: Exactly 2 frames absent then returns
# ---------------------------------------------------------------------------

class _ModelChairTwoAbsentThenBack:
    """Call 1 → baseline.  Calls 2–3 → absent.  Calls 4+ → present."""
    names = {0: "chair"}
    _n = 0

    def __call__(self, frame, conf, verbose):
        self._n += 1
        if self._n in (2, 3):
            return [FakeResult([])]
        return [FakeResult([FakeBox(0, 0.90, [4, 4, 20, 24])])]


class TestOcclusionTwoFrames(_MissingBase):
    MODEL_CLASS = _ModelChairTwoAbsentThenBack

    def test_two_absent_frames_produce_no_alert(self):
        """2 absent frames < CHANGE_CONFIRMATION_FRAMES (3) → no alert."""
        self._baseline()
        self._observe()           # frame 2: absent
        result = self._observe()  # frame 3: absent
        self.assertEqual(result["alerts"], [],
                         f"2 absent frames should produce no alert; got {result['alerts']}")

    def test_object_returns_after_two_absent_frames_still_no_alert(self):
        """Chair returns after 2 absent frames → counter was reset, no alert."""
        self._baseline()
        self._observe()           # frame 2: absent
        self._observe()           # frame 3: absent
        result = self._observe()  # frame 4: back
        self.assertEqual(result["alerts"], [],
                         f"Return after 2 absent frames should produce no alert; got {result['alerts']}")


# ---------------------------------------------------------------------------
# G3: Counter resets after reappearance
# ---------------------------------------------------------------------------

class _ModelChairDisappearReturnDisappear:
    """
    Baseline: chair present.
    Frames 2-3: absent (count → 2, no alert yet).
    Frame 4:    present (count reset to 0).
    Frames 5-6: absent again (count → 2, still no alert — below threshold).
    """
    names = {0: "chair"}
    _n = 0

    def __call__(self, frame, conf, verbose):
        self._n += 1
        if self._n in (2, 3, 5, 6):
            return [FakeResult([])]
        return [FakeResult([FakeBox(0, 0.90, [4, 4, 20, 24])])]


class TestCounterResetsAfterReappearance(_MissingBase):
    MODEL_CLASS = _ModelChairDisappearReturnDisappear

    def test_counter_resets_on_reappearance(self):
        """
        Absent × 2 → return × 1 → absent × 2.
        The second run of 2 absent frames must NOT fire an alert because the
        counter was reset to 0 when the chair reappeared on frame 4.
        """
        self._baseline()
        self._observe()           # frame 2: absent (count=1)
        self._observe()           # frame 3: absent (count=2, below threshold of 3)
        self._observe()           # frame 4: present (count reset)
        self._observe()           # frame 5: absent (count=1)
        result = self._observe()  # frame 6: absent (count=2, still below threshold)
        self.assertEqual(result["alerts"], [],
                         f"Second 2-frame absence after reset should not alert; got {result['alerts']}")

    def test_first_disappearance_run_also_produces_no_alert(self):
        """Sanity: first run of 2 absent frames alone produces no alert."""
        self._baseline()
        self._observe()           # frame 2: absent
        result = self._observe()  # frame 3: absent (count=2 < 3)
        self.assertEqual(result["alerts"], [],
                         f"First 2-frame absence should not alert; got {result['alerts']}")


# ---------------------------------------------------------------------------
# G7 + persistent: Persistent absence produces not_currently_visible
# ---------------------------------------------------------------------------

class _ModelChairAlwaysAbsent:
    """Baseline: chair present.  All monitoring frames: chair absent."""
    names = {0: "chair"}
    _n = 0

    def __call__(self, frame, conf, verbose):
        self._n += 1
        if self._n == 1:
            return [FakeResult([FakeBox(0, 0.90, [4, 4, 20, 24])])]
        return [FakeResult([])]


class TestPersistentMissingEvent(_MissingBase):
    MODEL_CLASS = _ModelChairAlwaysAbsent

    def test_no_alert_before_confirmation(self):
        """Frames 2 and 3 (count 1 and 2) must not emit an alert."""
        from config import CHANGE_CONFIRMATION_FRAMES
        self._baseline()
        for i in range(CHANGE_CONFIRMATION_FRAMES - 1):
            result = self._observe()
            self.assertEqual(result["alerts"], [],
                             f"Frame {i+2} (count {i+1}) should not alert yet; got {result['alerts']}")

    def test_alert_fires_on_confirmation_frame(self):
        """Frame CHANGE_CONFIRMATION_FRAMES (the 3rd) must emit not_currently_visible."""
        from config import CHANGE_CONFIRMATION_FRAMES
        self._baseline()
        result = None
        for _ in range(CHANGE_CONFIRMATION_FRAMES):
            result = self._observe()
        missing = self._alerts_of_type(result, "not_currently_visible")
        self.assertEqual(len(missing), 1,
                         f"Expected 1 not_currently_visible alert; got {result['alerts']}")

    def test_alert_message_does_not_say_removed(self):
        """
        Confirmed message must include the disclaimer 'does not confirm it was removed'
        and must NOT flatly assert that the object was removed (i.e. it must not
        contain 'was removed' without the negating disclaimer prefix).
        """
        from config import CHANGE_CONFIRMATION_FRAMES
        self._baseline()
        result = None
        for _ in range(CHANGE_CONFIRMATION_FRAMES):
            result = self._observe()
        msg = result["alerts"][0]["message"]
        self.assertIn("not currently visible", msg.lower())
        # The disclaimer must be present — it negates any removal claim.
        self.assertIn(
            "does not confirm it was removed", msg,
            f"Disclaimer must be present; got: {msg!r}",
        )
        # The message must not open with an unqualified removal statement.
        self.assertNotIn(
            "has been removed", msg.lower(),
            f"Message must not assert removal; got: {msg!r}",
        )


# ---------------------------------------------------------------------------
# G8: Duplicate-alert suppression
# ---------------------------------------------------------------------------

class TestDuplicateAlertSuppression(_MissingBase):
    MODEL_CLASS = _ModelChairAlwaysAbsent

    def test_no_duplicate_on_fourth_frame(self):
        """Frame 4 — object still absent but already announced → no new alert."""
        from config import CHANGE_CONFIRMATION_FRAMES
        self._baseline()
        for _ in range(CHANGE_CONFIRMATION_FRAMES):
            self._observe()
        result = self._observe()   # frame 4
        missing = self._alerts_of_type(result, "not_currently_visible")
        self.assertEqual(missing, [],
                         f"Frame 4 should not re-emit already-announced alert; got {missing}")

    def test_no_duplicate_on_fifth_frame(self):
        """Frame 5 — still absent, still announced → no new alert."""
        from config import CHANGE_CONFIRMATION_FRAMES
        self._baseline()
        for _ in range(CHANGE_CONFIRMATION_FRAMES):
            self._observe()
        self._observe()            # frame 4
        result = self._observe()   # frame 5
        missing = self._alerts_of_type(result, "not_currently_visible")
        self.assertEqual(missing, [],
                         f"Frame 5 should not re-emit already-announced alert; got {missing}")


# ---------------------------------------------------------------------------
# G4: Camera moved wipes pending missing count
# ---------------------------------------------------------------------------

class _ModelChairBaselineThenAlwaysAbsent:
    """Baseline: chair.  All subsequent frames: no detections."""
    names = {0: "chair"}
    _n = 0

    def __call__(self, frame, conf, verbose):
        self._n += 1
        if self._n == 1:
            return [FakeResult([FakeBox(0, 0.90, [4, 4, 20, 24])])]
        return [FakeResult([])]


class TestCameraMovedWipesPendingCount(_MissingBase):
    MODEL_CLASS = _ModelChairBaselineThenAlwaysAbsent

    def test_camera_move_resets_missing_count(self):
        """
        Absent × 2 (count=2) → camera moves (count cleared) → absent × 2 again.
        The second 2-frame run must NOT fire because the count was wiped.
        """
        self._baseline()

        # Build up count to 2 with stable camera
        self._observe()   # absent, count=1
        self._observe()   # absent, count=2 (below threshold of 3, no alert yet)

        # Camera moves — tracker["counts"].clear() is called
        with patch("server.camera_view_status", return_value="moved"):
            cam_result = self._observe()

        self.assertEqual(cam_result["status"], "camera_moved")

        # Two more absent frames with stable camera — count starts from 0 again
        self._observe()          # absent, count=1
        result = self._observe() # absent, count=2 (below threshold → no alert)

        missing = self._alerts_of_type(result, "not_currently_visible")
        self.assertEqual(missing, [],
                         f"After camera move reset, 2 absent frames should not alert; got {missing}")

    def test_camera_move_produces_camera_event_not_object_event(self):
        """
        When the camera moves, only a camera_view_changed event is emitted,
        never a not_currently_visible event.
        """
        self._baseline()
        self._observe()   # absent, count=1

        with patch("server.camera_view_status", return_value="moved"):
            result = self._observe()

        camera_alerts = self._alerts_of_type(result, "camera_view_changed")
        object_alerts = self._alerts_of_type(result, "not_currently_visible")
        self.assertEqual(len(camera_alerts), 1)
        self.assertEqual(object_alerts, [],
                         f"Camera-moved frame must not emit object alerts; got {object_alerts}")


# ---------------------------------------------------------------------------
# G5: Two chairs — one disappears, one stays
# ---------------------------------------------------------------------------

class _ModelTwoChairsOneDisappears:
    """
    Call 1  → baseline: two chairs side-by-side.
    Calls 2+ → monitoring: only the left chair remains; right chair gone.
    """
    names = {0: "chair"}
    _n = 0

    def __call__(self, frame, conf, verbose):
        self._n += 1
        if self._n == 1:
            return [FakeResult([
                FakeBox(0, 0.90, [0,  4, 20, 44]),   # chair-1 left
                FakeBox(0, 0.88, [44, 4, 62, 44]),   # chair-2 right
            ])]
        # Only chair-1 (left) present in monitoring frames
        return [FakeResult([FakeBox(0, 0.90, [0, 4, 20, 44])])]


class TestTwoChairsOneMissing(_MissingBase):
    MODEL_CLASS = _ModelTwoChairsOneDisappears

    def test_only_missing_chair_fires_alert(self):
        """After confirmation, exactly one not_currently_visible for the missing chair."""
        from config import CHANGE_CONFIRMATION_FRAMES
        self._baseline()
        result = None
        for _ in range(CHANGE_CONFIRMATION_FRAMES):
            result = self._observe()
        missing = self._alerts_of_type(result, "not_currently_visible")
        self.assertEqual(len(missing), 1,
                         f"Exactly 1 missing chair expected; alerts: {result['alerts']}")

    def test_stationary_chair_does_not_appear_in_missing_alerts(self):
        """The chair that stayed put must never appear as not_currently_visible."""
        from config import CHANGE_CONFIRMATION_FRAMES
        self._baseline()
        result = None
        for _ in range(CHANGE_CONFIRMATION_FRAMES + 1):
            result = self._observe()
        # All history should have at most one not_currently_visible (the missing one)
        # and that one should be for a chair — the stationary chair generates no event
        missing_events = self._history_of_type(result, "not_currently_visible")
        self.assertLessEqual(len(missing_events), 1,
                             f"At most 1 missing-chair event expected; history: {result['history']}")

    def test_missing_chair_message_references_its_original_zone(self):
        """The not_currently_visible message must name the zone where the chair was."""
        from config import CHANGE_CONFIRMATION_FRAMES
        self._baseline()
        result = None
        for _ in range(CHANGE_CONFIRMATION_FRAMES):
            result = self._observe()
        missing = self._alerts_of_type(result, "not_currently_visible")
        self.assertEqual(len(missing), 1)
        msg = missing[0]["message"]
        # Chair-2 was in the right zone of the 64-pixel-wide frame
        self.assertIn("right", msg.lower(),
                      f"Message should mention 'right' zone; got: {msg!r}")


# ---------------------------------------------------------------------------
# G6: Missing-object tracking isolated between rooms
# ---------------------------------------------------------------------------

class _ModelChairBaselineOnly:
    """Always returns a chair — baseline sets it; monitoring frames also see it."""
    names = {0: "chair"}

    def __call__(self, frame, conf, verbose):
        return [FakeResult([FakeBox(0, 0.90, [4, 4, 20, 24])])]


class _ModelChairBaselineThenMissing:
    """Call 1 → chair in baseline.  Calls 2+ → no detections (chair missing)."""
    names = {0: "chair"}
    _n = 0

    def __call__(self, frame, conf, verbose):
        self._n += 1
        if self._n == 1:
            return [FakeResult([FakeBox(0, 0.90, [4, 4, 20, 24])])]
        return [FakeResult([])]


class TestMissingObjectRoomIsolation(unittest.TestCase):
    """
    Room A has a persistently missing chair that eventually fires an event.
    Room B has the same chair present in every frame.
    Room B must never receive a not_currently_visible event.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._image = _encoded_image()
        self._view_patch = patch("server.camera_view_status", return_value="stable")
        self._view_patch.start()

    def tearDown(self):
        self._view_patch.stop()
        self._tmp.cleanup()

    def _run_scenario(self):
        """
        Room A: missing chair model.  Room B: chair always present model.
        Returns (room_a_last_result, room_b_last_result) after confirmation frames.
        """
        from config import CHANGE_CONFIRMATION_FRAMES

        # Two separate apps share the same temp database (different baseline rows)
        model_a = _ModelChairBaselineThenMissing()
        model_b = _ModelChairBaselineOnly()
        app_a = _make_app(model_a, self._tmp.name)
        # Room B uses the same DB file (same as production would); inject a
        # second model to simulate a second camera session
        db_path = Path(self._tmp.name) / "layout.sqlite3"

        from server import create_app
        app_b = create_app(db_path, detector=model_b)
        app_b.config["TESTING"] = True

        client_a = app_a.test_client()
        client_b = app_b.test_client()

        # Baselines for both rooms
        client_a.post("/api/baseline", json={"room_name": "Hall",    "image": self._image})
        client_b.post("/api/baseline", json={"room_name": "Kitchen", "image": self._image})

        result_a = result_b = None
        for _ in range(CHANGE_CONFIRMATION_FRAMES + 1):
            result_a = client_a.post("/api/observe",
                                     json={"room_name": "Hall",    "image": self._image}).get_json()
            result_b = client_b.post("/api/observe",
                                     json={"room_name": "Kitchen", "image": self._image}).get_json()

        return result_a, result_b

    def test_room_a_missing_chair_fires(self):
        """Hall (room A) should produce a not_currently_visible event."""
        result_a, _ = self._run_scenario()
        all_a = [e for e in result_a["history"] if e["change_type"] == "not_currently_visible"]
        self.assertTrue(len(all_a) > 0,
                        f"Hall should have a missing-chair event; history: {result_a['history']}")

    def test_room_b_unaffected_by_room_a_missing_object(self):
        """Kitchen (room B) must have zero not_currently_visible events."""
        _, result_b = self._run_scenario()
        missing_b = [e for e in result_b["history"] if e["change_type"] == "not_currently_visible"]
        self.assertEqual(missing_b, [],
                         f"Kitchen should have no missing-object events; got {missing_b}")


if __name__ == "__main__":
    unittest.main()
