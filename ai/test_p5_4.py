"""
P5-4 tests: False-alert suppression and detection stability.

Focus areas:
  1. Severe lighting changes and blank frames (ORB stability / unknown fallback).
  2. Camera movement suppressing pending object alerts (tracker wipe).
  3. View restoration and clean tracker reset (no premature confirmation).
  4. Bounding-box center jitter suppression (shifts < MOVE_DISTANCE_THRESHOLD).
  5. Intermittent YOLO class-label flickering (alternating detections suppressed).
  6. Duplicate-alert cooldown and sustained state deduplication.

No production files are modified. Run from the ai/ directory:
    python -m pytest test_p5_4.py -v
"""

import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from config import (
    CHANGE_CONFIRMATION_FRAMES,
    MOVE_DISTANCE_THRESHOLD,
    OBJECT_COOLDOWN_SECONDS,
)
from services.camera_validation import camera_view_status


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _encoded_image(img=None):
    """Return a base64 JPEG data-URL of an image (default: blank 64x48)."""
    if img is None:
        img = np.zeros((48, 64, 3), dtype=np.uint8)
    success, encoded = cv2.imencode(".jpg", img)
    assert success
    return "data:image/jpeg;base64," + base64.b64encode(encoded.tobytes()).decode("ascii")


def _textured_image(seed=42, width=320, height=240):
    """Generate a rich, repeatable textured image suitable for ORB keypoint detection."""
    rng = np.random.default_rng(seed)
    noise = rng.integers(0, 256, (height, width), dtype=np.uint8)
    blurred = cv2.GaussianBlur(noise, (5, 5), 0)
    color = cv2.cvtColor(blurred, cv2.COLOR_GRAY2BGR)
    # Add high-contrast geometric landmarks to guarantee plentiful ORB features
    for x in range(30, width - 30, 40):
        for y in range(30, height - 30, 40):
            cv2.rectangle(color, (x, y), (x + 15, y + 15), (0, 255, 0), -1)
            cv2.circle(color, (x + 25, y + 25), 8, (255, 0, 0), -1)
    return color


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
# 1. Severe lighting changes and blank frames
# ---------------------------------------------------------------------------

