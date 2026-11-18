"""
P5-5 tests: Voice assistant, speech recognition queries, and object finder.

Focus areas:
  1. Natural-language voice query recognition and prefix stripping.
  2. Object aliases: chair, bag, sofa, water bottle, and plant.
  3. Unsupported object queries (HTTP 400 with descriptive error).
  4. Current object-location responses (status="latest_observation", found=True).
  5. Baseline-only location responses (status="baseline_only", found=False).
  6. Object-not-found responses (status="not_found", found=False).
  7. Camera-unverified responses when camera view is moved/unknown.

No production files are modified. Run from the ai/ directory:
    python -m pytest test_p5_5.py -v
"""

import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from services.object_finder import find_target_classes


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _encoded_image():
    """Return a base64 JPEG data-URL of a blank 64x48 image."""
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
# 1. Natural-language voice query recognition
# ---------------------------------------------------------------------------

class TestNaturalLanguageQueryRecognition(unittest.TestCase):
    """
    Validates natural language cleaning, prefix stripping, and article handling.
    """

    def test_natural_language_prefix_stripping(self):
        """Phrasal prefixes like 'where is', 'can you find', 'locate' must be stripped."""
        prefixes = [
            ("Where is my chair?", "chair"),
            ("Can you find the chair?", "chair"),
            ("Please find a chair", "chair"),
            ("Locate my chair", "chair"),
            ("Look for the chair", "chair"),
            ("Search for a chair", "chair"),
        ]
        for query, expected_norm in prefixes:
            norm, targets = find_target_classes(query)
            self.assertEqual(
                norm, expected_norm,
                f"Query '{query}' should normalize to '{expected_norm}'; got '{norm}'",
            )
            self.assertIn("chair", targets)

    def test_article_and_punctuation_handling(self):
        """Articles (a, an, the, my) and punctuation must be stripped cleanly."""
        queries = [
            ("Where is the bottle?", "bottle"),
            ("Where are my bags?", "bags"),
            ("Find an apple", "apple"),
            ("Where's the couch?!", "couch"),
        ]
        for query, expected_norm in queries:
            norm, _ = find_target_classes(query)
            self.assertEqual(
                norm, expected_norm,
                f"Query '{query}' should normalize to '{expected_norm}'; got '{norm}'",
            )

    def test_direct_class_name_without_prefix(self):
        """Direct queries without phrasing (e.g. 'chair', 'couch') must parse directly."""
        norm, targets = find_target_classes("chair")
        self.assertEqual(norm, "chair")
        self.assertEqual(targets, {"chair"})


# ---------------------------------------------------------------------------
# 2. Object aliases: chair, bag, sofa, water bottle, plant
# ---------------------------------------------------------------------------

class TestObjectAliases(unittest.TestCase):
    """
    Validates alias mapping to underlying YOLO classes.
    """

    def test_chair_alias_mapping(self):
        norm, targets = find_target_classes("find my chair")
        self.assertEqual(norm, "chair")
        self.assertEqual(targets, {"chair"})

    def test_bag_alias_mapping(self):
        """'bag' should expand to backpack, handbag, and suitcase."""
        norm, targets = find_target_classes("where is my bag")
        self.assertEqual(norm, "bag")
        self.assertEqual(targets, {"backpack", "handbag", "suitcase"})

    def test_sofa_alias_mapping(self):
        """'sofa' should map to 'couch'."""
        norm, targets = find_target_classes("can you find the sofa")
        self.assertEqual(norm, "sofa")
        self.assertEqual(targets, {"couch"})

    def test_water_bottle_alias_mapping(self):
        """'water bottle' should map to 'bottle'."""
        norm, targets = find_target_classes("where is my water bottle")
        self.assertEqual(norm, "water bottle")
        self.assertEqual(targets, {"bottle"})

    def test_plant_alias_mapping(self):
        """
        'plant' alias: should map to {'potted plant'}.
        Tests expected alias expansion for household plants.
        """
        norm, targets = find_target_classes("find my plant")
        self.assertEqual(norm, "plant")
        self.assertEqual(targets, {"potted plant"})


