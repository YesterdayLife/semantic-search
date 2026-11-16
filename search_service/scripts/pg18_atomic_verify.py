"""Local PostgreSQL 18 atomic migration check.

This process never reads the Neon URL and never calls the cloud write command.
It calls the same load_destination transaction used by the staging runner.
"""

from __future__ import annotations

import json
import os
import re
import urllib.request
from pathlib import Path

from scripts.neon_staging_migrate import (
    APPROVED_SCHEMA_SHA256,
    APPROVED_SQLITE_SHA256,
    COLLECTION,
    FINGERPRINT,
    FRACTIONAL_QUANTITIES,
    MigrationRefused,
    _sqlite_path,
    file_sha256,
    load_destination,
    schema_identity,
    scroll_qdrant,
    source_report,
)

LOCAL_HOSTS = frozenset({"s1g14-pg18-atomic", "127.0.0.1", "localhost"})
SUCCESS_DB = "s1g14_pg18_success"
ROLLBACK_IDS = ("B01", "B02", "B03", "B04", "B05", "B06", "B07", "B08", "B09", "B10")
COMPONENT_LIMIT = 1e-6
SCORE_LIMIT = 1e-5


class InjectedFailure(RuntimeError):
    """A controlled pre-commit failure sent through the real transaction."""


def assert_local_process() -> None:
    """Refuse cloud credentials and any host other than the disposable container."""
    if os.environ.get("STAGING_DATABASE_URL", "").strip():
        raise RuntimeError("STAGING_DATABASE_URL is present; the local test will not run")
    if os.environ.get("S1G14_STAGING_WRITE_APPROVED", "").strip() not in {"", "0"}:
        raise RuntimeError("the cloud write approval flag is present; the local test will not run")
    if os.environ.get("DATABASE_URL", "").strip():
        raise RuntimeError("DATABASE_URL is present; the local test will not run")
    if os.environ.get("S1G14_PG18_LOCAL_TEST") != "1":
        raise RuntimeError("the local PostgreSQL 18 test marker is not set")
    host = os.environ.get("PGHOST", "").strip().lower()
    if host not in LOCAL_HOSTS or "neon" in host or host.endswith(".tech"):
        raise RuntimeError("the integration host is not the local PostgreSQL 18 container")


def main() -> int:
    assert_local_process()
    source_path = _sqlite_path()
    identity = {
        "sqlite_matches": file_sha256(source_path) == APPROVED_SQLITE_SHA256,
        "schema_matches": schema_identity()["sha256"] == APPROVED_SCHEMA_SHA256,
    }
    if not identity["sqlite_matches"] or not identity["schema_matches"]:
        raise SystemExit("source or schema identity does not match the approved values")
    points = scroll_qdrant(os.environ.get("QDRANT_URL", "http://127.0.0.1:6333"))
    source = source_report(source_path, points)
    if source["vectors"]["fingerprint"] != FINGERPRINT or not source["fingerprint_matches"]:
        raise SystemExit("the source vector fingerprint does not match")
    import psycopg

    admin = _connect(psycopg, "postgres")
    admin.autocommit = True
    try:
        version = admin.execute("SHOW server_version").fetchone()[0]
        extension = admin.execute(
            "SELECT default_version FROM pg_available_extensions WHERE name = 'vector'"
        ).fetchone()
        if not str(version).startswith("18.") or extension is None or extension[0] != "0.8.7":
            raise SystemExit("the server is not PostgreSQL 18 with pgvector 0.8.7")
        databases = [SUCCESS_DB, *[f"s1g14_pg18_{item.lower()}" for item in ROLLBACK_IDS]]
        for name in databases:
            _create_database(admin, name)
        success = _success(psycopg, admin, points, source)
        rollbacks = [_rollback(psycopg, admin, points, source, item) for item in ROLLBACK_IDS]
        equivalence = _equivalence(psycopg, points) if success["passed"] else {"status": "NOT RUN"}
        report = {
            "postgresql": version,
            "pgvector_available": extension[0],
            "identity": identity,
            "fingerprint_matches": True,
            "success": success,
            "rollbacks": rollbacks,
            "equivalence": equivalence,
            "cloud_write": False,
        }
    finally:
        admin.close()
    print("PG18_RESULT " + json.dumps(report, ensure_ascii=False))
    failed = (not success["passed"]) or any(row["result"] != "PASS" for row in rollbacks)
    return 1 if failed else 0


