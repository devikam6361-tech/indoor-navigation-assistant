"""
Fix 2 — Phase A tests: Class filtering and chair tracking protection.

Verifies that:
  1. laptop, keyboard, mouse, remote are absent from SUPPORTED_CLASSES.
  2. Navigation-critical classes (chair, table, sofa, backpack, handbag,
     suitcase, bottle, potted plant) are still present in SUPPORTED_CLASSES.
  3. All MONITORED_CLASSES remain a strict subset of SUPPORTED_CLASSES.
  4. The YOLO pipeline discards laptop detections entirely (Tier 1 filter).
  5. When YOLO returns a laptop FP alongside a genuine chair, only the chair
     reaches the detections list — chair tracking is preserved.
  6. The monitoring compare_detections() algorithm correctly produces a
     'moved' event for the chair when the laptop FP is also present.
  7. The /api/baseline endpoint saves only the chair, not the laptop.

Run from the ai/ directory:
    python -m pytest test_fix2_class_filter.py -v
"""

import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _encoded_image(w=64, h=48):
    """Return a valid base64 JPEG data-URL of a blank frame."""
    ok, buf = cv2.imencode(".jpg", np.zeros((h, w, 3), dtype=np.uint8))
    assert ok
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode("ascii")


class FakeBox:
    def __init__(self, class_id, confidence, bounds):
        self.cls = [class_id]
        self.conf = [confidence]
        # bounds: [x1, y1, x2, y2] in pixel coords
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
# 1. Static config assertions — no app needed
# ---------------------------------------------------------------------------

class TestSupportedClassesConfig(unittest.TestCase):
    """
    Verify the SUPPORTED_CLASSES set has the correct membership after
    Phase A changes.
    """

    def setUp(self):
        from config import SUPPORTED_CLASSES, MONITORED_CLASSES
        self.supported = SUPPORTED_CLASSES
        self.monitored = MONITORED_CLASSES

    # --- Removed classes ---

    def test_laptop_removed_from_supported(self):
        """'laptop' must NOT be in SUPPORTED_CLASSES (high false-positive risk)."""
        self.assertNotIn("laptop", self.supported)

    def test_keyboard_removed_from_supported(self):
        """'keyboard' must NOT be in SUPPORTED_CLASSES."""
        self.assertNotIn("keyboard", self.supported)

    def test_mouse_removed_from_supported(self):
        """'mouse' must NOT be in SUPPORTED_CLASSES."""
        self.assertNotIn("mouse", self.supported)

    def test_remote_removed_from_supported(self):
        """'remote' must NOT be in SUPPORTED_CLASSES."""
        self.assertNotIn("remote", self.supported)

    # --- Preserved navigation-critical classes ---

    def test_chair_still_in_supported(self):
        self.assertIn("chair", self.supported)

    def test_dining_table_still_in_supported(self):
        self.assertIn("dining table", self.supported)

    def test_couch_still_in_supported(self):
        self.assertIn("couch", self.supported)

    def test_backpack_still_in_supported(self):
        self.assertIn("backpack", self.supported)

    def test_handbag_still_in_supported(self):
        self.assertIn("handbag", self.supported)

    def test_suitcase_still_in_supported(self):
        self.assertIn("suitcase", self.supported)

    def test_bottle_still_in_supported(self):
        self.assertIn("bottle", self.supported)

    def test_potted_plant_still_in_supported(self):
        self.assertIn("potted plant", self.supported)

    def test_bed_still_in_supported(self):
        self.assertIn("bed", self.supported)

    # --- Retained electronics (low FP risk, large fixtures) ---

    def test_tv_still_in_supported(self):
        """'tv' should remain — large fixture, low confusion with furniture."""
        self.assertIn("tv", self.supported)

    def test_cell_phone_still_in_supported(self):
        """'cell phone' should remain — it is in MONITORED_CLASSES."""
        self.assertIn("cell phone", self.supported)

    def test_microwave_still_in_supported(self):
        self.assertIn("microwave", self.supported)

    def test_refrigerator_still_in_supported(self):
        self.assertIn("refrigerator", self.supported)

    # --- Invariant: MONITORED ⊆ SUPPORTED ---

    def test_monitored_classes_still_subset_of_supported(self):
        """
        Every class in MONITORED_CLASSES must still be in SUPPORTED_CLASSES.
        Removing laptop/keyboard/mouse/remote must not break this invariant.
        """
        diff = self.monitored - self.supported
        self.assertEqual(
            diff,
            set(),
            f"MONITORED classes not in SUPPORTED after Phase A: {diff}",
        )

    def test_monitored_classes_unchanged(self):
        """MONITORED_CLASSES must not have been altered by Phase A."""
        expected = {
            "backpack", "bottle", "cell phone", "chair", "couch",
            "dining table", "handbag", "potted plant", "suitcase", "teddy bear",
        }
        self.assertEqual(self.monitored, expected)


# ---------------------------------------------------------------------------
# 2. YOLO pipeline Tier-1 filter — laptop detections are discarded
# ---------------------------------------------------------------------------

