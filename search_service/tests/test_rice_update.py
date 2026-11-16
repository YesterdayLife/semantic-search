"""Source reconciliation, repeatable imports, and search after catalog growth."""
import sqlite3
import copy
from decimal import Decimal
import pytest

from app.config import DEFAULT_SQLITE_PATH
from app.database import connect_readonly, verify_catalog, DatabaseError
from app.documents import load_documents
from app.records import load_catalog
from app.qdrant_store import CollectionStatus
from app.search import SearchFailure
from scripts.update_rice_regions import prepare, apply_rows
from tests.test_search import _service


@pytest.fixture()
def updated(tmp_path):
    path = tmp_path / "updated.sqlite"
    with connect_readonly(DEFAULT_SQLITE_PATH) as src, sqlite3.connect(path) as dst:
        src.backup(dst)
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA foreign_keys=ON")
        prepared = prepare(db)
        apply_rows(db, prepared)
    return path, prepared


def test_full_six_region_coverage_and_exact_source_reconciliation(updated):
    path, prepared = updated
    assert len(prepared[-1]) == 36
    assert all(row["exact"] for row in prepared[-1])
    with connect_readonly(path) as db:
        assert load_catalog(db).process_count == 180
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        counts = db.execute("SELECT season,region_code,count(*) FROM process WHERE source_id='SRC-04' AND spatial_level='region' GROUP BY 1,2").fetchall()
        assert len(counts) == 12
        assert all(row[2] == 6 for row in counts)
        assert db.execute("SELECT count(*) FROM process WHERE region_code='SOU' AND crop_id IN ('CAS','MAI')").fetchone()[0] == 0
        for season, year, expected in [('wet', 2023, 274135), ('dry', 2024, 44427)]:
            quantity = db.execute("SELECT e.quantity FROM exchange e JOIN process p USING(process_id) WHERE p.region_code='SOU' AND p.season=? AND p.year_ce=?", (season, year)).fetchone()[0]
            assert quantity == expected


def test_import_is_idempotent_and_documents_cover_new_rice(updated):
    path, prepared = updated
    with sqlite3.connect(path) as db:
        before = list(db.iterdump())
        apply_rows(db, prepared)
        assert list(db.iterdump()) == before
    docs = load_documents(path)
    assert len(docs) == 180
    assert len({d.point_id for d in docs}) == 180
    southern = [d for d in docs if d.payload['region_code'] == 'SOU']
    assert len(southern) == 12
    assert all('ภาคใต้' in d.text for d in southern)


def test_growth_is_allowed_but_stale_vector_count_is_rejected(updated):
    path, _ = updated
    with connect_readonly(path) as db:
        catalog = load_catalog(db)
        verify_catalog(db)
        with pytest.raises(DatabaseError, match='expected 105'):
            verify_catalog(db, 105)
    service, _, _ = _service(status=CollectionStatus(True, 1024, 'cosine', 180))
    service._catalog_override = catalog
    assert service.ready()['points'] == 180
    stale, _, _ = _service(status=CollectionStatus(True, 1024, 'cosine', 105))
    stale._catalog_override = catalog
    with pytest.raises(SearchFailure, match='incompatible'):
        stale.ready()


def test_failed_write_rolls_back_all_partial_changes(updated):
    path, prepared = updated
    invalid = copy.deepcopy(prepared)
    # The first country row violates the positive quantity constraint, after
    # the importer has already attempted source/process writes.
    key = sorted(invalid[1])[0]
    old = invalid[1][key]['production']
    invalid[1][key]['production'] = (Decimal(-1), *old[1:])
    with sqlite3.connect(path) as db:
        before = list(db.iterdump())
        with pytest.raises(sqlite3.IntegrityError):
            with db:
                apply_rows(db, invalid)
        assert list(db.iterdump()) == before