class LocalConnection:
    """Counts commits on a real session and can abort one named stage."""

    def __init__(self, raw, fail: str | None):
        self._raw = raw
        self.fail = fail
        self.commits = 0
        self.rollbacks = 0
        self.autocommit_statements = 0
        self.injected = False
        self.extension_done = False
        self.embeddings_table = False
        self.relational_inserts = 0
        self.embedding_inserts = 0
        raw.autocommit = False

    @property
    def autocommit(self):
        return self._raw.autocommit

    @autocommit.setter
    def autocommit(self, value):
        self._raw.autocommit = bool(value)

    def execute(self, sql, params=None):
        return self._perform(sql, lambda: self._raw.execute(sql) if params is None else self._raw.execute(sql, params))

    def cursor(self, *args, **kwargs):
        return _Cursor(self._raw.cursor(*args, **kwargs), self)

    def commit(self):
        self.commits += 1
        self._raw.execute("SET log_statement = 'all'")
        return self._raw.commit()

    def rollback(self):
        self.rollbacks += 1
        return self._raw.rollback()

    def close(self):
        return self._raw.close()

    def _perform(self, sql, call):
        self._guard(sql)
        if self._raw.autocommit:
            self.autocommit_statements += 1
        result = call()
        self._observe(sql)
        return result

    def _guard(self, sql: str) -> None:
        if self.injected or not self.fail:
            return
        compact = " ".join(sql.split()).upper()
        trigger = False
        if self.fail == "B01":
            trigger = compact.startswith("CREATE EXTENSION")
        elif self.fail == "B02":
            trigger = self.extension_done
        elif self.fail == "B03":
            trigger = self.embeddings_table and compact.startswith("INSERT")
        elif self.fail == "B04":
            trigger = self.relational_inserts >= 1 and compact.startswith("INSERT") and "PROCESS_EMBEDDINGS" not in compact
        elif self.fail == "B05":
            trigger = self.relational_inserts >= 11 and compact.startswith("INSERT INTO PROCESS_EMBEDDINGS")
        elif self.fail == "B06":
            trigger = self.embedding_inserts >= 1 and compact.startswith("INSERT INTO PROCESS_EMBEDDINGS")
        elif self.fail == "B07":
            trigger = self.embedding_inserts >= 105 and compact.startswith("SELECT")
        elif self.fail == "B08":
            trigger = re.search(r"COUNT\(\*\) FROM CROP\b", compact) is not None and "JOIN" not in compact
        elif self.fail == "B09":
            trigger = "QUANTITY FROM EXCHANGE" in compact
        elif self.fail == "B10":
            trigger = "VECTOR_DIMS" in compact
        if trigger:
            self.injected = True
            raise InjectedFailure(self.fail)

    def _observe(self, sql: str) -> None:
        compact = " ".join(sql.split()).upper()
        if compact.startswith("CREATE EXTENSION"):
            self.extension_done = True
        elif compact.startswith("CREATE TABLE") and "PROCESS_EMBEDDINGS" in compact:
            self.embeddings_table = True
        elif compact.startswith("INSERT INTO PROCESS_EMBEDDINGS"):
            self.embedding_inserts += 1
        elif compact.startswith("INSERT INTO"):
            self.relational_inserts += 1


