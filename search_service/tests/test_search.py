"""Search pipeline checks with fake Qdrant and SQLite records."""

from __future__ import annotations

import hashlib
import sqlite3
import time

import httpx
import pytest

from app.config import load_settings
from app.database import connect_readonly
from app.embeddings import ONNX_MODEL_REVISION, EmbeddingError
from app.qdrant_store import CollectionStatus, ScoredPoint
from app.records import Catalog, IndicatorValue, ProcessRecord, SourceHint, fetch_records
from app.schemas import FilterSet, SearchRequest
from app.search import SearchFailure, SearchService, payload_filter

CANONICAL = r"D:\Final Project\Hee_M3\output\S1-G14_M3.sqlite"


def test_payload_filter_uses_indexed_metadata():
    query_filter = payload_filter(
        {"crop_id": "CAS", "year_ce": 2023, "region_code": "NOR", "season": None, "spatial_level": "region", "source_id": None}
    )
    assert query_filter == {
        "must": [
            {"key": "crop_id", "match": {"value": "CAS"}},
            {"key": "year_ce", "match": {"value": 2023}},
            {"key": "region_code", "match": {"value": "NOR"}},
            {"key": "spatial_level", "match": {"value": "region"}},
        ]
    }


def test_explicit_filter_overrides_the_parsed_crop_and_is_sent_to_qdrant():
    service, store, embedder = _service()
    request = SearchRequest(query="มันสำปะหลังภาคเหนือปี 2566", filters=FilterSet(crop_id="MAI"))
    response = service.search(request)
    assert response["parsed_filters"]["crop_id"] == "MAI"
    assert response["parsed_filters"]["region_code"] == "NOR"
    assert response["parsed_filters"]["year_ce"] == 2023
    assert store.filters[0]["must"][0] == {"key": "crop_id", "match": {"value": "MAI"}}
    assert any("explicit crop_id" in warning for warning in response["warnings"])
    assert embedder.calls == 2


def test_invalid_filter_does_not_embed():
    service, _store, embedder = _service()
    with pytest.raises(SearchFailure) as caught:
        service.search(SearchRequest(query="rice", filters=FilterSet(crop_id="WHEAT")))
    assert caught.value.status_code == 422
    assert embedder.calls == 1


def test_results_follow_similarity_and_keep_sqlite_quantities():
    maize = _record("P-MAI", "MAI", "ข้าวโพดเลี้ยงสัตว์", 2022, "CEN", "กลาง", 431024.0)
    cassava = _record("P-CAS", "CAS", "มันสำปะหลัง", 2023, "NOR", "เหนือ", 7707851.0)
    service, _store, _embedder = _service(
        hits=[_hit("P-MAI", 0.2), _hit("P-CAS", 0.91)],
        records={maize.process_id: maize, cassava.process_id: cassava},
    )
    response = service.search(SearchRequest(query="crop production"))
    assert [item["process_id"] for item in response["results"]] == ["P-CAS", "P-MAI"]
    assert response["results"][0]["similarity_score"] == 0.91
    assert response["results"][0]["production_quantity"] == 7707851.0
    assert response["results"][0]["production_unit"] == "t"
    assert response["results"][0]["production_quantity"] != response["results"][0]["similarity_score"]
    assert response["results"][1]["indicators"][0]["value"] == 10.0


def test_empty_ranking_stays_empty():
    service, _store, _embedder = _service(hits=[])
    response = service.search(SearchRequest(query="มันสำปะหลังภาคใต้ปี 2566"))
    assert response["count"] == 0
    assert response["results"] == []


def test_fertilizer_and_carbon_requests_warn_without_inventing_values():
    record = _record("P-CAS", "CAS", "มันสำปะหลัง", 2023, "NOR", "เหนือ", 12.5)
    service, _store, _embedder = _service(hits=[_hit("P-CAS", 0.5)], records={record.process_id: record})
    fertilizer = service.search(SearchRequest(query="ปริมาณปุ๋ยที่ใช้ปลูกมันสำปะหลัง"))
    assert fertilizer["unavailable_measures"] == ["fertilizer"]
    assert fertilizer["results"][0]["production_quantity"] == 12.5
    assert "fertilizer" in " ".join(fertilizer["warnings"]).lower() or "ปุ๋ย" in " ".join(fertilizer["warnings"]) or "Validated fertilizer" in " ".join(fertilizer["warnings"])
    carbon = service.search(SearchRequest(query="carbon footprint of rice production"))
    assert "carbon_footprint" in carbon["unavailable_measures"]
    assert any("carbon-footprint" in warning for warning in carbon["warnings"])


def test_qdrant_outage_is_not_an_empty_result():
    service, _store, _embedder = _service(error=httpx.ConnectError("refused"))
    with pytest.raises(SearchFailure) as caught:
        service.search(SearchRequest(query="rice"))
    assert caught.value.status_code == 503
    assert caught.value.code == "qdrant_unavailable"


def test_incompatible_collection_is_rejected():
    service, _store, _embedder = _service(status=CollectionStatus(True, 1536, "cosine", 105))
    with pytest.raises(SearchFailure) as caught:
        service.ready()
    assert caught.value.status_code == 503
    assert caught.value.code == "collection_incompatible"


def test_missing_model_cache_fails_readiness():
    settings = load_settings()
    service = SearchService(settings, _BrokenEmbedder(), _Store(), catalog=_catalog())
    service.start()
    with pytest.raises(SearchFailure) as caught:
        service.ready()
    assert caught.value.status_code == 503
    assert "cache" in caught.value.message