class FakeLaptopModel:
    """
    Simulates YOLO returning only a laptop detection (a chair back misclassified).
    COCO class 63 = laptop.
    Frame assumed 64x48.
    """
    names = {63: "laptop"}

    def __call__(self, frame, conf, verbose):
        # Bounding box covering most of the frame — typical for chair back FP
        return [FakeResult([FakeBox(63, 0.31, [2, 2, 60, 44])])]


class FakeChairAndLaptopModel:
    """
    Simulates YOLO returning one genuine chair AND one laptop FP in the same
    frame. Only the chair should pass the SUPPORTED_CLASSES filter.
    Frame assumed 64x48 pixels (halves: left=0–31, right=32–63).
    """
    names = {56: "chair", 63: "laptop"}

    def __call__(self, frame, conf, verbose):
        return [FakeResult([
            FakeBox(56, 0.52, [2,  2, 30, 44]),   # genuine chair — left half
            FakeBox(63, 0.30, [33, 2, 62, 44]),   # laptop FP    — right half
        ])]


class FakeTwoChairsAndLaptopModel:
    """
    Baseline model: two chairs, no laptop FP.
    Current model: same two chairs but ONE is moved, plus a laptop FP.
    Used to verify that chair tracking is unaffected by the laptop FP.
    """
    names = {56: "chair", 63: "laptop"}
    _call_count = 0

    def __call__(self, frame, conf, verbose):
        self._call_count += 1
        if self._call_count == 1:
            # First call — baseline: two chairs side by side
            return [FakeResult([
                FakeBox(56, 0.80, [2,  2, 20, 44]),   # chair 1 — far left
                FakeBox(56, 0.75, [42, 2, 62, 44]),   # chair 2 — far right
            ])]
        # Subsequent calls — current scan: chair 1 unchanged, chair 2 moved center,
        # plus a laptop FP on the right
        return [FakeResult([
            FakeBox(56, 0.78, [2,  2, 20, 44]),   # chair 1 — stationary
            FakeBox(56, 0.70, [22, 2, 42, 44]),   # chair 2 — moved to center
            FakeBox(63, 0.29, [44, 2, 62, 44]),   # laptop FP — should be discarded
        ])]