class _Cursor:
    def __init__(self, cursor, owner: LocalConnection):
        self._cursor = cursor
        self._owner = owner

    def __enter__(self):
        self._cursor.__enter__()
        return self

    def __exit__(self, exc_type, exc, traceback):
        return self._cursor.__exit__(exc_type, exc, traceback)

    def execute(self, sql, params=None):
        return self._owner._perform(sql, lambda: self._cursor.execute(sql) if params is None else self._cursor.execute(sql, params))

    def executemany(self, sql, params):
        return self._owner._perform(sql, lambda: self._cursor.executemany(sql, params))

    def __getattr__(self, name):
        return getattr(self._cursor, name)


def _success(psycopg, admin, points, source) -> dict:
    raw = _connect(psycopg, SUCCESS_DB)
    proxy = LocalConnection(raw, None)
    before = _stat(admin, SUCCESS_DB)
    try:
        load_destination(proxy, points, source)
    finally:
        raw.close()
    after = _stat(admin, SUCCESS_DB)
    catalog = _catalog(psycopg, SUCCESS_DB)
    content = _content(psycopg, points, source)
    passed = (
        proxy.commits == 1
        and proxy.autocommit_statements == 0
        and catalog["vector_extension"] == "0.8.7"
        and content["passed"]
    )
    return {
        "passed": passed,
        "python_commits": proxy.commits,
        "server_commit_delta": after[0] - before[0],
        "server_rollback_delta": after[1] - before[1],
        "autocommit_statements": proxy.autocommit_statements,
        "catalog": catalog,
        "content": content,
    }


def _rollback(psycopg, admin, points, source, stage: str) -> dict:
    database = f"s1g14_pg18_{stage.lower()}"
    raw = _connect(psycopg, database)
    proxy = LocalConnection(raw, stage)
    before = _stat(admin, database)
    raised = False
    try:
        load_destination(proxy, points, source)
    except MigrationRefused as exc:
        raised = isinstance(exc.__cause__, InjectedFailure)
    finally:
        raw.close()
    after = _stat(admin, database)
    catalog = _catalog(psycopg, database)
    passed = (
        raised
        and proxy.injected
        and proxy.commits == 0
        and catalog["public_relations"] == []
        and catalog["vector_extension"] is None
        and proxy.autocommit_statements == 0
    )
    return {
        "id": stage,
        "result": "PASS" if passed else "FAIL",
        "exception": raised,
        "injected": proxy.injected,
        "python_commits": proxy.commits,
        "server_commit_delta": after[0] - before[0],
        "public_relations": catalog["public_relations"],
        "vector_extension": catalog["vector_extension"],
        "attempts": 1,
    }


