"""DEPLOY-01B adapter tests. These use mocks or the read-only SQLite file.

They do not open Neon, install a PostgreSQL driver, or change Qdrant.
"""

from __future__ import annotations

import hashlib
import inspect
from pathlib import Path

import pytest

from app.adapters import DictionarySearchAdapter, _from_dictionary, load_dictionary_module
from app.config import BGE_COLLECTION, BGE_MODEL, load_settings
from app.database import DatabaseError, connect_readonly
from app.dictionary_postgres import PostgresDictionaryAdapter, dictionary_statement
from app.eligibility import eligible_process_ids
from app.embeddings import ONNX_MODEL_REVISION
from app.hybrid_planner import NumericCondition
from app.migration_audit import audit_embeddings, audit_sqlite
from app.pgvector_store import PgvectorStore
from app.postgres_provider import PostgresDataProvider, eligibility_query, sqlite_catalog_unchanged
from app.qdrant_store import QdrantRequestError
from app.records import fetch_records, load_catalog
from app.search import SearchService

from tests.legacy_catalog import CATALOG as CANONICAL, CATALOG_SHA256 as SQLITE_SHA256
DICTIONARY_SHA256 = "8db66ee8ee675e43822e827375a2bba299eeed252063cc2a88f4a130e8e7cc60"
SCHEMA = Path(__file__).resolve().parents[1] / "migrations" / "postgres" / "001_schema.sql"
VECTOR_SCHEMA = Path(__file__).resolve().parents[1] / "migrations" / "postgres" / "002_pgvector.sql"
NORTHERN = "P-REG-SRC-06-CAS-NOR-2023"
FRACTIONAL = (
    "P-SRC-01-RIC-all-2022",
    "P-SRC-01-RIC-all-2023",
    "P-SRC-01-RIC-all-2024",
)


def _silence_dotenv(monkeypatch) -> None:
    monkeypatch.setattr("app.config.load_dotenv", lambda *_args, **_kwargs: None)


class SqliteAsPostgres:
    """Run PostgreSQL-shaped statements on the read-only SQLite file."""

    def __init__(self, inner):
        self.inner = inner
        self.statements: list[str] = []

    def execute(self, sql, params=()):
        self.statements.append(sql)
        if sql.strip().upper().startswith("SET "):
            return _Rows(())
        return self.inner.execute(sql.replace("%s", "?"), tuple(params or ()))

    def close(self) -> None:
        self.inner.close()


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None


class RecordingConnection:
    def __init__(self, rows):
        self.calls = []
        self._rows = rows

    def execute(self, sql, params=()):
        self.calls.append((sql, list(params or ())))
        return _Rows(self._rows)

    def close(self) -> None:
        return None


def _provider() -> PostgresDataProvider:
    def connect():
        return SqliteAsPostgres(connect_readonly(CANONICAL))

    return PostgresDataProvider("postgresql://configured", connect=connect)


