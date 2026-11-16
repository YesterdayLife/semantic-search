"""Atomic migration failure injection. These tests never open Neon."""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest
from tests.legacy_catalog import CATALOG, legacy_migration

from app.migration_audit import EXPECTED_COUNTS, FRACTIONAL_QUANTITIES, audit_sqlite
from scripts.neon_staging_migrate import (
    APPROVAL,
    APPROVED_SCHEMA_SHA256,
    BRANCH_ID_ENV,
    DESTINATION_URL,
    ENDPOINT_ID_ENV,
    PROJECT_ID_ENV,
    REVISION,
    CommitOutcomeUnknown,
    MigrationRefused,
    PostCommitValidationFailed,
    _apply_sql,
    _copy_tables,
    _copy_vectors,
    _insert_rows,
    _sqlite_path,
    _validate_uncommitted,
    load_destination,
    main,
    run,
)
from tests.test_neon_staging_migrate import Rows
from tests.test_neon_write_gates import _arm, _skip_source

ROOT = Path(__file__).resolve().parents[1]
WRITE = ["--write", "--database", "s1g14_staging"]
NULL_REGIONS = audit_sqlite(CATALOG)["country_null_regions"]
EXPECTED_TABLES = set(EXPECTED_COUNTS) | {"process_embeddings"}


def _points():
    return [
        {
            "id": f"00000000-0000-0000-0000-{index:012d}",
            "vector": [0.0] * 1024,
            "payload": {
                "process_id": f"P-{index}",
                "model_revision": REVISION,
                "embedding_model": "BAAI/bge-m3",
                "embedding_provider": "onnx",
                "vector_dimension": 1024,
                "text_hash": "abc",
                "document_schema_version": "1",
                "crop_id": "RIC",
                "year_ce": 2020,
                "season": "all",
                "spatial_level": "country",
                "region_code": None,
                "source_id": "SRC-01",
            },
        }
        for index in range(105)
    ]


class AtomicCloud:
    def __init__(self, **flags):
        self.fail_sql = flags.get("fail_sql")
        self.sqlstate = flags.get("sqlstate", "23503")
        self.bad_dims = flags.get("bad_dims", False)
        self.bad_counts = flags.get("bad_counts", False)
        self.bad_quantity = flags.get("bad_quantity", False)
        self.fk_fail = flags.get("fk_fail", False)
        self.post_commit_bad = flags.get("post_commit_bad", False)
        self.commit_error = flags.get("commit_error")
        self.preset_tables = flags.get("preset_tables")
        self.settings = {
            "neon.project_id": flags.get("project", "project-confirmed"),
            "neon.branch_id": "branch-confirmed",
            "neon.endpoint_id": "ep-example",
        }
        self.pgconn = type("PgConn", (), {"ssl_in_use": True})()
        self.autocommit = False
        self.statements = []
        self.commit_calls = 0
        self.committed = 0
        self.rollback_calls = 0

    def execute(self, sql, params=()):
        self.statements.append(sql)
        if self.fail_sql and self.fail_sql in sql and self.committed == 0:
            error = RuntimeError("injected")
            error.sqlstate = self.sqlstate
            raise error
        if "current_database" in sql:
            return Rows([("s1g14_staging",)])
        if sql.strip() == "SELECT current_user":
            return Rows([("neondb_owner",)])
        if "current_setting" in sql:
            return Rows([(self.settings[params[0]],)])
        if "server_version" in sql:
            return Rows([("18.7",)])
        if "extversion" in sql:
            return Rows([("0.8.7",)])
        if "SET TRANSACTION READ ONLY" in sql:
            return Rows([()])
        if "tablename" in sql:
            return Rows([(name,) for name in self._tables()])
        if "pg_constraint" in sql:
            return Rows([({"p": 12, "f": 16, "u": 6, "c": 12}[params[0]],)])
        if "quantity FROM exchange" in sql:
            if self.bad_quantity:
                return Rows([(1.0,)])
            return Rows([(dict(FRACTIONAL_QUANTITIES)[params[0]],)])
        if "spatial_level = 'country'" in sql:
            return Rows([(NULL_REGIONS,)])
        if "vector_dims" in sql:
            return Rows([(1 if self.bad_dims else 0,)])
        if "LEFT JOIN" in sql:
            failed = self.fk_fail and "crop_indicator AS child" in sql
            return Rows([(1 if failed else 0,)])
        if "COUNT(DISTINCT" in sql:
            return Rows([(0,)])
        match = re.search(r"COUNT\(\*\) FROM ([A-Za-z_][A-Za-z0-9_]*)", sql)
        if match and "JOIN" not in sql:
            table = match.group(1)
            if self.bad_counts and table == "crop":
                return Rows([(0,)])
            if self.post_commit_bad and self.committed and table == "crop":
                return Rows([(0,)])
            if table == "process_embeddings":
                return Rows([(105,)])
            return Rows([(EXPECTED_COUNTS.get(table, 0),)])
        return Rows([()])

    def _tables(self):
        created = any("CREATE TABLE" in item for item in self.statements[:-1])
        if not created:
            return list(self.preset_tables or [])
        return sorted(EXPECTED_TABLES)

    def commit(self):
        self.commit_calls += 1
        if self.commit_error is not None:
            raise self.commit_error
        self.committed += 1

    def rollback(self):
        self.rollback_calls += 1

    def close(self):
        return None


