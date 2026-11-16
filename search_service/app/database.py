"""Read-only access to the canonical SQLite database."""

from __future__ import annotations

import sqlite3
from pathlib import Path

PROJECT_TABLES = (
    "crop",
    "crop_indicator",
    "data_source",
    "exchange",
    "flow",
    "process",
    "province_region_map",
    "region",
    "regional_aggregate",
    "regional_contribution",
    "source_file",
)

REQUIRED_COLUMNS = {
    "process": (
        "process_id",
        "crop_id",
        "source_id",
        "area",
        "year_ce",
        "year_original",
        "calendar",
        "season",
        "product_name",
        "spatial_level",
        "region_code",
    ),
    "crop": ("crop_id", "crop_name"),
    "region": ("region_code", "region_name"),
    "data_source": ("source_id", "agency", "title"),
    "exchange": ("process_id", "flow_id", "direction", "unit"),
    "flow": ("flow_id", "flow_name", "flow_type"),
    "crop_indicator": ("process_id", "metric_code", "unit"),
    "regional_aggregate": ("process_id", "method"),
}


class DatabaseError(RuntimeError):
    """The SQLite catalog does not match the indexing contract."""


def connect_readonly(path: Path) -> sqlite3.Connection:
    """Open SQLite with URI mode=ro and PRAGMA query_only=ON."""
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise DatabaseError(f"SQLite database file is missing: {resolved.name}")
    connection = sqlite3.connect(resolved.as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    mode = connection.execute("PRAGMA query_only").fetchone()[0]
    if mode != 1:
        connection.close()
        raise DatabaseError("PRAGMA query_only did not stay enabled")
    return connection


def list_tables(connection: sqlite3.Connection) -> list[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    )
    return [row[0] for row in rows]


def table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}


def verify_catalog(connection: sqlite3.Connection, expected_process_count: int | None = None) -> None:
    """Confirm the validated project catalog before any document is built."""
    tables = list_tables(connection)
    if set(tables) != set(PROJECT_TABLES):
        missing = sorted(set(PROJECT_TABLES) - set(tables))
        extra = sorted(set(tables) - set(PROJECT_TABLES))
        raise DatabaseError(f"SQLite catalog mismatch; missing={missing}; extra={extra}")
    if len(tables) != len(PROJECT_TABLES):
        raise DatabaseError("expected the 11 validated project tables")
    for table, columns in REQUIRED_COLUMNS.items():
        present = table_columns(connection, table)
        missing = [column for column in columns if column not in present]
        if missing:
            raise DatabaseError(f"{table} is missing columns: {', '.join(missing)}")
    count = connection.execute("SELECT COUNT(*) FROM process").fetchone()[0]
    if count <= 0:
        raise DatabaseError("process catalog is empty")
    if expected_process_count is not None and count != expected_process_count:
        raise DatabaseError(f"process count is {count}, expected {expected_process_count}")
