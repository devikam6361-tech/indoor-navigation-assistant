import base64
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

import cv2
import numpy as np
from unittest.mock import patch

from server import camera_view_status, create_app


class FakeBox:
    def __init__(self, class_id, confidence, bounds):
        self.cls = [class_id]
        self.conf = [confidence]
        self.xyxy = [bounds]


class FakeResult:
    def __init__(self, boxes):
        self.boxes = boxes


class FakeModel:
    names = {0: "chair", 1: "bottle", 2: "person", 3: "dining table"}

    def __init__(self):
        self.boxes = [
            FakeBox(0, 0.91, [4, 4, 20, 24]),
            FakeBox(0, 0.87, [25, 4, 42, 24]),
            FakeBox(1, 0.76, [12, 2, 19, 16]),
            FakeBox(2, 0.99, [1, 1, 6, 8]),
        ]

    def __call__(self, frame, conf, verbose):
        return [FakeResult(self.boxes)]


class HomeLayoutApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "layout.sqlite3"
        self.model = FakeModel()
        self.app = create_app(self.database_path, detector=self.model)
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()
        self.view_patch = patch("server.camera_view_status", return_value="stable")
        self.view_patch.start()
        success, encoded = cv2.imencode(
            ".jpg", np.zeros((48, 64, 3), dtype=np.uint8)
        )
        self.assertTrue(success)
        self.image_data = (
            "data:image/jpeg;base64,"
            + base64.b64encode(encoded.tobytes()).decode("ascii")
        )

    def tearDown(self):
        self.view_patch.stop()
        self.temp_dir.cleanup()

    @staticmethod
    def encode_image(image):
        success, encoded = cv2.imencode(".jpg", image)
        if not success:
            raise AssertionError("Could not encode test image.")
        return "data:image/jpeg;base64," + base64.b64encode(
            encoded.tobytes()
        ).decode("ascii")

    def post_observation(self):
        return self.client.post(
            "/api/observe",
            json={"room_name": "Living room", "image": self.image_data},
        )

    def post_baseline(self, **fields):
        payload = {
            "room_name": "Living room",
            "image": self.image_data,
            "replace": False,
            **fields,
        }
        return self.client.post("/api/baseline", json=payload)

    def test_saves_supported_detections_zones_and_review_image(self):
        response = self.post_baseline()

        self.assertEqual(response.status_code, 201)
        baseline = response.get_json()["baseline"]
        self.assertEqual(baseline["image_width"], 64)
        self.assertEqual(baseline["image_height"], 48)
        self.assertTrue(baseline["image_data_url"].startswith("data:image/jpeg;base64,"))
        self.assertEqual(
            [(item["class_name"], item["instance_number"]) for item in baseline["detections"]],
            [("bottle", 1), ("chair", 1), ("chair", 2)],
        )
        self.assertEqual(baseline["detections"][0]["zone"], "upper-left")
        self.assertAlmostEqual(baseline["detections"][0]["confidence"], 0.76)

        restarted_client = create_app(
            self.database_path, detector=FakeModel()
        ).test_client()
        saved = restarted_client.get(
            "/api/baseline?room_name=Living%20room"
        ).get_json()["baseline"]
        self.assertEqual(saved["id"], baseline["id"])
        self.assertEqual(len(saved["detections"]), 3)

    def test_existing_baseline_is_not_replaced_without_explicit_confirmation(self):
        original = self.post_baseline().get_json()["baseline"]

        response = self.post_baseline()

        self.assertEqual(response.status_code, 409)
        saved = self.client.get(
            "/api/baseline?room_name=Living%20room"
        ).get_json()["baseline"]
        self.assertEqual(saved["id"], original["id"])

    def test_confirmed_replacement_keeps_history_and_only_one_baseline_active(self):
        original = self.post_baseline().get_json()["baseline"]

        response = self.post_baseline(replace=True)

        self.assertEqual(response.status_code, 201)
        self.assertNotEqual(response.get_json()["baseline"]["id"], original["id"])
        with closing(sqlite3.connect(self.database_path)) as connection:
            observations = connection.execute(
                "SELECT is_baseline FROM observations ORDER BY id"
            ).fetchall()
        self.assertEqual(observations, [(0,), (1,)])

    def test_invalid_image_is_rejected_without_creating_a_baseline(self):
        response = self.post_baseline(image="not an image")

        self.assertEqual(response.status_code, 400)
        self.assertIsNone(
            self.client.get("/api/baseline?room_name=Living%20room").get_json()[
                "baseline"
            ]
        )

    def test_moved_object_is_confirmed_once_after_three_scans(self):
        self.model.boxes = [FakeBox(0, 0.93, [4, 4, 20, 24])]
        self.post_baseline()
        self.model.boxes = [FakeBox(0, 0.91, [42, 24, 61, 43])]

        first, second, third, fourth = [
            self.post_observation() for _ in range(4)
        ]

        self.assertEqual(first.get_json()["alerts"], [])
        self.assertEqual(second.get_json()["alerts"], [])
        alerts = third.get_json()["alerts"]
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["change_type"], "moved")
        self.assertIn("appears to have moved", alerts[0]["message"])
        self.assertIn("left", alerts[0]["message"])
        self.assertEqual(fourth.get_json()["alerts"], [])
        self.assertEqual(len(fourth.get_json()["history"]), 1)

    def test_a_new_movement_situation_gets_a_distinct_alert(self):
        self.model.boxes = [FakeBox(0, 0.93, [4, 4, 20, 24])]
        self.post_baseline()
        self.model.boxes = [FakeBox(0, 0.91, [42, 24, 61, 43])]
        first_alert = [
            self.post_observation().get_json(),
            self.post_observation().get_json(),
            self.post_observation().get_json(),
        ][-1]["alerts"][0]
        self.model.boxes = [FakeBox(0, 0.94, [25, 0, 43, 17])]

        first, second, third = [
            self.post_observation().get_json() for _ in range(3)
        ]

        self.assertEqual(first["alerts"], [])
        self.assertEqual(second["alerts"], [])
        second_alert = third["alerts"][0]
        self.assertNotEqual(second_alert["id"], first_alert["id"])
        self.assertEqual(second_alert["change_type"], "moved")
        self.assertIn("upper center", second_alert["message"])

    def test_moved_furniture_in_lower_center_gets_a_cautious_warning(self):
        self.model.boxes = [FakeBox(0, 0.93, [4, 4, 20, 24])]
        self.post_baseline()
        self.model.boxes = [FakeBox(0, 0.91, [25, 32, 43, 46])]

        alert = [
            self.post_observation().get_json(),
            self.post_observation().get_json(),
            self.post_observation().get_json(),
        ][-1]["alerts"][0]

        self.assertIn("may be an obstacle", alert["message"])
        self.assertIn("cannot confirm that a walkway is blocked", alert["message"])

    def test_cooldown_suppresses_a_repeated_unchanged_alert(self):
        self.model.boxes = [FakeBox(0, 0.93, [4, 4, 20, 24])]
        self.post_baseline()
        self.model.boxes = [FakeBox(0, 0.91, [42, 24, 61, 43])]
        first_alert = [
            self.post_observation().get_json(),
            self.post_observation().get_json(),
            self.post_observation().get_json(),
        ][-1]["alerts"][0]
        self.model.boxes = [FakeBox(0, 0.93, [4, 4, 20, 24])]
        self.post_observation()
        self.model.boxes = [FakeBox(0, 0.91, [42, 24, 61, 43])]

        with patch("server.OBJECT_COOLDOWN_SECONDS", 3600):
            first, second, third = [
                self.post_observation().get_json() for _ in range(3)
            ]

        self.assertEqual(first["alerts"], [])
        self.assertEqual(second["alerts"], [])
        self.assertEqual(third["alerts"], [])
        history = self.client.get(
            "/api/alerts?room_name=Living%20room"
        ).get_json()["history"]
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["id"], first_alert["id"])

    def test_new_obstacle_is_cautiously_announced_after_repeated_detections(self):
        self.model.boxes = [FakeBox(0, 0.93, [4, 4, 20, 24])]
        self.post_baseline()
        self.model.boxes = [
            FakeBox(0, 0.92, [4, 4, 20, 24]),
            FakeBox(3, 0.88, [25, 32, 43, 46]),
        ]

        first, second, third = [self.post_observation() for _ in range(3)]

        self.assertEqual(first.get_json()["alerts"], [])
        self.assertEqual(second.get_json()["alerts"], [])
        alert = third.get_json()["alerts"][0]
        self.assertEqual(alert["change_type"], "newly_observed")
        self.assertIn("may be an obstacle", alert["message"])
        self.assertIn("cannot confirm", alert["message"])

    def test_temporary_occlusion_does_not_confirm_an_object_as_missing(self):
        self.model.boxes = [
            FakeBox(0, 0.91, [4, 4, 20, 24]),
            FakeBox(0, 0.87, [25, 4, 42, 24]),
        ]
        self.post_baseline()
        self.model.boxes = [FakeBox(0, 0.91, [4, 4, 20, 24])]

        first, second = [self.post_observation() for _ in range(2)]
        self.model.boxes = [
            FakeBox(0, 0.91, [4, 4, 20, 24]),
            FakeBox(0, 0.87, [25, 4, 42, 24]),
        ]
        returned = self.post_observation()

        self.assertEqual(first.get_json()["alerts"], [])
        self.assertEqual(second.get_json()["alerts"], [])
        self.assertEqual(returned.get_json()["alerts"], [])

    def test_persistent_missing_detection_is_reported_as_not_visible_not_removed(self):
        self.model.boxes = [FakeBox(0, 0.91, [4, 4, 20, 24])]
        self.post_baseline()
        self.model.boxes = []

        first, second, third = [self.post_observation() for _ in range(3)]

        self.assertEqual(first.get_json()["alerts"], [])
        self.assertEqual(second.get_json()["alerts"], [])
        message = third.get_json()["alerts"][0]["message"]
        self.assertIn("not currently visible", message)
        self.assertIn("does not confirm it was removed", message)

    def test_moved_camera_suppresses_detection_alerts_and_keeps_latest_reliable_scan(self):
        self.model.boxes = [FakeBox(0, 0.91, [4, 4, 20, 24])]
        self.post_baseline()
        previous = self.post_observation().get_json()["latest"]
        self.model.boxes = [FakeBox(0, 0.91, [42, 24, 61, 43])]
        with patch("server.camera_view_status", return_value="moved"):
            response = self.post_observation()

        self.assertEqual(response.get_json()["status"], "camera_moved")
        alerts = response.get_json()["alerts"]
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["change_type"], "camera_view_changed")
        self.assertIn("alerts are paused", alerts[0]["message"])
        latest = self.client.get(
            "/api/latest?room_name=Living%20room"
        ).get_json()["latest"]
        self.assertEqual(latest["captured_at"], previous["captured_at"])

    def test_restoring_the_camera_view_is_announced(self):
        self.model.boxes = [FakeBox(0, 0.91, [4, 4, 20, 24])]
        self.post_baseline()
        self.post_observation()
        with patch("server.camera_view_status", return_value="moved"):
            self.post_observation()
        with patch("server.camera_view_status", return_value="stable"):
            response = self.post_observation()

        camera_alerts = [
            event
            for event in response.get_json()["alerts"]
            if event["change_type"] == "camera_view_restored"
        ]
        self.assertEqual(len(camera_alerts), 1)
        self.assertIn("monitoring has resumed", camera_alerts[0]["message"])

    def test_orb_view_check_detects_a_global_camera_translation(self):
        random = np.random.default_rng(7)
        reference = random.integers(0, 255, (360, 480), dtype=np.uint8)
        reference = cv2.GaussianBlur(reference, (3, 3), 0)
        color_reference = cv2.cvtColor(reference, cv2.COLOR_GRAY2BGR)
        shifted = cv2.warpAffine(
            color_reference,
            np.float32([[1, 0, 45], [0, 1, 0]]),
            (480, 360),
        )
        success, encoded = cv2.imencode(".jpg", color_reference)
        self.assertTrue(success)

        self.assertEqual(camera_view_status(encoded.tobytes(), shifted), "moved")

    def test_orb_view_check_accepts_fixed_view_lighting_change(self):
        random = np.random.default_rng(8)
        reference = random.integers(0, 255, (360, 480), dtype=np.uint8)
        reference = cv2.GaussianBlur(reference, (3, 3), 0)
        color_reference = cv2.cvtColor(reference, cv2.COLOR_GRAY2BGR)
        brighter = cv2.convertScaleAbs(color_reference, alpha=0.78, beta=38)
        success, encoded = cv2.imencode(".jpg", color_reference)
        self.assertTrue(success)

        self.assertEqual(camera_view_status(encoded.tobytes(), brighter), "stable")

    def test_object_finder_uses_latest_reliable_observation_with_aliases(self):
        self.model.boxes = [FakeBox(1, 0.88, [32, 16, 48, 38])]
        self.post_baseline()
        self.post_observation()

        response = self.client.get(
            "/api/find?room_name=Living%20room&object_name=Where%20is%20my%20water%20bottle%3F"
        )

        result = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(result["found"])
        self.assertEqual(result["status"], "latest_observation")
        self.assertIn("latest reliable scan saw your water bottle", result["message"])

    def test_object_finder_does_not_return_a_current_location_after_camera_moves(self):
        self.model.boxes = [FakeBox(1, 0.88, [32, 16, 48, 38])]
        self.post_baseline()
        with patch("server.camera_view_status", return_value="moved"):
            self.post_observation()

        response = self.client.get(
            "/api/find?room_name=Living%20room&object_name=bottle"
        )

        self.assertFalse(response.get_json()["found"])
        self.assertEqual(response.get_json()["status"], "view_unverified")
        self.assertIn("cannot give a current location", response.get_json()["message"])

    def test_voice_playback_failure_is_persisted_in_alert_history(self):
        self.model.boxes = [FakeBox(0, 0.91, [4, 4, 20, 24])]
        self.post_baseline()
        self.model.boxes = []
        event = [
            self.post_observation().get_json(),
            self.post_observation().get_json(),
            self.post_observation().get_json(),
        ][-1]["alerts"][0]

        response = self.client.post(
            f"/api/alerts/{event['id']}/playback",
            json={"status": "failed", "error": "audio output unavailable"},
        )

        self.assertEqual(response.status_code, 200)
        history = self.client.get(
            "/api/alerts?room_name=Living%20room"
        ).get_json()["history"]
        self.assertEqual(history[0]["speech_status"], "failed")
        self.assertEqual(history[0]["speech_error"], "audio output unavailable")


if __name__ == "__main__":
    unittest.main()
