"""Adapter and comparison checks that do not load the ONNX model."""

from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi.testclient import TestClient

from app.adapters import BGEM3SearchAdapter, DictionarySearchAdapter, dispatch
from app.main import create_app
from app.search import SearchFailure
from tests.test_search import _service

PROTECTED = {
    Path(r"D:\Final Project\Hee_M4\ch6 semantic search\src\semantic_search.py"):
        "8db66ee8ee675e43822e827375a2bba299eeed252063cc2a88f4a130e8e7cc60",
    Path(r"D:\Final Project\Hee_M4\ch6 semantic search\src\build_serving_layer.py"):
        "b770300f8835ab5c58f40d32132d4dd65530bfd2ac4692082fd3fd7caef0ca78",
    Path(r"D:\Final Project\Hee_M4\ch6 semantic search\graph\import\import.cypher"):
        "5286e190259a123aaed76fda427851a62bf126e69c71ad0a4e013070e2b3ab1d",
}


def test_dictionary_adapter_preserves_the_original_payload():
    module = _DictionaryModule()
    adapter = DictionarySearchAdapter(module)
    result = adapter.search("มันสำปะหลังภาคเหนือปี 2566", top_k=5)
    assert result["ok"] is True
    assert result["backend"] == "dictionary-sqlite"
    assert result["original"] == module.payload
    assert result["results"][0]["process_id"] == "P-1"
    assert result["results"][0]["production_quantity"] == 12.5
    assert result["results"][0]["similarity_score"] is None
    assert result["results"][0]["match_reason"].startswith("dictionary:")
    assert "source_file" not in result["results"][0]["source"]
    assert module.calls == [("มันสำปะหลังภาคเหนือปี 2566", 5)]


def test_dictionary_filters_do_not_change_the_original_call():
    module = _DictionaryModule()
    result = DictionarySearchAdapter(module).search("rice", {"crop_id": "MAI"}, top_k=3)
    assert module.calls == [("rice", 3)]
    assert any("were not applied" in warning for warning in result["warnings"])
    assert result["original"]["results"][0]["crop_name"] == "มันสำปะหลัง"


def test_semantic_adapter_reuses_the_existing_service():
    service, _store, embedder = _service()
    adapter = BGEM3SearchAdapter(service)
    result = adapter.search("maize", top_k=5)
    assert result["ok"] is True
    assert result["backend"] == "local-bge-m3"
    assert result["results"][0]["similarity_score"] == 0.8
    assert result["results"][0]["match_reason"] is None
    assert result["results"][0]["production_quantity"] == 431024.0
    assert result["original"]["search_engine"] == "local-bge-m3"
    assert embedder.calls >= 1


def test_compare_keeps_results_separate_and_does_not_merge_scores():
    compared = dispatch("compare", "production", 5, None, DictionarySearchAdapter(_DictionaryModule()), BGEM3SearchAdapter(_service()[0]))
    assert compared["score_comparison"] is None
    assert compared["dictionary"]["results"][0]["similarity_score"] is None
    assert compared["semantic"]["results"][0]["match_reason"] is None
    assert "ranked_results" not in compared
    assert compared["dictionary"]["backend"] != compared["semantic"]["backend"]


def test_semantic_failure_does_not_silently_call_dictionary():
    dictionary = _DictionaryModule()
    service, _store, _embedder = _service(error=__import__("httpx").ConnectError("refused"))
    result = dispatch("semantic", "rice", 5, None, DictionarySearchAdapter(dictionary), BGEM3SearchAdapter(service))
    assert result["ok"] is False
    assert result["semantic"]["error"]["code"] == "qdrant_unavailable"
    assert result["dictionary"] is None
    assert dictionary.calls == []


def test_explicit_fallback_is_marked_degraded():
    dictionary = _DictionaryModule()
    service, _store, _embedder = _service(error=SearchFailure(503, "qdrant_unavailable", "Qdrant is unavailable"))
    result = dispatch("semantic-fallback", "มันสำปะหลัง", 5, None, DictionarySearchAdapter(dictionary), BGEM3SearchAdapter(service))
    assert result["degraded"] is True
    assert result["fallback_applied"] is True
    assert result["active_backend"] == "dictionary-sqlite"
    assert result["semantic"]["ok"] is False
    assert result["dictionary"]["ok"] is True
    assert dictionary.calls