def test_t01_local_remains_the_default(monkeypatch):
    _silence_dotenv(monkeypatch)
    monkeypatch.delenv("DATA_BACKEND", raising=False)
    monkeypatch.delenv("VECTOR_BACKEND", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    settings = load_settings()
    assert settings.data_backend == "sqlite"
    assert settings.vector_backend == "qdrant"
    assert settings.database_url == ""
    service = SearchService(settings, object(), object())
    assert service.relational is None


def test_t02_sqlite_eligibility_is_unchanged():
    source = inspect.getsource(eligible_process_ids)
    assert "?" in source
    assert "%s" not in source
    connection = connect_readonly(CANONICAL)
    try:
        found = eligible_process_ids(
            connection,
            crop_ids=("CAS",),
            year_from=2023,
            year_to=2023,
            region_code="NOR",
            spatial_level="region",
        )
    finally:
        connection.close()
    assert found == [NORTHERN]
    connection = connect_readonly(CANONICAL)
    try:
        record = fetch_records(connection, [NORTHERN])[NORTHERN]
    finally:
        connection.close()
    assert record.production_quantity == 7707851.0
    assert record.production_unit == "t"


def test_t03_postgres_connection_uses_the_injected_factory():
    opened = []

    def connect():
        opened.append("opened")
        return RecordingConnection(())

    provider = PostgresDataProvider("postgresql://configured", connect=connect)
    connection = provider.connect()
    assert opened == ["opened"]
    assert connection.calls[0][0] == "SET default_transaction_read_only = on"
    with pytest.raises(DatabaseError, match="DATABASE_URL is required"):
        PostgresDataProvider("").connect()


def test_t03_connection_errors_do_not_reveal_the_url(monkeypatch):
    url = "postgresql://example-user:example-secret@example.invalid/crop"

    class BrokenDriver:
        @staticmethod
        def connect(dsn, connect_timeout=10):
            raise RuntimeError(f"refused {dsn}")

    monkeypatch.setitem(__import__("sys").modules, "psycopg", BrokenDriver)
    with pytest.raises(DatabaseError, match="PostgreSQL is unavailable") as caught:
        PostgresDataProvider(url).connect()
    assert "example-secret" not in str(caught.value)
    assert url not in str(caught.value)


def test_t04_eligibility_parameters_are_not_interpolated():
    injected = "CAS' OR '1'='1"
    sql, params = eligibility_query(crop_ids=(injected,), year_from=2023, placeholder="%s")
    assert injected not in sql
    assert "%s" in sql
    assert params[0] == injected
    assert params[1] == 2023


def test_t05_catalog_matches_sqlite_on_the_same_rows():
    connection = connect_readonly(CANONICAL)
    try:
        expected = load_catalog(connection)
    finally:
        connection.close()
    provider = _provider()
    postgres = provider.load_catalog(provider.connect())
    assert postgres.crop_ids == expected.crop_ids
    assert postgres.region_codes == expected.region_codes
    assert postgres.seasons == expected.seasons
    assert postgres.spatial_levels == expected.spatial_levels
    assert postgres.source_ids == expected.source_ids
    assert postgres.sources == expected.sources
    assert postgres.process_count == 105
    assert sqlite_catalog_unchanged()


def test_t06_eligibility_matches_sqlite():
    kwargs = {
        "crop_ids": ("CAS", "MAI"),
        "year_from": 2022,
        "year_to": 2024,
        "region_code": "CEN",
        "spatial_level": "region",
    }
    connection = connect_readonly(CANONICAL)
    try:
        expected = eligible_process_ids(connection, **kwargs)
    finally:
        connection.close()
    provider = _provider()
    found = provider.eligible_process_ids(provider.connect(), **kwargs)
    assert found == expected
    assert found


def test_t07_numeric_filter_matches_sqlite():
    numeric = (NumericCondition("production", "gt", 1_000_000, "t", True),)
    connection = connect_readonly(CANONICAL)
    try:
        expected = eligible_process_ids(connection, numeric=numeric)
    finally:
        connection.close()
    provider = _provider()
    found = provider.eligible_process_ids(provider.connect(), numeric=numeric)
    assert found == expected
    assert len(found) == 81


def test_t08_hydration_matches_sqlite_including_null_regions():
    ids = [NORTHERN, *FRACTIONAL, "P-SRC-01-RIC-all-2020"]
    connection = connect_readonly(CANONICAL)
    try:
        expected = fetch_records(connection, ids)
    finally:
        connection.close()
    provider = _provider()
    found = provider.fetch_records(provider.connect(), ids)
    assert found.keys() == expected.keys()
    for process_id, record in expected.items():
        assert found[process_id] == record
    assert any(record.region_code is None for record in found.values())


def test_t09_dictionary_adapter_matches_the_course_script():
    module = load_dictionary_module()
    adapter = PostgresDictionaryAdapter("postgresql://configured", provider=_provider(), module=module)
    queries = (
        "ผลผลิตมันสำปะหลังภาคเหนือปี 2566",
        "ข้าวนาปรังปี 2565",
        "ปุ๋ยมันสำปะหลัง",
        "hello",
    )
    for query in queries:
        direct = module.search(query, CANONICAL, 5)
        body = adapter.search(query, top_k=5)
        original = body["original"]
        assert body["backend"] == "dictionary-postgres"
        assert original["message"] == direct["message"]
        assert original["count"] == direct["count"]
        assert [
            (row["process_id"], row["output_quantity"]) for row in original["results"]
        ] == [
            (row["process_id"], row["output_quantity"]) for row in direct["results"]
        ]
    warned = adapter.search("มันสำปะหลัง", {"crop_id": "MAI"}, 5)
    assert any("not applied" in warning for warning in warned["warnings"])
    local = DictionarySearchAdapter(module=module, db_path=CANONICAL)
    local_body = local.search("ผลผลิตมันสำปะหลังภาคเหนือปี 2566", top_k=5)
    assert local_body["backend"] == "dictionary-sqlite"
    assert local_body["results"][0]["process_id"] == NORTHERN
    sql, params = dictionary_statement(module.parse_query("ผลผลิตมันสำปะหลังภาคเหนือปี 2566"), 5)
    assert "ORDER BY p.year_ce, p.area, p.source_id LIMIT %s" in sql
    assert params[-1] == 5
    assert "2566" not in sql


def test_t10_cosine_similarity_is_one_minus_distance():
    connection = RecordingConnection([_embedding_row(distance=0.25)])
    store = PgvectorStore(_Relational(connection))
    found = store.search_points(BGE_COLLECTION, [0.0] * 1024, 5, None)
    assert found[0].score == 0.75
    sql = connection.calls[-1][0]
    assert "<=>" in sql
    assert "1 -" not in sql or found[0].score == 1.0 - 0.25


def test_t11_eligible_ids_are_filtered_before_ranking():
    class Closed:
        def connect(self):
            raise AssertionError("empty candidates must not be ranked")

    empty = PgvectorStore(Closed())
    assert empty.search_points(
        BGE_COLLECTION,
        [0.0] * 1024,
        5,
        {"must": [{"key": "process_id", "match": {"any": []}}]},
    ) == []
    injected = "P-1'; DROP TABLE process_embeddings;--"
    connection = RecordingConnection([_embedding_row(process_id="P-1")])
    store = PgvectorStore(_Relational(connection))
    store.search_points(
        BGE_COLLECTION,
        [0.0] * 1024,
        5,
        {"must": [{"key": "process_id", "match": {"any": [injected]}}]},
    )
    sql, params = connection.calls[-1]
    assert "WHERE process_id = ANY(%s)" in sql
    assert sql.index("WHERE") < sql.index("ORDER BY")
    assert injected not in sql
    assert injected in params[1]


def test_t12_tie_break_orders_distance_then_process_id():
    connection = RecordingConnection([_embedding_row()])
    store = PgvectorStore(_Relational(connection))
    store.search_points(BGE_COLLECTION, [0.0] * 1024, 2, None)
    assert "ORDER BY embedding <=> %s::vector, process_id" in connection.calls[-1][0]


def test_t13_revision_mismatch_is_rejected():
    connection = RecordingConnection([_embedding_row(revision="other-revision")])
    store = PgvectorStore(_Relational(connection))
    with pytest.raises(QdrantRequestError, match="revision"):
        store.search_points(BGE_COLLECTION, [0.0] * 1024, 1, None)


def test_t14_dimension_mismatch_is_rejected():
    class Closed:
        def connect(self):
            raise AssertionError("a bad query vector must not reach the database")

    store = PgvectorStore(Closed())
    with pytest.raises(QdrantRequestError, match="dimension"):
        store.search_points(BGE_COLLECTION, [1.0, 2.0], 1, None)
    with pytest.raises(QdrantRequestError, match="dimension"):
        store.search_points(BGE_COLLECTION, [float("nan")] * 1024, 1, None)
    connection = RecordingConnection([_embedding_row(dimension=768)])
    stored = PgvectorStore(_Relational(connection))
    with pytest.raises(QdrantRequestError, match="dimension"):
        stored.search_points(BGE_COLLECTION, [0.0] * 1024, 1, None)


def test_t15_cloud_configuration_missing_fails_closed(monkeypatch):
    _silence_dotenv(monkeypatch)
    monkeypatch.setenv("DATA_BACKEND", "postgres")
    monkeypatch.setenv("VECTOR_BACKEND", "pgvector")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValueError, match="DATABASE_URL is required when DATA_BACKEND is postgres"):
        load_settings()
    monkeypatch.setenv("DATA_BACKEND", "sqlite")
    monkeypatch.setenv("VECTOR_BACKEND", "pgvector")
    with pytest.raises(ValueError, match="combination is not supported"):
        load_settings()
    monkeypatch.setenv("DATA_BACKEND", "postgres")
    monkeypatch.setenv("VECTOR_BACKEND", "qdrant")
    monkeypatch.setenv("DATABASE_URL", "postgresql://configured")
    with pytest.raises(ValueError, match="combination is not supported"):
        load_settings()


