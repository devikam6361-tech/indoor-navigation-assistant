import json
import unittest
from pathlib import Path
from server import create_app


class VideoRoutesTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()
        self.before_id = "8d212ee1e3c14ad190be168c80644261"
        self.after_id = "d60ab0339316421c90dede1e5829c5ab"

    def test_list_videos(self):
        response = self.client.get("/api/videos")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn("videos", data)
        self.assertIsInstance(data["videos"], list)

    def test_get_video_source_invalid_id(self):
        response = self.client.get("/api/videos/short_id/source")
        self.assertEqual(response.status_code, 400)

    def test_get_video_source_not_found(self):
        response = self.client.get(f"/api/videos/{'a' * 32}/source")
        self.assertEqual(response.status_code, 404)

    def test_get_video_source_existing(self):
        root = Path(self.app.instance_path) / "video_uploads" / self.before_id
        if (root / "source.mp4").is_file():
            response = self.client.get(f"/api/videos/{self.before_id}/source")
            self.assertEqual(response.status_code, 200)
            self.assertIn(response.mimetype, ["video/mp4", "video/quicktime", "video/webm"])

    def test_get_video_frame_invalid(self):
        response = self.client.get("/api/videos/bad_id/frames/frame_0000.jpg")
        self.assertEqual(response.status_code, 400)

        response = self.client.get(f"/api/videos/{self.before_id}/frames/invalid.png")
        self.assertEqual(response.status_code, 400)

    def test_compare_videos_validation(self):
        # Empty payload
        response = self.client.post("/api/videos/compare", json=None)
        self.assertEqual(response.status_code, 400)

        # Missing fields
        response = self.client.post("/api/videos/compare", json={"before_video_id": self.before_id})
        self.assertEqual(response.status_code, 400)

        # Invalid ID format
        response = self.client.post("/api/videos/compare", json={
            "before_video_id": "invalid",
            "after_video_id": self.after_id,
        })
        self.assertEqual(response.status_code, 400)

        # Nonexistent video
        response = self.client.post("/api/videos/compare", json={
            "before_video_id": "0" * 32,
            "after_video_id": self.after_id,
        })
        self.assertEqual(response.status_code, 404)

    def test_compare_videos_real_videos(self):
        root = Path(self.app.instance_path) / "video_uploads"
        if not ((root / self.before_id).is_dir() and (root / self.after_id).is_dir()):
            self.skipTest("Uploaded test videos not found in instance folder")

        response = self.client.post("/api/videos/compare", json={
            "before_video_id": self.before_id,
            "after_video_id": self.after_id,
            "before_frame": "frame_0000.jpg",
            "after_frame": "frame_0000.jpg",
        })
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["summary"]["moved"], 1)
        self.assertEqual(data["summary"]["unchanged"], 2)
        self.assertGreater(len(data["detected_changes"]), 0)
        self.assertIn("chair", data["detected_changes"][0]["class_name"].lower())
        self.assertIn("chair", data["voice_announcement"].lower())


if __name__ == "__main__":
    unittest.main()
