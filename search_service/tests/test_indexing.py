"""Indexing guards, mock vectors, and Qdrant upsert behavior."""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import replace

import pytest

from app.config import MOCK_EMBEDDING_MODEL, load_settings
from app.documents import load_documents
from app.embeddings import EmbeddingError, MockEmbeddingProvider, OpenAIEmbeddingProvider
from app.index_sqlite import AuthorizationError, execute_index
from app.qdrant_store import (
    UNIT_TEST_COLLECTION,
    CollectionSnapshot,
    CollectionSpec,
    ExistingPoint,
    IncompatibleCollectionError,
    QdrantStore,
    VectorPoint,
    validate_snapshot,
)

CANONICAL = load_settings().sqlite_path
UNIT_COLLECTION = UNIT_TEST_COLLECTION


def test_mock_vectors_are_deterministic_1536():
    provider = MockEmbeddingProvider()
    assert provider.semantic is False
    assert provider.model_name != "text-embedding-3-small"
    first = provider.embed_texts(["cassava north", "rice"])
    second = provider.embed_texts(["cassava north", "rice"])
    assert first == second
    assert len(first[0]) == 1536
    assert first[0] != first[1]
    norm = sum(value * value for value in first[0]) ** 0.5
    assert abs(norm - 1) < 1e-6


def test_openai_retries_without_a_network_call(monkeypatch):
    monkeypatch.setattr("app.embeddings.time.sleep", lambda _seconds: None)
    provider = OpenAIEmbeddingProvider(api_key="test-key-not-real", attempts=3)

    class RateLimitError(Exception):
        pass

    provider.retriable_error_names = ("RateLimitError",)
    calls = {"count": 0}

    def call(_texts):
        calls["count"] += 1
        if calls["count"] < 3:
            raise RateLimitError("slow down")
        return [[0.0] * 1536]

    assert provider._embed_with_retries(["doc"], call) == [[0.0] * 1536]
    assert calls["count"] == 3


def test_openai_failure_message_hides_the_key():
    provider = OpenAIEmbeddingProvider(api_key="sk-test-secret-value", attempts=1)

    def call(_texts):
        raise RuntimeError("sk-test-secret-value leaked")

    with pytest.raises(EmbeddingError) as caught:
        provider._embed_with_retries(["doc"], call)
    assert "sk-test-secret-value" not in str(caught.value)


def test_incompatible_collections_are_rejected():
    point = ExistingPoint("id", "P1", "hash", "mock-deterministic-v1", "1")
    wrong_size = CollectionSnapshot("crop_process", True, 128, "cosine", ())
    mixed = CollectionSnapshot("crop_process_mock", True, 1536, "cosine", (point,))
    empty_ok = CollectionSnapshot("crop_process_mock", True, 1536, "cosine", ())
    mock_spec = CollectionSpec("crop_process_mock", MOCK_EMBEDDING_MODEL, "1", semantic=False)
    real_spec = CollectionSpec("crop_process", "text-embedding-3-small", "1", semantic=True)
    with pytest.raises(IncompatibleCollectionError):
        validate_snapshot(wrong_size, real_spec)
    with pytest.raises(IncompatibleCollectionError):
        validate_snapshot(mixed, CollectionSpec("crop_process_mock", "text-embedding-3-small", "1", semantic=True))
    validate_snapshot(empty_ok, mock_spec)


def test_dry_run_does_not_embed_or_write():
    settings = load_settings()
    documents = load_documents(settings.sqlite_path)
    provider = _ExplodingProvider()
    store = _ExplodingStore()
    report = execute_index(settings, documents, mode="mock", dry_run=True, provider=provider, store=store)
    assert report.dry_run is True
    assert report.documents == 180
    assert report.new == 180
    assert report.embedded == 0
    assert report.upserted == 0
    assert report.created_collection is False
    assert provider.calls == 0
    assert store.upserts == 0
    assert store.created is False


def test_real_mode_requires_explicit_authorization():
    settings = load_settings()
    documents = load_documents(settings.sqlite_path)[:1]
    provider = _ExplodingProvider(model_name="text-embedding-3-small", semantic=True)
    with pytest.raises(AuthorizationError):
        execute_index(settings, documents, mode="real", dry_run=False, execute_real=False, provider=provider, store=_ExplodingStore())
    assert provider.calls == 0


def test_real_dry_run_does_not_call_the_provider():
    settings = load_settings()
    documents = load_documents(settings.sqlite_path)[:2]
    provider = _ExplodingProvider(model_name="text-embedding-3-small", semantic=True)
    report = execute_index(
        settings,
        documents,
        mode="real",
        dry_run=True,
        execute_real=True,
        provider=provider,
        store=_ExplodingStore(),
    )
    assert report.collection == "crop_process"
    assert report.embedding_model == "text-embedding-3-small"
    assert report.embedded == 0
    assert provider.calls == 0


def test_mock_mode_refuses_the_real_collection_name():
    settings = replace(load_settings(), qdrant_collection="crop_process", qdrant_mock_collection="crop_process")
    documents = load_documents(settings.sqlite_path)[:1]
    with pytest.raises(IncompatibleCollectionError):
        execute_index(settings, documents, mode="mock", dry_run=True, provider=_ExplodingProvider(), store=_ExplodingStore())


def test_failed_embedding_does_not_change_sqlite(tmp_path):
    source = CANONICAL
    copied = tmp_path / "copy.sqlite"
    shutil.copy2(source, copied)
    before_copy = hashlib.sha256(copied.read_bytes()).hexdigest()
    before_canonical = hashlib.sha256(source.read_bytes()).hexdigest()
    settings = replace(load_settings(), sqlite_path=copied, qdrant_mock_collection=UNIT_COLLECTION)
    documents = load_documents(copied)
    store = _MemoryStore.empty(UNIT_COLLECTION)
    with pytest.raises(EmbeddingError):
        execute_index(settings, documents, mode="mock", provider=_FailProvider(), store=store)
    assert store.upserts == []
    assert hashlib.sha256(copied.read_bytes()).hexdigest() == before_copy
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before_canonical