def test_t16_postgres_session_is_read_only():
    connection = RecordingConnection(())
    PostgresDataProvider("postgresql://configured", connect=lambda: connection).connect()
    assert connection.calls[0] == ("SET default_transaction_read_only = on", [])
    sqlite_connection = connect_readonly(CANONICAL)
    try:
        assert sqlite_connection.execute("PRAGMA query_only").fetchone()[0] == 1
    finally:
        sqlite_connection.close()


def test_t17_country_null_regions_are_preserved():
    report = audit_sqlite(CANONICAL)
    assert report["country_null_regions"] == 45
    connection = connect_readonly(CANONICAL)
    try:
        stored = connection.execute(
            "SELECT COUNT(*) FROM process WHERE spatial_level = 'country' AND region_code IS NULL"
        ).fetchone()[0]
    finally:
        connection.close()
    assert stored == 45


def test_t18_fractional_quantities_are_exact():
    report = audit_sqlite(CANONICAL)
    assert [item["exact"] for item in report["fractional_quantities"]] == [True, True, True]
    assert report["quantity_comparison"] == "exact binary equality"
    schema = SCHEMA.read_text(encoding="utf-8")
    assert "quantity double precision" in schema


def test_t19_foreign_key_audit_reports_zero_orphans():
    report = audit_sqlite(CANONICAL)
    assert report["orphan_total"] == 0
    assert report["orphans"]
    assert report["count_mismatches"] == {}
    assert report["counts"]["process"] == 105
    assert report["output_exchanges"] == 105
    assert report["duplicate_process_ids"] == 0
    schema = SCHEMA.read_text(encoding="utf-8")
    for table in report["counts"]:
        assert f"CREATE TABLE {table} " in schema
    assert "REFERENCES" in schema
    vector = VECTOR_SCHEMA.read_text(encoding="utf-8")
    assert "CREATE EXTENSION IF NOT EXISTS vector;" in vector
    assert "embedding vector(1024)" in vector
    assert "point_id uuid UNIQUE" in vector
    assert "USING hnsw" not in vector.lower()
    assert "CREATE INDEX" not in vector
    assert "Do not execute" in vector