class TestLightingAndBlankFrames(unittest.TestCase):
    """
    Validates camera_view_status and observe route under severe lighting shifts
    and featureless (blank) frames.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ref_img = _textured_image(seed=101)
        ok, buf = cv2.imencode(".jpg", self.ref_img)
        self.assertTrue(ok)
        self.ref_bytes = buf.tobytes()

    def tearDown(self):
        self._tmp.cleanup()

    def test_camera_view_blank_frame_returns_unknown(self):
        """A featureless solid blank image must return 'unknown', never 'moved' or 'stable'."""
        blank_frame = np.zeros_like(self.ref_img)
        status = camera_view_status(self.ref_bytes, blank_frame)
        self.assertEqual(
            status, "unknown",
            f"Solid black frame must return 'unknown'; got {status!r}",
        )

    def test_camera_view_lighting_shift_does_not_flag_moved(self):
        """
        A severe brightness / contrast adjustment without physical camera movement
        must remain 'stable' or safely fall back to 'unknown', but never report 'moved'.
        """
        # Dim the image significantly and add contrast scaling
        dimmed = cv2.convertScaleAbs(self.ref_img, alpha=0.55, beta=-20)
        status = camera_view_status(self.ref_bytes, dimmed)
        self.assertIn(
            status, {"stable", "unknown"},
            f"Lighting change must not falsely report camera movement; got {status!r}",
        )

    def test_observe_with_unverified_view_emits_no_object_alerts(self):
        """
        When camera_view_status is 'unknown', /api/observe must report 'view_unverified',
        suppress object detections (latest=None), and emit zero object change alerts.
        """
        class ModelWithChair:
            names = {0: "chair"}
            def __call__(self, frame, conf, verbose):
                return [FakeResult([FakeBox(0, 0.90, [10, 10, 30, 30])])]

        app = _make_app(ModelWithChair(), self._tmp.name)
        client = app.test_client()
        img = _encoded_image()

        # Capture baseline under stable view
        with patch("server.camera_view_status", return_value="stable"):
            res_b = client.post("/api/baseline", json={"room_name": "Living room", "image": img})
            self.assertEqual(res_b.status_code, 201)

        # Observe under 'unknown' camera view
        with patch("server.camera_view_status", return_value="unknown"):
            res_o = client.post("/api/observe", json={"room_name": "Living room", "image": img})
            self.assertEqual(res_o.status_code, 200)
            data = res_o.get_json()
            self.assertEqual(data["status"], "view_unverified")
            self.assertIsNone(data["latest"])
            # Alerts must contain no object alerts (only camera alert if any)
            object_alerts = [
                a for a in data["alerts"]
                if a["change_type"] in {"moved", "newly_observed", "not_currently_visible"}
            ]
            self.assertEqual(
                object_alerts, [],
                f"No object alerts allowed when view is unverified; got {object_alerts}",
            )


# ---------------------------------------------------------------------------
# 2. Camera movement suppressing pending object alerts
# ---------------------------------------------------------------------------

class TestCameraMovementSuppressesPendingAlerts(unittest.TestCase):
    """
    Validates that physical camera movement immediately aborts any in-progress
    multi-frame confirmation counters and emits zero false object alerts.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._image = _encoded_image()

    def tearDown(self):
        self._tmp.cleanup()

    def test_camera_movement_suppresses_pending_missing_alert(self):
        """
        Chair missing for 2 frames (count=2, < 3). On frame 3, camera moves.
        Must report 'camera_moved', wipe tracker counts, and emit no missing alert.
        """
        class ModelBaselineOnly:
            names = {0: "chair"}
            call_count = 0
            def __call__(self, frame, conf, verbose):
                self.call_count += 1
                if self.call_count == 1:
                    return [FakeResult([FakeBox(0, 0.90, [4, 4, 20, 24])])]
                return [FakeResult([])]

        app = _make_app(ModelBaselineOnly(), self._tmp.name)
        client = app.test_client()

        with patch("server.camera_view_status", return_value="stable"):
            client.post("/api/baseline", json={"room_name": "Hall", "image": self._image})
            # 2 frames missing under stable view (count reaches 2)
            for _ in range(2):
                r = client.post("/api/observe", json={"room_name": "Hall", "image": self._image}).get_json()
                self.assertEqual(r["alerts"], [])

        # Frame 3: camera moves
        with patch("server.camera_view_status", return_value="moved"):
            r3 = client.post("/api/observe", json={"room_name": "Hall", "image": self._image}).get_json()
            self.assertEqual(r3["status"], "camera_moved")
            missing_alerts = [a for a in r3["alerts"] if a["change_type"] == "not_currently_visible"]
            self.assertEqual(
                missing_alerts, [],
                "Camera movement must suppress pending missing object alert.",
            )

    def test_camera_movement_suppresses_pending_newly_observed_alert(self):
        """
        New backpack appears for 2 frames (count=2, < 3). On frame 3, camera moves.
        Must not emit newly_observed alert.
        """
        class ModelNewBagOnMonitoring:
            names = {0: "chair", 1: "backpack"}
            call_count = 0
            def __call__(self, frame, conf, verbose):
                self.call_count += 1
                if self.call_count == 1:
                    return [FakeResult([FakeBox(0, 0.90, [4, 4, 20, 24])])]
                # Monitoring frames have chair + new backpack
                return [FakeResult([
                    FakeBox(0, 0.90, [4, 4, 20, 24]),
                    FakeBox(1, 0.85, [22, 34, 42, 46]),
                ])]

        app = _make_app(ModelNewBagOnMonitoring(), self._tmp.name)
        client = app.test_client()

        with patch("server.camera_view_status", return_value="stable"):
            client.post("/api/baseline", json={"room_name": "Hall", "image": self._image})
            for _ in range(2):
                client.post("/api/observe", json={"room_name": "Hall", "image": self._image})

        with patch("server.camera_view_status", return_value="moved"):
            r_move = client.post("/api/observe", json={"room_name": "Hall", "image": self._image}).get_json()
            new_alerts = [a for a in r_move["alerts"] if a["change_type"] == "newly_observed"]
            self.assertEqual(
                new_alerts, [],
                "Camera movement must suppress pending newly_observed alert.",
            )


# ---------------------------------------------------------------------------
# 3. View restoration and tracker reset
# ---------------------------------------------------------------------------

