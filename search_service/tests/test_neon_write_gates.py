"""Write-gate tests. They use fixtures and do not open the live Neon database."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.legacy_catalog import legacy_migration

from scripts.neon_staging_migrate import (
    APPROVAL,
    APPROVED_SCHEMA_SHA256,
    BRANCH_ID_ENV,
    DESTINATION_URL,
    ENDPOINT_ID_ENV,
    PROJECT_ID_ENV,
    MigrationRefused,
    run,
    validate_target_url,
)
from tests.test_neon_staging_migrate import Rows, _points

ROOT = Path(__file__).resolve().parents[1]
WRITE = ["--write", "--database", "s1g14_staging"]


class Cloud:
    def __init__(self, user="neondb_owner", version="18.7 (a21afb5)", endpoint="ep-example", tables=None):
        self.user = user
        self.version = version
        self.settings = {
            "neon.project_id": "project-confirmed",
            "neon.branch_id": "branch-confirmed",
            "neon.endpoint_id": endpoint,
        }
        self.tables = tables or {}
        self.pgconn = type("PgConn", (), {"ssl_in_use": True})()
        self.statements = []

    def execute(self, sql, params=()):
        self.statements.append(sql)
        if "current_database" in sql:
            return Rows([("s1g14_staging",)])
        if sql.strip() == "SELECT current_user":
            return Rows([(self.user,)])
        if "current_setting" in sql:
            return Rows([(self.settings[params[0]],)])
        if "server_version" in sql:
            return Rows([(self.version,)])
        if "extversion" in sql:
            return Rows([("0.8.7",)])
        if "tablename" in sql:
            return Rows([(name,) for name in self.tables])
        if "COUNT(*)" in sql:
            for name, count in self.tables.items():
                if f"FROM {name}" in sql:
                    return Rows([(count,)])
            return Rows([(0,)])
        return Rows([()])

    def close(self):
        return None


def _url(host="ep-example.ap-southeast-1.aws.neon.tech", database="s1g14_staging", query="sslmode=require&channel_binding=require"):
    return f"postgresql://staging-user:example-secret@{host}/{database}?{query}"


def _refuse_contact():
    raise AssertionError("the destination was contacted")


def _arm(monkeypatch, url=None):
    monkeypatch.setenv(APPROVAL, "1")
    monkeypatch.setenv(DESTINATION_URL, url or _url())
    monkeypatch.setenv(PROJECT_ID_ENV, "project-confirmed")
    monkeypatch.setenv(BRANCH_ID_ENV, "branch-confirmed")
    monkeypatch.setenv(ENDPOINT_ID_ENV, "ep-example")


def _skip_source(monkeypatch):
    monkeypatch.setattr("scripts.neon_staging_migrate.assert_source_integrity", lambda _source, _schema: None)


def test_t01_rejects_localhost(monkeypatch):
    _arm(monkeypatch, _url(host="localhost"))
    with pytest.raises(MigrationRefused, match="direct Neon endpoint"):
        run(WRITE, scroll=lambda _url: _points(), connect=_refuse_contact)


def test_t02_rejects_a_pooled_neon_host(monkeypatch):
    _arm(monkeypatch, _url(host="ep-example-pooler.ap-southeast-1.aws.neon.tech"))
    with pytest.raises(MigrationRefused, match="pooled"):
        run(WRITE, scroll=lambda _url: _points(), connect=_refuse_contact)


def test_t03_rejects_an_incorrect_database_name(monkeypatch):
    _arm(monkeypatch, _url(database="neondb"))
    with pytest.raises(MigrationRefused, match="database name"):
        run(WRITE, scroll=lambda _url: _points(), connect=_refuse_contact)


def test_t04_rejects_missing_tls(monkeypatch):
    _arm(monkeypatch, _url(query="channel_binding=require"))
    with pytest.raises(MigrationRefused, match="TLS"):
        run(WRITE, scroll=lambda _url: _points(), connect=_refuse_contact)


def test_t05_rejects_a_missing_project_id(monkeypatch):
    _arm(monkeypatch)
    monkeypatch.delenv(PROJECT_ID_ENV)
    with pytest.raises(MigrationRefused, match="project id"):
        run(WRITE, scroll=lambda _url: _points(), connect=_refuse_contact)


def test_t06_rejects_a_missing_branch_id(monkeypatch):
    _arm(monkeypatch)
    monkeypatch.delenv(BRANCH_ID_ENV)
    with pytest.raises(MigrationRefused, match="branch id"):
        run(WRITE, scroll=lambda _url: _points(), connect=_refuse_contact)


def test_t07_rejects_an_endpoint_mismatch(monkeypatch):
    _arm(monkeypatch)
    _skip_source(monkeypatch)
    with pytest.raises(MigrationRefused, match="endpoint"):
        run(WRITE, scroll=lambda _url: _points(), connect=lambda: Cloud(endpoint="ep-other"))


def test_t08_rejects_an_incorrect_schema_hash(monkeypatch):
    _arm(monkeypatch)
    monkeypatch.setitem(APPROVED_SCHEMA_SHA256, "001_schema.sql", "0" * 64)
    with pytest.raises(MigrationRefused, match="schema file hash"):
        run(WRITE, scroll=lambda _url: _points(), connect=_refuse_contact)


def test_t09_rejects_an_incorrect_source_fingerprint(monkeypatch):
    _arm(monkeypatch)
    with pytest.raises(MigrationRefused, match="fingerprint"):
        run(WRITE, scroll=lambda _url: _points(), connect=_refuse_contact)


def test_t10_rejects_an_unexpected_public_table(monkeypatch):
    _arm(monkeypatch)
    _skip_source(monkeypatch)
    with pytest.raises(MigrationRefused, match="unexpected application table"):
        run(WRITE, scroll=lambda _url: _points(), connect=lambda: Cloud(tables={"playing_with_neon": 0}))


def test_t11_rejects_the_select_only_application_role(monkeypatch):
    _arm(monkeypatch)
    _skip_source(monkeypatch)
    with pytest.raises(MigrationRefused, match="application role"):
        run(WRITE, scroll=lambda _url: _points(), connect=lambda: Cloud(user="s1g14_staging_app"))


def test_t12_rejects_an_unapproved_postgresql_major(monkeypatch):
    _arm(monkeypatch)
    _skip_source(monkeypatch)
    with pytest.raises(MigrationRefused, match="major version"):
        run(WRITE, scroll=lambda _url: _points(), connect=lambda: Cloud(version="16.16"))


def test_t13_rejects_write_without_the_approval_flag(monkeypatch):
    monkeypatch.delenv(APPROVAL, raising=False)
    with pytest.raises(MigrationRefused, match="has not been approved"):
        run(WRITE, scroll=lambda _url: _points(), connect=_refuse_contact)


def test_t14_rejects_the_approval_flag_without_write(monkeypatch):
    monkeypatch.setenv(APPROVAL, "1")
    with pytest.raises(MigrationRefused, match="without --write"):
        run([], scroll=lambda _url: _points(), connect=_refuse_contact)


def test_t15_rejects_missing_owner_approved_target_metadata(monkeypatch):
    _arm(monkeypatch)
    for name in (PROJECT_ID_ENV, BRANCH_ID_ENV, ENDPOINT_ID_ENV):
        monkeypatch.delenv(name)
    with pytest.raises(MigrationRefused, match="target metadata"):
        run(WRITE, scroll=lambda _url: _points(), connect=_refuse_contact)


def test_t16_dry_run_performs_zero_writes(monkeypatch):
    monkeypatch.delenv(APPROVAL, raising=False)
    monkeypatch.delenv(DESTINATION_URL, raising=False)
    report = run([], scroll=lambda _url: _points(), connect=_refuse_contact)
    assert report["mode"] == "dry-run"
    assert report["writes"] == 0
    assert report["destination"]["status"] == "NOT CONNECTED"


def test_t17_errors_do_not_contain_credentials():
    url = _url(host="127.0.0.1")
    with pytest.raises(MigrationRefused) as caught:
        validate_target_url(url, "s1g14_staging")
    assert "example-secret" not in str(caught.value)
    assert "postgresql://" not in str(caught.value)


def test_t18_local_backends_remain_sqlite_and_qdrant():
    config = (ROOT / "app" / "config.py").read_text(encoding="utf-8")
    assert 'os.environ.get("DATA_BACKEND", "sqlite")' in config
    assert 'os.environ.get("VECTOR_BACKEND", "qdrant")' in config
    eligibility = (ROOT / "app" / "eligibility.py").read_text(encoding="utf-8")
    assert "%s" not in eligibility
