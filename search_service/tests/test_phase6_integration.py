"""Live Phase 6 checks against SQLite, Qdrant, and the cached ONNX model."""

from __future__ import annotations

import hashlib
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.embeddings import OpenAIEmbeddingProvider
from app.evaluate_search import load_dataset, safety_snapshot
from app.main import create_app

CANONICAL = Path(r"D:\Final Project\Hee_M3\output\S1-G14_M3.sqlite")
DATASET = Path(__file__).resolve().parents[1] / "evaluation" / "queries.json"
pytestmark = pytest.mark.integration


@pytest.fixture
def live_client():
    before = _qdrant()
    digest = hashlib.sha256(CANONICAL.read_bytes()).hexdigest()
    with TestClient(create_app()) as client:
        assert client.get("/ready").status_code == 200
        yield client, before, digest
    assert hashlib.sha256(CANONICAL.read_bytes()).hexdigest() == digest
    assert _qdrant() == before


def test_live_compare_keeps_search_compatible(live_client, monkeypatch):
    client, before, _digest = live_client
    monkeypatch.setattr(OpenAIEmbeddingProvider, "embed_texts", _reject_openai)
    search = client.post("/search", json={"query": "มันสำปะหลังภาคเหนือปี 2566", "top_k": 5})
    compared = client.post("/compare", json={"query": "มันสำปะหลังภาคเหนือปี 2566", "top_k": 5, "mode": "compare"})
    assert search.status_code == 200
    assert "parsed_filters" in search.json()
    assert "fallback_applied" not in search.json()
    assert compared.status_code == 200
    body = compared.json()
    assert body["dictionary"]["results"][0]["process_id"] == "P-REG-SRC-06-CAS-NOR-2023"
    assert body["semantic"]["results"][0]["process_id"] == "P-REG-SRC-06-CAS-NOR-2023"
    assert body["score_comparison"] is None
    assert body["dictionary"]["results"][0]["similarity_score"] is None
    assert body["semantic"]["results"][0]["match_reason"] is None
    assert body["timing_ms"]["embed"] is not None
    unsupported = client.post("/compare", json={"query": "carbon footprint", "mode": "semantic"})
    assert unsupported.json()["availability_status"]["semantic"] == "unsupported"
    assert unsupported.json()["semantic"]["results"] == []
    assert _qdrant() == before
    assert before["points_count"] == 180
    assert before["vector_size"] == 1024
    assert before["distance"] == "Cosine"


def test_live_evaluation_reports_both_backends(monkeypatch):
    before = _qdrant()
    digest = hashlib.sha256(CANONICAL.read_bytes()).hexdigest()
    monkeypatch.setattr(OpenAIEmbeddingProvider, "embed_texts", _reject_openai)
    from app.evaluate_search import ROOT, main

    output_dir = ROOT / "evaluation" / "reports" / "pytest"
    exit_code = main(["--dataset", str(DATASET), "--top-k", "5", "--backends", "both", "--repetitions", "3", "--warmup", "1", "--output-dir", str(output_dir)])
    assert exit_code == 0
    report = __import__("json").loads((output_dir / "evaluation.json").read_text(encoding="utf-8"))
    assert (output_dir / "evaluation.md").is_file()
    assert report["query_count"] >= 30
    assert report["backends"]["dictionary"]["aggregate"]["precision_at_k"] is not None
    assert report["backends"]["semantic"]["aggregate"]["precision_at_k"] is not None
    assert report["benchmark"]["model_initialization_ms"] >= 0
    assert report["benchmark"]["dictionary_warm"]["count"] == 9
    assert report["benchmark"]["semantic_warm"]["count"] == 9
    assert "Hybrid search is not implemented" in report["hybrid_recommendation"]
    assert report["safety"]["sqlite_unchanged"] is True
    assert report["safety"]["after"]["sqlite_sha256"] == digest
    assert report["safety"]["after"]["qdrant"]["points_count"] == before["points_count"]
    assert all(report["safety"]["after"]["protected_files_unchanged"].values())
    snapshot = safety_snapshot()
    assert snapshot["qdrant"]["points_count"] == 180
    assert load_dataset(DATASET)


def _qdrant() -> dict:
    response = httpx.get("http://127.0.0.1:6333/collections/crop_process_bge_m3", timeout=5)
    result = response.json()["result"]
    vectors = result["config"]["params"]["vectors"]
    return {"points_count": result["points_count"], "vector_size": vectors["size"], "distance": vectors["distance"]}


def _reject_openai(*_args, **_kwargs):
    raise AssertionError("OpenAI embeddings were called")