# ---------------------------------------------------------------------------
# 3. Unsupported object queries
# ---------------------------------------------------------------------------

class TestUnsupportedObjectQueries(unittest.TestCase):
    """
    Validates proper error response when user queries an unsupported class.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        class EmptyModel:
            names = {}
            def __call__(self, frame, conf, verbose):
                return [FakeResult([])]
        self._app = _make_app(EmptyModel(), self._tmp.name)
        self._client = self._app.test_client()

    def tearDown(self):
        self._tmp.cleanup()

    def test_unsupported_object_returns_400(self):
        """Asking for an unsupported item (e.g. 'keys') must return HTTP 400 with an error."""
        resp = self._client.get("/api/find?room_name=Hall&object_name=where%20are%20my%20keys")
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertIn("error", data)
        self.assertIn("not a supported", data["error"].lower())

    def test_empty_query_returns_400(self):
        """Empty or whitespace-only query must return HTTP 400."""
        resp = self._client.get("/api/find?room_name=Hall&object_name=")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("error", resp.get_json())


# ---------------------------------------------------------------------------
# 4. Current object-location responses
# ---------------------------------------------------------------------------

class TestCurrentObjectLocationResponses(unittest.TestCase):
    """
    Validates response structure when an object is detected in the latest reliable scan.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._image = _encoded_image()

    def tearDown(self):
        self._tmp.cleanup()

    def test_current_location_response_structure(self):
        """
        When object is in latest observation under stable view, /api/find returns:
          - found: True
          - status: 'latest_observation'
          - message containing zone label and timestamp
        """
        class ModelWithChair:
            names = {0: "chair"}
            def __call__(self, frame, conf, verbose):
                # Center left chair: [4, 16, 20, 32]
                return [FakeResult([FakeBox(0, 0.92, [4, 16, 20, 32])])]

        app = _make_app(ModelWithChair(), self._tmp.name)
        client = app.test_client()

        with patch("server.camera_view_status", return_value="stable"):
            client.post("/api/baseline", json={"room_name": "Living room", "image": self._image})
            client.post("/api/observe", json={"room_name": "Living room", "image": self._image})

            resp = client.get("/api/find?room_name=Living%20room&object_name=find%20my%20chair")
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertTrue(data["found"])
            self.assertEqual(data["status"], "latest_observation")
            self.assertIn("latest reliable scan", data["message"])
            self.assertIn("chair", data["message"])
            self.assertIn("left", data["message"].lower())
            self.assertIsNotNone(data.get("object"))

    def test_highest_confidence_selected_for_multiple(self):
        """
        If multiple matching objects exist in latest scan, the one with highest
        confidence should be chosen.
        """
        class ModelTwoBottles:
            names = {1: "bottle"}
            def __call__(self, frame, conf, verbose):
                return [FakeResult([
                    FakeBox(1, 0.70, [4, 4, 14, 14]),    # lower conf
                    FakeBox(1, 0.95, [40, 20, 50, 30]),  # higher conf
                ])]

        app = _make_app(ModelTwoBottles(), self._tmp.name)
        client = app.test_client()

        with patch("server.camera_view_status", return_value="stable"):
            client.post("/api/baseline", json={"room_name": "Kitchen", "image": self._image})
            client.post("/api/observe", json={"room_name": "Kitchen", "image": self._image})

            resp = client.get("/api/find?room_name=Kitchen&object_name=where%20is%20my%20bottle")
            data = resp.get_json()
            self.assertTrue(data["found"])
            self.assertAlmostEqual(data["object"]["confidence"], 0.95, places=2)


# ---------------------------------------------------------------------------
# 5. Baseline-only location responses
# ---------------------------------------------------------------------------

