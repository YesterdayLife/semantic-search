"""Local BGE-M3 provider checks. The integration test is the only one that loads weights."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from app.config import BGE_MODEL, BGE_REVISION, load_settings
from app.documents import load_documents
from app.embeddings import ONNX_MODEL_REVISION, LocalBgeM3Provider
from app.index_sqlite import AuthorizationError, IncompatibleCollectionError, _guard_collection_name, execute_index
from app.qdrant_store import CollectionSnapshot, CollectionSpec, ExistingPoint, validate_snapshot

CANONICAL = Path(r"D:\Final Project\Hee_M3\output\S1-G14_M3.sqlite")
PROTECTED = {
    Path(r"D:\Final Project\Hee_M4\ch6 semantic search\src\semantic_search.py"):
        "8db66ee8ee675e43822e827375a2bba299eeed252063cc2a88f4a130e8e7cc60",
    Path(r"D:\Final Project\Hee_M4\ch6 semantic search\src\build_serving_layer.py"):
        "b770300f8835ab5c58f40d32132d4dd65530bfd2ac4692082fd3fd7caef0ca78",
    Path(r"D:\Final Project\Hee_M4\ch6 semantic search\graph\import\import.cypher"):
        "5286e190259a123aaed76fda427851a62bf126e69c71ad0a4e013070e2b3ab1d",
}


def test_local_provider_needs_no_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    settings = load_settings()
    documents = load_documents(settings.sqlite_path)[:1]
    provider = _FakeBge()
    report = execute_index(
        settings,
        documents,
        mode="local-bge-m3",
        dry_run=True,
        provider=provider,
        store=_ReadOnlyStore(),
    )
    assert settings.api_key_configured is False
    assert report.embedding_model == BGE_MODEL
    assert report.embedding_provider == "local-bge-m3"
    assert provider.calls == 0


def test_local_path_does_not_construct_openai(monkeypatch):
    constructed = {"count": 0}

    def deny_openai(*_args, **_kwargs):
        constructed["count"] += 1
        raise AssertionError("OpenAI client constructed")

    monkeypatch.setattr("app.embeddings.OpenAIEmbeddingProvider.__init__", deny_openai)
    provider = LocalBgeM3Provider()
    provider._encode = lambda texts: [[1.0] + [0.0] * 1023 for _ in texts]
    vector = provider.embed_texts(["cassava production"])
    assert constructed["count"] == 0
    assert len(vector[0]) == 1024


def test_normalized_local_vector_shape():
    provider = LocalBgeM3Provider()
    provider._encode = lambda texts: [[3.0, 4.0] + [0.0] * 1022]
    vector = provider.embed_texts(["ข้าวโพด"])[0]
    assert len(vector) == 1024
    assert all(value == value and abs(value) != float("inf") for value in vector)
    assert any(value != 0 for value in vector)
    assert abs(sum(value * value for value in vector) - 1) < 1e-6
    assert provider.embed_texts([]) == []


def test_query_and_document_use_the_same_encoder():
    provider = LocalBgeM3Provider()
    seen = []

    def encode(texts):
        seen.append(list(texts))
        return [[1.0] + [0.0] * 1023 for _ in texts]

    provider._encode = encode
    document = provider.embed_texts(["rice ข้าว"])[0]
    query = provider.embed_query("rice ข้าว")
    assert document == query
    assert seen == [["rice ข้าว"], ["rice ข้าว"]]
    assert provider.model_revision == BGE_REVISION


def test_local_collections_stay_isolated():
    with pytest.raises(IncompatibleCollectionError):
        _guard_collection_name("crop_process", "local-bge-m3", BGE_MODEL)
    with pytest.raises(IncompatibleCollectionError):
        _guard_collection_name("crop_process_mock", "local-bge-m3", BGE_MODEL)
    with pytest.raises(IncompatibleCollectionError):
        _guard_collection_name("crop_process_bge_m3", "mock", "mock-deterministic-v1")


def test_incompatible_bge_collection_is_rejected():
    wrong_size = CollectionSnapshot("crop_process_bge_m3", True, 1536, "cosine", ())
    spec = CollectionSpec(
        "crop_process_bge_m3",
        BGE_MODEL,
        "1",
        dimension=1024,
        model_revision=BGE_REVISION,
        embedding_provider="local-bge-m3",
    )
    with pytest.raises(IncompatibleCollectionError):
        validate_snapshot(wrong_size, spec)
    foreign = ExistingPoint(
        "id",
        "P1",
        "hash",
        BGE_MODEL,
        "1",
        embedding_provider="local-bge-m3",
        model_revision="other-revision",
        vector_dimension="1024",
    )
    mixed = CollectionSnapshot("crop_process_bge_m3", True, 1024, "cosine", (foreign,))
    with pytest.raises(IncompatibleCollectionError):
        validate_snapshot(mixed, spec)


def test_local_dry_run_writes_nothing():
    settings = load_settings()
    documents = load_documents(settings.sqlite_path)
    before = hashlib.sha256(CANONICAL.read_bytes()).hexdigest()
    store = _ReadOnlyStore()
    provider = _FakeBge()
    report = execute_index(settings, documents, mode="local-bge-m3", dry_run=True, provider=provider, store=store)
    assert report.dry_run is True
    assert report.documents == 180
    assert report.embedded == 0
    assert report.upserted == 0
    assert store.upserts == []
    assert provider.calls == 0
    assert hashlib.sha256(CANONICAL.read_bytes()).hexdigest() == before


def test_local_indexing_is_idempotent_without_a_model():
    settings = replace(load_settings(), qdrant_bge_collection="crop_process_unit_test")
    documents = load_documents(settings.sqlite_path)[:2]
    provider = _FakeBge()
    store = _MemoryStore("crop_process_unit_test")
    first = execute_index(settings, documents, mode="local-bge-m3", execute_local=True, provider=provider, store=store)
    second = execute_index(settings, documents, mode="local-bge-m3", execute_local=True, provider=provider, store=store)
    assert first.upserted == 2
    assert first.embedded == 2
    assert second.unchanged == 2
    assert second.embedded == 0
    assert second.upserted == 0
    assert provider.calls == 1
    assert store.count("crop_process_unit_test") == 2


def test_local_write_requires_execute_local():
    settings = load_settings()
    documents = load_documents(settings.sqlite_path)[:1]
    with pytest.raises(AuthorizationError):
        execute_index(settings, documents, mode="local-bge-m3", dry_run=False, execute_local=False, provider=_FakeBge(), store=_ReadOnlyStore())


def test_existing_search_files_are_unchanged():
    for path, expected in PROTECTED.items():
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected


def test_live_mock_and_openai_collections_are_separate():
    client = httpx.Client(base_url="http://127.0.0.1:6333", timeout=30)
    try:
        names = [item["name"] for item in client.get("/collections").json()["result"]["collections"]]
        assert "crop_process_mock" in names
        assert "crop_process" not in names
        count = client.post("/collections/crop_process_mock/points/count", json={"exact": True}).json()["result"]["count"]
        assert count == 105
    finally:
        client.close()


@pytest.mark.integration
def test_real_bge_m3_encodes_thai_and_english():
    provider = LocalBgeM3Provider(device="auto")
    thai = provider.embed_texts(["มันสำปะหลังภาคเหนือ"])[0]
    english = provider.embed_query("cassava production in northern Thailand")
    assert len(thai) == 1024
    assert len(english) == 1024
    assert all(value == value and abs(value) != float("inf") for value in thai + english)
    assert any(value != 0 for value in thai)
    assert any(value != 0 for value in english)
    assert abs(sum(value * value for value in thai) - 1) < 1e-4
    assert provider.model_name == BGE_MODEL
    assert provider.model_revision in {BGE_REVISION, ONNX_MODEL_REVISION}
    assert provider.device in {"cpu", "cuda", "onnx-cpu"}
    assert thai != english


class _FakeBge:
    model_name = BGE_MODEL
    dimension = 1024
    semantic = True
    provider_id = "local-bge-m3"
    model_revision = BGE_REVISION
    device = "cpu"

    def __init__(self):
        self.calls = 0

    def embed_texts(self, texts):
        self.calls += 1
        return [[0.0] * 1023 + [1.0] for _ in texts]

    def embed_query(self, text):
        return self.embed_texts([text])[0]


class _ReadOnlyStore:
    def __init__(self):
        self.upserts = []

    def snapshot(self, name):
        return CollectionSnapshot(name, False, None, None, ())

    def ensure_compatible(self, spec):
        raise AssertionError("dry-run created a collection")

    def list_points(self, name):
        return []

    def upsert(self, name, points):
        self.upserts.extend(points)
        raise AssertionError("dry-run uploaded vectors")

    def count(self, name):
        raise AssertionError("dry-run counted a write")


class _MemoryStore:
    def __init__(self, name: str):
        self.name = name
        self.points: list[ExistingPoint] = []
        self.created = False

    def snapshot(self, name):
        if not self.created:
            return CollectionSnapshot(name, False, None, None, ())
        return CollectionSnapshot(name, True, 1024, "cosine", tuple(self.points))

    def ensure_compatible(self, spec):
        validate_snapshot(self.snapshot(spec.name), spec)
        created = not self.created
        self.created = True
        return created

    def list_points(self, name):
        return list(self.points)

    def upsert(self, name, points):
        for point in points:
            payload = point.payload
            self.points = [item for item in self.points if item.point_id != point.id]
            self.points.append(
                ExistingPoint(
                    point_id=str(point.id),
                    process_id=payload["process_id"],
                    text_hash=payload["text_hash"],
                    embedding_model=payload["embedding_model"],
                    document_schema_version=payload["document_schema_version"],
                    embedding_provider=str(payload.get("embedding_provider") or ""),
                    model_revision=str(payload.get("model_revision") or ""),
                    vector_dimension=str(payload.get("vector_dimension") or ""),
                )
            )

    def count(self, name):
        return len(self.points)