def test_stale_points_are_reported_and_not_deleted():
    settings = replace(load_settings(), qdrant_mock_collection=UNIT_COLLECTION)
    documents = load_documents(settings.sqlite_path)[:1]
    stale = ExistingPoint("stale-id", "P-STALE", "old", MOCK_EMBEDDING_MODEL, "1")
    store = _MemoryStore.with_points(UNIT_COLLECTION, [stale])
    provider = MockEmbeddingProvider()
    report = execute_index(settings, documents, mode="mock", provider=provider, store=store)
    assert report.stale_process_ids == ["P-STALE"]
    assert report.upserted == 1
    assert store.deleted is False


def test_qdrant_upsert_is_idempotent(unit_collection):
    settings = replace(load_settings(), qdrant_mock_collection=unit_collection)
    documents = load_documents(settings.sqlite_path)[:2]
    provider = _CountingMock()
    store = QdrantStore(settings.qdrant_url)
    try:
        first = execute_index(settings, documents, mode="mock", provider=provider, store=store)
        second = execute_index(settings, documents, mode="mock", provider=provider, store=store)
        assert first.upserted == 2
        assert first.created_collection is True
        assert second.upserted == 0
        assert second.unchanged == 2
        assert second.embedded == 0
        assert provider.calls == 1
        assert store.count(unit_collection) == 2
        stored = {point.process_id for point in store.list_points(unit_collection)}
        assert stored == {item.process_id for item in documents}
    finally:
        store.close()


def test_live_collection_rejects_a_different_embedding_model(unit_collection):
    settings = replace(load_settings(), qdrant_mock_collection=unit_collection)
    store = QdrantStore(settings.qdrant_url)
    try:
        store.ensure_compatible(CollectionSpec(unit_collection, MOCK_EMBEDDING_MODEL, "1"))
        store.upsert(
            unit_collection,
            [
                VectorPoint(
                    id="11111111-1111-4111-8111-111111111111",
                    vector=[0.0] * 1536,
                    payload={
                        "process_id": "P-FOREIGN",
                        "text_hash": "abc",
                        "embedding_model": "text-embedding-3-small",
                        "document_schema_version": "1",
                    },
                )
            ],
        )
        documents = load_documents(settings.sqlite_path)[:1]
        with pytest.raises(IncompatibleCollectionError):
            execute_index(settings, documents, mode="mock", provider=MockEmbeddingProvider(), store=store)
        assert store.count(unit_collection) == 1
    finally:
        store.close()


@pytest.fixture
def unit_collection():
    store = QdrantStore("http://127.0.0.1:6333")
    try:
        store.delete_unit_test_collection(UNIT_COLLECTION)
        yield UNIT_COLLECTION
    finally:
        store.delete_unit_test_collection(UNIT_COLLECTION)
        store.close()


class _ExplodingProvider:
    def __init__(self, model_name=MOCK_EMBEDDING_MODEL, semantic=False):
        self.model_name = model_name
        self.dimension = 1536
        self.semantic = semantic
        self.calls = 0

    def embed_texts(self, texts):
        self.calls += 1
        raise AssertionError("embedding provider was called")


class _FailProvider:
    model_name = MOCK_EMBEDDING_MODEL
    dimension = 1536
    semantic = False

    def embed_texts(self, texts):
        raise EmbeddingError("forced failure")


class _CountingMock(MockEmbeddingProvider):
    def __init__(self):
        self.calls = 0

    def embed_texts(self, texts):
        self.calls += 1
        return super().embed_texts(texts)


class _ExplodingStore:
    def __init__(self):
        self.upserts = 0
        self.created = False

    def snapshot(self, name):
        return CollectionSnapshot(name, False, None, None, ())

    def ensure_compatible(self, spec):
        raise AssertionError("dry-run created a collection")

    def list_points(self, name):
        return []

    def upsert(self, name, points):
        self.upserts += len(points)
        raise AssertionError("dry-run uploaded vectors")

    def count(self, name):
        raise AssertionError("dry-run counted a write")


class _MemoryStore:
    def __init__(self, snapshot: CollectionSnapshot):
        self.snapshot_value = snapshot
        self.upserts = []
        self.deleted = False

    @classmethod
    def empty(cls, name: str) -> "_MemoryStore":
        return cls(CollectionSnapshot(name, False, None, None, ()))

    @classmethod
    def with_points(cls, name: str, points: list[ExistingPoint]) -> "_MemoryStore":
        return cls(CollectionSnapshot(name, True, 1536, "cosine", tuple(points)))

    def snapshot(self, name):
        return self.snapshot_value

    def ensure_compatible(self, spec):
        validate_snapshot(self.snapshot_value, spec)
        if not self.snapshot_value.exists:
            self.snapshot_value = CollectionSnapshot(spec.name, True, spec.dimension, spec.distance, ())
            return True
        return False

    def list_points(self, name):
        points = list(self.snapshot_value.points)
        for point in self.upserts:
            payload = point.payload
            points.append(
                ExistingPoint(
                    point_id=str(point.id),
                    process_id=payload["process_id"],
                    text_hash=payload["text_hash"],
                    embedding_model=payload["embedding_model"],
                    document_schema_version=payload["document_schema_version"],
                )
            )
        return points

    def upsert(self, name, points):
        self.upserts.extend(points)

    def count(self, name):
        return len({item.point_id for item in self.list_points(name)})
