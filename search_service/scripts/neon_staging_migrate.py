"""Dry-run planner for a future Neon staging migration.

The default does not connect to Neon and does not write. A write also requires
S1G14_STAGING_WRITE_APPROVED=1 in that process. This preparation phase does not
set that variable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import struct
import urllib.request
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from app.database import connect_readonly
from app.migration_audit import EXPECTED_COUNTS, FRACTIONAL_QUANTITIES, ORPHAN_CHECKS, audit_sqlite

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_FILES = (
    ROOT / "migrations" / "postgres" / "001_schema.sql",
    ROOT / "migrations" / "postgres" / "002_pgvector.sql",
)
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
FINGERPRINT = "75aecb4737a45afa01a135af63eff05ff73953a9b4065f2d481ab1716f6f79ef"
REVISION = "xenova-4de13258303883538bd53b696b452bf8099f0858-model_quantized.onnx"
COLLECTION = "crop_process_bge_m3"
APPROVAL = "S1G14_STAGING_WRITE_APPROVED"
DESTINATION_URL = "STAGING_DATABASE_URL"
APPROVED_DATABASE = "s1g14_staging"
APPROVED_PG_MAJOR = "18"
APPROVED_SQLITE_SHA256 = "9a80da4111beb44a00c5128c3ffdc10f1e6810825f10a838492981d8e3727808"
APPROVED_SCHEMA_SHA256 = {
    "001_schema.sql": "e73c2f25342c3210e3ff793427dd763d234ba1d36f8d4e9d3054dece4f2fd17e",
    "002_pgvector.sql": "47afa1781c649e8e1e94026eb25e5401a0a759c2d55abc417bcfb26ed246861f",
}
PROJECT_ID_ENV = "EXPECTED_NEON_PROJECT_ID"
BRANCH_ID_ENV = "EXPECTED_NEON_BRANCH_ID"
ENDPOINT_ID_ENV = "EXPECTED_NEON_ENDPOINT_ID"
APP_ROLE = "s1g14_staging_app"
MIGRATION_ROLES = frozenset({"neondb_owner", "s1g14_staging_migrator"})
BLOCKED_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "postgres", "host.docker.internal"})
ALLOWED_SSLMODES = frozenset({"require", "verify-ca", "verify-full"})
ALLOWED_QUERY_KEYS = frozenset({
    "sslmode",
    "channel_binding",
    "connect_timeout",
    "application_name",
    "keepalives",
    "keepalives_idle",
    "keepalives_interval",
    "keepalives_count",
})
COMPONENT_LIMIT = 1e-6
SCORE_LIMIT = 1e-5
DEMONSTRATION_QUERIES = (
    "ผลผลิตมันสำปะหลังภาคเหนือปี 2566",
    "maize production in central Thailand 2022",
    "ข้าวนาปรังปี 2565",
    "มันสำปะหลังและข้าวโพด",
    "ผลผลิตมากกว่า 1000000 ตัน",
    "มันสำปะหลังภาคใต้ปี 2566",
    "carbon footprint of rice production",
)
DICTIONARY_TIE = {
    "queries": ("ข้าว", "rice in Thailand", "ผลผลิตข้าวกับอ้อย"),
    "process_ids": ("P-SRC-04-RIC-dry-2020", "P-SRC-04-RIC-wet-2020"),
    "sort": "p.year_ce, p.area, p.source_id",
    "note": "Those three rows share year 2020, area Thailand, and source SRC-04. The course statement does not define the remaining order.",
}


class MigrationRefused(RuntimeError):
    """A staging write was refused before any destination change."""


class PostCommitValidationFailed(MigrationRefused):
    """The migration committed. A later read-only check failed."""


class CommitOutcomeUnknown(MigrationRefused):
    """The server did not confirm whether COMMIT completed."""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Plan or, only when approved, load Neon staging.")
    parser.add_argument("--write", action="store_true", help="Write to the approved staging database.")
    parser.add_argument("--database", default="", help="Exact staging database name. Required for a write.")
    parser.set_defaults(write=False)
    return parser.parse_args(argv)


def run(argv: list[str] | None = None, *, scroll=None, connect=None) -> dict:
    args = parse_args(argv)
    approved = os.environ.get(APPROVAL) == "1"
    if args.write and not approved:
        raise MigrationRefused("staging write has not been approved for this session")
    if approved and not args.write:
        raise MigrationRefused("the approval flag is set without --write")
    confirmed = None
    host = ""
    if args.write:
        host = prepare_write(args)
        confirmed = confirmed_identity()
    points = (scroll or scroll_qdrant)(_qdrant_url())
    source = source_report(_sqlite_path(), points)
    schema = schema_identity()
    report = {
        "mode": "dry-run",
        "writes": 0,
        "source": source,
        "schema": schema,
        "destination": {"status": "NOT CONNECTED"},
        "validation": validation_plan(),
        "dictionary_tie": DICTIONARY_TIE,
    }
    if not args.write:
        return report
    assert_source_integrity(source, schema)
    connection = (connect or connect_staging)()
    try:
        report["destination"] = authorize_write(connection, args.database, confirmed, host)
        report["load"] = load_destination(connection, points, source)
        report["mode"] = "write"
        report["writes"] = 1
        report["commits"] = 1
    finally:
        connection.close()
    return report


def source_report(path: Path, points: list[dict]) -> dict:
    audit = audit_sqlite(path)
    vectors = vector_report(points)
    return {
        "counts": audit["counts"],
        "count_mismatches": audit["count_mismatches"],
        "orphan_total": audit["orphan_total"],
        "country_null_regions": audit["country_null_regions"],
        "fractional_exact": all(row["exact"] for row in audit["fractional_quantities"]),
        "vectors": vectors,
        "fingerprint_matches": vectors["fingerprint"] == FINGERPRINT,
        "ready": not audit["count_mismatches"] and audit["orphan_total"] == 0 and vectors["accepted"],
    }


def vector_report(points: list[dict]) -> dict:
    process_ids = [point.get("payload", {}).get("process_id") for point in points]
    point_ids = [point.get("id") for point in points]
    revisions = {point.get("payload", {}).get("model_revision") for point in points}
    bad_dimension = 0
    nonfinite = 0
    for point in points:
        vector = point.get("vector") or []
        if len(vector) != 1024:
            bad_dimension += 1
        elif any(not math.isfinite(float(value)) for value in vector):
            nonfinite += 1
    return {
        "count": len(points),
        "distinct_process_ids": len(set(process_ids)),
        "distinct_point_ids": len(set(point_ids)),
        "bad_dimension": bad_dimension,
        "nonfinite": nonfinite,
        "revisions": sorted(str(item) for item in revisions),
        "fingerprint": fingerprint(points),
        "accepted": (
            len(points) == 105
            and len(set(process_ids)) == 105
            and len(set(point_ids)) == 105
            and bad_dimension == 0
            and nonfinite == 0
            and revisions == {REVISION}
        ),
    }


def schema_identity() -> dict:
    return {
        "files": [path.name for path in SCHEMA_FILES],
        "sha256": {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in SCHEMA_FILES},
        "load_order": list(LOAD_ORDER),
    }


def validation_plan() -> dict:
    return {
        "component_abs_diff": COMPONENT_LIMIT,
        "cosine_similarity_abs_diff": SCORE_LIMIT,
        "ranking": "exact cosine distance, then process_id; no HNSW",
        "demonstration_queries": list(DEMONSTRATION_QUERIES),
        "saved_queries": 61,
        "report_file": "evaluation/reports/evaluation.json",
        "report_rewrite": False,
    }


def inspect_destination(database: str, *, connect=None) -> dict:
    """Read destination identity. This function does not insert or change schema."""
    require_tls(os.environ[DESTINATION_URL])
    connection = (connect or connect_staging)()
    try:
        return destination_snapshot(connection, database)
    finally:
        connection.close()


def destination_snapshot(connection, database: str) -> dict:
    current = connection.execute("SELECT current_database()").fetchone()[0]
    version = connection.execute("SHOW server_version").fetchone()[0]
    extension = connection.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'").fetchone()
    present = {
        row[0]
        for row in connection.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        )
    }
    counts = {}
    for table in present:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table):
            raise MigrationRefused("the destination has an unexpected application table")
        counts[table] = int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    return {
        "status": "CONNECTED",
        "database_matches": current == database,
        "database": current,
        "server_version": version,
        "pgvector": None if extension is None else extension[0],
        "public_tables": sorted(present),
        "existing_rows": {table: count for table, count in counts.items() if count},
        "empty": not present,
    }


def assert_destination_ready(connection, database: str) -> dict:
    refuse_production_name(database)
    snapshot = destination_snapshot(connection, database)
    if not snapshot["database_matches"]:
        raise MigrationRefused("the connected database does not match the requested staging name")
    if snapshot["existing_rows"]:
        raise MigrationRefused("the destination already has rows; refusing to overwrite them")
    if snapshot["public_tables"]:
        raise MigrationRefused("the destination has an unexpected application table")
    return snapshot


def prepare_write(args: argparse.Namespace) -> str:
    if args.database != APPROVED_DATABASE:
        raise MigrationRefused("the staging database name is not approved")
    refuse_production_name(args.database)
    destination = os.environ.get(DESTINATION_URL, "").strip()
    if not destination:
        raise MigrationRefused("STAGING_DATABASE_URL is required for a write")
    return validate_target_url(destination, args.database)


def confirmed_identity() -> dict[str, str]:
    """Owner-confirmed Console ids. They are not stored in the repository."""
    project = os.environ.get(PROJECT_ID_ENV, "").strip()
    branch = os.environ.get(BRANCH_ID_ENV, "").strip()
    endpoint = os.environ.get(ENDPOINT_ID_ENV, "").strip()
    if not project and not branch and not endpoint:
        raise MigrationRefused("approved Neon target metadata is not confirmed")
    if not project:
        raise MigrationRefused("the approved Neon project id is not confirmed")
    if not branch:
        raise MigrationRefused("the approved Neon branch id is not confirmed")
    if not endpoint:
        raise MigrationRefused("the approved Neon endpoint id is not confirmed")
    return {"project": project, "branch": branch, "endpoint": endpoint}


def assert_source_integrity(source: dict, schema: dict) -> None:
    if file_sha256(_sqlite_path()) != APPROVED_SQLITE_SHA256:
        raise MigrationRefused("the canonical SQLite checksum does not match")
    for name, digest in APPROVED_SCHEMA_SHA256.items():
        if schema["sha256"].get(name) != digest:
            raise MigrationRefused("a schema file hash does not match the approved value")
    if source["vectors"]["fingerprint"] != FINGERPRINT or not source["fingerprint_matches"]:
        raise MigrationRefused("the source vector fingerprint does not match")
    vectors = source["vectors"]
    if (
        not source["ready"]
        or source["orphan_total"] != 0
        or source["count_mismatches"]
        or vectors["count"] != 105
        or vectors["distinct_process_ids"] != 105
        or vectors["distinct_point_ids"] != 105
        or vectors["bad_dimension"] != 0
        or vectors["nonfinite"] != 0
        or vectors["revisions"] != [REVISION]
    ):
        raise MigrationRefused("the source vectors or relational audit failed validation")


def authorize_write(connection, database: str, confirmed: dict[str, str], host: str) -> dict:
    snapshot = assert_destination_ready(connection, database)
    if not bool(getattr(getattr(connection, "pgconn", None), "ssl_in_use", False)):
        raise MigrationRefused("the client session is not using TLS")
    user = connection.execute("SELECT current_user").fetchone()[0]
    if user == APP_ROLE:
        raise MigrationRefused("the SELECT-only application role cannot migrate")
    if user not in MIGRATION_ROLES:
        raise MigrationRefused("the current role is not migration-authorized")
    version = connection.execute("SHOW server_version").fetchone()[0]
    if str(version).split(".", 1)[0] != APPROVED_PG_MAJOR:
        raise MigrationRefused("the PostgreSQL major version is not approved")
    observed = {
        "project": connection.execute("SELECT current_setting(%s)", ("neon.project_id",)).fetchone()[0],
        "branch": connection.execute("SELECT current_setting(%s)", ("neon.branch_id",)).fetchone()[0],
        "endpoint": connection.execute("SELECT current_setting(%s)", ("neon.endpoint_id",)).fetchone()[0],
    }
    host_endpoint = host.split(".", 1)[0]
    if observed["endpoint"] != confirmed["endpoint"] or host_endpoint != confirmed["endpoint"]:
        raise MigrationRefused("the Neon endpoint does not match the approved endpoint")
    if observed["project"] != confirmed["project"] or observed["branch"] != confirmed["branch"]:
        raise MigrationRefused("the Neon project or branch id does not match the approved value")
    snapshot["current_user"] = user
    snapshot["project_id_matches"] = True
    snapshot["branch_id_matches"] = True
    snapshot["endpoint_id_matches"] = True
    return snapshot


def validate_target_url(url: str, database: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host in BLOCKED_HOSTS or not host or _docker_hostname(host):
        raise MigrationRefused("the staging host is not a direct Neon endpoint")
    if "-pooler" in host:
        raise MigrationRefused("a pooled Neon endpoint is not a migration target")
    if not (host.startswith("ep-") and host.endswith(".aws.neon.tech") and host.count(".") >= 3):
        raise MigrationRefused("the staging host is not a direct Neon endpoint")
    if database != APPROVED_DATABASE or (parsed.path or "").lstrip("/") != APPROVED_DATABASE:
        raise MigrationRefused("the staging database name is not approved")
    query = {key.lower(): values[-1].lower() if values else "" for key, values in parse_qs(parsed.query).items()}
    if not set(query) <= ALLOWED_QUERY_KEYS:
        raise MigrationRefused("the staging URL contains an unapproved parameter")
    if query.get("sslmode", "") not in ALLOWED_SSLMODES:
        raise MigrationRefused("a remote staging connection requires TLS")
    if query.get("channel_binding", "") != "require":
        raise MigrationRefused("the staging connection does not require channel binding")
    return host


def _docker_hostname(host: str) -> bool:
    return host == "postgres" or host.endswith(".docker.internal") or "." not in host


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_destination(connection, points: list[dict], source: dict) -> dict:
    """Apply schema and data in the transaction already required to be uncommitted."""
    if getattr(connection, "autocommit", False):
        raise MigrationRefused("the migration connection must not use autocommit")
    connection.rollback()
    try:
        for path in SCHEMA_FILES:
            _apply_sql(connection, path.read_text(encoding="utf-8"))
        _copy_tables(connection)
        _copy_vectors(connection, points)
        _validate_uncommitted(connection, source)
    except MigrationRefused:
        connection.rollback()
        raise
    except Exception as exc:
        connection.rollback()
        raise MigrationRefused(_failure_text(exc)) from exc
    try:
        connection.commit()
    except Exception as exc:
        _rollback_after_uncertain_commit(connection, exc)
    try:
        _post_commit_verify(connection, source)
    except PostCommitValidationFailed:
        raise
    except Exception as exc:
        raise PostCommitValidationFailed(_failure_text(exc)) from exc
    return {
        "schema": [path.name for path in SCHEMA_FILES],
        "tables": list(LOAD_ORDER),
        "vectors": len(points),
        "commits": 1,
    }


def refuse_production_name(database: str) -> None:
    lowered = database.lower()
    if lowered in {"postgres", "template0", "template1"} or "production" in lowered or lowered.endswith("_prod"):
        raise MigrationRefused("refusing a production or system database name")


def require_tls(url: str) -> None:
    validate_target_url(url, APPROVED_DATABASE)


def connect_staging():
    url = os.environ.get(DESTINATION_URL, "").strip()
    if not url:
        raise MigrationRefused("STAGING_DATABASE_URL is required")
    import psycopg

    try:
        connection = psycopg.connect(url, connect_timeout=10)
        connection.autocommit = False
        return connection
    except Exception as exc:
        raise MigrationRefused("the staging database is unavailable") from exc


def redact(text: str) -> str:
    hidden = text
    for name in (DESTINATION_URL, "DATABASE_URL", "PGPASSWORD"):
        secret = os.environ.get(name, "").strip()
        if secret:
            hidden = hidden.replace(secret, "[redacted]")
    return hidden


def scroll_qdrant(url: str) -> list[dict]:
    offset = None
    points = []
    while True:
        body = {"limit": 64, "with_payload": True, "with_vector": True}
        if offset is not None:
            body["offset"] = offset
        request = urllib.request.Request(
            f"{url.rstrip('/')}/collections/{COLLECTION}/points/scroll",
            data=json.dumps(body).encode(),
            headers={"content-type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            page = json.load(response)["result"]
        points.extend(page.get("points") or [])
        offset = page.get("next_page_offset")
        if not offset:
            break
    return points


def fingerprint(points: list[dict]) -> str:
    digest = hashlib.sha256()
    ordered = sorted(points, key=lambda point: str(point.get("payload", {}).get("process_id")))
    for point in ordered:
        vector = point.get("vector") or []
        if len(vector) != 1024:
            continue
        digest.update(str(point.get("payload", {}).get("process_id")).encode())
        digest.update(struct.pack("<1024d", *[float(value) for value in vector]))
    return digest.hexdigest()


def _sqlite_path() -> Path:
    raw = os.environ.get("SQLITE_PATH", "").strip()
    return Path(raw) if raw else Path(r"D:\Final Project\Hee_M3\output\S1-G14_M3.sqlite")


def _qdrant_url() -> str:
    return os.environ.get("QDRANT_URL", "http://127.0.0.1:6333").rstrip("/")


def _apply_sql(connection, text: str) -> None:
    statements = []
    for line in text.splitlines():
        if "--" in line:
            line = line[: line.index("--")]
        statements.append(line)
    for statement in (part.strip() for part in "\n".join(statements).split(";")):
        command = statement.upper()
        if statement and not command.startswith("DROP") and not command.startswith("TRUNCATE"):
            connection.execute(statement)


def _copy_tables(connection) -> None:
    source = connect_readonly(_sqlite_path())
    try:
        for table in LOAD_ORDER:
            columns = [row[1] for row in source.execute(f"PRAGMA table_info({table})")]
            rows = list(source.execute(f"SELECT {', '.join(columns)} FROM {table}"))
            marks = ", ".join(["%s"] * len(columns))
            _insert_rows(connection, table, columns, rows, marks)
    finally:
        source.close()


def _insert_rows(connection, table: str, columns: list[str], rows: list, marks: str) -> None:
    statement = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({marks})"
    cursor_factory = getattr(connection, "cursor", None)
    if cursor_factory is None:
        for row in rows:
            connection.execute(statement, tuple(row))
        return
    with connection.cursor() as cursor:
        cursor.executemany(statement, [tuple(row) for row in rows])


def _copy_vectors(connection, points: list[dict]) -> None:
    for point in points:
        payload = point["payload"]
        vector = point["vector"]
        if len(vector) != 1024 or any(not math.isfinite(float(value)) for value in vector):
            raise MigrationRefused("a source vector failed validation")
        connection.execute(
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
                "[" + ",".join(repr(float(value)) for value in vector) + "]",
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


def _validate_uncommitted(connection, source: dict) -> None:
    mismatches = {}
    for table, expected in EXPECTED_COUNTS.items():
        found = _count(connection, f"SELECT COUNT(*) FROM {table}")
        if found != expected:
            mismatches[table] = found
    if mismatches or sum(EXPECTED_COUNTS.values()) != 3573:
        raise MigrationRefused("a relational row count does not match the source")
    if _count(connection, "SELECT COUNT(*) FROM process_embeddings") != 105:
        raise MigrationRefused("the embedding count does not match the source")
    if _count(
        connection,
        "SELECT COUNT(*) FROM process_embeddings WHERE embedding IS NULL OR vector_dims(embedding) <> 1024",
    ):
        raise MigrationRefused("an embedding dimension does not match the source")
    if _count(
        connection,
        """
        SELECT COUNT(*) FROM process AS parent
        LEFT JOIN process_embeddings AS child ON child.process_id = parent.process_id
        WHERE child.process_id IS NULL
        """,
    ):
        raise MigrationRefused("a process has no embedding")
    if _count(
        connection,
        """
        SELECT COUNT(*) FROM process_embeddings AS child
        LEFT JOIN process AS parent ON parent.process_id = child.process_id
        WHERE parent.process_id IS NULL
        """,
    ):
        raise MigrationRefused("an embedding has no process")
    if _count(connection, "SELECT COUNT(*) - COUNT(DISTINCT process_id) FROM process_embeddings"):
        raise MigrationRefused("an embedding process id is duplicated")
    if any(_count(connection, sql) for sql in ORPHAN_CHECKS.values()):
        raise MigrationRefused("a foreign-key relationship failed validation")
    for label, contype, expected in (("primary", "p", 12), ("foreign", "f", 16), ("unique", "u", 6), ("check", "c", 12)):
        found = _count(
            connection,
            """
            SELECT COUNT(*) FROM pg_constraint AS constraint_row
            JOIN pg_namespace AS namespace_row ON namespace_row.oid = constraint_row.connamespace
            WHERE namespace_row.nspname = 'public' AND constraint_row.contype = %s
            """,
            (contype,),
        )
        if found != expected:
            raise MigrationRefused(f"the {label} constraint count does not match the approved schema")
    tables = {
        row[0]
        for row in connection.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
    }
    expected_tables = set(EXPECTED_COUNTS) | {"process_embeddings"}
    if tables != expected_tables:
        raise MigrationRefused("the destination has an unexpected application table")
    for process_id, expected in FRACTIONAL_QUANTITIES:
        found = connection.execute(
            "SELECT quantity FROM exchange WHERE process_id = %s AND direction = 'Output'",
            (process_id,),
        ).fetchone()
        if found is None or float(found[0]) != expected:
            raise MigrationRefused("a fractional quantity changed during the copy")
    null_regions = _count(
        connection,
        "SELECT COUNT(*) FROM process WHERE spatial_level = 'country' AND region_code IS NULL",
    )
    if null_regions != source["country_null_regions"]:
        raise MigrationRefused("country rows with a null region changed during the copy")


def _post_commit_verify(connection, source: dict) -> None:
    connection.rollback()
    try:
        connection.execute("SET TRANSACTION READ ONLY")
        _validate_uncommitted(connection, source)
    except PostCommitValidationFailed:
        raise
    except Exception as exc:
        raise PostCommitValidationFailed(str(exc)) from exc
    finally:
        connection.rollback()


def _count(connection, sql: str, params: tuple = ()) -> int:
    return int(connection.execute(sql, params).fetchone()[0])


def _rollback_after_uncertain_commit(connection, exc: BaseException) -> None:
    uncertain = bool(getattr(exc, "commit_uncertain", False)) or type(exc).__name__ in {
        "OperationalError",
        "InterfaceError",
    }
    if uncertain:
        raise CommitOutcomeUnknown("commit acknowledgement was not received") from exc
    try:
        connection.rollback()
    except Exception as rollback_error:
        raise CommitOutcomeUnknown("commit acknowledgement was not received") from rollback_error
    raise MigrationRefused(_failure_text(exc)) from exc


def _failure_text(exc: BaseException) -> str:
    sqlstate = getattr(exc, "sqlstate", None)
    text = str(exc)
    if "://" in text or "@" in text or "password" in text.lower():
        text = type(exc).__name__
    if sqlstate:
        return f"migration rolled back sqlstate={sqlstate} {text}"
    return f"migration rolled back {text}"


def main(argv: list[str] | None = None) -> int:
    try:
        report = run(argv)
    except CommitOutcomeUnknown as exc:
        print(json.dumps({"mode": "COMMIT OUTCOME UNKNOWN — OWNER REVIEW REQUIRED", "writes": None, "reason": redact(str(exc))}, ensure_ascii=False))
        return 5
    except PostCommitValidationFailed as exc:
        print(json.dumps({"mode": "COMMITTED — POST-COMMIT VALIDATION FAILED", "writes": 1, "reason": redact(str(exc))}, ensure_ascii=False))
        return 4
    except MigrationRefused as exc:
        print(json.dumps({"mode": "refused", "writes": 0, "reason": redact(str(exc))}, ensure_ascii=False))
        return 3
    except Exception as exc:
        print(json.dumps({"mode": "error", "writes": 0, "reason": redact(str(exc))}, ensure_ascii=False))
        return 1
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["source"]["ready"] and report["source"]["fingerprint_matches"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