def _run(monkeypatch, cloud):
    _arm(monkeypatch)
    _skip_source(monkeypatch)
    holder = {}

    def connect():
        holder["cloud"] = cloud
        return cloud

    with pytest.raises(MigrationRefused) as caught:
        run(WRITE, scroll=lambda _url: _points(), connect=connect)
    return caught.value, holder["cloud"]


def test_t01_schema_creation_failure_rolls_back(monkeypatch):
    error, cloud = _run(monkeypatch, AtomicCloud(fail_sql="CREATE TABLE", sqlstate="42601"))
    assert cloud.commit_calls == 0
    assert cloud.rollback_calls >= 1
    assert "sqlstate=42601" in str(error)


def test_t02_extension_creation_failure_rolls_back(monkeypatch):
    error, cloud = _run(monkeypatch, AtomicCloud(fail_sql="CREATE EXTENSION", sqlstate="58P01"))
    assert cloud.commit_calls == 0
    assert any("CREATE TABLE" in item for item in cloud.statements)
    assert "sqlstate=58P01" in str(error)


def test_t03_relational_import_failure_rolls_back(monkeypatch):
    _error, cloud = _run(monkeypatch, AtomicCloud(fail_sql="INSERT INTO crop", sqlstate="23502"))
    assert cloud.commit_calls == 0
    assert cloud.rollback_calls >= 1


def test_t04_foreign_key_validation_failure_rolls_back(monkeypatch):
    error, cloud = _run(monkeypatch, AtomicCloud(fk_fail=True))
    assert cloud.commit_calls == 0
    assert "foreign-key" in str(error)


def test_t05_embedding_insertion_failure_rolls_back(monkeypatch):
    _error, cloud = _run(monkeypatch, AtomicCloud(fail_sql="INSERT INTO process_embeddings", sqlstate="22P02"))
    assert cloud.commit_calls == 0
    assert "sqlstate=22P02" in str(_error)


def test_t06_incorrect_vector_dimensions_roll_back(monkeypatch):
    error, cloud = _run(monkeypatch, AtomicCloud(bad_dims=True))
    assert cloud.commit_calls == 0
    assert "dimension" in str(error)


def test_t07_row_count_mismatch_rolls_back(monkeypatch):
    error, cloud = _run(monkeypatch, AtomicCloud(bad_counts=True))
    assert cloud.commit_calls == 0
    assert "row count" in str(error)


def test_t08_fractional_quantity_mismatch_rolls_back(monkeypatch):
    error, cloud = _run(monkeypatch, AtomicCloud(bad_quantity=True))
    assert cloud.commit_calls == 0
    assert "fractional" in str(error)


def test_t09_source_fingerprint_mismatch_does_not_connect(monkeypatch):
    _arm(monkeypatch)

    def connect():
        raise AssertionError("the destination was contacted")

    with pytest.raises(MigrationRefused, match="fingerprint"):
        run(WRITE, scroll=lambda _url: _points(), connect=connect)


def test_t10_schema_hash_mismatch_does_not_connect(monkeypatch):
    _arm(monkeypatch)
    monkeypatch.setitem(APPROVED_SCHEMA_SHA256, "001_schema.sql", "0" * 64)

    def connect():
        raise AssertionError("the destination was contacted")

    with pytest.raises(MigrationRefused, match="schema file hash"):
        run(WRITE, scroll=lambda _url: _points(), connect=connect)


def test_t11_identity_mismatch_does_not_commit(monkeypatch):
    error, cloud = _run(monkeypatch, AtomicCloud(project="other-project"))
    assert cloud.commit_calls == 0
    assert "project or branch" in str(error)


def test_t12_unexpected_public_table_does_not_commit(monkeypatch):
    error, cloud = _run(monkeypatch, AtomicCloud(preset_tables=["playing_with_neon"]))
    assert cloud.commit_calls == 0
    assert "unexpected application table" in str(error)


def test_t13_commit_succeeds_exactly_once(monkeypatch):
    _arm(monkeypatch)
    _skip_source(monkeypatch)
    cloud = AtomicCloud()
    report = run(WRITE, scroll=lambda _url: _points(), connect=lambda: cloud)
    assert report["commits"] == 1
    assert cloud.commit_calls == 1
    assert cloud.committed == 1