def _content(psycopg, points, source) -> dict:
    connection = _connect(psycopg, SUCCESS_DB)
    connection.execute("SET default_transaction_read_only = on")
    try:
        counts = {
            table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in (
                "crop",
                "region",
                "data_source",
                "source_file",
                "flow",
                "province_region_map",
                "process",
                "exchange",
                "crop_indicator",
                "regional_aggregate",
                "regional_contribution",
                "process_embeddings",
            )
        }
        constraints = {
            kind: int(
                connection.execute(
                    """
                    SELECT COUNT(*) FROM pg_constraint AS constraint_row
                    JOIN pg_namespace AS namespace_row ON namespace_row.oid = constraint_row.connamespace
                    WHERE namespace_row.nspname = 'public' AND constraint_row.contype = %s
                    """,
                    (code,),
                ).fetchone()[0]
            )
            for kind, code in (("primary", "p"), ("foreign", "f"), ("unique", "u"), ("check", "c"))
        }
        bad_vectors = int(
            connection.execute(
                "SELECT COUNT(*) FROM process_embeddings WHERE embedding IS NULL OR vector_dims(embedding) <> 1024"
            ).fetchone()[0]
        )
        orphans = int(
            connection.execute(
                """
                SELECT COUNT(*) FROM process_embeddings AS child
                LEFT JOIN process AS parent ON parent.process_id = child.process_id
                WHERE parent.process_id IS NULL
                """
            ).fetchone()[0]
        )
        duplicates = int(
            connection.execute("SELECT COUNT(*) - COUNT(DISTINCT process_id) FROM process_embeddings").fetchone()[0]
        )
        fractional = []
        for process_id, expected in FRACTIONAL_QUANTITIES:
            found = connection.execute(
                "SELECT quantity FROM exchange WHERE process_id = %s AND direction = 'Output'",
                (process_id,),
            ).fetchone()[0]
            fractional.append(float(found) == expected)
        null_regions = int(
            connection.execute(
                "SELECT COUNT(*) FROM process WHERE spatial_level = 'country' AND region_code IS NULL"
            ).fetchone()[0]
        )
        relational = _relational_diff(connection)
        vectors = _vector_diff(connection, points)
        version = connection.execute("SHOW server_version").fetchone()[0]
        installed = connection.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'").fetchone()[0]
    finally:
        connection.rollback()
        connection.close()
    passed = (
        sum(counts[table] for table in counts if table != "process_embeddings") == 3573
        and counts["process_embeddings"] == 105
        and constraints == {"primary": 12, "foreign": 16, "unique": 6, "check": 12}
        and bad_vectors == 0
        and orphans == 0
        and duplicates == 0
        and all(fractional)
        and null_regions == source["country_null_regions"]
        and relational["mismatched_tables"] == []
        and vectors["max_abs_difference"] <= COMPONENT_LIMIT
        and vectors["association_mismatches"] == 0
        and str(version).startswith("18.")
        and installed == "0.8.7"
    )
    return {
        "passed": passed,
        "counts": counts,
        "constraints": constraints,
        "bad_vectors": bad_vectors,
        "orphan_embeddings": orphans,
        "duplicate_embeddings": duplicates,
        "fractional_exact": all(fractional),
        "country_null_regions": null_regions,
        "relational": relational,
        "vectors": vectors,
        "server_version": version,
        "pgvector": installed,
    }


def _equivalence(psycopg, points) -> dict:
    samples = _sample_ids(points)
    connection = _connect(psycopg, SUCCESS_DB)
    connection.execute("SET default_transaction_read_only = on")
    store_url = os.environ.get("QDRANT_URL", "http://127.0.0.1:6333")
    comparisons = []
    try:
        by_id = {point["payload"]["process_id"]: point for point in points}
        self_matches = 0
        for point in points:
            literal = _literal(point["vector"])
            top = connection.execute(
                """
                SELECT process_id, (embedding <=> %s::vector) AS distance
                FROM process_embeddings
                ORDER BY embedding <=> %s::vector, process_id
                LIMIT 1
                """,
                (literal, literal),
            ).fetchone()
            if top[0] == point["payload"]["process_id"] and float(top[1]) <= COMPONENT_LIMIT:
                self_matches += 1
        for process_id in samples:
            point = by_id[process_id]
            literal = _literal(point["vector"])
            pg_rows = connection.execute(
                """
                SELECT process_id, (embedding <=> %s::vector) AS distance
                FROM process_embeddings
                ORDER BY embedding <=> %s::vector, process_id
                LIMIT 5
                """,
                (literal, literal),
            ).fetchall()
            qdrant_rows = _qdrant_search(store_url, point["vector"])
            pg_ids = [row[0] for row in pg_rows]
            qdrant_ids = [row["process_id"] for row in qdrant_rows]
            score_gaps = []
            for pg_row, qdrant_row in zip(pg_rows, qdrant_rows):
                if pg_row[0] != qdrant_row["process_id"]:
                    continue
                score_gaps.append(abs((1.0 - float(pg_row[1])) - qdrant_row["score"]))
            comparisons.append(
                {
                    "process_id": process_id,
                    "ids_match": pg_ids == qdrant_ids,
                    "pgvector": pg_ids,
                    "qdrant": qdrant_ids,
                    "max_score_gap": None if not score_gaps else max(score_gaps),
                }
            )
        saved = _saved_queries()
    finally:
        connection.rollback()
        connection.close()
    text_queries = _text_queries(psycopg, saved, store_url)
    return {
        "status": "COMPARED",
        "self_nearest_matches": self_matches,
        "self_nearest_total": len(points),
        "samples": comparisons,
        "sample_rank_matches": sum(1 for row in comparisons if row["ids_match"]),
        "text_queries": text_queries,
    }


