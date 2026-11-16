"""Apply the draft schema and copy SQLite plus Qdrant into the disposable database.

The canonical SQLite file is opened read-only. Qdrant is only scrolled.
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
import struct
import urllib.request
from pathlib import Path

from app.migration_audit import EXPECTED_COUNTS, FRACTIONAL_QUANTITIES, ORPHAN_CHECKS
from scripts.pg_local_common import DATABASE, HOST, PORT, connect_migration, redact

ROOT = Path(__file__).resolve().parents[1]
SQLITE = Path(os.environ.get("SQLITE_PATH", r"D:\Final Project\Hee_M3\output\S1-G14_M3.sqlite"))
QDRANT = os.environ.get("QDRANT_URL", "http://127.0.0.1:6333").rstrip("/")
SCHEMA = ROOT / "migrations" / "postgres" / "001_schema.sql"
VECTOR_SCHEMA = ROOT / "migrations" / "postgres" / "002_pgvector.sql"
REPORT = ROOT / "artifacts" / "deploy01c" / "load_report.json"
FINGERPRINT = "75aecb4737a45afa01a135af63eff05ff73953a9b4065f2d481ab1716f6f79ef"
LOAD_ORDER = (
    "crop",
    "region",
    "data_source",
    "flow",
    "source_file",
    "province_region_map",
    "process",
    "exchange",
    "crop_indicator",
    "regional_aggregate",
    "regional_contribution",
)


def main() -> None:
    if DATABASE != "s1g14_migration_test" or HOST not in {"127.0.0.1", "localhost", "postgres"}:
        raise SystemExit("this loader is limited to the disposable local database")
    report: dict = {"database": DATABASE, "host": HOST, "port": PORT}
    with connect_migration() as connection:
        report["versions"] = _versions(connection)
        report["schema"] = _apply_schema(connection)
        report["relational"] = _copy_relational(connection)
        report["vectors"] = _copy_vectors(connection)
        report["constraints"] = _constraint_summary(connection)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("versions", "schema", "relational", "vectors", "constraints")}, indent=2))


def _versions(connection) -> dict:
    version = connection.execute("SELECT version()").fetchone()[0]
    server = connection.execute("SHOW server_version").fetchone()[0]
    return {"server_version": server, "version": version}


def _apply_schema(connection) -> dict:
    connection.commit()
    connection.execute("DROP SCHEMA IF EXISTS public CASCADE")
    connection.execute("CREATE SCHEMA public")
    connection.execute("GRANT ALL ON SCHEMA public TO public")
    connection.commit()
    _apply_file(connection, SCHEMA)
    first_extension = _apply_file(connection, VECTOR_SCHEMA)
    rerun = {}
    for name, path in (("001_schema.sql", SCHEMA), ("002_pgvector.sql", VECTOR_SCHEMA)):
        try:
            _apply_file(connection, path)
        except Exception as exc:
            connection.rollback()
            rerun[name] = {"failed": True, "error": type(exc).__name__, "message": redact(str(exc)).splitlines()[0]}
        else:
            rerun[name] = {"failed": False}
    extension = connection.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'").fetchone()
    dimension = connection.execute(
        """
        SELECT atttypmod
        FROM pg_attribute
        JOIN pg_class ON pg_class.oid = pg_attribute.attrelid
        WHERE pg_class.relname = 'process_embeddings' AND pg_attribute.attname = 'embedding'
        """
    ).fetchone()
    tables = [
        row[0]
        for row in connection.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
        )
    ]
    connection.commit()
    return {
        "extension": None if extension is None else extension[0],
        "vector_typmod": None if dimension is None else int(dimension[0]),
        "tables": tables,
        "rerun": rerun,
        "vector_file_applied": first_extension,
    }


def _apply_file(connection, path: Path) -> int:
    statements = _statements(path.read_text(encoding="utf-8"))
    with connection.transaction():
        for statement in statements:
            connection.execute(statement)
    connection.commit()
    return len(statements)


def _statements(text: str) -> list[str]:
    kept = []
    for line in text.splitlines():
        if "--" in line:
            line = line[: line.index("--")]
        kept.append(line)
    return [part.strip() for part in "\n".join(kept).split(";") if part.strip()]


def _copy_relational(connection) -> dict:
    source = _sqlite()
    try:
        source.execute("PRAGMA query_only=ON")
        with connection.transaction():
            for table in LOAD_ORDER:
                sqlite_columns = [row[1] for row in source.execute(f"PRAGMA table_info({table})")]
                postgres_columns = [
                    row[0]
                    for row in connection.execute(
                        """
                        SELECT column_name FROM information_schema.columns
                        WHERE table_schema = 'public' AND table_name = %s
                        ORDER BY ordinal_position
                        """,
                        (table,),
                    )
                ]
                if sqlite_columns != postgres_columns:
                    raise RuntimeError(f"column mismatch for {table}: {sqlite_columns} vs {postgres_columns}")
                rows = list(source.execute(f"SELECT {', '.join(sqlite_columns)} FROM {table}"))
                marks = ", ".join(["%s"] * len(postgres_columns))
                columns = ", ".join(postgres_columns)
                with connection.cursor() as cursor:
                    cursor.executemany(
                        f"INSERT INTO {table} ({columns}) VALUES ({marks})",
                        rows,
                    )
        connection.commit()
        counts = {
            table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in LOAD_ORDER
        }
        orphans = {
            name: int(connection.execute(sql).fetchone()[0])
            for name, sql in ORPHAN_CHECKS.items()
        }
        fractional = []
        for process_id, expected in FRACTIONAL_QUANTITIES:
            found = connection.execute(
                "SELECT quantity FROM exchange WHERE process_id = %s AND direction = 'Output'",
                (process_id,),
            ).fetchone()[0]
            fractional.append(
                {
                    "process_id": process_id,
                    "exact": float(found) == expected and struct.pack(">d", float(found)) == struct.pack(">d", expected),
                }
            )
        country_null = int(
            connection.execute(
                "SELECT COUNT(*) FROM process WHERE spatial_level = 'country' AND region_code IS NULL"
            ).fetchone()[0]
        )
        codes = {
            "crops": [row[0] for row in connection.execute("SELECT crop_id FROM crop ORDER BY crop_id")],
            "regions": [row[0] for row in connection.execute("SELECT region_code FROM region ORDER BY region_code")],
        }
    finally:
        source.close()
    return {
        "counts": counts,
        "count_mismatches": {table: counts[table] for table, expected in EXPECTED_COUNTS.items() if counts[table] != expected},
        "orphan_total": sum(orphans.values()),
        "country_null_regions": country_null,
        "fractional_exact": fractional,
        "codes": codes,
    }


def _copy_vectors(connection) -> dict:
    points = _scroll()
    fingerprint = _fingerprint(points)
    with connection.transaction():
        with connection.cursor() as cursor:
            for point in points:
                payload = point["payload"]
                vector = point["vector"]
                if len(vector) != 1024 or any(not math.isfinite(float(value)) for value in vector):
                    raise RuntimeError(f"rejected vector for {payload.get('process_id')}")
                cursor.execute(
                    """
                    INSERT INTO process_embeddings (
                      process_id, point_id, embedding, embedding_model, embedding_provider,
                      model_revision, vector_dimension, text_hash, document_schema_version,
                      crop_id, year_ce, season, spatial_level, region_code, source_id
                    ) VALUES (
                      %s, %s, %s::vector, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        payload["process_id"],
                        point["id"],
                        _vector_literal(vector),
                        payload["embedding_model"],
                        payload["embedding_provider"],
                        payload["model_revision"],
                        int(payload["vector_dimension"]),
                        payload["text_hash"],
                        payload["document_schema_version"],
                        payload["crop_id"],
                        int(payload["year_ce"]),
                        payload["season"],
                        payload["spatial_level"],
                        payload["region_code"],
                        payload["source_id"],
                    ),
                )
    connection.commit()
    connection.execute("SET extra_float_digits = 3")
    stored = connection.execute(
        """
        SELECT process_id, point_id::text, embedding::text, model_revision, vector_dimension,
               embedding_model, embedding_provider, text_hash, document_schema_version,
               crop_id, year_ce, season, spatial_level, region_code, source_id
        FROM process_embeddings
        ORDER BY process_id
        """
    ).fetchall()
    by_id = {point["payload"]["process_id"]: point for point in points}
    max_diff = 0.0
    worst = None
    metadata_mismatches = []
    for row in stored:
        source = by_id[row[0]]
        parsed = [float(part) for part in row[2].strip()[1:-1].split(",")]
        diffs = [abs(float(left) - right) for left, right in zip(source["vector"], parsed)]
        local_max = max(diffs)
        if local_max > max_diff:
            max_diff = local_max
            worst = row[0]
        payload = source["payload"]
        if (
            row[1] != source["id"]
            or row[3] != payload["model_revision"]
            or int(row[4]) != int(payload["vector_dimension"])
            or row[5] != payload["embedding_model"]
            or row[6] != payload["embedding_provider"]
            or row[7] != payload["text_hash"]
            or row[8] != payload["document_schema_version"]
            or row[9] != payload["crop_id"]
            or int(row[10]) != int(payload["year_ce"])
            or row[11] != payload["season"]
            or row[12] != payload["spatial_level"]
            or row[13] != payload["region_code"]
            or row[14] != payload["source_id"]
        ):
            metadata_mismatches.append(row[0])
    norms = connection.execute(
        "SELECT COUNT(*) FILTER (WHERE vector_norm(embedding) > 0), COUNT(*) FROM process_embeddings"
    ).fetchone()
    return {
        "rows": len(stored),
        "distinct_process_ids": int(connection.execute("SELECT COUNT(DISTINCT process_id) FROM process_embeddings").fetchone()[0]),
        "distinct_point_ids": int(connection.execute("SELECT COUNT(DISTINCT point_id) FROM process_embeddings").fetchone()[0]),
        "fingerprint_matches": fingerprint == FINGERPRINT,
        "max_component_abs_diff": max_diff,
        "worst_process_id": worst,
        "metadata_mismatches": metadata_mismatches,
        "nonzero_vectors": int(norms[0]),
        "stored_rows": int(norms[1]),
        "component_threshold": 1e-6,
        "within_component_threshold": max_diff <= 1e-6,
    }


