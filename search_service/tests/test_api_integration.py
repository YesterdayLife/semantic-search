"""Live checks against SQLite, the cached ONNX model, and Qdrant."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.database import connect_readonly
from app.embeddings import ONNX_MODEL_REVISION
from app.main import create_app

CANONICAL = Path(r"D:\Final Project\Hee_M3\output\S1-G14_M3.sqlite")
pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def live_client():
    before = hashlib.sha256(CANONICAL.read_bytes()).hexdigest()
    with TestClient(create_app()) as client:
        ready = client.get("/ready")
        assert ready.status_code == 200, ready.text
        yield client
    assert hashlib.sha256(CANONICAL.read_bytes()).hexdigest() == before


def test_ready_reports_the_indexed_collection(live_client):
    body = live_client.get("/ready").json()
    assert body["collection"] == "crop_process_bge_m3"
    assert body["vector_dimension"] == 1024
    assert body["distance"] == "cosine"
    assert body["points"] == 180
    assert body["process_count"] == 180
    assert body["model_revision"] == ONNX_MODEL_REVISION
    assert body["embedding_runtime"] == "onnx-cpu"
    assert "\\" not in live_client.get("/ready").text


def test_cassava_north_2023_matches_sqlite(live_client):
    _assert_matches(live_client, "มันสำปะหลังภาคเหนือปี 2566", "CAS", 2023, "NOR", None)


def test_maize_central_2022_matches_sqlite(live_client):
    _assert_matches(live_client, "maize production in central Thailand 2022", "MAI", 2022, "CEN", None)


def test_dry_season_rice_matches_sqlite(live_client):
    _assert_matches(live_client, "ข้าวนาปรัง", "RIC", None, None, "dry")


@pytest.mark.parametrize('query,year,season,quantity', [
    ('ข้าวนาปีภาคใต้ปี 2566', 2023, 'wet', 274135),
    ('ข้าวนาปรังภาคใต้ปี 2567', 2024, 'dry', 44427),
])
def test_southern_rice_matches_original_source(live_client, query, year, season, quantity):
    _assert_matches(live_client, query, 'RIC', year, 'SOU', season)
    body = live_client.post('/search', json={'query': query, 'top_k': 5}).json()
    assert body['count'] == 1
    assert body['results'][0]['production_quantity'] == quantity


def test_unfiltered_cassava_query_stays_on_cassava(live_client):
    response = live_client.post("/search", json={"query": "มันสำปะหลัง", "top_k": 5})
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 5
    assert body["parsed_filters"]["crop_id"] == "CAS"
    _assert_quantities(body["results"])
    assert all(item["crop"]["crop_id"] == "CAS" for item in body["results"])
    assert body["timing_ms"]["embed"] >= 0
    assert body["timing_ms"]["qdrant"] >= 0
    assert body["timing_ms"]["sqlite"] >= 0


def test_cassava_south_2023_has_no_substitute_result(live_client):
    response = live_client.post("/search", json={"query": "มันสำปะหลังภาคใต้ปี 2566", "top_k": 5})
    assert response.status_code == 200
    body = response.json()
    assert body["parsed_filters"]["region_code"] == "SOU"
    assert body["parsed_filters"]["year_ce"] == 2023
    assert body["count"] == 0
    assert body["results"] == []


def test_carbon_footprint_is_marked_unavailable(live_client, monkeypatch):
    constructed = {"count": 0}

    def deny_openai(*_args, **_kwargs):
        constructed["count"] += 1
        raise AssertionError("OpenAI client constructed")

    monkeypatch.setattr("app.embeddings.OpenAIEmbeddingProvider.__init__", deny_openai)
    response = live_client.post("/search", json={"query": "carbon footprint of rice production", "top_k": 3})
    assert response.status_code == 200
    body = response.json()
    assert "carbon_footprint" in body["unavailable_measures"]
    assert any("carbon-footprint" in warning for warning in body["warnings"])
    _assert_quantities(body["results"])
    assert constructed["count"] == 0


def test_collections_and_sqlite_checksum_remain_unchanged(live_client):
    digest = hashlib.sha256(CANONICAL.read_bytes()).hexdigest()
    assert digest == "700df10769c76624572c9761e8636daf82a6bd4c63b1d7ee0f3383f766834807"
    client = httpx.Client(base_url="http://127.0.0.1:6333", timeout=30)
    try:
        names = [item["name"] for item in client.get("/collections").json()["result"]["collections"]]
        assert "crop_process" not in names
        for name, size in (("crop_process_bge_m3", 1024), ("crop_process_mock", 1536)):
            count = client.post(f"/collections/{name}/points/count", json={"exact": True}).json()["result"]["count"]
            vectors = client.get(f"/collections/{name}").json()["result"]["config"]["params"]["vectors"]
            assert count == (180 if name == "crop_process_bge_m3" else 105)
            assert vectors["size"] == size
    finally:
        client.close()


def _assert_matches(client, query: str, crop_id: str, year_ce: int | None, region_code: str | None, season: str | None):
    response = client.post("/search", json={"query": query, "top_k": 5})
    assert response.status_code == 200, response.text
    body = response.json()
    expected = _sql_rows(crop_id, year_ce, region_code, season)
    assert body["count"] == min(5, len(expected))
    returned = {item["process_id"]: item for item in body["results"]}
    assert set(returned) <= set(expected)
    if len(expected) <= 5:
        assert set(returned) == set(expected)
    else:
        assert len(returned) == 5
    for process_id, item in returned.items():
        assert item["production_quantity"] == expected[process_id]["quantity"]
        assert item["production_unit"] == expected[process_id]["unit"]
        assert item["crop"]["crop_id"] == crop_id
        assert item["similarity_score"] != item["production_quantity"]
    scores = [item["similarity_score"] for item in body["results"]]
    assert scores == sorted(scores, reverse=True)


def _assert_quantities(results: list[dict]):
    if not results:
        return
    expected = _quantities([item["process_id"] for item in results])
    for item in results:
        assert item["production_quantity"] == expected[item["process_id"]]["quantity"]
        assert item["production_unit"] == expected[item["process_id"]]["unit"]


def _sql_rows(crop_id: str, year_ce: int | None, region_code: str | None, season: str | None) -> dict[str, sqlite3.Row]:
    clauses = ["p.crop_id = ?"]
    params: list = [crop_id]
    if year_ce is not None:
        clauses.append("p.year_ce = ?")
        params.append(year_ce)
    if region_code is not None:
        clauses.append("p.region_code = ?")
        params.append(region_code)
    if season is not None:
        clauses.append("p.season = ?")
        params.append(season)
    connection = connect_readonly(CANONICAL)
    try:
        rows = connection.execute(
            f"""
            SELECT p.process_id, e.quantity, e.unit
            FROM process AS p
            JOIN exchange AS e ON e.process_id = p.process_id AND e.direction = 'Output'
            WHERE {" AND ".join(clauses)}
            ORDER BY p.process_id
            """,
            params,
        ).fetchall()
    finally:
        connection.close()
    return {row["process_id"]: row for row in rows}


def _quantities(process_ids: list[str]) -> dict[str, sqlite3.Row]:
    placeholders = ",".join("?" for _ in process_ids)
    connection = connect_readonly(CANONICAL)
    try:
        rows = connection.execute(
            f"""
            SELECT process_id, quantity, unit
            FROM exchange
            WHERE direction = 'Output' AND process_id IN ({placeholders})
            """,
            process_ids,
        ).fetchall()
    finally:
        connection.close()
    return {row["process_id"]: row for row in rows}