def test_t14_helpers_do_not_commit():
    for function in (_apply_sql, _copy_tables, _copy_vectors, _insert_rows, _validate_uncommitted):
        source = inspect.getsource(function)
        assert ".commit(" not in source
        assert "transaction(" not in source
    assert inspect.getsource(load_destination).count(".commit(") == 1


def test_t15_post_commit_validation_failure_is_not_a_rollback(monkeypatch, capsys):
    _arm(monkeypatch)
    _skip_source(monkeypatch)
    clouds = []

    def connect():
        cloud = AtomicCloud(post_commit_bad=True)
        clouds.append(cloud)
        return cloud

    with pytest.raises(PostCommitValidationFailed):
        run(WRITE, scroll=lambda _url: _points(), connect=connect)
    assert clouds[0].committed == 1
    assert clouds[0].commit_calls == 1
    monkeypatch.setattr("scripts.neon_staging_migrate.connect_staging", connect)
    monkeypatch.setattr("scripts.neon_staging_migrate.scroll_qdrant", lambda _url: _points())
    monkeypatch.setattr("scripts.neon_staging_migrate.assert_source_integrity", lambda _source, _schema: None)
    assert main(WRITE) == 4
    assert "COMMITTED — POST-COMMIT VALIDATION FAILED" in capsys.readouterr().out
    assert clouds[1].commit_calls == 1


def test_t16_uncertain_commit_is_not_retried(monkeypatch, capsys):
    _arm(monkeypatch)
    _skip_source(monkeypatch)
    error = RuntimeError("connection closed")
    error.commit_uncertain = True
    calls = {"connect": 0}

    def connect():
        calls["connect"] += 1
        return AtomicCloud(commit_error=error)

    with pytest.raises(CommitOutcomeUnknown):
        run(WRITE, scroll=lambda _url: _points(), connect=connect)
    assert calls["connect"] == 1
    monkeypatch.setattr("scripts.neon_staging_migrate.connect_staging", connect)
    monkeypatch.setattr("scripts.neon_staging_migrate.scroll_qdrant", lambda _url: _points())
    monkeypatch.setattr("scripts.neon_staging_migrate.assert_source_integrity", lambda _source, _schema: None)
    assert main(WRITE) == 5
    assert "COMMIT OUTCOME UNKNOWN — OWNER REVIEW REQUIRED" in capsys.readouterr().out
    assert calls["connect"] == 2


def test_t17_a_failed_migration_is_not_retried(monkeypatch):
    calls = {"connect": 0}

    def connect():
        calls["connect"] += 1
        return AtomicCloud(fail_sql="CREATE TABLE", sqlstate="42601")

    _arm(monkeypatch)
    _skip_source(monkeypatch)
    with pytest.raises(MigrationRefused):
        run(WRITE, scroll=lambda _url: _points(), connect=connect)
    assert calls["connect"] == 1
    assert "retry" not in inspect.getsource(run)


def test_t18_failure_does_not_drop_or_truncate(monkeypatch):
    _error, cloud = _run(monkeypatch, AtomicCloud(fail_sql="CREATE TABLE", sqlstate="42601"))
    assert not any("TRUNCATE" in item.upper() or item.upper().startswith("DROP") for item in cloud.statements)
    source = (ROOT / "scripts" / "neon_staging_migrate.py").read_text(encoding="utf-8")
    assert "TRUNCATE TABLE" not in source
    assert "DROP SCHEMA" not in source
    assert "DROP DATABASE" not in source


def test_t19_failure_text_does_not_leak_the_url(monkeypatch):
    cloud = AtomicCloud(fail_sql="CREATE TABLE", sqlstate="XX000")

    def execute(sql, params=()):
        cloud.statements.append(sql)
        if "CREATE TABLE" in sql:
            error = RuntimeError("postgresql://staging-user:example-secret@ep-example.aws.neon.tech/s1g14_staging")
            error.sqlstate = "XX000"
            raise error
        return AtomicCloud.execute(cloud, sql, params)

    cloud.execute = execute
    error, _cloud = _run(monkeypatch, cloud)
    assert "example-secret" not in str(error)
    assert "postgresql://" not in str(error)
    assert "sqlstate=XX000" in str(error)


def test_t20_default_dry_run_stays_disconnected(monkeypatch):
    monkeypatch.delenv(DESTINATION_URL, raising=False)
    monkeypatch.delenv(APPROVAL, raising=False)

    def connect():
        raise AssertionError("the destination was contacted")

    report = run([], scroll=lambda _url: _points(), connect=connect)
    assert report["mode"] == "dry-run"
    assert report["writes"] == 0
    assert report["destination"]["status"] == "NOT CONNECTED"
