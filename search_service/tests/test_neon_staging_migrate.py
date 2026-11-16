"""Safety checks for the Neon staging planner. These tests do not contact Neon."""

from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path

import pytest
from tests.legacy_catalog import legacy_migration

from scripts.neon_staging_migrate import (
    APPROVAL,
    DEMONSTRATION_QUERIES,
    DESTINATION_URL,
    DICTIONARY_TIE,
    REVISION,
    MigrationRefused,
    _apply_sql,
    assert_destination_ready,
    redact,
    refuse_production_name,
    require_tls,
    run,
)

ROOT = Path(__file__).resolve().parents[1]


class Rows:
    def __init__(self, rows):
        self._rows = rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def __iter__(self):
        return iter(self._rows)


class Destination:
    def __init__(self, database="s1g14_staging", counts=None):
        self.database = database
        self.counts = counts or {}
        self.statements = []

    def execute(self, sql, params=()):
        self.statements.append(sql)
        if "current_database" in sql:
            return Rows([(self.database,)])
        if "server_version" in sql:
            return Rows([("16.16",)])
        if "extversion" in sql:
            return Rows([("0.8.7",)])
        if "tablename" in sql:
            return Rows([(name,) for name in self.counts])
        if "COUNT(*)" in sql:
            for name, count in self.counts.items():
                if f"FROM {name}" in sql:
                    return Rows([(count,)])
            return Rows([(0,)])
        return Rows([()])

    def transaction(self):
        return nullcontext()

    def commit(self):
        return None

    def close(self):
        return None


def _points(count=105):
    return [
        {
            "id": f"00000000-0000-0000-0000-{index:012d}",
            "vector": [0.0] * 1024,
            "payload": {"process_id": f"P-{index}", "model_revision": REVISION},
        }
        for index in range(count)
    ]


def test_default_run_is_a_dry_run_and_does_not_connect(monkeypatch):
    monkeypatch.delenv(DESTINATION_URL, raising=False)
    monkeypatch.delenv(APPROVAL, raising=False)
    report = run([], scroll=lambda _url: _points())
    assert report["mode"] == "dry-run"
    assert report["writes"] == 0
    assert report["destination"]["status"] == "NOT CONNECTED"
    assert report["source"]["counts"]["process"] == 105
    assert report["source"]["vectors"]["accepted"] is True
    assert report["dictionary_tie"]["process_ids"] == DICTIONARY_TIE["process_ids"]
    assert len(DEMONSTRATION_QUERIES) == 7


def test_write_without_approval_is_refused(monkeypatch):
    monkeypatch.delenv(APPROVAL, raising=False)
    with pytest.raises(MigrationRefused, match="has not been approved"):
        run(["--write", "--database", "s1g14_staging"], scroll=lambda _url: _points())


def test_populated_destination_is_refused():
    with pytest.raises(MigrationRefused, match="already has rows"):
        assert_destination_ready(Destination(counts={"process": 105}), "s1g14_staging")


def test_database_name_must_match_the_connection():
    with pytest.raises(MigrationRefused, match="does not match"):
        assert_destination_ready(Destination(database="other"), "s1g14_staging")


def test_production_names_are_refused():
    with pytest.raises(MigrationRefused):
        refuse_production_name("s1g14_production")
    with pytest.raises(MigrationRefused):
        refuse_production_name("postgres")


def test_remote_staging_requires_tls():
    with pytest.raises(MigrationRefused, match="TLS"):
        require_tls(
            "postgresql://staging-user:example-secret@ep-example.ap-southeast-1.aws.neon.tech/s1g14_staging?channel_binding=require"
        )
    with pytest.raises(MigrationRefused, match="channel binding"):
        require_tls(
            "postgresql://staging-user:example-secret@ep-example.ap-southeast-1.aws.neon.tech/s1g14_staging?sslmode=require"
        )


def test_errors_do_not_keep_the_destination_url(monkeypatch):
    monkeypatch.setenv(DESTINATION_URL, "postgresql://staging-user:example-secret@ep.example.neon.tech/db")
    assert "example-secret" not in redact("failed postgresql://staging-user:example-secret@ep.example.neon.tech/db")


def test_schema_apply_skips_drop_statements():
    connection = Destination()
    _apply_sql(connection, "DROP TABLE crop;\nCREATE TABLE crop (crop_id text);")
    assert all(not statement.upper().startswith("DROP") for statement in connection.statements)
    assert any(statement.upper().startswith("CREATE TABLE") for statement in connection.statements)


def test_role_draft_is_select_only_and_has_no_password():
    text = (ROOT / "migrations" / "postgres" / "003_roles.draft.sql").read_text(encoding="utf-8")
    assert "GRANT SELECT" in text
    assert "default_transaction_read_only = on" in text
    assert "statement_timeout = '5s'" in text
    assert "NOINHERIT" in text
    assert "<set outside this file>" in text
    assert "postgresql://" not in text


def test_linux_requirements_pin_psycopg_without_torch_or_openai():
    text = (ROOT / "requirements-linux.txt").read_text(encoding="utf-8").lower()
    assert "psycopg[binary]==3.3.9" in text
    for blocked in ("torch", "cuda", "openai", "sentence-transformers"):
        assert blocked not in "\n".join(line for line in text.splitlines() if line.strip() and not line.strip().startswith("#"))


def test_archived_source_dry_run_matches_the_approved_fingerprint(monkeypatch):
    monkeypatch.delenv(DESTINATION_URL, raising=False)
    monkeypatch.delenv(APPROVAL, raising=False)
    report = run([])
    assert report["writes"] == 0
    assert report["destination"]["status"] == "NOT CONNECTED"
    assert report["source"]["fingerprint_matches"] is True
    assert report["source"]["counts"]["process"] == 105
    assert report["source"]["vectors"]["count"] == 105
    assert report["source"]["orphan_total"] == 0
    assert report["source"]["fractional_exact"] is True
