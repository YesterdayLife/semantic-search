"""HTTP checks that do not load BGE-M3 weights."""

from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from app.schemas import FilterSet, SearchRequest
from tests.test_search import _service

PROTECTED = {
    Path(r"D:\Final Project\Hee_M4\ch6 semantic search\src\semantic_search.py"):
        "8db66ee8ee675e43822e827375a2bba299eeed252063cc2a88f4a130e8e7cc60",
    Path(r"D:\Final Project\Hee_M4\ch6 semantic search\src\build_serving_layer.py"):
        "b770300f8835ab5c58f40d32132d4dd65530bfd2ac4692082fd3fd7caef0ca78",
    Path(r"D:\Final Project\Hee_M4\ch6 semantic search\graph\import\import.cypher"):
        "5286e190259a123aaed76fda427851a62bf126e69c71ad0a4e013070e2b3ab1d",
}


def test_api_starts_and_reports_health_and_readiness(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    service, _store, _embedder = _service()
    with TestClient(create_app(service)) as client:
        health = client.get("/health")
        ready = client.get("/ready")
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert ready.status_code == 200
    assert ready.json()["collection"] == "crop_process_bge_m3"
    assert ready.json()["vector_dimension"] == 1024
    assert ready.json()["sqlite"] == "ok"
    assert "\\" not in health.text


def test_search_endpoints_reject_invalid_input_and_unknown_fields():
    service, _store, embedder = _service()
    with TestClient(create_app(service)) as client:
        empty = client.post("/search", json={"query": "   "})
        unknown = client.post("/search", json={"query": "rice", "filters": {"province": "เชียงใหม่"}})
        invalid_year = client.post("/search", json={"query": "rice", "filters": {"year_ce": 2566}})
        invalid_region = client.post("/search", json={"query": "rice", "filters": {"region_code": "NORTH"}})
        extra_query = client.get("/search", params={"query": "rice", "limit": 3})
        whitespace = client.get("/search", params={"query": " "})
    assert empty.status_code == 422
    assert unknown.status_code == 422
    assert invalid_year.status_code == 422
    assert invalid_region.status_code == 422
    assert extra_query.status_code == 422
    assert whitespace.status_code == 422
    assert embedder.calls == 1
    for response in (empty, unknown, invalid_year, invalid_region, extra_query, whitespace):
        assert "Traceback" not in response.text
        assert "results" not in response.json()


def test_post_and_get_search_return_ranked_json(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    constructed = {"count": 0}

    def deny_openai(*_args, **_kwargs):
        constructed["count"] += 1
        raise AssertionError("OpenAI client constructed")

    monkeypatch.setattr("app.embeddings.OpenAIEmbeddingProvider.__init__", deny_openai)
    service, _store, _embedder = _service()
    with TestClient(create_app(service)) as client:
        posted = client.post("/search", json={"query": "maize production in central Thailand 2022", "top_k": 5})
        fetched = client.get("/search", params={"query": "production", "top_k": 1})
    assert posted.status_code == 200
    body = posted.json()
    assert body["search_engine"] == "local-bge-m3"
    assert body["embedding_model"] == "BAAI/bge-m3"
    assert body["count"] == 1
    assert body["results"][0]["production_quantity"] == 431024.0
    assert body["timing_ms"]["total"] >= 0
    assert fetched.status_code == 200
    assert fetched.json()["count"] == 1
    assert constructed["count"] == 0


def test_qdrant_outage_returns_service_unavailable():
    import httpx

    service, _store, _embedder = _service(error=httpx.ConnectError("refused"))
    with TestClient(create_app(service)) as client:
        response = client.post("/search", json={"query": "rice"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "qdrant_unavailable"
    assert "results" not in response.json()


def test_existing_dictionary_and_neo4j_files_are_unchanged():
    for path, expected in PROTECTED.items():
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected


def test_request_model_bounds_top_k():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        SearchRequest(query="rice", top_k=106)
    assert SearchRequest(query=" rice ", filters=FilterSet()).query == "rice"