def _constraint_summary(connection) -> dict:
    rows = connection.execute(
        """
        SELECT contype, COUNT(*)
        FROM pg_constraint
        WHERE connamespace = 'public'::regnamespace
        GROUP BY contype
        ORDER BY contype
        """
    ).fetchall()
    labels = {"p": "primary_key", "f": "foreign_key", "u": "unique", "c": "check"}
    return {labels.get(row[0], row[0]): int(row[1]) for row in rows}


def _sqlite() -> sqlite3.Connection:
    uri = SQLITE.resolve().as_uri().replace("file:///", "file:/") + "?mode=ro"
    return sqlite3.connect(uri, uri=True)


def _scroll() -> list[dict]:
    offset = None
    points = []
    while True:
        body = {"limit": 64, "with_payload": True, "with_vector": True}
        if offset is not None:
            body["offset"] = offset
        request = urllib.request.Request(
            f"{QDRANT}/collections/crop_process_bge_m3/points/scroll",
            data=json.dumps(body).encode(),
            headers={"content-type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            page = json.load(response)["result"]
        points.extend(page.get("points") or [])
        offset = page.get("next_page_offset")
        if not offset:
            break
    if len(points) != 105:
        raise RuntimeError(f"expected 105 Qdrant points, scrolled {len(points)}")
    return points


def _fingerprint(points: list[dict]) -> str:
    import hashlib

    digest = hashlib.sha256()
    for point in sorted(points, key=lambda item: str(item["payload"]["process_id"])):
        digest.update(str(point["payload"]["process_id"]).encode())
        digest.update(struct.pack("<1024d", *[float(value) for value in point["vector"]]))
    return digest.hexdigest()


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(repr(float(value)) for value in vector) + "]"


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        raise SystemExit(redact(str(exc))) from None
