"""Live dictionary and BGE-M3 comparison checks."""

from __future__ import annotations

import hashlib
from pathlib import Path

import httpx
import pytest

from app.adapters import BGEM3SearchAdapter, DictionarySearchAdapter, dispatch, load_dictionary_module
from app.database import connect_readonly
from app.search import build_service

CANONICAL = Path(r"D:\Final Project\Hee_M3\output\S1-G14_M3.sqlite")
pytestmark = pytest.mark.integration

CASES = (
    {"query": "มันสำปะหลังภาคเหนือปี 2566", "crop_id": "CAS", "region_code": "NOR", "year": 2023, "season": None, "availability": "supported"},
    {"query": "cassava", "crop_id": "CAS", "region_code": None, "year": None, "season": None, "availability": "supported"},
    {"query": "maize production in central Thailand 2022", "crop_id": "MAI", "region_code": "CEN", "year": 2022, "season": None, "availability": "supported"},
    {"query": "มันสำปะหลังตะวันออกเฉียงเหนือ", "crop_id": "CAS", "region_code": "NEA", "year": None, "season": None, "availability": "supported"},
    {"query": "มันสำปะหลังภาคเหนือ", "crop_id": "CAS", "region_code": "NOR", "year": None, "season": None, "availability": "supported"},
    {"query": "ข้าวนาปรังปี 2565", "crop_id": "RIC", "region_code": None, "year": 2022, "season": "dry", "availability": "supported"},
    {"query": "ข้าวนาปี", "crop_id": "RIC", "region_code": None, "year": None, "season": "wet", "availability": "supported"},
    {"query": "มันสำปะหลังภาคใต้ปี 2566", "crop_id": "CAS", "region_code": "SOU", "year": 2023, "season": None, "availability": "supported"},
    {"query": "ปริมาณปุ๋ยที่ใช้ปลูกมันสำปะหลัง", "crop_id": "CAS", "region_code": None, "year": None, "season": None, "availability": "unsupported"},
    {"query": "carbon footprint of rice production", "crop_id": "RIC", "region_code": None, "year": None, "season": None, "availability": "unsupported"},
)


@pytest.fixture(scope="module")
def adapters():
    semantic = BGEM3SearchAdapter(build_service())
    dictionary = DictionarySearchAdapter()
    yield dictionary, semantic
    semantic.close()


def test_dictionary_matches_the_original_function_and_sqlite(adapters):
    dictionary, _semantic = adapters
    module = load_dictionary_module()
    before = hashlib.sha256(CANONICAL.read_bytes()).hexdigest()
    for case in CASES:
        direct = module.search(case["query"], CANONICAL, 5)
        adapted = dictionary.search(case["query"], top_k=5)
        assert adapted["original"] == direct
        assert adapted["availability_status"] == case["availability"]
        assert direct["intent"]["crop_id"] == case["crop_id"]
        assert direct["intent"]["region_code"] == case["region_code"]
        assert direct["intent"]["season"] == case["season"]
        if case["year"] is None:
            assert direct["intent"]["year_from"] is None
        else:
            assert direct["intent"]["year_from"] == case["year"]
            assert direct["intent"]["year_to"] == case["year"]
        if case["availability"] == "unsupported":
            assert direct["count"] == 0
            assert adapted["results"] == []
            continue
        expected = _expected_ids(case)
        returned = [row["process_id"] for row in direct["results"]]
        assert set(returned) <= set(expected)
        if len(expected) <= 5:
            assert set(returned) == set(expected)
        _assert_quantities(direct["results"])
        for row in adapted["results"]:
            assert row["similarity_score"] is None
            assert row["production_quantity"] == next(item["output_quantity"] for item in direct["results"] if item["process_id"] == row["process_id"])
    assert hashlib.sha256(CANONICAL.read_bytes()).hexdigest() == before