class TestBaselineOnlyLocationResponses(unittest.TestCase):
    """
    Validates response structure when an object existed in baseline but is absent currently.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._image = _encoded_image()

    def tearDown(self):
        self._tmp.cleanup()

    def test_baseline_only_response(self):
        """
        Chair recorded in baseline, but absent in latest observation:
          - found: False
          - status: 'baseline_only'
          - message clarifies this was recorded in original layout, not a current sighting.
        """
        class ModelBaselineOnly:
            names = {0: "chair"}
            call_count = 0
            def __call__(self, frame, conf, verbose):
                self.call_count += 1
                if self.call_count == 1:
                    return [FakeResult([FakeBox(0, 0.88, [4, 4, 20, 24])])]
                return [FakeResult([])]  # absent in monitoring

        app = _make_app(ModelBaselineOnly(), self._tmp.name)
        client = app.test_client()

        with patch("server.camera_view_status", return_value="stable"):
            client.post("/api/baseline", json={"room_name": "Living room", "image": self._image})
            client.post("/api/observe", json={"room_name": "Living room", "image": self._image})

            resp = client.get("/api/find?room_name=Living%20room&object_name=where%20is%20my%20chair")
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertFalse(data["found"])
            self.assertEqual(data["status"], "baseline_only")
            self.assertIn("original room layout", data["message"])
            self.assertIn("not a current sighting", data["message"])


# ---------------------------------------------------------------------------
# 6. Object-not-found responses
# ---------------------------------------------------------------------------

class TestObjectNotFoundResponses(unittest.TestCase):
    """
    Validates response when object was never detected in baseline nor latest observation.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._image = _encoded_image()

    def tearDown(self):
        self._tmp.cleanup()

    def test_object_not_found_response(self):
        """
        Searching for 'bottle' when only 'chair' was ever detected:
          - found: False
          - status: 'not_found'
          - message states object could not be found.
        """
        class ModelChairOnly:
            names = {0: "chair"}
            def __call__(self, frame, conf, verbose):
                return [FakeResult([FakeBox(0, 0.90, [4, 4, 20, 24])])]

        app = _make_app(ModelChairOnly(), self._tmp.name)
        client = app.test_client()

        with patch("server.camera_view_status", return_value="stable"):
            client.post("/api/baseline", json={"room_name": "Hall", "image": self._image})
            client.post("/api/observe", json={"room_name": "Hall", "image": self._image})

            resp = client.get("/api/find?room_name=Hall&object_name=find%20my%20bottle")
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertFalse(data["found"])
            self.assertEqual(data["status"], "not_found")
            self.assertIn("could not find", data["message"].lower())


# ---------------------------------------------------------------------------
# 7. Camera-unverified responses
# ---------------------------------------------------------------------------

class TestCameraUnverifiedResponses(unittest.TestCase):
    """
    Validates that when the camera view is moved or unverified, /api/find refrains
    from giving current object locations.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._image = _encoded_image()

    def tearDown(self):
        self._tmp.cleanup()

    def test_camera_unverified_response(self):
        """
        When camera view is moved, /api/find returns:
          - found: False
          - status: 'view_unverified'
          - message explains camera view cannot be verified.
        """
        class ModelWithChair:
            names = {0: "chair"}
            def __call__(self, frame, conf, verbose):
                return [FakeResult([FakeBox(0, 0.90, [4, 4, 20, 24])])]

        app = _make_app(ModelWithChair(), self._tmp.name)
        client = app.test_client()

        # Step 1: Baseline under stable view
        with patch("server.camera_view_status", return_value="stable"):
            client.post("/api/baseline", json={"room_name": "Hall", "image": self._image})

        # Step 2: Observe under moved camera
        with patch("server.camera_view_status", return_value="moved"):
            client.post("/api/observe", json={"room_name": "Hall", "image": self._image})

        # Step 3: Find query
        resp = client.get("/api/find?room_name=Hall&object_name=find%20my%20chair")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertFalse(data["found"])
        self.assertEqual(data["status"], "view_unverified")
        self.assertIn("cannot currently be verified", data["message"])


if __name__ == "__main__":
    unittest.main()
