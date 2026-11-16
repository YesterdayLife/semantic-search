"""Live hybrid checks against SQLite, Qdrant, and the cached ONNX model."""

from __future__ import annotations

import hashlib
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.database import connect_readonly
from app.embeddings import OpenAIEmbeddingProvider
from app.main import create_app

CANONICAL = Path(r"D:\Final Project\Hee_M3\output\S1-G14_M3.sqlite")
pytestmark = pytest.mark.integration


def test_live_hybrid_matches_sqlite_and_keeps_existing_routes(monkeypatch):
    before = _qdrant()
    digest = hashlib.sha256(CANONICAL.read_bytes()).hexdigest()
    monkeypatch.setattr(OpenAIEmbeddingProvider, "embed_texts", _reject_openai)
    with TestClient(create_app()) as client:
        search = client.post("/search", json={"query": "มันสำปะหลังภาคเหนือปี 2566", "top_k": 5})
        compared = client.post("/compare", json={"query": "มันสำปะหลังและข้าวโพด", "mode": "compare", "top_k": 5})
        hybrid = client.post("/hybrid-search", json={"query": "มันสำปะหลังและข้าวโพด", "top_k": 5})
        numeric = client.post("/hybrid-search", json={"query": "cassava production greater than 10000000 tonnes", "top_k": 5})
        missing = client.post("/hybrid-search", json={"query": "sugarcane and cassava in the south in 2023", "top_k": 5})
        exact = client.post("/hybrid-search", json={"query": "มันสำปะหลังภาคเหนือปี 2566", "top_k": 5})
    assert search.status_code == 200 and "ranking_method" not in search.json()
    assert compared.status_code == 200 and compared.json()["score_comparison"] is None
    body = hybrid.json()
    assert hybrid.status_code == 200
    assert body["search_mode"] == "hybrid"
    assert {row["crop"]["crop_id"] for row in body["results"]} == {"CAS", "MAI"}
    assert numeric.json()["applied_numeric"][0]["operator"] == "gt"
    assert numeric.json()["eligible_count"] == 18
    assert all(row["production_quantity"] > 10000000 for row in numeric.json()["results"])
    assert missing.json()["count"] == 0
    assert missing.json()["embedding_skipped"] is True
    assert set(missing.json()["missing_groups"]) == {"SUG", "CAS"}
    exact_body = exact.json()
    assert exact_body["results"][0]["process_id"] == "P-REG-SRC-06-CAS-NOR-2023"
    connection = connect_readonly(CANONICAL)
    try:
        quantity = connection.execute(
            "SELECT quantity FROM exchange WHERE process_id = ? AND direction = 'Output'",
            ("P-REG-SRC-06-CAS-NOR-2023",),
        ).fetchone()[0]
    finally:
        connection.close()
    assert exact_body["results"][0]["production_quantity"] == quantity
    assert hashlib.sha256(CANONICAL.read_bytes()).hexdigest() == digest
    assert _qdrant() == before


def test_extended_evaluation_matches_expanded_catalog(monkeypatch, tmp_path):
    monkeypatch.setattr(OpenAIEmbeddingProvider, "embed_texts", _reject_openai)
    from app.evaluate_search import ROOT, main

    output_dir = ROOT / "evaluation" / "reports" / "hybrid-pytest"
    exit_code = main(["--backends", "all", "--repetitions", "0", "--output-dir", str(output_dir)])
    assert exit_code == 0
    report = __import__("json").loads((output_dir / "evaluation.json").read_text(encoding="utf-8"))
    assert report["query_count"] >= 60
    for backend in ("dictionary", "semantic"):
        subset = report["backends"][backend]["phase6_subset"]
        assert subset["precision_at_k"] == 1.0
        # Top-5 covers a smaller fraction of the now-expanded relevant rice set.
        assert subset["recall_at_k"] == 0.5446
        assert subset["availability_accuracy"] == 1.0
    hybrid = report["backends"]["hybrid"]["aggregate"]
    assert hybrid["precision_at_k"] is not None
    assert hybrid["numeric_condition_correctness"] == 1.0
    assert report["safety"]["sqlite_unchanged"] is True
    assert report["safety"]["after"]["qdrant"]["points_count"] == 180


def _qdrant() -> dict:
    response = httpx.get("http://127.0.0.1:6333/collections/crop_process_bge_m3", timeout=5)
    result = response.json()["result"]
    vectors = result["config"]["params"]["vectors"]
    return {"points_count": result["points_count"], "vector_size": vectors["size"], "distance": vectors["distance"]}


def _reject_openai(*_args, **_kwargs):
    raise AssertionError("OpenAI embeddings were called")