def test_semantic_and_compare_use_sqlite_quantities(adapters, monkeypatch):
    dictionary, semantic = adapters
    constructed = {"count": 0}

    def deny_openai(*_args, **_kwargs):
        constructed["count"] += 1
        raise AssertionError("OpenAI client constructed")

    monkeypatch.setattr("app.embeddings.OpenAIEmbeddingProvider.__init__", deny_openai)
    compared = dispatch("compare", "มันสำปะหลังภาคเหนือปี 2566", 5, None, dictionary, semantic)
    assert compared["score_comparison"] is None
    assert compared["dictionary"]["ok"] is True
    assert compared["semantic"]["ok"] is True
    assert compared["dictionary"]["results"][0]["similarity_score"] is None
    assert compared["semantic"]["results"][0]["match_reason"] is None
    expected = _expected_ids(CASES[0])
    assert {row["process_id"] for row in compared["dictionary"]["results"]} == set(expected)
    assert {row["process_id"] for row in compared["semantic"]["results"]} == set(expected)
    _assert_quantities_normalized(compared["dictionary"]["results"])
    _assert_quantities_normalized(compared["semantic"]["results"])
    assert constructed["count"] == 0


def test_ambiguous_query_is_not_forced_into_one_ranking(adapters):
    dictionary, semantic = adapters
    compared = dispatch("compare", "มันสำปะหลังและข้าวโพด", 5, None, dictionary, semantic)
    assert compared["dictionary"]["original"]["intent"]["crop_id"] in {"CAS", "MAI"}
    assert compared["semantic"]["original"]["parsed_filters"]["crop_id"] is None
    assert compared["score_comparison"] is None


def test_qdrant_counts_remain_unchanged(adapters):
    _dictionary, semantic = adapters
    semantic.search("มันสำปะหลัง", top_k=1)
    client = httpx.Client(base_url="http://127.0.0.1:6333", timeout=30)
    try:
        names = [item["name"] for item in client.get("/collections").json()["result"]["collections"]]
        assert "crop_process" not in names
        for name in ("crop_process_bge_m3", "crop_process_mock"):
            count = client.post(f"/collections/{name}/points/count", json={"exact": True}).json()["result"]["count"]
            assert count == (180 if name == "crop_process_bge_m3" else 105)
    finally:
        client.close()


def _expected_ids(case: dict) -> list[str]:
    clauses = ["p.crop_id = ?"]
    params: list = [case["crop_id"]]
    if case["region_code"] is not None:
        clauses.append("p.region_code = ?")
        params.append(case["region_code"])
    if case["year"] is not None:
        clauses.append("p.year_ce = ?")
        params.append(case["year"])
    if case["season"] is not None:
        clauses.append("p.season = ?")
        params.append(case["season"])
    connection = connect_readonly(CANONICAL)
    try:
        rows = connection.execute(
            f"SELECT process_id FROM process AS p WHERE {' AND '.join(clauses)} ORDER BY p.year_ce, p.area, p.source_id",
            params,
        ).fetchall()
    finally:
        connection.close()
    return [row[0] for row in rows]


def _assert_quantities(rows: list[dict]) -> None:
    if not rows:
        return
    expected = _quantities([row["process_id"] for row in rows])
    for row in rows:
        assert row["output_quantity"] == expected[row["process_id"]]["quantity"]
        assert row["output_unit"] == expected[row["process_id"]]["unit"]


def _assert_quantities_normalized(rows: list[dict]) -> None:
    if not rows:
        return
    expected = _quantities([row["process_id"] for row in rows])
    for row in rows:
        assert row["production_quantity"] == expected[row["process_id"]]["quantity"]
        assert row["production_unit"] == expected[row["process_id"]]["unit"]


def _quantities(process_ids: list[str]) -> dict:
    placeholders = ",".join("?" for _ in process_ids)
    connection = connect_readonly(CANONICAL)
    try:
        rows = connection.execute(
            f"SELECT process_id, quantity, unit FROM exchange WHERE direction = 'Output' AND process_id IN ({placeholders})",
            process_ids,
        ).fetchall()
    finally:
        connection.close()
    return {row["process_id"]: row for row in rows}