class TestTier1LaptopFilter(unittest.TestCase):
    """
    Verify the Tier-1 (SUPPORTED_CLASSES) filter in yolo_service.py drops
    laptop detections before they reach the database.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self._tmp.cleanup()

    def test_laptop_only_model_produces_empty_detections(self):
        """
        When YOLO returns only a laptop, the /api/baseline endpoint must
        store zero detections (laptop is not in SUPPORTED_CLASSES).
        """
        app = _make_app(FakeLaptopModel(), self._tmp.name)
        client = app.test_client()
        resp = client.post(
            "/api/baseline",
            json={"room_name": "Living room", "image": _encoded_image()},
        )
        self.assertEqual(resp.status_code, 201, resp.get_json())
        data = resp.get_json()
        detections = data["baseline"]["detections"]
        self.assertEqual(
            detections,
            [],
            f"laptop FP must be discarded by Tier-1 filter; got: {detections}",
        )

    def test_chair_survives_when_laptop_fp_is_also_detected(self):
        """
        When YOLO returns both a chair (genuine) and a laptop (FP), only the
        chair must appear in baseline detections. The laptop must be absent.
        """
        app = _make_app(FakeChairAndLaptopModel(), self._tmp.name)
        client = app.test_client()
        resp = client.post(
            "/api/baseline",
            json={"room_name": "Living room", "image": _encoded_image()},
        )
        self.assertEqual(resp.status_code, 201, resp.get_json())
        detections = resp.get_json()["baseline"]["detections"]
        class_names = [d["class_name"] for d in detections]

        self.assertIn("chair", class_names, "Chair must be saved when laptop FP is co-detected.")
        self.assertNotIn("laptop", class_names, "Laptop FP must be discarded by Tier-1 filter.")
        self.assertEqual(len(detections), 1, f"Exactly 1 detection (chair) expected; got: {class_names}")

    def test_laptop_fp_does_not_appear_in_comparison_detections(self):
        """
        After saving a baseline with a chair+laptop FP, the comparison endpoint
        must not list 'laptop' in baseline detections.
        """
        app = _make_app(FakeChairAndLaptopModel(), self._tmp.name)
        client = app.test_client()

        # Save baseline
        client.post(
            "/api/baseline",
            json={"room_name": "Living room", "image": _encoded_image()},
        )

        # Fetch comparison (no latest yet — baseline detections checked)
        resp = client.get("/api/comparison?room_name=Living%20room")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        baseline_detections = data["baseline"]["detections"]
        class_names = [d["class_name"] for d in baseline_detections]

        self.assertNotIn(
            "laptop", class_names,
            f"laptop must not appear in comparison baseline; classes: {class_names}",
        )


# ---------------------------------------------------------------------------
# 3. Chair tracking with concurrent laptop FP — monitoring pipeline
# ---------------------------------------------------------------------------

class TestChairTrackingWithLaptopFP(unittest.TestCase):
    """
    End-to-end test: saves a two-chair baseline, then submits a monitoring
    scan where one chair moved and a laptop FP is returned. Verifies that
    the laptop FP does not interfere with chair change detection.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._view_patch = patch("server.camera_view_status", return_value="stable")
        self._view_patch.start()
        self._model = FakeTwoChairsAndLaptopModel()
        self._app = _make_app(self._model, self._tmp.name)
        self._client = self._app.test_client()

        # Save baseline — two chairs, no laptop FP (call 1)
        resp = self._client.post(
            "/api/baseline",
            json={"room_name": "Living room", "image": _encoded_image()},
        )
        self.assertEqual(resp.status_code, 201)
        baseline_detections = resp.get_json()["baseline"]["detections"]
        self._baseline_classes = [d["class_name"] for d in baseline_detections]

    def tearDown(self):
        self._view_patch.stop()
        self._tmp.cleanup()

    def test_baseline_contains_two_chairs_no_laptop(self):
        """Baseline must have exactly 2 chairs and no laptop."""
        self.assertEqual(
            self._baseline_classes.count("chair"), 2,
            f"Expected 2 chairs in baseline; got: {self._baseline_classes}",
        )
        self.assertNotIn(
            "laptop", self._baseline_classes,
            f"Laptop must not be in baseline; got: {self._baseline_classes}",
        )

    def test_monitoring_scan_discards_laptop_fp(self):
        """
        After submitting 3 observation scans (the confirmation threshold),
        no laptop entry must appear in the latest detections_json.
        """
        for _ in range(3):
            resp = self._client.post(
                "/api/observe",
                json={"room_name": "Living room", "image": _encoded_image()},
            )
            self.assertEqual(resp.status_code, 200, resp.get_json())

        # Check the latest observation stored in DB via /api/comparison
        resp = self._client.get("/api/comparison?room_name=Living%20room")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        latest_detections = data["latest"]["detections"]
        latest_classes = [d["class_name"] for d in latest_detections]

        self.assertNotIn(
            "laptop", latest_classes,
            f"Laptop FP must be discarded from latest scan; got: {latest_classes}",
        )

    def test_chair_move_event_fires_despite_laptop_fp(self):
        """
        After 3 observation scans, the monitoring pipeline must report a
        'moved' event for the chair that changed position. The laptop FP
        must not suppress or block this alert.
        """
        last_resp = None
        for _ in range(3):
            last_resp = self._client.post(
                "/api/observe",
                json={"room_name": "Living room", "image": _encoded_image()},
            )
            self.assertEqual(last_resp.status_code, 200)

        alerts = last_resp.get_json().get("alerts", [])
        alert_types = [a.get("change_type") for a in alerts]
        alert_objects = [a.get("object_name") for a in alerts]

        # At least one 'moved' event for chair must be present
        self.assertTrue(
            any(ct == "moved" and obj == "chair" for ct, obj in zip(alert_types, alert_objects)),
            f"Expected a 'moved' chair alert after 3 confirmation scans; "
            f"got alerts: {alerts}",
        )

    def test_no_laptop_event_fired(self):
        """
        No monitoring event must reference 'laptop' — it must be completely
        absent from the event stream even when YOLO returns laptop FPs.
        """
        for _ in range(3):
            last_resp = self._client.post(
                "/api/observe",
                json={"room_name": "Living room", "image": _encoded_image()},
            )

        # Check all events across all history
        resp = self._client.get("/api/latest?room_name=Living%20room")
        self.assertEqual(resp.status_code, 200)
        history = resp.get_json().get("history", [])
        laptop_events = [e for e in history if e.get("object_name") == "laptop"]
        self.assertEqual(
            laptop_events,
            [],
            f"No laptop events must be fired; found: {laptop_events}",
        )


# ---------------------------------------------------------------------------
# 4. compare_detections() is unaffected — kitchen electronics still work
# ---------------------------------------------------------------------------

class TestRetainedElectronicsNotBroken(unittest.TestCase):
    """
    Verify that retained electronics (tv, cell phone, microwave, refrigerator)
    still pass the Tier-1 filter and are still in SUPPORTED_CLASSES.
    """

    def test_tv_in_supported(self):
        from config import SUPPORTED_CLASSES
        self.assertIn("tv", SUPPORTED_CLASSES)

    def test_cell_phone_in_supported_and_monitored(self):
        from config import SUPPORTED_CLASSES, MONITORED_CLASSES
        self.assertIn("cell phone", SUPPORTED_CLASSES)
        self.assertIn("cell phone", MONITORED_CLASSES)

    def test_microwave_in_supported(self):
        from config import SUPPORTED_CLASSES
        self.assertIn("microwave", SUPPORTED_CLASSES)

    def test_refrigerator_in_supported(self):
        from config import SUPPORTED_CLASSES
        self.assertIn("refrigerator", SUPPORTED_CLASSES)


if __name__ == "__main__":
    unittest.main()
