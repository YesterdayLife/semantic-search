"""Local semantic search over the indexed BGE-M3 collection and SQLite facts."""

from __future__ import annotations

import math
import sqlite3
import threading
import time

import httpx

from .config import BGE_COLLECTION, BGE_MODEL, Settings, load_settings
from .database import DatabaseError, connect_readonly
from .embeddings import ONNX_MODEL_REVISION, EmbeddingError, LocalBgeM3Provider
from .qdrant_store import QdrantRequestError, QdrantStore, ScoredPoint
from .query_parser import FILTER_FIELDS, ParsedQuery, parse_query
from .records import Catalog, ProcessRecord, fetch_records, load_catalog
from .schemas import SearchRequest

# A successful metadata check is reused only inside this process.
# ready() always bypasses the cache. A Qdrant error or an incompatible
# collection clears it immediately. Restarting the API process clears it too.
COLLECTION_VALIDATION_TTL_SECONDS = 30.0

MEASURE_WARNINGS = {
    "fertilizer": "Validated fertilizer quantities are not in this dataset. Any listed records are production output only.",
    "carbon_footprint": "Validated carbon-footprint values are not in this dataset. Any listed records are production output only.",
    "energy": "Validated energy-input quantities are not in this dataset. Any listed records are production output only.",
    "water": "Validated water-consumption quantities are not in this dataset. Any listed records are production output only.",
}


class SearchFailure(Exception):
    """A search request failed with a client-safe message."""

    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def payload_filter(filters: dict) -> dict | None:
    """Build a Qdrant filter from indexed payload fields. Text is never interpolated."""
    must = []
    for key in FILTER_FIELDS:
        value = filters.get(key)
        if value is not None:
            must.append({"key": key, "match": {"value": value}})
    if not must:
        return None
    return {"must": must}


def build_service() -> SearchService:
    settings = load_settings()
    provider = LocalBgeM3Provider(
        model_name=settings.bge_model,
        revision=settings.bge_revision,
        dimension=settings.bge_dimension,
        batch_size=1,
        device="cpu",
        backend="onnx",
    )
    if settings.data_backend == "sqlite" and settings.vector_backend == "qdrant":
        return SearchService(settings, provider, QdrantStore(settings.qdrant_url))
    if settings.data_backend == "postgres" and settings.vector_backend == "pgvector":
        from .pgvector_store import PgvectorStore
        from .postgres_provider import PostgresDataProvider

        relational = PostgresDataProvider(settings.database_url)
        return SearchService(settings, provider, PgvectorStore(relational), relational=relational)
    raise ValueError("DATA_BACKEND and VECTOR_BACKEND combination is not supported")


