"""Read-only catalog and saved evaluation views for the local frontend.

These helpers do not write SQLite, do not call Qdrant, and do not regenerate reports.
"""

from __future__ import annotations

import json
from pathlib import Path

from .config import DEFAULT_SQLITE_PATH, load_settings
from .database import DatabaseError, connect_readonly

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT_PATH = ROOT / "evaluation" / "reports" / "evaluation.json"
NUMERIC_METRICS = (
    {"metric": "production", "unit": "t"},
    {"metric": "yield_harvested", "unit": "kg/rai"},
    {"metric": "yield_planted", "unit": "kg/rai"},
    {"metric": "area_harvested", "unit": "rai"},
    {"metric": "area_planted", "unit": "rai"},
)


class PublicDataError(RuntimeError):
    """A frontend read failed with a client-safe message."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def read_configured_catalog() -> dict:
    """Read the catalog for the selected backend. PostgreSQL errors do not open SQLite."""
    settings = load_settings()
    if settings.data_backend == "postgres":
        return _read_postgres_catalog(settings.database_url)
    return read_public_catalog(settings.sqlite_path)


def read_public_catalog(db_path: Path | None = None) -> dict:
    """Return filter values that exist in SQLite. Paths are not included."""
    path = DEFAULT_SQLITE_PATH if db_path is None else db_path
    try:
        connection = connect_readonly(path)
    except DatabaseError as exc:
        raise PublicDataError("sqlite_unavailable", "SQLite is unavailable") from exc
    try:
        return _catalog_payload(connection)
    except Exception as exc:
        raise PublicDataError("sqlite_unavailable", "SQLite is unavailable") from exc
    finally:
        connection.close()


def _read_postgres_catalog(database_url: str) -> dict:
    from .postgres_provider import PostgresDataProvider

    provider = PostgresDataProvider(database_url)
    try:
        connection = provider.connect()
    except DatabaseError as exc:
        raise PublicDataError("postgres_unavailable", "PostgreSQL is unavailable") from exc
    try:
        return _catalog_payload(connection)
    except PublicDataError:
        raise
    except Exception as exc:
        raise PublicDataError("postgres_unavailable", "PostgreSQL is unavailable") from exc
    finally:
        connection.close()


def _catalog_payload(connection) -> dict:
    crops = [
        {"crop_id": row[0], "crop_name": row[1]}
        for row in connection.execute("SELECT crop_id, crop_name FROM crop ORDER BY crop_id")
    ]
    regions = [
        {"region_code": row[0], "region_name": row[1]}
        for row in connection.execute("SELECT region_code, region_name FROM region ORDER BY region_code")
    ]
    seasons = [row[0] for row in connection.execute("SELECT DISTINCT season FROM process ORDER BY season")]
    spatial_levels = [row[0] for row in connection.execute("SELECT DISTINCT spatial_level FROM process ORDER BY spatial_level")]
    sources = [
        {"source_id": row[0], "agency": row[1], "title": row[2]}
        for row in connection.execute("SELECT source_id, agency, title FROM data_source ORDER BY source_id")
    ]
    years = [int(row[0]) for row in connection.execute("SELECT DISTINCT year_ce FROM process ORDER BY year_ce")]
    process_count = int(connection.execute("SELECT COUNT(*) FROM process").fetchone()[0])
    return {
        "crops": crops,
        "regions": regions,
        "seasons": seasons,
        "spatial_levels": spatial_levels,
        "sources": sources,
        "years": years,
        "process_count": process_count,
        "numeric_metrics": list(NUMERIC_METRICS),
        "numeric_operators": ["gt", "gte", "lt", "lte"],
    }


def read_evaluation_report(path: Path = DEFAULT_REPORT_PATH) -> dict:
    """Return the saved evaluation report. This function does not rerun the evaluation."""
    if not path.is_file():
        raise PublicDataError("report_unavailable", "The evaluation report is not available.")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PublicDataError("report_unavailable", "The evaluation report is not available.") from exc
    if not isinstance(payload, dict):
        raise PublicDataError("report_unavailable", "The evaluation report is not available.")
    payload.pop("safety", None)
    backends = payload.get("backends")
    if isinstance(backends, dict):
        for body in backends.values():
            if isinstance(body, dict):
                body.pop("queries", None)
    public = _strip_paths(payload)
    public["report_note"] = "Values are read from the saved evaluation report. This request does not rerun the evaluation."
    return public


def _strip_paths(value):
    if isinstance(value, dict):
        return {key: _strip_paths(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_strip_paths(item) for item in value]
    if isinstance(value, str) and ("\\" in value or value.startswith("/") or value.lower().startswith("file:")):
        return None
    return value
