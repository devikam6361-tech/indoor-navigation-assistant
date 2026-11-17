import sqlite3
from contextlib import closing
from pathlib import Path

from database.migrations import migrate_database


def connect_database(database_path):
    connection = sqlite3.connect(database_path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database(database_path):
    Path(database_path).parent.mkdir(parents=True, exist_ok=True)
    with closing(connect_database(database_path)) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_key TEXT NOT NULL,
                room_name TEXT NOT NULL,
                camera_id TEXT NOT NULL,
                captured_at TEXT NOT NULL,
                image BLOB NOT NULL,
                image_width INTEGER NOT NULL,
                image_height INTEGER NOT NULL,
                is_baseline INTEGER NOT NULL DEFAULT 1
            );
            CREATE UNIQUE INDEX IF NOT EXISTS one_baseline_per_room_camera
                ON observations (room_key, camera_id)
                WHERE is_baseline = 1;
            CREATE TABLE IF NOT EXISTS detections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                observation_id INTEGER NOT NULL
                    REFERENCES observations(id) ON DELETE CASCADE,
                class_name TEXT NOT NULL,
                instance_number INTEGER NOT NULL,
                confidence REAL NOT NULL,
                center_x REAL NOT NULL,
                center_y REAL NOT NULL,
                x1 REAL NOT NULL,
                y1 REAL NOT NULL,
                x2 REAL NOT NULL,
                y2 REAL NOT NULL,
                zone TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS latest_observations (
                room_key TEXT PRIMARY KEY,
                room_name TEXT NOT NULL,
                camera_id TEXT NOT NULL,
                captured_at TEXT NOT NULL,
                image BLOB NOT NULL,
                image_width INTEGER NOT NULL,
                image_height INTEGER NOT NULL,
                detections_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS change_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_key TEXT NOT NULL,
                baseline_id INTEGER NOT NULL REFERENCES observations(id),
                event_signature TEXT NOT NULL,
                class_name TEXT NOT NULL,
                change_type TEXT NOT NULL,
                original_zone TEXT,
                current_zone TEXT,
                confidence REAL NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL,
                speech_status TEXT NOT NULL DEFAULT 'pending',
                speech_error TEXT
            );
            CREATE INDEX IF NOT EXISTS change_events_by_room
                ON change_events (room_key, created_at DESC);
            CREATE TABLE IF NOT EXISTS room_monitor_status (
                room_key TEXT PRIMARY KEY,
                camera_id TEXT NOT NULL,
                view_status TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        migrate_database(connection)
