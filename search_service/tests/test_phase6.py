"""Phase 6 comparison API and metric checks. These tests do not load ONNX weights."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.adapters import BGEM3SearchAdapter, DictionarySearchAdapter
from app.database import connect_readonly
from app.evaluate_search import CATEGORIES, load_dataset
from app.main import create_app
from app.metrics import answer_ids, empty_result_correct, hit_at_k, ndcg_at_k, precision_at_k, recall_at_k, reciprocal_rank, score_query
from app.search import SearchFailure
from tests.test_compare import _DictionaryModule
from tests.test_search import _service

CANONICAL = Path(r"D:\Final Project\Hee_M3\output\S1-G14_M3.sqlite")
SQLITE_SHA256 = "700df10769c76624572c9761e8636daf82a6bd4c63b1d7ee0f3383f766834807"
DATASET = Path(__file__).resolve().parents[1] / "evaluation" / "queries.json"


def test_compare_endpoint_returns_separate_backend_sections():
    body = _compare({"query": "maize", "top_k": 5, "mode": "compare"})
    assert body["query"] == "maize"
    assert body["mode"] == "compare"
    assert body["dictionary"]["backend"] == "dictionary-sqlite"
    assert body["semantic"]["backend"] == "local-bge-m3"
    assert body["normalized_results"]["dictionary"][0]["process_id"] == "P-1"
    assert body["normalized_results"]["semantic"][0]["process_id"] == "P-MAI"
    assert body["score_comparison"] is None
    assert "\\" not in _text(body)


def test_dictionary_mode_does_not_call_semantic_ranking():
    service, _store, embedder = _service()
    module = _DictionaryModule()
    before = embedder.calls
    with _client(service, module) as client:
        response = client.post("/compare", json={"query": "maize", "mode": "dictionary"})
    assert response.status_code == 200
    body = response.json()
    assert body["semantic"] is None
    assert body["dictionary"]["ok"] is True
    assert embedder.calls == before
    assert module.calls == [("maize", 5)]


def test_semantic_mode_does_not_call_dictionary():
    module = _DictionaryModule()
    body = _compare({"query": "maize", "mode": "semantic"}, module)
    assert module.calls == []
    assert body["dictionary"] is None
    assert body["availability_status"]["semantic"] == "supported"
    assert body["semantic"]["results"][0]["answers_requested_measure"] is True


def test_compare_mode_preserves_each_ranking():
    module = _TwoRowDictionary()
    body = _compare({"query": "maize", "mode": "compare"}, module)
    assert [row["process_id"] for row in body["dictionary"]["results"]] == ["P-A", "P-B"]
    assert body["dictionary"]["results"][0]["similarity_score"] is None
    assert body["semantic"]["results"][0]["match_reason"] is None
    assert body["dictionary"]["results"][0]["similarity_score"] != body["semantic"]["results"][0]["similarity_score"]


def test_semantic_fallback_mode_is_marked():
    module = _DictionaryModule()
    service, _store, _embedder = _service(error=SearchFailure(503, "qdrant_unavailable", "Qdrant is unavailable"))
    with _client(service, module) as client:
        response = client.post("/compare", json={"query": "maize", "mode": "semantic-fallback"})
    body = response.json()
    assert response.status_code == 200
    assert body["degraded"] is True
    assert body["fallback_applied"] is True
    assert body["errors"]["semantic"]["code"] == "qdrant_unavailable"
    assert body["dictionary"]["ok"] is True
    assert module.calls


def test_compare_rejects_invalid_requests():
    service, _store, _embedder = _service()
    module = _DictionaryModule()
    with _client(service, module) as client:
        empty = client.post("/compare", json={"query": " ", "mode": "compare"})
        mode = client.post("/compare", json={"query": "maize", "mode": "hybrid"})
        top_k = client.post("/compare", json={"query": "maize", "top_k": 0})
        unknown = client.post("/compare", json={"query": "maize", "filters": {"colour": "green"}})
    assert empty.status_code == 422
    assert mode.status_code == 422
    assert top_k.status_code == 422
    assert unknown.status_code == 422
    assert module.calls == []


def test_original_search_contract_stays_in_place():
    service, _store, _embedder = _service()
    with _client(service, _DictionaryModule()) as client:
        search = client.post("/search", json={"query": "maize", "top_k": 5})
        health = client.get("/health")
        listed = client.get("/search", params={"query": "production", "top_k": 5})
    assert health.json() == {"status": "ok"}
    assert search.status_code == 200
    assert listed.status_code == 200
    for key in ("query", "parsed_filters", "count", "results", "warnings", "search_engine", "embedding_model"):
        assert key in search.json()
    assert "fallback_applied" not in search.json()
    assert "filter_comparability" not in listed.json()


def test_separate_filters_are_marked_not_comparable():
    body = _compare({"query": "maize", "mode": "compare", "filters": {"crop_id": "CAS"}})
    assert body["filter_comparability"]["directly_comparable"] is False
    assert any("not directly comparable" in warning for warning in body["warnings"])
    assert any("were not applied" in warning for warning in body["dictionary"]["warnings"])


def test_partial_and_unsupported_measures_stay_distinct():
    supported = _compare({"query": "maize", "mode": "semantic"})
    partial = _compare({"query": "fertilizer use for maize", "mode": "semantic"})
    unsupported = _compare({"query": "fertilizer", "mode": "semantic"})
    assert supported["availability_status"]["semantic"] == "supported"
    assert partial["availability_status"]["semantic"] == "partially_supported"
    assert partial["semantic"]["results"][0]["answers_requested_measure"] is False
    assert unsupported["availability_status"]["semantic"] == "unsupported"
    assert unsupported["semantic"]["results"] == []
    assert unsupported["semantic"]["context_results"][0]["answers_requested_measure"] is False


def test_context_rows_are_excluded_from_relevance():
    section = {
        "results": [{"process_id": "P-ANSWER", "answers_requested_measure": False}],
        "context_results": [{"process_id": "P-CONTEXT", "answers_requested_measure": False}],
    }
    assert answer_ids(section) == []
    scored = score_query([], set(), 5)
    assert scored["empty_result_correct"] == 1.0
    assert scored["precision_at_k"] is None


def test_precision_recall_hit_and_rank_metrics():
    relevant = {"a", "b"}
    retrieved = ["c", "a", "b"]
    assert precision_at_k(retrieved, relevant, 2) == 0.5
    assert recall_at_k(retrieved, relevant, 3) == 1.0
    assert hit_at_k(retrieved, relevant, 2) == 1.0
    assert reciprocal_rank(retrieved, relevant, 3) == 0.5
    assert ndcg_at_k(["a"], {"a"}, 1) == 1.0
    graded = ndcg_at_k(["b", "a"], {"a", "b"}, 2, {"a": 2.0, "b": 1.0})
    assert 0 < graded < 1


def test_empty_ground_truth_does_not_divide_by_zero():
    with pytest.raises(ValueError):
        precision_at_k([], set(), 5)
    correct = score_query([], set(), 5)
    incorrect = score_query(["P-1"], set(), 5)
    assert correct["empty_result_correct"] == 1.0
    assert incorrect["empty_result_correct"] == 0.0
    assert empty_result_correct([]) == 1.0


def test_dataset_has_the_required_categories_and_sqlite_labels():
    cases = load_dataset(DATASET)
    assert len(cases) >= 30
    assert set(CATEGORIES) <= {case["category"] for case in cases}
    labels = {case["query_id"]: case for case in cases}
    connection = connect_readonly(CANONICAL)
    try:
        north = connection.execute(
            "SELECT process_id FROM process WHERE crop_id='CAS' AND region_code='NOR' AND year_ce=2023"
        ).fetchall()
        south = connection.execute(
            "SELECT COUNT(*) FROM process WHERE crop_id='CAS' AND region_code='SOU' AND year_ce=2023"
        ).fetchone()[0]
        mode = connection.execute("PRAGMA query_only").fetchone()[0]
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("UPDATE process SET year_ce = 2023 WHERE process_id = ?", (north[0]["process_id"],))
    finally:
        connection.close()
    assert mode == 1
    assert len(north) == 1
    assert south == 0
    assert labels["Q15"]["expected_filters"]["year_ce"] == 2023
    assert labels["Q15"]["expected_filters"]["region_code"] == "NOR"
    assert labels["Q29"]["evaluate_relevance"] is True
    assert hashlib.sha256(CANONICAL.read_bytes()).hexdigest() == SQLITE_SHA256


def test_dictionary_evaluation_matches_sqlite_labels(tmp_path):
    from app.evaluate_search import evaluate

    cases = load_dataset(DATASET)
    report = evaluate(cases, DictionarySearchAdapter(), None, 5, {"dictionary"})
    aggregate = report["backends"]["dictionary"]["aggregate"]
    failures = [
        (row["query_id"], row["expected_filters"], row["actual_filters"], row["actual_availability"])
        for row in report["backends"]["dictionary"]["queries"]
        if row["availability_correct"] is False or row["filter_correct"] is False
    ]
    assert failures == []
    assert aggregate["availability_accuracy"] == 1.0
    assert aggregate["filter_correctness"] == 1.0
    missing = next(row for row in report["backends"]["dictionary"]["queries"] if row["query_id"] == "Q29")
    assert missing["empty_ground_truth"] is True
    assert missing["empty_result_correct"] == 1.0
    assert missing["retrieved_answer_ids"] == []
    north = next(row for row in report["backends"]["dictionary"]["queries"] if row["query_id"] == "Q15")
    assert north["hit_at_k"] == 1.0
    assert north["retrieved_answer_ids"] == ["P-REG-SRC-06-CAS-NOR-2023"]


def test_backend_error_and_timing_stay_on_the_compare_response():
    service, _store, _embedder = _service(error=SearchFailure(503, "qdrant_unavailable", "Qdrant is unavailable"))
    module = _DictionaryModule()
    with _client(service, module) as client:
        response = client.post("/compare", json={"query": "maize", "mode": "compare"})
    body = response.json()
    assert response.status_code == 200
    assert body["dictionary"]["ok"] is True
    assert body["semantic"]["ok"] is False
    assert body["errors"]["semantic"]["code"] == "qdrant_unavailable"
    assert {"dictionary", "semantic", "total"} <= set(body["timing_ms"])
    assert isinstance(body["timing_ms"]["total"], float)


def _compare(payload: dict, module=None) -> dict:
    service, _store, _embedder = _service()
    with _client(service, module or _DictionaryModule()) as client:
        response = client.post("/compare", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def _client(service, module):
    return TestClient(create_app(service, DictionarySearchAdapter(module), BGEM3SearchAdapter(service)))


def _text(body: dict) -> str:
    import json

    return json.dumps(body, ensure_ascii=False)


class _TwoRowDictionary:
    def __init__(self):
        self.calls = []

    def search(self, query, db_path, limit=50):
        self.calls.append((query, limit))
        return {
            "query": query,
            "intent": {"crop_id": "MAI", "region_code": None, "spatial_level": None, "season": None, "year_from": None, "year_to": None, "unsupported_input": False},
            "count": 2,
            "results": [
                {"process_id": "P-A", "crop_name": "ข้าวโพด", "spatial_level": "region", "area": "กลาง", "year_ce": 2021, "season": "all", "output_quantity": 1, "output_unit": "t", "source_id": "SRC-05", "source_file": "maize.csv"},
                {"process_id": "P-B", "crop_name": "ข้าวโพด", "spatial_level": "region", "area": "กลาง", "year_ce": 2022, "season": "all", "output_quantity": 2, "output_unit": "t", "source_id": "SRC-05", "source_file": "maize.csv"},
            ],
            "message": None,
        }