def _text_queries(psycopg, queries: list[dict], store_url: str) -> dict:
    if len(queries) != 61:
        return {"status": "NOT RUN", "reason": "the saved query file does not contain 61 queries", "count": len(queries)}
    try:
        from app.embeddings import LocalBgeM3Provider

        embedder = LocalBgeM3Provider(dimension=1024, batch_size=8, device="cpu", backend="onnx")
        embedder.prepare()
        vectors = [embedder.embed_query(row["query"]) for row in queries]
    except Exception as exc:
        return {"status": "NOT RUN", "reason": type(exc).__name__}
    connection = _connect(psycopg, SUCCESS_DB)
    connection.execute("SET default_transaction_read_only = on")
    mismatches = []
    score_gaps = []
    try:
        for query, vector in zip(queries, vectors):
            literal = _literal(vector)
            pg_rows = connection.execute(
                """
                SELECT process_id, (embedding <=> %s::vector) AS distance
                FROM process_embeddings
                ORDER BY embedding <=> %s::vector, process_id
                LIMIT 5
                """,
                (literal, literal),
            ).fetchall()
            qdrant_rows = _qdrant_search(store_url, vector)
            pg_ids = [row[0] for row in pg_rows]
            qdrant_ids = [row["process_id"] for row in qdrant_rows]
            if pg_ids != qdrant_ids:
                mismatches.append({"query_id": query.get("query_id"), "pgvector": pg_ids, "qdrant": qdrant_ids})
            for pg_row, qdrant_row in zip(pg_rows, qdrant_rows):
                if pg_row[0] == qdrant_row["process_id"]:
                    score_gaps.append(abs((1.0 - float(pg_row[1])) - qdrant_row["score"]))
    finally:
        connection.rollback()
        connection.close()
    return {
        "status": "COMPARED",
        "count": 61,
        "rank_matches": 61 - len(mismatches),
        "rank_mismatches": mismatches[:10],
        "max_score_gap": None if not score_gaps else max(score_gaps),
        "score_gap_within_limit": bool(score_gaps) and max(score_gaps) <= SCORE_LIMIT,
    }


def _relational_diff(connection) -> dict:
    import sqlite3

    source = sqlite3.connect(f"file:{_sqlite_path()}?mode=ro", uri=True)
    mismatched = []
    max_numeric = 0.0
    try:
        source.execute("PRAGMA query_only=ON")
        for table in (
            "crop",
            "region",
            "data_source",
            "source_file",
            "flow",
            "province_region_map",
            "process",
            "exchange",
            "crop_indicator",
            "regional_aggregate",
            "regional_contribution",
        ):
            columns = [row[1] for row in source.execute(f"PRAGMA table_info({table})")]
            selected = ", ".join(columns)
            left = [_stable(row) for row in source.execute(f"SELECT {selected} FROM {table}")]
            right = [_stable(row) for row in connection.execute(f"SELECT {selected} FROM {table}")]
            if sorted(left) != sorted(right):
                mismatched.append(table)
            for column_index, _name in enumerate(columns):
                for source_row, found_row in zip(sorted(left), sorted(right)):
                    if isinstance(source_row[column_index], float) and isinstance(found_row[column_index], float):
                        max_numeric = max(max_numeric, abs(source_row[column_index] - found_row[column_index]))
    finally:
        source.close()
    return {"mismatched_tables": mismatched, "max_numeric_abs_difference": max_numeric}