def test_empty_semantic_result_does_not_fallback():
    dictionary = _DictionaryModule()
    service, _store, _embedder = _service(hits=[])
    result = dispatch("semantic-fallback", "มันสำปะหลังภาคใต้ปี 2566", 5, None, DictionarySearchAdapter(dictionary), BGEM3SearchAdapter(service))
    assert result["fallback_applied"] is False
    assert result["degraded"] is False
    assert result["semantic"]["count"] == 0
    assert result["dictionary"] is None
    assert dictionary.calls == []


def test_invalid_filter_does_not_fallback():
    dictionary = _DictionaryModule()
    service, _store, _embedder = _service()
    result = dispatch("semantic-fallback", "rice", 5, {"crop_id": "WHEAT"}, DictionarySearchAdapter(dictionary), BGEM3SearchAdapter(service))
    assert result["fallback_applied"] is False
    assert result["semantic"]["error"]["code"] == "invalid_filter"
    assert dictionary.calls == []


def test_dictionary_backend_failure_is_explicit():
    result = DictionarySearchAdapter(_BrokenDictionary()).search("rice")
    assert result["ok"] is False
    assert result["error"]["code"] == "dictionary_unavailable"
    assert "\\" not in result["error"]["message"]
    assert result["results"] == []


def test_unsupported_dictionary_question_stays_unsupported():
    module = _DictionaryModule(unsupported=True)
    result = DictionarySearchAdapter(module).search("carbon footprint of rice production")
    assert result["availability_status"] == "unsupported"
    assert result["count"] == 0
    assert result["results"] == []
    assert result["original"]["count"] == 0


def test_exclusive_semantic_measure_is_context_not_an_answer():
    service, store, _embedder = _service()
    store.semantic_measures = ["carbon_footprint"]
    store.semantic_filters = {"crop_id": None, "year_ce": None, "region_code": None, "season": None, "spatial_level": None, "source_id": None}
    result = BGEM3SearchAdapter(service).search("carbon footprint")
    assert result["availability_status"] == "unsupported"
    assert result["results"] == []
    assert result["context_results"][0]["answers_requested_measure"] is False
    assert result["context_results"][0]["production_quantity"] == 431024.0


def test_existing_search_route_contract_is_unchanged():
    service, _store, _embedder = _service()
    with TestClient(create_app(service)) as client:
        response = client.post("/search", json={"query": "maize", "top_k": 5})
    body = response.json()
    assert response.status_code == 200
    for key in ("query", "parsed_filters", "count", "results", "warnings", "search_engine", "embedding_model"):
        assert key in body
    assert "dictionary" not in body
    assert "fallback_applied" not in body


def test_protected_course_files_remain_unchanged():
    for path, expected in PROTECTED.items():
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected


class _DictionaryModule:
    def __init__(self, unsupported: bool = False):
        self.calls = []
        self.payload = {
            "query": "มันสำปะหลังภาคเหนือปี 2566",
            "intent": {
                "crop_id": None if unsupported else "CAS",
                "region_code": "NOR",
                "spatial_level": "region",
                "season": None,
                "year_from": 2023,
                "year_to": 2023,
                "unsupported_input": unsupported,
            },
            "count": 0 if unsupported else 1,
            "results": [] if unsupported else [
                {
                    "process_id": "P-1",
                    "crop_name": "มันสำปะหลัง",
                    "spatial_level": "region",
                    "area": "เหนือ",
                    "year_ce": 2023,
                    "season": "all",
                    "output_quantity": 12.5,
                    "output_unit": "t",
                    "source_id": "SRC-06",
                    "source_file": r"D:\secret\source.csv",
                }
            ],
            "message": "ฐานข้อมูลนี้ยังไม่มีปริมาณ Input LCI หรือค่าผลกระทบที่ตรวจยืนยันแล้ว" if unsupported else "พบข้อมูลที่ตรงเงื่อนไข",
        }

    def search(self, query, db_path, limit=50):
        self.calls.append((query, limit))
        self.payload["query"] = query
        return self.payload


class _BrokenDictionary:
    def search(self, query, db_path, limit=50):
        raise OSError(r"D:\Final Project\missing.sqlite")
