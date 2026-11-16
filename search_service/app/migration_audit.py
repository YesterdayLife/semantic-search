"""Read-only migration checks. This module does not write a data export.

Source quantities are compared by exact binary equality. Vector scores are
a separate later check and are not treated as exact.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .database import connect_readonly

EXPECTED_COUNTS = {
    "crop": 4,
    "region": 6,
    "data_source": 5,
    "source_file": 8,
    "flow": 4,
    "province_region_map": 77,
    "process": 105,
    "exchange": 105,
    "crop_indicator": 324,
    "regional_aggregate": 60,
    "regional_contribution": 2875,
}

ORPHAN_CHECKS = {
    "crop_indicator.process_id": (
        "SELECT COUNT(*) FROM crop_indicator AS child "
        "LEFT JOIN process AS parent ON parent.process_id = child.process_id "
        "WHERE parent.process_id IS NULL"
    ),
    "crop_indicator.source_id": (
        "SELECT COUNT(*) FROM crop_indicator AS child "
        "LEFT JOIN data_source AS parent ON parent.source_id = child.source_id "
        "WHERE parent.source_id IS NULL"
    ),
    "exchange.process_id": (
        "SELECT COUNT(*) FROM exchange AS child "
        "LEFT JOIN process AS parent ON parent.process_id = child.process_id "
        "WHERE parent.process_id IS NULL"
    ),
    "exchange.flow_id": (
        "SELECT COUNT(*) FROM exchange AS child "
        "LEFT JOIN flow AS parent ON parent.flow_id = child.flow_id "
        "WHERE parent.flow_id IS NULL"
    ),
    "exchange.source_id": (
        "SELECT COUNT(*) FROM exchange AS child "
        "LEFT JOIN data_source AS parent ON parent.source_id = child.source_id "
        "WHERE parent.source_id IS NULL"
    ),
    "process.crop_id": (
        "SELECT COUNT(*) FROM process AS child "
        "LEFT JOIN crop AS parent ON parent.crop_id = child.crop_id "
        "WHERE parent.crop_id IS NULL"
    ),
    "process.source_id": (
        "SELECT COUNT(*) FROM process AS child "
        "LEFT JOIN data_source AS parent ON parent.source_id = child.source_id "
        "WHERE parent.source_id IS NULL"
    ),
    "process.source_file": (
        "SELECT COUNT(*) FROM process AS child "
        "LEFT JOIN source_file AS parent ON parent.file_path = child.source_file "
        "WHERE parent.file_path IS NULL"
    ),
    "process.region_code": (
        "SELECT COUNT(*) FROM process AS child "
        "LEFT JOIN region AS parent ON parent.region_code = child.region_code "
        "WHERE child.region_code IS NOT NULL AND parent.region_code IS NULL"
    ),
    "province_region_map.region_code": (
        "SELECT COUNT(*) FROM province_region_map AS child "
        "LEFT JOIN region AS parent ON parent.region_code = child.region_code "
        "WHERE parent.region_code IS NULL"
    ),
    "regional_aggregate.process_id": (
        "SELECT COUNT(*) FROM regional_aggregate AS child "
        "LEFT JOIN process AS parent ON parent.process_id = child.process_id "
        "WHERE parent.process_id IS NULL"
    ),
    "regional_contribution.process_id": (
        "SELECT COUNT(*) FROM regional_contribution AS child "
        "LEFT JOIN regional_aggregate AS parent ON parent.process_id = child.process_id "
        "WHERE parent.process_id IS NULL"
    ),
    "regional_contribution.province": (
        "SELECT COUNT(*) FROM regional_contribution AS child "
        "LEFT JOIN province_region_map AS parent ON parent.province = child.province "
        "WHERE parent.province IS NULL"
    ),
    "regional_contribution.source_file": (
        "SELECT COUNT(*) FROM regional_contribution AS child "
        "LEFT JOIN source_file AS parent ON parent.file_path = child.source_file "
        "WHERE parent.file_path IS NULL"
    ),
    "source_file.source_id": (
        "SELECT COUNT(*) FROM source_file AS child "
        "LEFT JOIN data_source AS parent ON parent.source_id = child.source_id "
        "WHERE parent.source_id IS NULL"
    ),
}

FRACTIONAL_QUANTITIES = (
    ("P-SRC-01-RIC-all-2022", 32882932.48),
    ("P-SRC-01-RIC-all-2023", 33851579.48),
    ("P-SRC-01-RIC-all-2024", 33551336.65),
)


def audit_sqlite(path: Path) -> dict:
    """Inspect the canonical file without leaving read-only mode."""
    connection = connect_readonly(path)
    try:
        connection.execute("PRAGMA query_only=ON")
        return audit_connection(connection)
    finally:
        connection.close()


def audit_connection(connection) -> dict:
    """Count rows, orphans, null country regions, and known fractional tonnes."""
    counts = {}
    for table in EXPECTED_COUNTS:
        counts[table] = int(_value(connection, f"SELECT COUNT(*) FROM {table}"))
    orphans = {name: int(_value(connection, sql)) for name, sql in ORPHAN_CHECKS.items()}
    country_null_regions = int(
        _value(connection, "SELECT COUNT(*) FROM process WHERE spatial_level = 'country' AND region_code IS NULL")
    )
    output_exchanges = int(
        _value(connection, "SELECT COUNT(*) FROM exchange WHERE direction = 'Output'")
    )
    fractional = []
    for process_id, expected in FRACTIONAL_QUANTITIES:
        found = _value(connection, "SELECT quantity FROM exchange WHERE process_id = ? AND direction = 'Output'", (process_id,))
        fractional.append(
            {
                "process_id": process_id,
                "expected": expected,
                "actual": None if found is None else float(found),
                "exact": found is not None and float(found) == expected,
            }
        )
    duplicate_processes = int(
        _value(connection, "SELECT COUNT(*) - COUNT(DISTINCT process_id) FROM process")
    )
    return {
        "counts": counts,
        "count_mismatches": {table: counts[table] for table, expected in EXPECTED_COUNTS.items() if counts[table] != expected},
        "orphans": orphans,
        "orphan_total": sum(orphans.values()),
        "country_null_regions": country_null_regions,
        "output_exchanges": output_exchanges,
        "duplicate_process_ids": duplicate_processes,
        "fractional_quantities": fractional,
        "quantity_comparison": "exact binary equality",
        "vector_score_comparison": "not part of this relational audit",
    }


def audit_embeddings(connection) -> dict:
    """Check a PostgreSQL process_embeddings table. Vectors themselves are not exported."""
    row = _row(
        connection,
        """
        SELECT
          COUNT(*) AS points,
          COUNT(*) FILTER (WHERE vector_dimension = 1024) AS dimensions_ok,
          COUNT(*) FILTER (
            WHERE model_revision = 'xenova-4de13258303883538bd53b696b452bf8099f0858-model_quantized.onnx'
          ) AS revision_ok,
          COUNT(*) FILTER (WHERE embedding_model = 'BAAI/bge-m3') AS model_ok,
          COUNT(DISTINCT process_id) AS identities
        FROM process_embeddings
        """,
    )
    finite = _value(
        connection,
        """
        SELECT COUNT(*) FROM process_embeddings
        WHERE vector_norm(embedding) > 0
        """,
    )
    return {
        "points": int(row[0]),
        "dimensions_ok": int(row[1]),
        "revision_ok": int(row[2]),
        "model_ok": int(row[3]),
        "distinct_process_ids": int(row[4]),
        "nonzero_vectors": None if finite is None else int(finite),
        "score_tolerance": "unset until a staging comparison defines one",
    }


def _value(connection, sql: str, params: tuple = ()):
    adapted = sql
    if params and "?" not in sql and "%s" not in sql:
        raise sqlite3.ProgrammingError("parameters require a placeholder")
    if params and "?" in sql:
        adapted = sql
    cursor = connection.execute(adapted if "?" in sql or not params else sql, params)
    row = cursor.fetchone()
    if row is None:
        return None
    return row[0]


def _row(connection, sql: str):
    return connection.execute(sql, ()).fetchone()