def test_embedding_audit_uses_vector_norm_on_pgvector_0_8():
    source = inspect.getsource(audit_embeddings)
    assert "vector_norm(embedding)" in source
    assert "l2_norm(" not in source


def test_t20_reads_do_not_change_sqlite_or_the_dictionary_script():
    before = hashlib.sha256(CANONICAL.read_bytes()).hexdigest()
    dictionary = Path(r"D:\Final Project\Hee_M4\ch6 semantic search\src\semantic_search.py")
    script = hashlib.sha256(dictionary.read_bytes()).hexdigest()
    audit_sqlite(CANONICAL)
    connection = connect_readonly(CANONICAL)
    try:
        eligible_process_ids(connection, crop_ids=("CAS",))
        fetch_records(connection, [NORTHERN])
    finally:
        connection.close()
    assert hashlib.sha256(CANONICAL.read_bytes()).hexdigest() == before == SQLITE_SHA256
    assert script == DICTIONARY_SHA256
    assert _from_dictionary("q", {"intent": {"crop_id": "CAS"}, "results": [], "message": "x"}, [], 0)["backend"] == "dictionary-sqlite"


def test_embedding_metadata_constants_stay_on_the_quantized_revision():
    assert ONNX_MODEL_REVISION == "xenova-4de13258303883538bd53b696b452bf8099f0858-model_quantized.onnx"
    assert BGE_MODEL == "BAAI/bge-m3"
    row = _embedding_row()
    assert row[11] == ONNX_MODEL_REVISION
    assert row[12] == 1024


class _Relational:
    def __init__(self, connection):
        self.connection = connection

    def connect(self):
        return self.connection


def _embedding_row(distance=0.1, process_id="P-1", revision=ONNX_MODEL_REVISION, dimension=1024):
    return (
        process_id,
        "11111111-1111-5111-8111-111111111111",
        distance,
        "CAS",
        2023,
        "all",
        "region",
        "NOR",
        "SRC-06",
        BGE_MODEL,
        "local-bge-m3",
        revision,
        dimension,
        "hash",
        "1",
    )