class TestViewRestorationAndTrackerReset(unittest.TestCase):
    """
    Validates that after camera view is restored, confirmation counters start fresh
    and do not prematurely fire based on pre-movement pending counts.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._image = _encoded_image()

    def tearDown(self):
        self._tmp.cleanup()

    def test_view_restoration_resets_tracker_requiring_full_confirmation(self):
        """
        Sequence:
          1. Chair absent for 2 frames under stable view (count=2).
          2. Camera moves on frame 3 (counts wiped).
          3. Camera restored on frame 4 (status = camera_view_restored).
          4. Chair absent for frame 4 and 5 (count = 1, then 2).
        Alert must NOT fire on frame 4 or 5; it must require a full 3 post-restoration frames.
        """
        class ModelAlwaysAbsentAfterBaseline:
            names = {0: "chair"}
            call_count = 0
            def __call__(self, frame, conf, verbose):
                self.call_count += 1
                if self.call_count == 1:
                    return [FakeResult([FakeBox(0, 0.90, [4, 4, 20, 24])])]
                return [FakeResult([])]

        app = _make_app(ModelAlwaysAbsentAfterBaseline(), self._tmp.name)
        client = app.test_client()

        # Step 1: Baseline + 2 absent frames
        with patch("server.camera_view_status", return_value="stable"):
            client.post("/api/baseline", json={"room_name": "Hall", "image": self._image})
            client.post("/api/observe", json={"room_name": "Hall", "image": self._image})
            client.post("/api/observe", json={"room_name": "Hall", "image": self._image})

        # Step 2: Camera moved
        with patch("server.camera_view_status", return_value="moved"):
            r_moved = client.post("/api/observe", json={"room_name": "Hall", "image": self._image}).get_json()
            self.assertEqual(r_moved["status"], "camera_moved")

        # Step 3: View restored (frame 1 post-restore)
        with patch("server.camera_view_status", return_value="stable"):
            r_restored = client.post("/api/observe", json={"room_name": "Hall", "image": self._image}).get_json()
            # Must emit camera_view_restored
            cam_events = [a for a in r_restored["alerts"] if a["change_type"] == "camera_view_restored"]
            self.assertEqual(len(cam_events), 1)
            # Must NOT emit not_currently_visible on first post-restoration frame
            obj_events = [a for a in r_restored["alerts"] if a["change_type"] == "not_currently_visible"]
            self.assertEqual(obj_events, [], "Must not prematurely fire missing alert on restoration.")

            # Step 4: Second frame post-restore
            r_post2 = client.post("/api/observe", json={"room_name": "Hall", "image": self._image}).get_json()
            self.assertEqual(
                [a for a in r_post2["alerts"] if a["change_type"] == "not_currently_visible"],
                [],
                "Must not fire missing alert on second post-restoration frame.",
            )

            # Step 5: Third frame post-restore (now reaches 3 consecutive stable frames)
            r_post3 = client.post("/api/observe", json={"room_name": "Hall", "image": self._image}).get_json()
            missing_events = [a for a in r_post3["alerts"] if a["change_type"] == "not_currently_visible"]
            self.assertEqual(
                len(missing_events), 1,
                "Must fire missing alert only after 3 consecutive frames post-restoration.",
            )


# ---------------------------------------------------------------------------
# 4. Bounding-box jitter suppression
# ---------------------------------------------------------------------------

class TestBoundingBoxJitterSuppression(unittest.TestCase):
    """
    Validates that natural bounding-box center fluctuation (< MOVE_DISTANCE_THRESHOLD)
    does not trigger false 'moved' alerts across multiple frames.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._image = _encoded_image()

    def tearDown(self):
        self._tmp.cleanup()

    def test_sub_threshold_bounding_box_jitter_suppressed(self):
        """
        Chair at center_x = 0.50, center_y = 0.50 in baseline.
        In 5 monitoring frames, bounding box center wiggles within +/- 0.05
        (distance <= 0.07 << 0.14 threshold).
        Zero change alerts must be emitted.
        """
        # Frame: 64x48. center_x = 0.50 => 32px, center_y = 0.50 => 24px.
        # Wiggle between [20,12,44,36] (center 32,24) and [22,14,46,38] (center 34,26 -> dx=2/64=0.031, dy=2/48=0.041)
        wiggles = [
            [20, 12, 44, 36],  # cx=0.500, cy=0.500
            [22, 14, 46, 38],  # cx=0.531, cy=0.541 -> dist = 0.051 < 0.14
            [19, 11, 43, 35],  # cx=0.484, cy=0.479 -> dist = 0.026 < 0.14
            [21, 13, 45, 37],  # cx=0.515, cy=0.520 -> dist = 0.025 < 0.14
            [20, 12, 44, 36],  # cx=0.500, cy=0.500
        ]

        class ModelWithJitter:
            names = {0: "chair"}
            call_count = 0
            def __call__(self, frame, conf, verbose):
                self.call_count += 1
                box_idx = min(self.call_count - 1, len(wiggles) - 1)
                return [FakeResult([FakeBox(0, 0.88, wiggles[box_idx])])]

        app = _make_app(ModelWithJitter(), self._tmp.name)
        client = app.test_client()

        with patch("server.camera_view_status", return_value="stable"):
            client.post("/api/baseline", json={"room_name": "Living room", "image": self._image})
            for i in range(len(wiggles)):
                res = client.post("/api/observe", json={"room_name": "Living room", "image": self._image}).get_json()
                self.assertEqual(
                    res["alerts"], [],
                    f"Frame {i+1}: Sub-threshold jitter caused false alert: {res['alerts']}",
                )

    def test_multi_axis_sub_threshold_jitter_suppressed(self):
        """
        Diagonal shift where hypot(dx, dy) = 0.09 < 0.14 threshold must not be flagged as moved.
        """
        from services.change_detection import compare_detections
        baseline = [{
            "class_name": "couch",
            "center_x": 0.50,
            "center_y": 0.50,
            "instance_number": 1,
            "zone": "middle-center",
            "confidence": 0.90,
        }]
        # Shift dx = 0.06, dy = 0.06 -> dist = sqrt(0.06^2 + 0.06^2) = 0.0848 < 0.14
        observed = [{
            "class_name": "couch",
            "center_x": 0.56,
            "center_y": 0.56,
            "instance_number": 1,
            "zone": "middle-center",
            "confidence": 0.89,
        }]
        candidates = compare_detections(baseline, observed)
        moved = [c for c in candidates if c["change_type"] == "moved"]
        self.assertEqual(moved, [], "Sub-threshold diagonal movement must produce zero moved candidates.")


