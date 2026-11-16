"""Path portability for the catalog and the course dictionary script."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.adapters import DictionarySearchAdapter
from app.config import DEFAULT_DICTIONARY_SCRIPT, DEFAULT_SQLITE_PATH, load_settings
from app.database import DatabaseError, connect_readonly
from app.main import create_app
from app.postgres_provider import PostgresDataProvider
from app.public_data import PublicDataError, _catalog_payload, read_configured_catalog, read_public_catalog

CANONICAL = Path(r"D:\Final Project\Hee_M3\output\S1-G14_M3.sqlite")
COURSE_SCRIPT = Path(r"D:\Final Project\Hee_M4\ch6 semantic search\src\semantic_search.py")


class _Quiet:
    def start(self):
        return None

    def close(self):
        return None

    def ready(self):
        return {"status": "ready"}


class _Translate:
    def __init__(self, inner):
        self.inner = inner

    def execute(self, sql, params=()):
        if sql.strip().upper().startswith("SET "):
            return self
        return self.inner.execute(sql.replace("%s", "?"), tuple(params or ()))

    def fetchone(self):
        return None

    def close(self):
        self.inner.close()


def _silence(monkeypatch) -> None:
    monkeypatch.setattr("app.config.load_dotenv", lambda *_args, **_kwargs: None)


def test_windows_sqlite_path_keeps_catalog_order(monkeypatch):
    _silence(monkeypatch)
    monkeypatch.setenv("SQLITE_PATH", str(CANONICAL))
    monkeypatch.delenv("DATA_BACKEND", raising=False)
    monkeypatch.delenv("VECTOR_BACKEND", raising=False)
    settings = load_settings()
    assert settings.sqlite_path == CANONICAL
    payload = read_public_catalog(settings.sqlite_path)
    assert [item["crop_id"] for item in payload["crops"]] == ["CAS", "MAI", "RIC", "SUG"]
    assert payload["process_count"] == 180
    assert payload["numeric_operators"] == ["gt", "gte", "lt", "lte"]


def test_linux_sqlite_path_is_accepted_and_missing_file_fails(monkeypatch):
    _silence(monkeypatch)
    monkeypatch.setenv("SQLITE_PATH", "/data/S1-G14_M3.sqlite")
    monkeypatch.delenv("DATA_BACKEND", raising=False)
    settings = load_settings()
    assert settings.sqlite_path.as_posix() == "/data/S1-G14_M3.sqlite"
    with pytest.raises(PublicDataError) as caught:
        read_public_catalog(Path("/data/missing-s1g14.sqlite"))
    assert caught.value.code == "sqlite_unavailable"


def test_postgres_catalog_does_not_open_sqlite(monkeypatch):
    _silence(monkeypatch)
    monkeypatch.setenv("DATA_BACKEND", "postgres")
    monkeypatch.setenv("VECTOR_BACKEND", "pgvector")
    monkeypatch.setenv("DATABASE_URL", "postgresql://configured")

    def refuse_sqlite(*_args, **_kwargs):
        raise AssertionError("SQLite was opened in postgres mode")

    monkeypatch.setattr("app.public_data.connect_readonly", refuse_sqlite)

    class Broken(PostgresDataProvider):
        def connect(self):
            raise DatabaseError("PostgreSQL is unavailable")

    monkeypatch.setattr("app.postgres_provider.PostgresDataProvider", Broken)
    with pytest.raises(PublicDataError) as caught:
        read_configured_catalog()
    assert caught.value.code == "postgres_unavailable"
    assert "configured" not in str(caught.value)


def test_postgres_catalog_matches_sqlite_rows():
    expected = read_public_catalog(CANONICAL)
    connection = connect_readonly(CANONICAL)
    try:
        found = _catalog_payload(_Translate(connection))
    finally:
        connection.close()
    assert found == expected


def test_catalog_route_uses_configured_sqlite_path(monkeypatch):
    _silence(monkeypatch)
    monkeypatch.setenv("SQLITE_PATH", str(CANONICAL))
    monkeypatch.delenv("DATA_BACKEND", raising=False)
    client = TestClient(create_app(_Quiet(), _Quiet(), _Quiet()))
    response = client.get("/catalog")
    assert response.status_code == 200
    assert response.json()["process_count"] == 180
    assert [item["crop_id"] for item in response.json()["crops"]] == ["CAS", "MAI", "RIC", "SUG"]


def test_dictionary_script_path_is_configurable_and_read_only(monkeypatch):
    _silence(monkeypatch)
    monkeypatch.setenv("DICTIONARY_SCRIPT", "/opt/dictionary/semantic_search.py")
    monkeypatch.setenv("SQLITE_PATH", "/data/S1-G14_M3.sqlite")
    monkeypatch.delenv("DATA_BACKEND", raising=False)
    settings = load_settings()
    assert settings.dictionary_script.as_posix() == "/opt/dictionary/semantic_search.py"
    assert settings.sqlite_path.as_posix() == "/data/S1-G14_M3.sqlite"
    assert DEFAULT_DICTIONARY_SCRIPT == COURSE_SCRIPT
    assert DEFAULT_SQLITE_PATH == CANONICAL
    adapter = DictionarySearchAdapter(db_path=CANONICAL, script_path=COURSE_SCRIPT)
    body = adapter.search("ผลผลิตมันสำปะหลังภาคเหนือปี 2566", top_k=5)
    assert body["backend"] == "dictionary-sqlite"
    assert body["results"][0]["process_id"] == "P-REG-SRC-06-CAS-NOR-2023"
    assert body["results"][0]["production_quantity"] == 7707851.0
    assert body["results"][0]["production_unit"] == "t"
