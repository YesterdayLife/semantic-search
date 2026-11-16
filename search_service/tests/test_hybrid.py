"""Eligibility-first hybrid checks that do not load ONNX weights."""

from __future__ import annotations

import hashlib
import sqlite3
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.database import connect_readonly
from app.eligibility import eligible_process_ids
from app.hybrid_planner import HybridIntent, NumericCondition, plan_query
from app.hybrid_search import HybridSearch, _reason, format_threshold, main
from app.main import create_app
from app.metrics import precision_at_k
from app.schemas import FilterSet, HybridSearchRequest
from app.search import SearchFailure
from app.qdrant_store import ScoredPoint
from tests.test_compare import _DictionaryModule
from tests.test_search import _hit, _record, _service

CANONICAL = Path(r"D:\Final Project\Hee_M3\output\S1-G14_M3.sqlite")
SQLITE_SHA256 = "700df10769c76624572c9761e8636daf82a6bd4c63b1d7ee0f3383f766834807"


def test_planner_recognizes_aliases_years_places_and_multiple_crops():
    assert plan_query("มันสำปะหลัง").crops == ("CAS",)
    assert plan_query("ข้าวโพด").crops == ("MAI",)
    assert plan_query("tapioca").crops == ("CAS",)
    assert plan_query("maize").crops == ("MAI",)
    north = plan_query("มันสำปะหลังภาคเหนือปี 2566")
    assert north.crops == ("CAS",)
    assert north.year_from == 2023 and north.year_to == 2023
    assert north.region_code == "NOR" and north.spatial_level == "region"
    assert plan_query("ข้าวนาปรัง").season == "dry"
    assert plan_query("wet season rice 2021").season == "wet"
    assert plan_query("มันสำปะหลังทั่วประเทศ").spatial_level == "country"
    assert plan_query("มันสำปะหลังและข้าวโพด").crops == ("CAS", "MAI")
    assert plan_query("cassava and maize").grouped is True
    ambiguous = plan_query("cassava 2019 and 2021")
    assert ambiguous.year_ambiguous is True
    assert ambiguous.year_from is None


def test_explicit_crop_overrides_the_query_and_conflict_is_rejected():
    overridden = plan_query(
        "maize",
        explicit={"crop_id": "CAS", "year_ce": None, "region_code": None, "season": None, "spatial_level": None, "source_id": None},
    )
    assert overridden.crops == ("CAS",)
    assert any("overrides" in warning for warning in overridden.warnings)
    service, _store, _embedder = _service()
    request = HybridSearchRequest(query="cassava", filters=FilterSet(region_code="NOR", spatial_level="country"))
    with pytest.raises(SearchFailure) as caught:
        HybridSearch(service).search(request)
    assert caught.value.status_code == 422
    assert caught.value.code == "invalid_filter"


def test_numeric_and_unit_rules_use_sqlite_values():
    greater = plan_query("cassava production greater than 10000000 tonnes")
    lesser = plan_query("cassava production less than 2000000 tonnes")
    rejected = plan_query("cassava production above 1000 kg")
    ambiguous = plan_query("cassava yield above 3500 kg/rai")
    assert greater.applied_numeric[0].operator == "gt"
    assert lesser.applied_numeric[0].operator == "lt"
    assert rejected.applied_numeric == ()
    assert ambiguous.applied_numeric == ()
    connection = connect_readonly(CANONICAL)
    try:
        assert len(_ids(connection, greater)) == 18
        assert len(_ids(connection, lesser)) == 6
        before = hashlib.sha256(CANONICAL.read_bytes()).hexdigest()
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("UPDATE process SET year_ce = year_ce")
    finally:
        connection.close()
    assert before == SQLITE_SHA256


def test_unavailable_measure_returns_no_answer_and_skips_embedding(monkeypatch):
    service, _store, embedder = _service()
    before = embedder.calls
    unsupported = HybridSearch(service).search_text("fertilizer")
    assert unsupported["availability_status"] == "unsupported"
    assert unsupported["results"] == []
    assert unsupported["embedding_skipped"] is True
    assert embedder.calls == before
    partial = _ranked(monkeypatch, service, "fertilizer use for maize", ["P-MAI"], {"P-MAI": "MAI"})
    assert partial["availability_status"] == "partially_supported"
    assert partial["results"][0]["answers_requested_measure"] is False
    assert partial["results"][0]["production_quantity"] == 431024.0


def test_ranking_uses_only_eligible_ids_and_covers_each_crop(monkeypatch):
    service, store, _embedder = _records_for(("P-CAS", "CAS", 0.2), ("P-MAI", "MAI", 0.9), ("P-NOT", "RIC", 0.99))
    store.search_points = _filter_search(store)
    _patch_eligibility(monkeypatch, ["P-CAS", "P-MAI"], {"P-CAS": "CAS", "P-MAI": "MAI"})
    covered = HybridSearch(service).search_text("มันสำปะหลังและข้าวโพด", top_k=2)
    limited = HybridSearch(service).search_text("มันสำปะหลังและข้าวโพด", top_k=1)
    assert store.calls[0][0] == 2
    assert set(store.calls[0][1]["must"][0]["match"]["any"]) == {"P-CAS", "P-MAI"}
    assert [row["process_id"] for row in covered["results"]] == ["P-MAI", "P-CAS"]
    assert {row["crop"]["crop_id"] for row in covered["results"]} == {"CAS", "MAI"}
    assert "P-NOT" not in {row["process_id"] for row in covered["results"]}
    assert limited["omitted_groups"] == ["MAI"]
    assert limited["results"][0]["crop"]["crop_id"] == "CAS"
    assert covered["ranking_method"] == "eligibility-first-bge-m3"
    assert covered["score_comparison"] is None