# ---------------------------------------------------------------------------
# 5. Intermittent YOLO class-label flickering
# ---------------------------------------------------------------------------

class TestClassLabelFlickering(unittest.TestCase):
    """
    Validates that detections alternating class labels or disappearing before
    reaching CHANGE_CONFIRMATION_FRAMES do not produce false alerts.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._image = _encoded_image()

    def tearDown(self):
        self._tmp.cleanup()

    def test_alternating_class_label_flicker_suppressed(self):
        """
        Baseline: chair at center.
        Monitoring frames alternate between predicting 'chair' and 'couch' on every frame:
          Frame 1: chair
          Frame 2: couch
          Frame 3: chair
          Frame 4: couch
          Frame 5: chair
        Neither classification sustains 3 consecutive frames; zero alerts must be emitted.
        """
        class ModelFlicker:
            names = {0: "chair", 1: "couch"}
            call_count = 0
            def __call__(self, frame, conf, verbose):
                self.call_count += 1
                if self.call_count == 1:
                    # Baseline: chair
                    return [FakeResult([FakeBox(0, 0.88, [20, 12, 44, 36])])]
                # Even calls -> couch, Odd calls -> chair
                cls_id = 1 if (self.call_count % 2 == 0) else 0
                return [FakeResult([FakeBox(cls_id, 0.82, [20, 12, 44, 36])])]

        app = _make_app(ModelFlicker(), self._tmp.name)
        client = app.test_client()

        with patch("server.camera_view_status", return_value="stable"):
            client.post("/api/baseline", json={"room_name": "Hall", "image": self._image})
            for i in range(5):
                res = client.post("/api/observe", json={"room_name": "Hall", "image": self._image}).get_json()
                self.assertEqual(
                    res["alerts"], [],
                    f"Frame {i+1}: Alternating class label flicker caused false alert: {res['alerts']}",
                )

    def test_single_frame_hallucination_suppressed(self):
        """
        A random false positive detection (e.g. teddy bear) appears on 1 frame only,
        then disappears. Zero alerts must be emitted.
        """
        class ModelSingleSpike:
            names = {0: "chair", 1: "teddy bear"}
            call_count = 0
            def __call__(self, frame, conf, verbose):
                self.call_count += 1
                if self.call_count == 1:
                    return [FakeResult([FakeBox(0, 0.90, [4, 4, 20, 24])])]
                if self.call_count == 3:
                    # Transient spike on frame 2 of monitoring
                    return [FakeResult([
                        FakeBox(0, 0.90, [4, 4, 20, 24]),
                        FakeBox(1, 0.70, [30, 20, 50, 40]),
                    ])]
                return [FakeResult([FakeBox(0, 0.90, [4, 4, 20, 24])])]

        app = _make_app(ModelSingleSpike(), self._tmp.name)
        client = app.test_client()

        with patch("server.camera_view_status", return_value="stable"):
            client.post("/api/baseline", json={"room_name": "Hall", "image": self._image})
            for i in range(4):
                res = client.post("/api/observe", json={"room_name": "Hall", "image": self._image}).get_json()
                self.assertEqual(
                    res["alerts"], [],
                    f"Frame {i+1}: Transient detection spike caused false alert: {res['alerts']}",
                )


# ---------------------------------------------------------------------------
# 6. Duplicate-alert cooldown
# ---------------------------------------------------------------------------

class TestDuplicateAlertCooldown(unittest.TestCase):
    """
    Validates alert deduplication:
      - Continuous sustained changed state does not re-emit duplicate alerts.
      - Repeated re-triggering of the same event signature within cooldown is suppressed.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._image = _encoded_image()

    def tearDown(self):
        self._tmp.cleanup()

    def test_sustained_moved_object_does_not_duplicate_alerts(self):
        """
        Once an object move is confirmed on frame 3, frames 4, 5, 6, 7 must emit zero
        duplicate alerts while the object remains in its new position.
        """
        class ModelMovedAndSustained:
            names = {0: "chair"}
            call_count = 0
            def __call__(self, frame, conf, verbose):
                self.call_count += 1
                if self.call_count == 1:
                    return [FakeResult([FakeBox(0, 0.90, [4, 4, 20, 24])])]  # left
                return [FakeResult([FakeBox(0, 0.90, [42, 24, 61, 43])])]      # right (moved)

        app = _make_app(ModelMovedAndSustained(), self._tmp.name)
        client = app.test_client()

        with patch("server.camera_view_status", return_value="stable"):
            client.post("/api/baseline", json={"room_name": "Hall", "image": self._image})

            # Frames 1 and 2: no alert yet
            r1 = client.post("/api/observe", json={"room_name": "Hall", "image": self._image}).get_json()
            r2 = client.post("/api/observe", json={"room_name": "Hall", "image": self._image}).get_json()
            self.assertEqual(r1["alerts"], [])
            self.assertEqual(r2["alerts"], [])

            # Frame 3: confirmed move alert fires exactly once
            r3 = client.post("/api/observe", json={"room_name": "Hall", "image": self._image}).get_json()
            self.assertEqual(len(r3["alerts"]), 1)
            self.assertEqual(r3["alerts"][0]["change_type"], "moved")

            # Frames 4-7: must NOT re-emit alert
            for frame_idx in range(4, 8):
                res = client.post("/api/observe", json={"room_name": "Hall", "image": self._image}).get_json()
                self.assertEqual(
                    res["alerts"], [],
                    f"Frame {frame_idx}: Duplicate alert emitted while state remained unchanged.",
                )

    def test_re_occurring_change_within_cooldown_window_suppressed(self):
        """
        If an object moves and triggers an alert, briefly moves elsewhere, and then
        returns to the same moved state within OBJECT_COOLDOWN_SECONDS, the second
        alert must be suppressed by the cooldown window.
        """
        box_left = [FakeBox(0, 0.90, [4, 4, 20, 24])]
        box_right = [FakeBox(0, 0.90, [42, 24, 61, 43])]

        class ModelMover:
            names = {0: "chair"}
            boxes = box_left
            def __call__(self, frame, conf, verbose):
                return [FakeResult(self.boxes)]

        model = ModelMover()
        app = _make_app(model, self._tmp.name)
        client = app.test_client()

        with patch("server.camera_view_status", return_value="stable"):
            # Step 1: Baseline at left
            model.boxes = box_left
            client.post("/api/baseline", json={"room_name": "Hall", "image": self._image})

            # Step 2: Move to right for 3 frames -> alert fires
            model.boxes = box_right
            for _ in range(2):
                client.post("/api/observe", json={"room_name": "Hall", "image": self._image})
            r3 = client.post("/api/observe", json={"room_name": "Hall", "image": self._image}).get_json()
            self.assertEqual(len(r3["alerts"]), 1)

            # Step 3: Briefly return to left for 1 frame (resets tracker announced/counts)
            model.boxes = box_left
            client.post("/api/observe", json={"room_name": "Hall", "image": self._image})

            # Step 4: Move back to right with cooldown active (3600s)
            model.boxes = box_right
            with patch("server.OBJECT_COOLDOWN_SECONDS", 3600):
                for _ in range(2):
                    client.post("/api/observe", json={"room_name": "Hall", "image": self._image})
                # On confirmation frame 3 of re-occurrence, cooldown must suppress it
                r_repeat = client.post("/api/observe", json={"room_name": "Hall", "image": self._image}).get_json()
                self.assertEqual(
                    r_repeat["alerts"], [],
                    "Cooldown must suppress repeated alert for same signature within window.",
                )


if __name__ == "__main__":
    unittest.main()
