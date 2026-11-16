"""Frozen pre-rice-update data for the historical migration contract tests.

The production migration approval hashes intentionally remain unchanged. These
tests use a SQLite backup (whose header differs) and the original 105 vectors.
"""
import gzip
import hashlib
import json
from pathlib import Path

import pytest

CATALOG = Path(__file__).parent / 'fixtures' / 'catalog_105.sqlite'
CATALOG_SHA256 = '79d2960e7521f936d4dcd8064d3fead5c45411f7ff2d2e3b1595784fddc75e64'


@pytest.fixture(autouse=True)
def legacy_migration(monkeypatch):
    assert hashlib.sha256(CATALOG.read_bytes()).hexdigest() == CATALOG_SHA256
    monkeypatch.setenv('SQLITE_PATH', str(CATALOG))
    monkeypatch.setattr('scripts.neon_staging_migrate.APPROVED_SQLITE_SHA256', CATALOG_SHA256)
    with gzip.open(CATALOG.with_name('qdrant_105.json.gz'), 'rt', encoding='utf-8') as stream:
        points = json.load(stream)
    monkeypatch.setattr('scripts.neon_staging_migrate.scroll_qdrant', lambda _url: points)
