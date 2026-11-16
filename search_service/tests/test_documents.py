"""Document identity, aliases, and the read-only SQLite catalog."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pytest

from app.config import DEFAULT_SQLITE_PATH
from app.database import connect_readonly, verify_catalog
from app.documents import (
    DOCUMENT_SCHEMA_VERSION,
    FLOW_SQL,
    INDICATOR_SQL,
    PAYLOAD_FIELDS,
    POINT_ID_NAMESPACE,
    PROCESS_SQL,
    load_documents,
    point_id_for,
    text_hash_for,
)

CANONICAL = DEFAULT_SQLITE_PATH
FORBIDDEN_LCI = (
    "fertilizer",
    "energy input",
    "energy consumption",
    "water consumption",
    "carbon footprint",
    "ปุ๋ย",
    "น้ำที่ใช้",
    "พลังงานที่ใช้",
    "คาร์บอนฟุตพริ้นท์",
)


@pytest.fixture(scope="module")
def documents():
    return load_documents(CANONICAL)


def test_sqlite_is_read_only():
    connection = connect_readonly(CANONICAL)
    try:
        assert connection.execute("PRAGMA query_only").fetchone()[0] == 1
        verify_catalog(connection, 180)
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("CREATE TABLE phase3_probe(id INTEGER)")
    finally:
        connection.close()


def test_document_count_and_unique_ids(documents):
    assert len(documents) == 180
    assert len({item.process_id for item in documents}) == 180
    assert len({item.point_id for item in documents}) == 180


def test_point_ids_are_deterministic_uuid5(documents):
    again = load_documents(CANONICAL)
    assert [item.point_id for item in documents] == [item.point_id for item in again]
    for document in documents:
        assert document.point_id == point_id_for(document.process_id)
        assert document.point_id == str(__import__("uuid").uuid5(POINT_ID_NAMESPACE, document.process_id))


def test_payload_contract_and_hash_stability(documents):
    first = documents[0].text
    assert documents[0].text_hash == text_hash_for(first)
    assert len(documents[0].text_hash) == 64
    for document in documents:
        assert document.payload["process_id"] == document.process_id
        assert document.payload["text_hash"] == document.text_hash
        assert document.payload["document_schema_version"] == DOCUMENT_SCHEMA_VERSION
        assert isinstance(document.payload["year_ce"], int)
        assert document.payload["spatial_level"] in {"country", "region"}
        assert document.payload["season"] in {"all", "dry", "wet"}
        stored = document.point_payload("mock-deterministic-v1")
        assert tuple(stored) == PAYLOAD_FIELDS


def test_rebuilding_text_is_stable(documents):
    again = load_documents(CANONICAL)
    assert [(item.process_id, item.text, item.text_hash) for item in documents] == [
        (item.process_id, item.text, item.text_hash) for item in again
    ]


def test_validated_crop_and_place_aliases(documents):
    by_crop = {}
    for document in documents:
        by_crop.setdefault(document.payload["crop_id"], document.text)
    assert "มันสำปะหลัง" in by_crop["CAS"] and "cassava" in by_crop["CAS"] and "tapioca" in by_crop["CAS"]
    assert "ข้าวโพด" in by_crop["MAI"] and "maize" in by_crop["MAI"] and "corn" in by_crop["MAI"]
    assert "ข้าว" in by_crop["RIC"] and "rice" in by_crop["RIC"]
    assert "อ้อย" in by_crop["SUG"] and "sugarcane" in by_crop["SUG"]
    regional = next(item for item in documents if item.payload["region_code"] == "NOR")
    assert "ภาคเหนือ" in regional.text and "north" in regional.text
    country = next(item for item in documents if item.payload["spatial_level"] == "country")
    assert "Thailand" in country.text and "ประเทศไทย" in country.text
    dry = next(item for item in documents if item.payload["season"] == "dry")
    assert "dry season" in dry.text and "นาปรัง" in dry.text


def test_sql_does_not_select_measures():
    for statement in (PROCESS_SQL, FLOW_SQL, INDICATOR_SQL):
        lowered = statement.lower()
        assert "quantity" not in lowered
        assert "value" not in lowered
        assert "source_file" not in lowered


def test_quantities_stay_out_of_search_text(documents):
    by_id = {item.process_id: item for item in documents}
    connection = connect_readonly(CANONICAL)
    try:
        rows = list(
            connection.execute(
                """
                SELECT process_id, quantity AS measure FROM exchange
                UNION ALL
                SELECT process_id, value AS measure FROM crop_indicator
                """
            )
        )
    finally:
        connection.close()
    for process_id, measure in rows:
        document = by_id[process_id]
        allowed = {str(document.payload["year_ce"])}
        year_label = re.search(r"Source year label: (\d+)", document.text)
        if year_label:
            allowed.add(year_label.group(1))
        for token in _measure_tokens(measure):
            if token in allowed or len(token) < 3:
                continue
            assert re.search(rf"(?<!\d){re.escape(token)}(?!\d)", document.text) is None


def test_no_unsupported_lci_language(documents):
    for document in documents:
        lowered = document.text.lower()
        for phrase in FORBIDDEN_LCI:
            assert phrase.lower() not in lowered
        assert "Input" not in document.text


def _measure_tokens(measure) -> set[str]:
    number = float(measure)
    tokens = {f"{number:.6f}".rstrip("0").rstrip(".")}
    if abs(number - round(number)) < 1e-6:
        tokens.add(str(int(round(number))))
    return {token for token in tokens if token}


def test_canonical_path_exists():
    assert Path(CANONICAL).is_file()