class SearchService:
    """One process-wide ONNX model and read-only access to Qdrant and SQLite."""

    def __init__(self, settings: Settings, embedder, store, catalog: Catalog | None = None, records=None, relational=None):
        self.settings = settings
        self.embedder = embedder
        self.store = store
        self.relational = relational
        self.collection = BGE_COLLECTION
        self._catalog_override = catalog
        self._records = records
        self._embed_lock = threading.Lock()
        self._cache_lock = threading.Lock()
        self._collection_valid_until = 0.0
        self._validated_status = None
        self.started = False
        self.model_error: str | None = None

    def start(self) -> None:
        if self.started:
            return
        try:
            prepare = getattr(self.embedder, "prepare", None)
            if prepare is not None:
                prepare()
            self._require_embedder()
            probe = self.embedder.embed_query("พร้อม")
            if len(probe) != self.embedder.dimension or any(not math.isfinite(value) for value in probe):
                raise EmbeddingError("query embedding probe was not a finite 1024-dimensional vector")
        except EmbeddingError as exc:
            self.model_error = _safe_text(str(exc), "The local embedding model is not ready")
            self.started = False
            return
        self.model_error = None
        self.started = True

    def close(self) -> None:
        closer = getattr(self.store, "close", None)
        if closer is not None:
            closer()

    def ready(self) -> dict:
        self._require_model()
        self.ensure_compatible_collection(force=True)
        status = self._validated_status
        catalog = self._catalog()
        if catalog.process_count != status.points:
            raise SearchFailure(503, "sqlite_unavailable", "SQLite process catalog is not the indexed dataset")
        return {
            "status": "ready",
            "qdrant": "ok",
            "collection": self.collection,
            "vector_dimension": status.size,
            "distance": status.distance,
            "points": status.points,
            "embedding_model": BGE_MODEL,
            "model_revision": ONNX_MODEL_REVISION,
            "sqlite": "ok",
            "process_count": catalog.process_count,
            "embedding_runtime": getattr(self.embedder, "device", "onnx-cpu"),
            "search_engine": "local-bge-m3",
        }

    def search(self, request: SearchRequest) -> dict:
        started = time.perf_counter()
        catalog = self._catalog()
        explicit = request.effective_filters().model_dump()
        self._validate_explicit(explicit, catalog)
        parsed = parse_query(request.query, catalog.sources)
        effective, warnings = _merge_filters(parsed, explicit, catalog)
        unavailable = list(parsed.unavailable_measures)
        for measure in unavailable:
            warnings.append(MEASURE_WARNINGS[measure])
        self._require_model()
        embed_started = time.perf_counter()
        try:
            with self._embed_lock:
                vector = self.embedder.embed_query(request.query)
        except EmbeddingError as exc:
            raise SearchFailure(503, "model_unavailable", _safe_text(str(exc), "Query embedding failed")) from None
        embed_ms = _elapsed_ms(embed_started)
        if len(vector) != 1024 or any(not math.isfinite(value) for value in vector):
            raise SearchFailure(503, "model_unavailable", "Query embedding was not a finite 1024-dimensional vector")
        validation_ms = self.ensure_compatible_collection()
        query_filter = payload_filter(effective)
        qdrant_started = time.perf_counter()
        try:
            hits = self.store.search_points(self.collection, vector, request.top_k, query_filter)
        except (QdrantRequestError, httpx.HTTPError):
            raise SearchFailure(503, "qdrant_unavailable", "Qdrant is unavailable") from None
        qdrant_ms = _elapsed_ms(qdrant_started)
        ranked = sorted(hits, key=lambda hit: hit.score, reverse=True)
        sqlite_started = time.perf_counter()
        try:
            records = self._hydrate([hit.process_id for hit in ranked if hit.process_id])
        except DatabaseError:
            raise SearchFailure(503, "sqlite_unavailable", "SQLite is unavailable") from None
        sqlite_ms = _elapsed_ms(sqlite_started)
        results = []
        for hit in ranked:
            record = records.get(hit.process_id)
            if record is None:
                warnings.append("A ranked point had no SQLite record and was omitted.")
                continue
            if not _record_matches(record, effective):
                warnings.append("A ranked record did not satisfy the structured filters and was omitted.")
                continue
            quantity = record.production_quantity
            unit = record.production_unit
            flow = record.production_flow
            if record.quantity_conflict:
                warnings.append("A process had more than one output quantity, so that quantity was omitted.")
                quantity = None
                unit = None
                flow = None
            results.append(_result_payload(hit.score, record, quantity, unit, flow))
        return {
            "query": request.query,
            "parsed_filters": effective,
            "count": len(results),
            "results": results,
            "warnings": warnings,
            "unavailable_measures": unavailable,
            "search_engine": "local-bge-m3",
            "embedding_model": BGE_MODEL,
            "model_revision": ONNX_MODEL_REVISION,
            "timing_ms": {
                "embed": embed_ms,
                "collection_validation": validation_ms,
                "qdrant": qdrant_ms,
                "sqlite": sqlite_ms,
                "total": _elapsed_ms(started),
            },
        }

    def _require_model(self) -> None:
        if self.model_error or not self.started:
            raise SearchFailure(503, "model_unavailable", self.model_error or "The local embedding model is not ready")
        try:
            self._require_embedder()
        except EmbeddingError as exc:
            raise SearchFailure(503, "model_unavailable", _safe_text(str(exc), "The local embedding model is not ready")) from None

    def _require_embedder(self) -> None:
        if getattr(self.embedder, "model_name", None) != BGE_MODEL:
            raise EmbeddingError("query model does not match the indexed model")
        if getattr(self.embedder, "model_revision", None) != ONNX_MODEL_REVISION:
            raise EmbeddingError("query model revision does not match the indexed ONNX revision")
        if int(getattr(self.embedder, "dimension", 0)) != 1024:
            raise EmbeddingError("query model dimension does not match the indexed collection")
        if getattr(self.embedder, "provider_id", "") not in {"", "local-bge-m3"}:
            raise EmbeddingError("query provider does not match the indexed collection")

    def ensure_compatible_collection(self, *, force: bool = False) -> float:
        """Validate the BGE-M3 collection and return milliseconds spent on a live check.

        A successful check is reused for COLLECTION_VALIDATION_TTL_SECONDS (30s).
        The cache lives only in this process. It is cleared when the process
        restarts, when the TTL expires, when Qdrant cannot be read, and when
        the collection metadata is incompatible. ready() passes force=True, so
        a mismatch is still detected on the readiness endpoint. A cache hit
        returns 0.0 and does not call Qdrant. This cache is not used for
        ranking or similarity scores.
        """
        if not force and self._collection_cache_is_fresh():
            return 0.0
        started = time.perf_counter()
        try:
            status, sample = self._collection_view()
            self._require_collection(status, sample)
        except Exception:
            self._clear_collection_cache()
            raise
        with self._cache_lock:
            self._validated_status = status
            self._collection_valid_until = time.perf_counter() + COLLECTION_VALIDATION_TTL_SECONDS
        return _elapsed_ms(started)

    def _collection_cache_is_fresh(self) -> bool:
        with self._cache_lock:
            return time.perf_counter() < self._collection_valid_until and self._validated_status is not None

    def _clear_collection_cache(self) -> None:
        with self._cache_lock:
            self._collection_valid_until = 0.0
            self._validated_status = None

    def _collection_view(self):
        try:
            status = self.store.collection_status(self.collection)
            sample = self.store.sample_payload(self.collection)
        except (QdrantRequestError, httpx.HTTPError):
            raise SearchFailure(503, "qdrant_unavailable", "Qdrant is unavailable") from None
        return status, sample

    def _require_collection(self, status, sample: dict | None) -> None:
        if self.collection != BGE_COLLECTION:
            raise SearchFailure(503, "collection_incompatible", "Search is bound to the local BGE-M3 collection")
        if not status.exists:
            raise SearchFailure(503, "collection_unavailable", "The BGE-M3 collection is unavailable")
        if status.size != 1024 or status.distance != "cosine" or status.points != self._catalog().process_count:
            raise SearchFailure(503, "collection_incompatible", "The search collection vector configuration is incompatible")
        if not sample:
            raise SearchFailure(503, "collection_incompatible", "The search collection has no model metadata")
        if sample.get("embedding_model") != BGE_MODEL or sample.get("embedding_provider") != "local-bge-m3":
            raise SearchFailure(503, "collection_incompatible", "The search collection model metadata is incompatible")
        if sample.get("model_revision") != ONNX_MODEL_REVISION or str(sample.get("vector_dimension")) != "1024":
            raise SearchFailure(503, "collection_incompatible", "The search collection model revision is incompatible")

    def open_relational(self):
        """Open the configured read-only database. SQLite stays the default."""
        if self.relational is None:
            return connect_readonly(self.settings.sqlite_path)
        return self.relational.connect()

    def _catalog(self) -> Catalog:
        if self._catalog_override is not None:
            return self._catalog_override
        try:
            connection = self.open_relational()
            try:
                if self.relational is None:
                    return load_catalog(connection)
                return self.relational.load_catalog(connection)
            finally:
                connection.close()
        except (DatabaseError, sqlite3.Error):
            raise self._relational_failure() from None

    def embed_query_vector(self, text: str) -> list[float]:
        """Embed one query with the existing ONNX model. This does not embed documents."""
        self._require_model()
        try:
            with self._embed_lock:
                vector = self.embedder.embed_query(text)
        except EmbeddingError as exc:
            raise SearchFailure(503, "model_unavailable", _safe_text(str(exc), "Query embedding failed")) from None
        if len(vector) != 1024 or any(not math.isfinite(value) for value in vector):
            raise SearchFailure(503, "model_unavailable", "Query embedding was not a finite 1024-dimensional vector")
        return vector

    def rank_process_ids(self, vector: list[float], process_ids: list[str]) -> list[ScoredPoint]:
        """Rank only the supplied process ids. Qdrant applies that constraint before scoring."""
        if not process_ids:
            return []
        self.ensure_compatible_collection()
        return self.search_eligible_ids(vector, process_ids)

    def search_eligible_ids(self, vector: list[float], process_ids: list[str]) -> list[ScoredPoint]:
        """Vector-search the supplied ids. This does not read collection metadata."""
        if not process_ids:
            return []
        query_filter = {"must": [{"key": "process_id", "match": {"any": list(process_ids)}}]}
        try:
            return self.store.search_points(self.collection, vector, len(process_ids), query_filter)
        except (QdrantRequestError, httpx.HTTPError):
            raise SearchFailure(503, "qdrant_unavailable", "Qdrant is unavailable") from None

    def hydrate_records(self, process_ids: list[str]) -> dict[str, ProcessRecord]:
        return self._hydrate(process_ids)

    def _hydrate(self, process_ids: list[str]) -> dict[str, ProcessRecord]:
        if self._records is not None:
            return self._records.fetch(process_ids)
        try:
            connection = self.open_relational()
            try:
                if self.relational is None:
                    return fetch_records(connection, process_ids)
                return self.relational.fetch_records(connection, process_ids)
            finally:
                connection.close()
        except (DatabaseError, sqlite3.Error):
            raise self._relational_failure() from None

    def _relational_failure(self) -> SearchFailure:
        if self.relational is None:
            return SearchFailure(503, "sqlite_unavailable", "SQLite is unavailable")
        return SearchFailure(503, "postgres_unavailable", "PostgreSQL is unavailable")

    def _validate_explicit(self, filters: dict, catalog: Catalog) -> None:
        checks = (
            ("crop_id", catalog.crop_ids, "crop_id is not a crop in the database"),
            ("region_code", catalog.region_codes, "region_code is not a region in the database"),
            ("season", catalog.seasons, "season is not a season in the database"),
            ("spatial_level", catalog.spatial_levels, "spatial_level is not a spatial level in the database"),
            ("source_id", catalog.source_ids, "source_id is not a source in the database"),
        )
        for key, allowed, message in checks:
            value = filters.get(key)
            if value is not None and value not in allowed:
                raise SearchFailure(422, "invalid_filter", message)
        if filters.get("region_code") and filters.get("spatial_level") == "country":
            raise SearchFailure(422, "invalid_filter", "region_code cannot be combined with spatial_level country")