def _vector_diff(connection, points) -> dict:
    stored = {
        row[0]: (row[1], _parse_vector(row[2]))
        for row in connection.execute("SELECT process_id, point_id::text, embedding::text FROM process_embeddings")
    }
    max_diff = 0.0
    missing = 0
    association = 0
    for point in points:
        process_id = point["payload"]["process_id"]
        found = stored.get(process_id)
        if found is None or found[0] != str(point["id"]):
            association += 1
            continue
        if len(found[1]) != len(point["vector"]):
            association += 1
            continue
        for left, right in zip(found[1], point["vector"]):
            max_diff = max(max_diff, abs(left - float(right)))
    if len(stored) != len(points):
        missing = abs(len(stored) - len(points))
    return {
        "rows": len(stored),
        "missing": missing,
        "association_mismatches": association,
        "max_abs_difference": max_diff,
    }


def _catalog(psycopg, database: str) -> dict:
    connection = _connect(psycopg, database)
    connection.execute("SET default_transaction_read_only = on")
    try:
        relations = [
            row[0]
            for row in connection.execute(
                """
                SELECT relation.relname
                FROM pg_class AS relation
                JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'public' AND relation.relkind IN ('r', 'p', 'v', 'm', 'f')
                ORDER BY relation.relname
                """
            )
        ]
        extension = connection.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'").fetchone()
    finally:
        connection.rollback()
        connection.close()
    return {"public_relations": relations, "vector_extension": None if extension is None else extension[0]}


def _create_database(admin, name: str) -> None:
    if not re.fullmatch(r"s1g14_pg18_[a-z0-9_]+", name) or name == "s1g14_staging":
        raise RuntimeError("refusing to create an unapproved local database name")
    exists = admin.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone()
    if exists is not None:
        admin.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()",
            (name,),
        )
        admin.execute(f"DROP DATABASE {name}")
    admin.execute(f"CREATE DATABASE {name}")


def _connect(psycopg, database: str):
    if database == "s1g14_staging" or "neon" in database:
        raise RuntimeError("refusing a cloud database name")
    return psycopg.connect(
        host=os.environ["PGHOST"],
        port=int(os.environ["PGPORT"]),
        user=os.environ["PGUSER"],
        password=os.environ["PGPASSWORD"],
        dbname=database,
        connect_timeout=10,
        autocommit=False,
        application_name="s1g14-pg18-migration",
    )


def _stat(admin, database: str) -> tuple[int, int]:
    row = admin.execute(
        "SELECT xact_commit, xact_rollback FROM pg_stat_database WHERE datname = %s",
        (database,),
    ).fetchone()
    if row is None:
        return (0, 0)
    return (int(row[0]), int(row[1]))


def _stable(row) -> tuple:
    values = []
    for value in row:
        if isinstance(value, memoryview):
            value = bytes(value)
        values.append(value)
    return tuple(values)


def _parse_vector(value: str) -> list[float]:
    return [float(part) for part in value.strip("[]").split(",") if part]


def _literal(vector) -> str:
    return "[" + ",".join(repr(float(value)) for value in vector) + "]"


def _sample_ids(points) -> list[str]:
    ids = [point["payload"]["process_id"] for point in points]
    required = [process_id for process_id, _expected in FRACTIONAL_QUANTITIES]
    chosen = []
    for process_id in required + [ids[0], ids[len(ids) // 2], ids[-1]]:
        if process_id not in chosen:
            chosen.append(process_id)
    return chosen


def _qdrant_search(url: str, vector) -> list[dict]:
    payload = json.dumps({"vector": [float(value) for value in vector], "limit": 5, "with_payload": True}).encode()
    request = urllib.request.Request(
        f"{url.rstrip('/')}/collections/{COLLECTION}/points/search",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        body = json.loads(response.read().decode())
    return [
        {"process_id": str((row.get("payload") or {}).get("process_id")), "score": float(row["score"])}
        for row in body["result"]
    ]


def _saved_queries() -> list[dict]:
    path = Path(__file__).resolve().parents[1] / "evaluation" / "reports" / "evaluation.json"
    saved = json.loads(path.read_text(encoding="utf-8"))
    return [
        {"query_id": row.get("query_id"), "query": row.get("query")}
        for row in saved["backends"]["dictionary"]["queries"]
    ]


if __name__ == "__main__":
    raise SystemExit(main())
