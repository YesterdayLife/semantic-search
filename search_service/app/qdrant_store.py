"""Qdrant collection guards and upserts over the local HTTP API.

The official Python client imports a gRPC extension that this machine's
application control policy blocks. Port 6333 is the HTTP API, so indexing
uses that interface directly. This module does not delete project collections.
Stale points are reported by the indexer and left in place.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from .config import EMBEDDING_DIMENSION

UNIT_TEST_COLLECTION = "crop_process_unit_test"


class IncompatibleCollectionError(RuntimeError):
    """The collection exists with a configuration this pipeline must not overwrite."""


class QdrantRequestError(RuntimeError):
    """Qdrant returned an error. The message does not include vectors or secrets."""


@dataclass(frozen=True)
class ExistingPoint:
    point_id: str
    process_id: str
    text_hash: str
    embedding_model: str
    document_schema_version: str
    embedding_provider: str = ""
    model_revision: str = ""
    vector_dimension: str = ""


@dataclass(frozen=True)
class CollectionSnapshot:
    name: str
    exists: bool
    size: int | None
    distance: str | None
    points: tuple[ExistingPoint, ...]


@dataclass(frozen=True)
class CollectionSpec:
    name: str
    embedding_model: str
    schema_version: str
    dimension: int = EMBEDDING_DIMENSION
    distance: str = "cosine"
    semantic: bool = False
    model_revision: str = ""
    embedding_provider: str = ""


@dataclass(frozen=True)
class VectorPoint:
    id: str
    vector: list[float]
    payload: dict


@dataclass(frozen=True)
class ScoredPoint:
    point_id: str
    score: float
    process_id: str
    payload: dict


@dataclass(frozen=True)
class CollectionStatus:
    exists: bool
    size: int | None
    distance: str | None
    points: int | None


PAYLOAD_INDEXES = {
    "process_id": "keyword",
    "crop_id": "keyword",
    "season": "keyword",
    "spatial_level": "keyword",
    "region_code": "keyword",
    "source_id": "keyword",
    "year_ce": "integer",
}


def validate_snapshot(snapshot: CollectionSnapshot, spec: CollectionSpec) -> None:
    """Reject a collection that cannot safely receive this embedding model."""
    if not snapshot.exists:
        return
    if snapshot.size != spec.dimension or snapshot.distance != spec.distance:
        raise IncompatibleCollectionError(
            f"{snapshot.name} uses size={snapshot.size} distance={snapshot.distance}; "
            f"expected size={spec.dimension} distance={spec.distance}"
        )
    models = {point.embedding_model for point in snapshot.points}
    schemas = {point.document_schema_version for point in snapshot.points}
    if not models and not schemas:
        return
    if models != {spec.embedding_model} or schemas != {spec.schema_version}:
        raise IncompatibleCollectionError(
            f"{snapshot.name} already stores embedding_model={sorted(models)} "
            f"schema={sorted(schemas)}; refusing to mix configurations"
        )
    if spec.model_revision:
        revisions = {point.model_revision for point in snapshot.points}
        if revisions != {spec.model_revision}:
            raise IncompatibleCollectionError(
                f"{snapshot.name} model_revision={sorted(revisions)}; expected {spec.model_revision}"
            )
    if spec.embedding_provider:
        providers = {point.embedding_provider for point in snapshot.points}
        if providers != {spec.embedding_provider}:
            raise IncompatibleCollectionError(
                f"{snapshot.name} embedding_provider={sorted(providers)}; expected {spec.embedding_provider}"
            )


class QdrantStore:
    def __init__(self, url: str, timeout: float = 30.0):
        self.url = url.rstrip("/")
        self.client = httpx.Client(base_url=self.url, timeout=timeout)

    def close(self) -> None:
        self.client.close()

    def collection_exists(self, name: str) -> bool:
        response = self.client.get(f"/collections/{name}")
        if response.status_code == 404:
            return False
        if response.status_code >= 400:
            _raise_for_status("GET", f"/collections/{name}", response)
        return True

    def snapshot(self, name: str) -> CollectionSnapshot:
        if not self.collection_exists(name):
            return CollectionSnapshot(name, False, None, None, ())
        info = self._json("GET", f"/collections/{name}")
        size, distance = _vector_config(info)
        return CollectionSnapshot(name, True, size, distance, tuple(self.list_points(name)))

    def ensure_compatible(self, spec: CollectionSpec) -> bool:
        """Create the collection when missing. Return True when this call created it."""
        snapshot = self.snapshot(spec.name)
        if not snapshot.exists:
            self._json(
                "PUT",
                f"/collections/{spec.name}",
                {"vectors": {"size": spec.dimension, "distance": "Cosine"}},
            )
            self.ensure_payload_indexes(spec.name)
            return True
        validate_snapshot(snapshot, spec)
        self.ensure_payload_indexes(spec.name)
        return False

    def ensure_payload_indexes(self, name: str) -> None:
        for field, schema in PAYLOAD_INDEXES.items():
            response = self.client.put(
                f"/collections/{name}/index",
                params={"wait": "true"},
                json={"field_name": field, "field_schema": schema},
            )
            if response.status_code < 400:
                continue
            message = response.text.lower()
            if response.status_code in {400, 409} and ("already exists" in message or "already created" in message):
                continue
            _raise_for_status("PUT", f"/collections/{name}/index", response)

    def list_points(self, name: str) -> list[ExistingPoint]:
        if not self.collection_exists(name):
            return []
        points: list[ExistingPoint] = []
        offset = None
        while True:
            body: dict = {"limit": 128, "with_payload": True, "with_vector": False}
            if offset is not None:
                body["offset"] = offset
            result = self._json("POST", f"/collections/{name}/points/scroll", body)["result"]
            for point in result.get("points", []):
                payload = point.get("payload") or {}
                points.append(
                    ExistingPoint(
                        point_id=str(point.get("id")),
                        process_id=str(payload.get("process_id") or ""),
                        text_hash=str(payload.get("text_hash") or ""),
                        embedding_model=str(payload.get("embedding_model") or ""),
                        document_schema_version=str(payload.get("document_schema_version") or ""),
                        embedding_provider=str(payload.get("embedding_provider") or ""),
                        model_revision=str(payload.get("model_revision") or ""),
                        vector_dimension=str(payload.get("vector_dimension") or ""),
                    )
                )
            offset = result.get("next_page_offset")
            if offset is None:
                break
        return points

    def upsert(self, name: str, points: list[VectorPoint]) -> None:
        if not points:
            return
        self._json(
            "PUT",
            f"/collections/{name}/points",
            {"points": [{"id": point.id, "vector": point.vector, "payload": point.payload} for point in points]},
            params={"wait": "true"},
        )

    def count(self, name: str) -> int:
        result = self._json("POST", f"/collections/{name}/points/count", {"exact": True})
        return int(result["result"]["count"])

    def collection_status(self, name: str) -> CollectionStatus:
        """Read collection configuration. This does not create or change the collection."""
        if not self.collection_exists(name):
            return CollectionStatus(False, None, None, None)
        info = self._json("GET", f"/collections/{name}")
        size, distance = _vector_config(info)
        return CollectionStatus(True, size, distance, self.count(name))

    def sample_payload(self, name: str) -> dict | None:
        if not self.collection_exists(name):
            return None
        result = self._json(
            "POST",
            f"/collections/{name}/points/scroll",
            {"limit": 1, "with_payload": True, "with_vector": False},
        )["result"]
        points = result.get("points") or []
        if not points:
            return None
        return dict(points[0].get("payload") or {})

    def search_points(self, name: str, vector: list[float], limit: int, query_filter: dict | None) -> list[ScoredPoint]:
        """Rank points in an existing collection. Payload filters are applied by Qdrant before ranking."""
        body: dict = {"vector": vector, "limit": limit, "with_payload": True, "with_vector": False}
        if query_filter:
            body["filter"] = query_filter
        result = self._json("POST", f"/collections/{name}/points/search", body)["result"]
        found: list[ScoredPoint] = []
        for point in result:
            payload = dict(point.get("payload") or {})
            found.append(
                ScoredPoint(
                    point_id=str(point.get("id")),
                    score=float(point.get("score")),
                    process_id=str(payload.get("process_id") or ""),
                    payload=payload,
                )
            )
        return found

    def delete_unit_test_collection(self, name: str) -> None:
        """Remove only the disposable unit-test collection."""
        if name != UNIT_TEST_COLLECTION:
            raise QdrantRequestError("refusing to delete a project collection")
        if not self.collection_exists(name):
            return
        self._json("DELETE", f"/collections/{name}")

    def _json(self, method: str, path: str, body: dict | None = None, params: dict | None = None) -> dict:
        response = self.client.request(method, path, json=body, params=params)
        if response.status_code >= 400:
            _raise_for_status(method, path, response)
        if not response.content:
            return {}
        return response.json()


def _raise_for_status(method: str, path: str, response: httpx.Response) -> None:
    detail = " ".join(response.text.split())[:240]
    raise QdrantRequestError(f"{method} {path} failed with {response.status_code}: {detail}")


def _vector_config(info: dict) -> tuple[int, str]:
    vectors = info["result"]["config"]["params"]["vectors"]
    if isinstance(vectors, dict) and "size" not in vectors:
        if len(vectors) != 1:
            raise IncompatibleCollectionError("named multi-vector collections are not supported")
        vectors = next(iter(vectors.values()))
    size = int(vectors["size"])
    distance = str(vectors["distance"]).split(".")[-1].lower()
    return size, distance