def _merge_filters(parsed: ParsedQuery, explicit: dict, catalog: Catalog) -> tuple[dict, list[str]]:
    effective = parsed.as_filters()
    warnings = list(parsed.warnings)
    allowed = {
        "crop_id": catalog.crop_ids,
        "region_code": catalog.region_codes,
        "season": catalog.seasons,
        "spatial_level": catalog.spatial_levels,
        "source_id": catalog.source_ids,
    }
    for key in FILTER_FIELDS:
        if key == "year_ce":
            continue
        value = effective.get(key)
        if value is not None and value not in allowed[key]:
            effective[key] = None
            warnings.append(f"The inferred {key} is not present in the database, so it was not applied.")
    for key, value in explicit.items():
        if value is None:
            continue
        inferred = effective.get(key)
        if inferred is not None and inferred != value:
            warnings.append(f"The explicit {key} filter overrides the value inferred from the query.")
        effective[key] = value
    if effective.get("spatial_level") == "country" and effective.get("region_code"):
        if explicit.get("region_code"):
            raise SearchFailure(422, "invalid_filter", "region_code cannot be combined with spatial_level country")
        effective["region_code"] = None
        warnings.append("A country-level filter cleared the inferred region.")
    return effective, warnings


def _record_matches(record: ProcessRecord, filters: dict) -> bool:
    pairs = (
        ("crop_id", record.crop_id),
        ("year_ce", record.year_ce),
        ("region_code", record.region_code),
        ("season", record.season),
        ("spatial_level", record.spatial_level),
        ("source_id", record.source_id),
    )
    return all(filters.get(key) is None or filters[key] == value for key, value in pairs)


def _result_payload(score: float, record: ProcessRecord, quantity, unit, flow) -> dict:
    return {
        "process_id": record.process_id,
        "similarity_score": score,
        "crop": {"crop_id": record.crop_id, "crop_name": record.crop_name},
        "year": {"year_ce": record.year_ce, "year_original": record.year_original, "calendar": record.calendar},
        "region": {
            "region_code": record.region_code,
            "region_name": record.region_name,
            "area": record.area,
        },
        "season": record.season,
        "spatial_level": record.spatial_level,
        "production_quantity": quantity,
        "production_unit": unit,
        "production_flow": flow,
        "source": {"source_id": record.source_id, "agency": record.agency, "title": record.title},
        "indicators": [
            {"metric_code": item.metric_code, "value": item.value, "unit": item.unit} for item in record.indicators
        ],
    }


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)


def _safe_text(text: str, fallback: str) -> str:
    if any(mark in text for mark in ("\\", ":/", "Traceback", ".py")):
        return fallback
    return text[:300]