def test_sqlite_hydration_quantity_matches_the_database():
    connection = connect_readonly(load_settings().sqlite_path)
    try:
        selected = connection.execute(
            """
            SELECT p.process_id, e.quantity, e.unit
            FROM process AS p
            JOIN exchange AS e ON e.process_id = p.process_id AND e.direction = 'Output'
            WHERE p.crop_id = 'CAS' AND p.region_code = 'NOR' AND p.year_ce = 2023
            """
        ).fetchone()
        hydrated = fetch_records(connection, [selected["process_id"]])
    finally:
        connection.close()
    assert hydrated[selected["process_id"]].production_quantity == selected["quantity"]
    assert hydrated[selected["process_id"]].production_unit == selected["unit"]


def test_semantic_qdrant_timing_excludes_collection_validation():
    service, store, _embedder = _service()
    calls = {"status": 0}
    original = store.collection_status

    def slow_status(name):
        calls["status"] += 1
        time.sleep(0.05)
        if store.error:
            raise store.error
        return original(name)

    store.collection_status = slow_status
    first = service.search(SearchRequest(query="maize"))
    assert first["timing_ms"]["collection_validation"] >= 40
    assert first["timing_ms"]["qdrant"] < 30
    assert first["results"][0]["similarity_score"] == 0.8
    second = service.search(SearchRequest(query="maize"))
    assert calls["status"] == 1
    assert second["timing_ms"]["collection_validation"] == 0.0
    assert second["results"][0]["similarity_score"] == first["results"][0]["similarity_score"]
    store.error = httpx.ConnectError("refused")
    service._collection_valid_until = 0
    with pytest.raises(SearchFailure) as caught:
        service.search(SearchRequest(query="maize"))
    assert caught.value.code == "qdrant_unavailable"
    store.error = None
    recovered = service.search(SearchRequest(query="maize"))
    assert recovered["results"][0]["process_id"] == first["results"][0]["process_id"]
    assert calls["status"] == 3


def test_readonly_connection_rejects_modification():
    path = load_settings().sqlite_path
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    connection = connect_readonly(path)
    try:
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("UPDATE process SET season = 'all'")
    finally:
        connection.close()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def _service(hits=None, records=None, status=None, error=None):
    if hits is None:
        record = _record("P-MAI", "MAI", "ข้าวโพดเลี้ยงสัตว์", 2022, "CEN", "กลาง", 431024.0)
        hits = [_hit(record.process_id, 0.8)]
        records = {record.process_id: record}
    embedder = _Embedder()
    store = _Store(hits=hits, status=status, error=error)
    service = SearchService(load_settings(), embedder, store, catalog=_catalog(), records=_Records(records or {}))
    service.start()
    return service, store, embedder


def _catalog() -> Catalog:
    return Catalog(
        crop_ids=frozenset({"CAS", "MAI", "RIC", "SUG"}),
        region_codes=frozenset({"NEA", "NOR", "SOU", "EAS", "WES", "CEN"}),
        seasons=frozenset({"all", "dry", "wet"}),
        spatial_levels=frozenset({"country", "region"}),
        source_ids=frozenset({"SRC-01", "SRC-06"}),
        sources=(SourceHint("SRC-01", "FAO", "FAOSTAT QCL"), SourceHint("SRC-06", "OAE", "OAE cassava")),
        process_count=105,
    )


def _record(process_id, crop_id, crop_name, year, region_code, region_name, quantity) -> ProcessRecord:
    return ProcessRecord(
        process_id=process_id,
        crop_id=crop_id,
        crop_name=crop_name,
        year_ce=year,
        year_original=str(year),
        calendar="CE",
        season="all",
        spatial_level="region",
        region_code=region_code,
        region_name=region_name,
        area=region_name,
        production_quantity=quantity,
        production_unit="t",
        production_flow=crop_name,
        source_id="SRC-06",
        agency="OAE",
        title="OAE cassava",
        indicators=(IndicatorValue("area_harvested", 10.0, "rai"),),
    )


def _hit(process_id: str, score: float) -> ScoredPoint:
    return ScoredPoint(process_id, score, process_id, {"process_id": process_id})


class _Embedder:
    model_name = "BAAI/bge-m3"
    model_revision = ONNX_MODEL_REVISION
    dimension = 1024
    provider_id = "local-bge-m3"
    device = "onnx-cpu"

    def __init__(self):
        self.calls = 0

    def prepare(self):
        return None

    def embed_query(self, text: str):
        self.calls += 1
        return [1.0, *([0.0] * 1023)]


class _BrokenEmbedder(_Embedder):
    def prepare(self):
        raise EmbeddingError("local BGE-M3 ONNX weights are not in the local cache")


class _Records:
    def __init__(self, rows: dict[str, ProcessRecord]):
        self.rows = rows

    def fetch(self, process_ids: list[str]) -> dict[str, ProcessRecord]:
        return {process_id: self.rows[process_id] for process_id in process_ids if process_id in self.rows}


class _Store:
    def __init__(self, hits=None, status=None, error=None):
        self.hits = hits or []
        self.status = status or CollectionStatus(True, 1024, "cosine", 105)
        self.sample = {
            "embedding_model": "BAAI/bge-m3",
            "embedding_provider": "local-bge-m3",
            "model_revision": ONNX_MODEL_REVISION,
            "vector_dimension": 1024,
        }
        self.error = error
        self.filters = []

    def collection_status(self, name):
        if self.error:
            raise self.error
        return self.status

    def sample_payload(self, name):
        return self.sample

    def search_points(self, name, vector, limit, query_filter):
        self.filters.append(query_filter)
        return list(self.hits)[:limit]

    def close(self):
        return None