def test_empty_eligibility_does_not_embed_or_invent_rows(monkeypatch):
    service, _store, embedder = _service()
    before = embedder.calls
    monkeypatch.setattr("app.hybrid_search.eligible_process_ids", lambda *args, **kwargs: [])
    monkeypatch.setattr("app.hybrid_search.process_crops", lambda *args, **kwargs: {})
    result = HybridSearch(service).search_text("sugarcane northeast 2024")
    assert result["count"] == 0
    assert result["embedding_skipped"] is True
    assert embedder.calls == before


def test_hybrid_api_validation_and_existing_routes_stay_separate():
    service, _store, _embedder = _service()
    from app.adapters import BGEM3SearchAdapter, DictionarySearchAdapter

    with TestClient(create_app(service, DictionarySearchAdapter(_DictionaryModule()), BGEM3SearchAdapter(service))) as client:
        rejected = client.post("/hybrid-search", json={"query": "maize", "unknown": 1})
        search = client.post("/search", json={"query": "maize", "top_k": 5})
        compared = client.post("/compare", json={"query": "maize", "mode": "compare"})
    assert rejected.status_code == 422
    assert search.status_code == 200
    assert "ranking_method" not in search.json()
    assert "parsed_filters" in search.json()
    assert compared.status_code == 200
    assert compared.json()["score_comparison"] is None
    assert compared.json()["mode"] == "compare"


def test_cli_prints_hybrid_mode(monkeypatch, capsys):
    service, _store, _embedder = _service()
    monkeypatch.setattr("app.hybrid_search.build_service", lambda: service)
    monkeypatch.setattr("app.hybrid_search.eligible_process_ids", lambda *args, **kwargs: ["P-MAI"])
    monkeypatch.setattr("app.hybrid_search.process_crops", lambda *args, **kwargs: {"P-MAI": "MAI"})
    assert main(["--query", "maize", "--top-k", "5"]) == 0
    output = capsys.readouterr().out
    assert "\"search_mode\": \"hybrid\"" in output
    assert "P-MAI" in output


def test_precision_definition_is_unchanged():
    assert precision_at_k(["a"], {"a", "b"}, 5) == 1.0


def test_hybrid_qdrant_timing_excludes_collection_validation(monkeypatch):
    service, store, _embedder = _service()
    calls = {"status": 0}
    original = store.collection_status

    def slow_status(name):
        calls["status"] += 1
        time.sleep(0.05)
        return original(name)

    store.collection_status = slow_status
    _patch_eligibility(monkeypatch, ["P-MAI"], {"P-MAI": "MAI"})
    first = HybridSearch(service).search_text("ข้าวโพด", top_k=5)
    second = HybridSearch(service).search_text("ข้าวโพด", top_k=5)
    assert first["timing_ms"]["collection_validation"] >= 40
    assert first["timing_ms"]["qdrant"] < 30
    assert {"parse", "eligibility", "embed", "collection_validation", "qdrant", "sqlite", "total"} <= set(first["timing_ms"])
    assert first["results"][0]["process_id"] == "P-MAI"
    assert first["results"][0]["similarity_score"] == 0.8
    assert calls["status"] == 1
    assert second["timing_ms"]["collection_validation"] == 0.0
    assert second["results"][0]["similarity_score"] == first["results"][0]["similarity_score"]
    assert second["results"][0]["production_quantity"] == first["results"][0]["production_quantity"]
    service.ensure_compatible_collection(force=True)
    assert calls["status"] == 2


def test_eligibility_explanation_prints_the_full_threshold():
    condition = NumericCondition("production", "gt", 10_000_000.0, "t", True)
    intent = HybridIntent(crops=("CAS",), numeric=(condition,))
    reason = _reason(intent)
    assert reason == "eligible:crop_id=CAS,productiongt10000000t"
    assert "e+" not in reason.lower()
    assert format_threshold(1.5) == "1.5"
    assert condition.threshold == 10_000_000.0


def _ids(connection, plan):
    return eligible_process_ids(
        connection,
        plan.crops,
        plan.year_from,
        plan.year_to,
        plan.region_code,
        plan.season,
        plan.spatial_level,
        plan.source_id,
        plan.applied_numeric,
    )


def _records_for(*items):
    records = {}
    hits = []
    for process_id, crop_id, score in items:
        records[process_id] = _record(process_id, crop_id, crop_id, 2023, "NOR", "เหนือ", 10.0)
        hits.append(_hit(process_id, score))
    return _service(hits=hits, records=records)


def _filter_search(store):
    def search_points(_name, _vector, limit, query_filter):
        store.calls.append((limit, query_filter))
        allowed = set(query_filter["must"][0]["match"]["any"]) if query_filter else None
        hits = [hit for hit in store.hits if allowed is None or hit.process_id in allowed]
        return hits[:limit]

    store.calls = []
    return search_points


def _patch_eligibility(monkeypatch, ids, crops):
    monkeypatch.setattr("app.hybrid_search.eligible_process_ids", lambda *args, **kwargs: list(ids))
    monkeypatch.setattr("app.hybrid_search.process_crops", lambda *args, **kwargs: dict(crops))


def _ranked(monkeypatch, service, query, ids, crops):
    _patch_eligibility(monkeypatch, ids, crops)
    return HybridSearch(service).search_text(query)
