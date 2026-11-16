"""Guards for the local PostgreSQL 18 harness. They do not open a database."""

from __future__ import annotations

import inspect

import pytest

from scripts.pg18_atomic_verify import SUCCESS_DB, assert_local_process


def test_local_harness_refuses_a_neon_host(monkeypatch):
    _arm(monkeypatch)
    monkeypatch.setenv("PGHOST", "ep-example.ap-southeast-1.aws.neon.tech")
    with pytest.raises(RuntimeError, match="local PostgreSQL 18"):
        assert_local_process()


def test_local_harness_refuses_the_staging_url(monkeypatch):
    _arm(monkeypatch)
    monkeypatch.setenv("STAGING_DATABASE_URL", "postgresql://staging-user:example-secret@ep-example.aws.neon.tech/s1g14_staging")
    with pytest.raises(RuntimeError, match="STAGING_DATABASE_URL"):
        assert_local_process()


def test_local_harness_refuses_cloud_write_approval(monkeypatch):
    _arm(monkeypatch)
    monkeypatch.setenv("S1G14_STAGING_WRITE_APPROVED", "1")
    with pytest.raises(RuntimeError, match="approval"):
        assert_local_process()


def test_local_harness_does_not_call_the_cloud_runner():
    source = inspect.getsource(assert_local_process)
    module = inspect.getsource(__import__("scripts.pg18_atomic_verify", fromlist=["main"]))
    assert "connect_staging" not in module
    assert "--write" not in module
    assert SUCCESS_DB != "s1g14_staging"
    assert "STAGING_DATABASE_URL" in source


def _arm(monkeypatch):
    monkeypatch.setenv("S1G14_PG18_LOCAL_TEST", "1")
    monkeypatch.setenv("PGHOST", "s1g14-pg18-atomic")
    monkeypatch.delenv("STAGING_DATABASE_URL", raising=False)
    monkeypatch.delenv("S1G14_STAGING_WRITE_APPROVED", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
