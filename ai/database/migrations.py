import re


LATEST_SCHEMA_VERSION = 1


class MigrationError(RuntimeError):
    pass


def _table_columns(connection, table_name):
    return {
        row["name"]
        for row in connection.execute(f"PRAGMA table_info('{table_name}')")
    }


def _index(connection, index_name):
    for row in connection.execute("PRAGMA index_list('observations')"):
        if row["name"] == index_name:
            return row
    return None


def _index_columns(connection, index_name):
    return [
        (row["name"], bool(row["desc"]))
        for row in connection.execute(f"PRAGMA index_xinfo('{index_name}')")
        if row["key"]
    ]


def _validate_baseline_index(connection):
    index = _index(connection, "one_baseline_per_room_camera")
    if index is None or not index["unique"] or not index["partial"]:
        raise MigrationError(
            "The one-baseline-per-room-camera unique partial index is missing or invalid."
        )

    index_sql = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'index' "
        "AND name = 'one_baseline_per_room_camera'"
    ).fetchone()
    if (
        _index_columns(connection, "one_baseline_per_room_camera")
        != [("room_key", False), ("camera_id", False)]
        or index_sql is None
        or re.search(r"\bwhere\s+is_baseline\s*=\s*1\s*$", index_sql["sql"], re.I)
        is None
    ):
        raise MigrationError(
            "The one-baseline-per-room-camera unique partial index is invalid."
        )


def _validate_history_index(connection):
    index = _index(connection, "observations_layout_history")
    if index is None or index["unique"] or index["partial"]:
        raise MigrationError("The observations_layout_history index is invalid.")
    if _index_columns(connection, "observations_layout_history") != [
        ("room_key", False),
        ("deleted_at", False),
        ("captured_at", True),
    ]:
        raise MigrationError("The observations_layout_history index is invalid.")


def _validate_version_1(connection):
    columns = _table_columns(connection, "observations")
    if not {"layout_name", "deleted_at"}.issubset(columns):
        raise MigrationError("Schema version 1 is missing required layout columns.")
    _validate_baseline_index(connection)
    _validate_history_index(connection)
    if connection.execute(
        "SELECT 1 FROM observations WHERE layout_name IS NULL LIMIT 1"
    ).fetchone():
        raise MigrationError("Schema version 1 contains observations without layout names.")


def _migrate_to_version_1(connection):
    columns = _table_columns(connection, "observations")
    required_columns = {
        "room_key",
        "camera_id",
        "captured_at",
        "is_baseline",
    }
    if not required_columns.issubset(columns):
        raise MigrationError("Cannot migrate: observations has an unexpected schema.")

    if "layout_name" not in columns:
        connection.execute("ALTER TABLE observations ADD COLUMN layout_name TEXT")
    if "deleted_at" not in columns:
        connection.execute("ALTER TABLE observations ADD COLUMN deleted_at TEXT")

    connection.execute(
        """
        UPDATE observations
        SET layout_name = 'Layout ' || captured_at
        WHERE layout_name IS NULL
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS observations_layout_history
        ON observations (room_key, deleted_at, captured_at DESC)
        """
    )

    _validate_version_1(connection)
    connection.execute(f"PRAGMA user_version = {LATEST_SCHEMA_VERSION}")


def migrate_database(connection):
    """Apply all supported schema migrations atomically on an open connection."""
    if connection.in_transaction:
        raise MigrationError("Database migrations require a connection with no active transaction.")

    try:
        connection.execute("BEGIN IMMEDIATE")
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version < 0 or version > LATEST_SCHEMA_VERSION:
            raise MigrationError(
                f"Database schema version {version} is outside the supported range "
                f"0-{LATEST_SCHEMA_VERSION}."
            )
        if version == 0:
            _migrate_to_version_1(connection)
        elif version == 1:
            _validate_version_1(connection)
        connection.commit()
    except BaseException:
        if connection.in_transaction:
            connection.rollback()
        raise
