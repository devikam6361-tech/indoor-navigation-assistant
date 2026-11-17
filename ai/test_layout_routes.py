import base64
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from config import CAMERA_ID
from database.connection import connect_database
from server import create_app
from utils.formatting import room_key


class FakeBox:
    def __init__(self, class_id, confidence, bounds):
        self.cls = [class_id]
        self.conf = [confidence]
        self.xyxy = [bounds]


class FakeResult:
    def __init__(self, boxes):
        self.boxes = boxes


class FakeModel:
    names = {0: "chair", 1: "person"}

    def __init__(self, boxes=None):
        self.boxes = boxes if boxes is not None else [
            FakeBox(0, 0.91, [8, 8, 28, 30]),
            FakeBox(1, 0.99, [2, 2, 12, 18]),
        ]

    def __call__(self, frame, conf, verbose):
        return [FakeResult(self.boxes)]


class LayoutRoutesTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "layouts.sqlite3"
        self.detector = FakeModel()
        self.app = create_app(self.database_path, detector=self.detector)
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()
        ok, encoded = cv2.imencode(
            ".jpg", np.zeros((48, 64, 3), dtype=np.uint8)
        )
        self.assertTrue(ok)
        self.image_data = (
            "data:image/jpeg;base64,"
            + base64.b64encode(encoded.tobytes()).decode("ascii")
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def post_layout(
        self,
        layout_name="Layout one",
        room_name="Living room",
        camera_id=CAMERA_ID,
        image=None,
        activate=None,
    ):
        payload = {
            "room_name": room_name,
            "camera_id": camera_id,
            "layout_name": layout_name,
            "image": image or self.image_data,
        }
        if activate is not None:
            payload["activate"] = activate
        return self.client.post(
            "/api/layouts",
            json=payload,
        )

    def compare(self, before_id, after_id, room_name="Living room", camera_id=CAMERA_ID):
        return self.client.post(
            "/api/layouts/compare",
            json={
                "room_name": room_name,
                "camera_id": camera_id,
                "before_layout_id": before_id,
                "after_layout_id": after_id,
            },
        )

    def owner_json(self, room_name="Living room", camera_id=CAMERA_ID):
        return {"room_name": room_name, "camera_id": camera_id}

    def activate(self, layout_id, room_name="Living room", camera_id=CAMERA_ID):
        return self.client.post(
            f"/api/layouts/{layout_id}/activate",
            json=self.owner_json(room_name, camera_id),
        )

    def delete(self, layout_id, room_name="Living room", camera_id=CAMERA_ID):
        return self.client.delete(
            f"/api/layouts/{layout_id}?room_name={room_name.replace(' ', '%20')}"
            f"&camera_id={camera_id}"
        )

    def get_layouts(self, room_name="Living room", camera_id=CAMERA_ID):
        return self.client.get(
            f"/api/layouts?room_name={room_name.replace(' ', '%20')}"
            f"&camera_id={camera_id}"
        )

    def rows(self, sql, params=()):
        with closing(sqlite3.connect(self.database_path)) as connection:
            return connection.execute(sql, params).fetchall()

    def set_view_status(self, room_name, status):
        with closing(connect_database(str(self.database_path))) as connection:
            connection.execute(
                """
                INSERT INTO room_monitor_status (
                    room_key, camera_id, view_status, updated_at
                ) VALUES (?, ?, ?, '2026-11-16T00:00:00Z')
                ON CONFLICT(room_key) DO UPDATE SET
                    camera_id = excluded.camera_id,
                    view_status = excluded.view_status,
                    updated_at = excluded.updated_at
                """,
                (room_key(room_name), CAMERA_ID, status),
            )
            connection.commit()

    def image_data_for_value(self, value):
        ok, encoded = cv2.imencode(
            ".jpg", np.full((48, 64, 3), value, dtype=np.uint8)
        )
        self.assertTrue(ok)
        return (
            "data:image/jpeg;base64,"
            + base64.b64encode(encoded.tobytes()).decode("ascii")
        )

    def save_pair(self, before_box=None, after_box=None):
        self.detector.boxes = [
            before_box if before_box is not None else FakeBox(0, 0.91, [8, 8, 28, 30])
        ]
        before = self.post_layout(
            "Before - Original Layout", activate=False
        ).get_json()["layout"]
        self.detector.boxes = [
            after_box if after_box is not None else FakeBox(0, 0.91, [8, 8, 28, 30])
        ]
        after = self.post_layout(
            "After - Updated Layout", activate=False
        ).get_json()["layout"]
        return before, after

    def test_get_lists_room_camera_history_and_marks_active_and_deleted(self):
        first = self.post_layout("First").get_json()["layout"]
        second = self.post_layout("Second").get_json()["layout"]
        self.assertEqual(self.delete(first["id"]).status_code, 200)

        response = self.get_layouts()

        self.assertEqual(response.status_code, 200)
        layouts = response.get_json()["layouts"]
        by_id = {layout["id"]: layout for layout in layouts}
        self.assertEqual(set(by_id), {first["id"], second["id"]})
        self.assertFalse(by_id[first["id"]]["is_active"])
        self.assertIsNotNone(by_id[first["id"]]["deleted_at"])
        self.assertTrue(by_id[second["id"]]["is_active"])
        self.assertTrue(
            by_id[second["id"]]["image_data_url"].startswith(
                "data:image/jpeg;base64,"
            )
        )
        self.assertEqual(by_id[second["id"]]["room_name"], "Living room")
        self.assertEqual(by_id[second["id"]]["camera_id"], CAMERA_ID)

    def test_post_saves_layout_detections_and_active_selection(self):
        first = self.post_layout("First").get_json()["layout"]

        response = self.post_layout("Second")

        self.assertEqual(response.status_code, 201)
        second = response.get_json()["layout"]
        self.assertNotEqual(first["id"], second["id"])
        self.assertTrue(second["is_active"])
        self.assertEqual(
            self.rows(
                "SELECT id, is_baseline, layout_name FROM observations ORDER BY id"
            ),
            [(first["id"], 0, "First"), (second["id"], 1, "Second")],
        )
        self.assertEqual(
            self.rows(
                "SELECT class_name FROM detections WHERE observation_id = ?",
                (second["id"],),
            ),
            [("chair",)],
        )
        self.assertEqual(
            self.rows(
                "SELECT view_status FROM room_monitor_status WHERE room_key = ?",
                (room_key("Living room"),),
            ),
            [("unknown",)],
        )

    def test_before_after_saves_preserve_active_baseline_monitor_state_and_trackers(self):
        baseline = self.post_layout("Existing baseline").get_json()["layout"]
        self.set_view_status("Living room", "stable")
        tracker_key = (room_key("Living room"), baseline["id"])
        tracker = {"counts": {"chair": 2}, "announced": {"chair"}}
        self.app.config["TRACKERS"][tracker_key] = tracker
        baseline_image = self.rows(
            "SELECT image FROM observations WHERE id = ?", (baseline["id"],)
        )[0][0]

        before_response = self.post_layout(
            "Before - Original Layout", activate=False
        )
        after_response = self.post_layout(
            "After - Updated Layout",
            image=self.image_data_for_value(180),
            activate=False,
        )

        self.assertEqual(before_response.status_code, 201)
        self.assertEqual(after_response.status_code, 201)
        before = before_response.get_json()["layout"]
        after = after_response.get_json()["layout"]
        self.assertNotEqual(before["id"], after["id"])
        self.assertFalse(before["is_active"])
        self.assertFalse(after["is_active"])
        self.assertEqual(
            self.rows(
                "SELECT id, is_baseline FROM observations "
                "WHERE room_key = ? AND camera_id = ? AND is_baseline = 1",
                (room_key("Living room"), CAMERA_ID),
            ),
            [(baseline["id"], 1)],
        )
        stored_images = self.rows(
            "SELECT id, image FROM observations WHERE id IN (?, ?) ORDER BY id",
            (before["id"], after["id"]),
        )
        self.assertEqual([row[0] for row in stored_images], [before["id"], after["id"]])
        self.assertNotEqual(stored_images[0][1], stored_images[1][1])
        self.assertEqual(
            self.rows(
                "SELECT observation_id, COUNT(*) FROM detections "
                "WHERE observation_id IN (?, ?) GROUP BY observation_id ORDER BY observation_id",
                (before["id"], after["id"]),
            ),
            [(before["id"], 1), (after["id"], 1)],
        )
        self.assertEqual(
            self.rows("SELECT view_status FROM room_monitor_status"),
            [("stable",)],
        )
        self.assertEqual(self.app.config["TRACKERS"][tracker_key], tracker)
        self.assertIs(self.app.config["TRACKERS"][tracker_key], tracker)
        self.assertEqual(
            self.rows(
                "SELECT image FROM observations WHERE id = ?", (baseline["id"],)
            )[0][0],
            baseline_image,
        )

    def test_inactive_save_rolls_back_without_changing_baseline_or_monitor_state(self):
        baseline = self.post_layout("Original").get_json()["layout"]
        self.set_view_status("Living room", "stable")
        tracker_key = (room_key("Living room"), baseline["id"])
        tracker = {"counts": {"chair": 1}, "announced": set()}
        self.app.config["TRACKERS"][tracker_key] = tracker

        with patch(
            "routes.layout_routes._insert_detections",
            side_effect=sqlite3.IntegrityError("injected insert failure"),
        ):
            response = self.post_layout("Before", activate=False)

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            self.rows("SELECT id, is_baseline FROM observations"),
            [(baseline["id"], 1)],
        )
        self.assertEqual(
            self.rows("SELECT view_status FROM room_monitor_status"),
            [("stable",)],
        )
        self.assertIs(self.app.config["TRACKERS"][tracker_key], tracker)

    def test_compare_saved_layouts_reports_changed_for_confirmed_position_change(self):
        before, after = self.save_pair(
            before_box=FakeBox(0, 0.91, [8, 8, 28, 30]),
            after_box=FakeBox(0, 0.92, [30, 8, 50, 30]),
        )

        with patch("routes.layout_routes.camera_view_status", return_value="stable"):
            response = self.compare(before["id"], after["id"])

        self.assertEqual(response.status_code, 200)
        result = response.get_json()
        self.assertEqual(result["status"], "changed")
        self.assertEqual(result["before"]["id"], before["id"])
        self.assertEqual(result["after"]["id"], after["id"])
        self.assertTrue(result["before"]["image_data_url"].startswith("data:image/jpeg;base64,"))
        self.assertTrue(result["after"]["image_data_url"].startswith("data:image/jpeg;base64,"))
        self.assertEqual(set(result), {"status", "before", "after", "comparison"})
        self.assertIn("summary", result["comparison"])
        self.assertEqual(result["comparison"]["summary"]["moved"], 1)

    def test_compare_saved_layouts_reports_unchanged_for_matching_records(self):
        before, after = self.save_pair()

        with patch("routes.layout_routes.camera_view_status", return_value="stable"):
            response = self.compare(before["id"], after["id"])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "unchanged")

    def test_compare_saved_layouts_reports_uncertain_for_ambiguous_chair_assignment(self):
        self.detector.boxes = [
            FakeBox(0, 0.91, [12, 12, 20, 30]),
            FakeBox(0, 0.89, [44, 12, 52, 30]),
        ]
        before = self.post_layout("Before", activate=False).get_json()["layout"]
        self.detector.boxes = [
            FakeBox(0, 0.91, [28, 12, 36, 30]),
            FakeBox(0, 0.89, [28, 12, 36, 30]),
        ]
        after = self.post_layout("After", activate=False).get_json()["layout"]

        with patch("routes.layout_routes.camera_view_status", return_value="stable"):
            response = self.compare(before["id"], after["id"])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "uncertain")
        self.assertEqual(set(response.get_json()), {"status", "before", "after", "comparison"})

    def test_compare_saved_layouts_reports_uncertain_for_unverified_view_or_missing_detections(self):
        before, after = self.save_pair()
        with patch("routes.layout_routes.camera_view_status", return_value="unknown"):
            unverified = self.compare(before["id"], after["id"])
        self.assertEqual(unverified.status_code, 200)
        self.assertEqual(unverified.get_json()["status"], "uncertain")

        self.detector.boxes = []
        empty_layout = self.post_layout(
            "After without detections", activate=False
        ).get_json()["layout"]
        with patch("routes.layout_routes.camera_view_status", return_value="stable"):
            missing = self.compare(before["id"], empty_layout["id"])
        self.assertEqual(missing.status_code, 200)
        self.assertEqual(missing.get_json()["status"], "uncertain")

    def test_compare_saved_layouts_returns_error_without_mutating_stored_records(self):
        before, after = self.save_pair()
        stored_records = self.rows(
            "SELECT id, is_baseline, image FROM observations ORDER BY id"
        )
        stored_detections = self.rows(
            "SELECT observation_id, class_name, center_x, center_y "
            "FROM detections ORDER BY id"
        )

        with patch(
            "routes.layout_routes.camera_view_status", return_value="stable"
        ), patch(
            "routes.layout_routes.categorize_room_comparison",
            side_effect=ValueError("injected comparison failure"),
        ):
            response = self.compare(before["id"], after["id"])

        self.assertEqual(response.status_code, 500)
        self.assertIn("Could not compare saved layouts", response.get_json()["error"])
        self.assertEqual(
            self.rows("SELECT id, is_baseline, image FROM observations ORDER BY id"),
            stored_records,
        )
        self.assertEqual(
            self.rows(
                "SELECT observation_id, class_name, center_x, center_y "
                "FROM detections ORDER BY id"
            ),
            stored_detections,
        )

    def test_compare_saved_layouts_rejects_invalid_scope_and_deleted_records(self):
        before, after = self.save_pair()

        self.assertEqual(self.compare(before["id"], after["id"], room_name="Kitchen").status_code, 404)
        self.assertEqual(self.compare(before["id"], after["id"], camera_id="other-camera").status_code, 400)
        self.assertEqual(self.compare(before["id"], before["id"]).status_code, 400)
        self.assertEqual(self.compare("invalid", after["id"]).status_code, 400)
        self.assertEqual(self.compare(99999, after["id"]).status_code, 404)

        self.assertEqual(self.delete(before["id"]).status_code, 200)
        self.assertEqual(self.compare(before["id"], after["id"]).status_code, 409)

    def test_invalid_camera_and_image_are_rejected(self):
        self.assertEqual(
            self.post_layout(camera_id="other-camera").status_code, 400
        )
        self.assertEqual(
            self.post_layout(activate="false").status_code, 400
        )
        self.assertEqual(
            self.post_layout(image="not-an-image").status_code, 400
        )
        self.assertEqual(
            self.rows("SELECT COUNT(*) FROM observations"), [(0,)]
        )

    def test_activation_restores_layout_resets_tracker_and_marks_view_unknown(self):
        first = self.post_layout("First").get_json()["layout"]
        second = self.post_layout("Second").get_json()["layout"]
        room = room_key("Living room")
        other_room = room_key("Kitchen")
        self.set_view_status("Living room", "stable")
        self.app.config["TRACKERS"][(room, first["id"])] = {
            "counts": {"chair": 2},
            "announced": {"chair"},
        }
        self.app.config["TRACKERS"][(other_room, 999)] = {
            "counts": {"bottle": 1},
            "announced": set(),
        }

        response = self.activate(first["id"])

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["layout"]["is_active"])
        self.assertEqual(
            self.rows(
                "SELECT id FROM observations "
                "WHERE room_key = ? AND camera_id = ? AND is_baseline = 1",
                (room, CAMERA_ID),
            ),
            [(first["id"],)],
        )
        self.assertEqual(
            self.rows(
                "SELECT view_status FROM room_monitor_status WHERE room_key = ?",
                (room,),
            ),
            [("unknown",)],
        )
        self.assertNotIn((room, first["id"]), self.app.config["TRACKERS"])
        self.assertNotIn((room, second["id"]), self.app.config["TRACKERS"])
        self.assertIn((other_room, 999), self.app.config["TRACKERS"])

    def test_activate_and_delete_enforce_room_and_camera_scope(self):
        layout = self.post_layout("Living").get_json()["layout"]

        self.assertEqual(self.activate(layout["id"], room_name="Kitchen").status_code, 404)
        self.assertEqual(self.delete(layout["id"], room_name="Kitchen").status_code, 404)
        self.assertEqual(
            self.activate(layout["id"], camera_id="other-camera").status_code, 400
        )
        self.assertEqual(
            self.delete(layout["id"], camera_id="other-camera").status_code, 400
        )
        self.assertEqual(
            self.get_layouts(camera_id="other-camera").status_code, 400
        )
        self.assertEqual(
            self.rows("SELECT id, is_baseline FROM observations"),
            [(layout["id"], 1)],
        )

    def test_invalid_and_missing_layout_ids_are_rejected(self):
        for invalid_id in ("not-a-number", "0", "-1"):
            with self.subTest(layout_id=invalid_id):
                self.assertEqual(self.activate(invalid_id).status_code, 400)
                self.assertEqual(self.delete(invalid_id).status_code, 400)
        self.assertEqual(self.activate("99999").status_code, 404)
        self.assertEqual(self.delete("99999").status_code, 404)

    def test_active_and_last_available_layouts_cannot_be_deleted(self):
        active = self.post_layout("Only layout").get_json()["layout"]
        self.assertEqual(self.delete(active["id"]).status_code, 409)

        with closing(connect_database(str(self.database_path))) as connection:
            connection.execute(
                """
                INSERT INTO observations (
                    room_key, room_name, camera_id, captured_at, image,
                    image_width, image_height, is_baseline, layout_name
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)
                """,
                (
                    room_key("Hall"),
                    "Hall",
                    CAMERA_ID,
                    "2026-11-16T00:00:00Z",
                    b"test-image",
                    64,
                    48,
                    "Only available",
                ),
            )
            connection.commit()
        last_id = self.rows(
            "SELECT id FROM observations WHERE room_key = ?", (room_key("Hall"),)
        )[0][0]

        response = self.delete(last_id, room_name="Hall")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            self.rows(
                "SELECT deleted_at FROM observations WHERE id = ?", (last_id,)
            ),
            [(None,)],
        )

    def test_delete_is_soft_and_never_removes_related_records(self):
        deleted = self.post_layout("Old").get_json()["layout"]
        active = self.post_layout("Current").get_json()["layout"]
        before_detections = self.rows(
            "SELECT id, observation_id, class_name FROM detections ORDER BY id"
        )
        before_events = self.rows("SELECT * FROM change_events ORDER BY id")

        response = self.delete(deleted["id"])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.rows(
                "SELECT is_baseline, deleted_at, length(image) "
                "FROM observations WHERE id = ?",
                (deleted["id"],),
            )[0][:2],
            (0, response.get_json()["deleted_at"]),
        )
        self.assertGreater(
            self.rows(
                "SELECT length(image) FROM observations WHERE id = ?",
                (deleted["id"],),
            )[0][0],
            0,
        )
        self.assertEqual(
            self.rows(
                "SELECT id, observation_id, class_name FROM detections ORDER BY id"
            ),
            before_detections,
        )
        self.assertEqual(
            self.rows("SELECT * FROM change_events ORDER BY id"), before_events
        )
        self.assertEqual(
            self.rows(
                "SELECT id FROM observations WHERE is_baseline = 1"
            ),
            [(active["id"],)],
        )
        self.assertEqual(self.activate(deleted["id"]).status_code, 409)

    def test_save_rolls_back_baseline_insert_detections_and_status_on_failure(self):
        active = self.post_layout("Original").get_json()["layout"]
        self.set_view_status("Living room", "stable")
        tracker_key = (room_key("Living room"), active["id"])
        tracker = {"counts": {"chair": 2}, "announced": {"chair"}}
        self.app.config["TRACKERS"][tracker_key] = tracker

        with patch(
            "routes.layout_routes._insert_detections",
            side_effect=sqlite3.IntegrityError("injected insert failure"),
        ):
            response = self.post_layout("Should roll back")

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            self.rows(
                "SELECT id, is_baseline, layout_name FROM observations"
            ),
            [(active["id"], 1, "Original")],
        )
        self.assertEqual(
            self.rows("SELECT view_status FROM room_monitor_status"),
            [("stable",)],
        )
        self.assertIs(self.app.config["TRACKERS"][tracker_key], tracker)

    def test_activation_rolls_back_baseline_switch_when_status_update_fails(self):
        first = self.post_layout("First").get_json()["layout"]
        second = self.post_layout("Second").get_json()["layout"]
        self.set_view_status("Living room", "stable")

        with patch(
            "routes.layout_routes._mark_view_unknown",
            side_effect=sqlite3.IntegrityError("injected status failure"),
        ):
            response = self.activate(first["id"])

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            self.rows(
                "SELECT id FROM observations WHERE is_baseline = 1"
            ),
            [(second["id"],)],
        )
        self.assertEqual(
            self.rows("SELECT view_status FROM room_monitor_status"),
            [("stable",)],
        )

    def test_layout_endpoints_require_completed_migration(self):
        other_path = Path(self.temp_dir.name) / "unmigrated.sqlite3"
        unmigrated_app = create_app(other_path, detector=FakeModel())
        client = unmigrated_app.test_client()
        with closing(connect_database(str(other_path))) as connection:
            connection.execute("PRAGMA user_version = 0")
            connection.commit()

        response = client.get(
            f"/api/layouts?room_name=Living%20room&camera_id={CAMERA_ID}"
        )

        self.assertEqual(response.status_code, 503)
        self.assertIn("migration", response.get_json()["error"].lower())

    def test_existing_baseline_api_keeps_response_and_assigns_history_name(self):
        response = self.client.post(
            "/api/baseline",
            json={"room_name": "Living room", "image": self.image_data},
        )

        self.assertEqual(response.status_code, 201)
        baseline = response.get_json()["baseline"]
        self.assertEqual(
            set(baseline),
            {
                "id",
                "room_name",
                "camera_id",
                "captured_at",
                "image_width",
                "image_height",
                "image_data_url",
                "detections",
            },
        )
        self.assertEqual(
            self.rows(
                "SELECT layout_name FROM observations WHERE id = ?",
                (baseline["id"],),
            ),
            [(f"Layout {baseline['captured_at']}",)],
        )


if __name__ == "__main__":
    unittest.main()
