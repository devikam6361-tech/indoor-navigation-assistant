import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from database.connection import connect_database, initialize_database
from database.migrations import MigrationError, migrate_database


class DatabaseMigrationsTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "migration.sqlite3"

    def tearDown(self):
        self.temp_dir.cleanup()

    def create_legacy_database(self, *, layout_name_column=False):
        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            layout_name = ", layout_name TEXT" if layout_name_column else ""
            connection.executescript(
                f"""
                CREATE TABLE observations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    room_key TEXT NOT NULL,
                    room_name TEXT NOT NULL,
                    camera_id TEXT NOT NULL,
                    captured_at TEXT NOT NULL,
                    image BLOB NOT NULL,
                    image_width INTEGER NOT NULL,
                    image_height INTEGER NOT NULL,
                    is_baseline INTEGER NOT NULL DEFAULT 1
                    {layout_name}
                );
                CREATE UNIQUE INDEX one_baseline_per_room_camera
                    ON observations (room_key, camera_id)
                    WHERE is_baseline = 1;
                CREATE TABLE detections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    observation_id INTEGER NOT NULL
                        REFERENCES observations(id) ON DELETE CASCADE,
                    class_name TEXT NOT NULL
                );
                CREATE TABLE latest_observations (
                    room_key TEXT PRIMARY KEY,
                    room_name TEXT NOT NULL,
                    camera_id TEXT NOT NULL,
                    captured_at TEXT NOT NULL,
                    image BLOB NOT NULL
                );
                CREATE TABLE change_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    room_key TEXT NOT NULL,
                    baseline_id INTEGER NOT NULL REFERENCES observations(id),
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE room_monitor_status (
                    room_key TEXT PRIMARY KEY,
                    camera_id TEXT NOT NULL,
                    view_status TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            insert_columns = (
                "room_key, room_name, camera_id, captured_at, image, "
                "image_width, image_height, is_baseline"
            )
            insert_values = (
                "living-room", "Living room", "default-webcam",
                "2026-11-17T10:00:00Z", sqlite3.Binary(b"baseline-image"), 64, 48, 1
            )
            if layout_name_column:
                insert_columns += ", layout_name"
                connection.execute(
                    f"INSERT INTO observations ({insert_columns}) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (*insert_values, "Custom name"),
                )
                connection.execute(
                    """
                    INSERT INTO observations (
                        room_key, room_name, camera_id, captured_at, image,
                        image_width, image_height, is_baseline, layout_name
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, NULL)
                    """,
                    (
                        "living-room", "Living room", "default-webcam",
                        "2026-11-17T10:01:00Z", sqlite3.Binary(b"historical-image"),
                        64, 48,
                    ),
                )
            else:
                connection.execute(
                    f"INSERT INTO observations ({insert_columns}) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    insert_values,
                )
                connection.execute(
                    """
                    INSERT INTO observations (
                        room_key, room_name, camera_id, captured_at, image,
                        image_width, image_height, is_baseline
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 0)
                    """,
                    (
                        "living-room", "Living room", "default-webcam",
                        "2026-11-17T10:01:00Z", sqlite3.Binary(b"historical-image"),
                        64, 48,
                    ),
                )

            connection.execute(
                "INSERT INTO detections (observation_id, class_name) VALUES (1, 'chair')"
            )
            connection.execute(
                "INSERT INTO latest_observations VALUES (?, ?, ?, ?, ?)",
                (
                    "living-room", "Living room", "default-webcam",
                    "2026-11-17T10:02:00Z", sqlite3.Binary(b"latest-image"),
                ),
            )
            connection.execute(
                """
                INSERT INTO change_events (room_key, baseline_id, message, created_at)
                VALUES ('living-room', 1, 'Moved chair', '2026-11-17T10:02:00Z')
                """
            )
            connection.execute(
                "INSERT INTO room_monitor_status VALUES (?, ?, ?, ?)",
                (
                    "living-room", "default-webcam", "stable",
                    "2026-11-17T10:02:00Z",
                ),
            )
            connection.commit()

    def migrate(self):
        with closing(connect_database(str(self.database_path))) as connection:
            migrate_database(connection)

    def test_existing_database_migration_preserves_all_existing_records(self):
        self.create_legacy_database()
        with closing(connect_database(str(self.database_path))) as connection:
            before = {}
            for table in (
                "observations",
                "detections",
                "latest_observations",
                "change_events",
                "room_monitor_status",
            ):
                columns = [
                    row["name"]
                    for row in connection.execute(f"PRAGMA table_info('{table}')")
                ]
                rows = connection.execute(
                    f"SELECT {', '.join(columns)} FROM {table} ORDER BY 1"
                ).fetchall()
                before[table] = (columns, [tuple(row) for row in rows])

        self.migrate()

        with closing(connect_database(str(self.database_path))) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info('observations')")
            }
            self.assertTrue({"layout_name", "deleted_at"}.issubset(columns))
            for table, (columns, rows) in before.items():
                after = connection.execute(
                    f"SELECT {', '.join(columns)} FROM {table} ORDER BY 1"
                ).fetchall()
                self.assertEqual([tuple(row) for row in after], rows)
            self.assertEqual(
                [tuple(row) for row in connection.execute(
                    "SELECT layout_name, deleted_at FROM observations ORDER BY id"
                )],
                [
                    ("Layout 2026-11-17T10:00:00Z", None),
                    ("Layout 2026-11-17T10:01:00Z", None),
                ],
            )
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_migration_adds_only_missing_columns_and_preserves_existing_names(self):
        self.create_legacy_database(layout_name_column=True)

        self.migrate()

        with closing(connect_database(str(self.database_path))) as connection:
            self.assertEqual(
                [tuple(row) for row in connection.execute(
                    "SELECT layout_name, deleted_at FROM observations ORDER BY id"
                )],
                [
                    ("Custom name", None),
                    ("Layout 2026-11-17T10:01:00Z", None),
                ],
            )
            columns = [
                row["name"]
                for row in connection.execute("PRAGMA table_info('observations')")
            ]
            self.assertEqual(columns.count("layout_name"), 1)
            self.assertEqual(columns.count("deleted_at"), 1)

    def test_migration_rolls_back_schema_backfill_and_version_on_failure(self):
        self.create_legacy_database()
        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.execute(
                """
                CREATE INDEX observations_layout_history
                ON observations (room_key, captured_at)
                """
            )
            connection.commit()

        with self.assertRaises(MigrationError):
            self.migrate()

        with closing(connect_database(str(self.database_path))) as connection:
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info('observations')")
            }
            self.assertNotIn("layout_name", columns)
            self.assertNotIn("deleted_at", columns)
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 0)
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0],
                2,
            )
            self.assertEqual(
                [tuple(row) for row in connection.execute(
                    "SELECT image FROM observations ORDER BY id"
                )],
                [(b"baseline-image",), (b"historical-image",)],
            )

    def test_rerunning_migration_is_idempotent(self):
        self.create_legacy_database()

        self.migrate()
        with closing(connect_database(str(self.database_path))) as connection:
            before = {
                table: [
                    tuple(row)
                    for row in connection.execute(f"SELECT * FROM {table} ORDER BY 1")
                ]
                for table in ("observations", "detections")
            }

        self.migrate()

        with closing(connect_database(str(self.database_path))) as connection:
            after = {
                table: [
                    tuple(row)
                    for row in connection.execute(f"SELECT * FROM {table} ORDER BY 1")
                ]
                for table in ("observations", "detections")
            }
            self.assertEqual(after, before)
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)

    def test_fresh_initialization_applies_version_one(self):
        initialize_database(self.database_path)

        with closing(connect_database(str(self.database_path))) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info('observations')")
            }
            self.assertTrue({"layout_name", "deleted_at"}.issubset(columns))
            self.assertIsNotNone(
                connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='index' "
                    "AND name='observations_layout_history'"
                ).fetchone()
            )

    def test_initialization_migrates_an_existing_version_zero_database(self):
        self.create_legacy_database()

        initialize_database(self.database_path)

        with closing(connect_database(str(self.database_path))) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0], 2)

    def test_importing_server_does_not_create_the_default_app(self):
        import server

        self.assertFalse(hasattr(server, "app"))


if __name__ == "__main__":
    unittest.main()
