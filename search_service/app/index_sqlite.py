"""Index SQLite process documents into Qdrant.

Dry-run writes nothing and does not call OpenAI.
Mock mode writes only the mock collection.
Real mode requires --execute-real and is not run by tests.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict, dataclass, field

from .config import (
    BGE_COLLECTION,
    BGE_MODEL,
    MOCK_EMBEDDING_MODEL,
    OPENAI_MODEL,
    REAL_COLLECTION,
    Settings,
    load_settings,
)
from .documents import SearchDocument, load_documents
from .embeddings import (
    EmbeddingError,
    LocalBgeM3Provider,
    MockEmbeddingProvider,
    OpenAIEmbeddingProvider,
    _bge_cache_dir,
    planned_bge_runtime,
)
from .qdrant_store import (
    CollectionSpec,
    ExistingPoint,
    IncompatibleCollectionError,
    QdrantStore,
    VectorPoint,
    validate_snapshot,
)

LOGGER = logging.getLogger("search_service.index")


class AuthorizationError(RuntimeError):
    """Real embedding mode was requested without explicit authorization."""


@dataclass
class IndexReport:
    mode: str
    dry_run: bool
    collection: str
    embedding_model: str
    vectors_are_semantic: bool
    document_schema_version: str
    sqlite_file: str
    documents: int
    unique_process_ids: int
    new: int = 0
    changed: int = 0
    unchanged: int = 0
    embedded: int = 0
    upserted: int = 0
    created_collection: bool = False
    point_count: int | None = None
    model_revision: str = ""
    embedding_provider: str = ""
    device: str = ""
    stale_process_ids: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def execute_index(
    settings: Settings,
    documents: list[SearchDocument],
    mode: str,
    dry_run: bool = False,
    execute_real: bool = False,
    execute_local: bool = False,
    batch_size: int | None = None,
    store: QdrantStore | None = None,
    provider=None,
) -> IndexReport:
    if mode not in {"mock", "real", "local-bge-m3"}:
        raise ValueError("mode must be mock, real, or local-bge-m3")
    _guard_mode(settings, mode, dry_run, execute_real, execute_local)
    _validate_documents(documents)
    if batch_size is None:
        batch_size = settings.bge_batch_size if mode == "local-bge-m3" else settings.batch_size
    if provider is None:
        provider = _provider_for(settings, mode, construct=not dry_run)
    if hasattr(provider, "prepare"):
        provider.prepare()
    collection = settings.collection_for(mode)
    _guard_collection_name(collection, mode, provider.model_name)
    report = IndexReport(
        mode=mode,
        dry_run=dry_run,
        collection=collection,
        embedding_model=provider.model_name,
        vectors_are_semantic=bool(getattr(provider, "semantic", mode == "real")),
        document_schema_version=settings.document_schema_version,
        sqlite_file=settings.sqlite_path.name,
        documents=len(documents),
        unique_process_ids=len({item.process_id for item in documents}),
        model_revision=getattr(provider, "model_revision", "") or "",
        embedding_provider=getattr(provider, "provider_id", "") or "",
        device=getattr(provider, "device", "") or "",
    )
    spec = CollectionSpec(
        name=collection,
        embedding_model=provider.model_name,
        schema_version=settings.document_schema_version,
        dimension=provider.dimension,
        semantic=report.vectors_are_semantic,
        model_revision=report.model_revision,
        embedding_provider=report.embedding_provider,
    )
    if store is None and not dry_run:
        store = QdrantStore(settings.qdrant_url)
    existing: list[ExistingPoint] = []
    if store is not None:
        snapshot = store.snapshot(collection)
        if dry_run:
            validate_snapshot(snapshot, spec) if snapshot.exists else None
            existing = list(snapshot.points)
        else:
            report.created_collection = store.ensure_compatible(spec)
            existing = store.list_points(collection) if not report.created_collection else []
    current_ids = {item.process_id for item in documents}
    by_process: dict[str, list[ExistingPoint]] = {}
    for point in existing:
        by_process.setdefault(point.process_id, []).append(point)
    report.stale_process_ids = sorted(process_id for process_id in by_process if process_id and process_id not in current_ids)
    pending: list[SearchDocument] = []
    for document in documents:
        matches = [
            point
            for point in by_process.get(document.process_id, [])
            if _same_point(point, document, provider, settings.document_schema_version)
        ]
        if matches:
            report.unchanged += 1
        elif by_process.get(document.process_id):
            report.changed += 1
            pending.append(document)
        else:
            report.new += 1
            pending.append(document)
    if dry_run:
        LOGGER.info("dry-run complete for %s documents; no collection write and no embedding call", len(documents))
        return report
    if store is None:
        raise RuntimeError("a Qdrant store is required when dry_run is false")
    for start in range(0, len(pending), batch_size):
        batch = pending[start : start + batch_size]
        vectors = provider.embed_texts([item.text for item in batch])
        points = [
            VectorPoint(
                id=item.point_id,
                vector=vector,
                payload=item.point_payload(
                provider.model_name,
                settings.document_schema_version,
                extra=_provider_metadata(provider),
            ),
            )
            for item, vector in zip(batch, vectors, strict=True)
        ]
        store.upsert(collection, points)
        report.embedded += len(batch)
        report.upserted += len(points)
    report.device = getattr(provider, "device", "") or report.device
    report.point_count = store.count(collection)
    stored = store.list_points(collection)
    for document in documents:
        if not any(_same_point(point, document, provider, settings.document_schema_version) for point in stored):
            report.errors.append(f"missing indexed point for {document.process_id}")
    if report.errors:
        raise RuntimeError("; ".join(report.errors))
    return report


def _same_point(point: ExistingPoint, document: SearchDocument, provider, schema_version: str) -> bool:
    if not (
        point.point_id == document.point_id
        and point.process_id == document.process_id
        and point.text_hash == document.text_hash
        and point.embedding_model == provider.model_name
        and point.document_schema_version == schema_version
    ):
        return False
    revision = getattr(provider, "model_revision", "") or ""
    if revision and point.model_revision != revision:
        return False
    provider_id = getattr(provider, "provider_id", "") or ""
    if provider_id and point.embedding_provider != provider_id:
        return False
    if point.vector_dimension and str(point.vector_dimension) != str(provider.dimension):
        return False
    return True


def _provider_metadata(provider) -> dict | None:
    provider_id = getattr(provider, "provider_id", "") or ""
    revision = getattr(provider, "model_revision", "") or ""
    if not provider_id and not revision:
        return None
    return {
        "embedding_provider": provider_id,
        "model_revision": revision,
        "vector_dimension": int(provider.dimension),
    }


def _guard_mode(settings: Settings, mode: str, dry_run: bool, execute_real: bool, execute_local: bool) -> None:
    if mode == "real" and not dry_run and not execute_real:
        raise AuthorizationError("real mode requires --execute-real")
    if mode == "real" and not dry_run and not settings.api_key_configured:
        raise AuthorizationError("real mode requires OPENAI_API_KEY")
    if mode == "local-bge-m3" and not dry_run and not execute_local:
        raise AuthorizationError("local BGE-M3 indexing requires --execute-local")
    names = {settings.qdrant_collection, settings.qdrant_mock_collection, settings.qdrant_bge_collection}
    if len(names) < 3:
        raise IncompatibleCollectionError("mock, OpenAI, and BGE collections must use different names")


def _guard_collection_name(collection: str, mode: str, model_name: str) -> None:
    protected = {REAL_COLLECTION, BGE_COLLECTION}
    if mode == "mock" and (collection in protected or model_name in {OPENAI_MODEL, BGE_MODEL}):
        raise IncompatibleCollectionError("mock embeddings cannot be written to a semantic collection or stored as another model")
    if mode == "real" and (collection != REAL_COLLECTION or model_name != OPENAI_MODEL):
        raise IncompatibleCollectionError("real embeddings can be written only to crop_process with text-embedding-3-small")
    if mode == "local-bge-m3" and (collection in {REAL_COLLECTION, "crop_process_mock"} or model_name != BGE_MODEL):
        raise IncompatibleCollectionError("BGE-M3 embeddings cannot be written to the mock or OpenAI collection")
    if model_name == MOCK_EMBEDDING_MODEL and collection in protected:
        raise IncompatibleCollectionError("refusing to mix mock vectors into a semantic collection")
    if model_name == BGE_MODEL and collection in {REAL_COLLECTION, "crop_process_mock"}:
        raise IncompatibleCollectionError("refusing to mix BGE-M3 vectors into another collection")


class _DryRunModel:
    """Names the model a dry-run would use without calling a provider."""

    semantic: bool

    def __init__(
        self,
        model_name: str,
        dimension: int,
        semantic: bool,
        provider_id: str = "",
        model_revision: str = "",
        device: str = "",
    ):
        self.model_name = model_name
        self.dimension = dimension
        self.semantic = semantic
        self.provider_id = provider_id
        self.model_revision = model_revision
        self.device = device

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        raise EmbeddingError("dry-run does not generate embeddings")


def _provider_for(settings: Settings, mode: str, construct: bool):
    if mode == "mock":
        return MockEmbeddingProvider()
    if mode == "local-bge-m3":
        if not construct:
            revision, device, _backend = planned_bge_runtime(_bge_cache_dir(), settings.bge_revision, settings.bge_device)
            return _DryRunModel(settings.bge_model, settings.bge_dimension, True, "local-bge-m3", revision, device)
        return LocalBgeM3Provider(
            model_name=settings.bge_model,
            revision=settings.bge_revision,
            dimension=settings.bge_dimension,
            batch_size=settings.bge_batch_size,
            device=settings.bge_device,
        )
    if not construct:
        return _DryRunModel(settings.openai_model, settings.embedding_dimension, True)
    return OpenAIEmbeddingProvider(
        api_key=settings.openai_api_key,
        model=settings.openai_model,
        dimension=settings.embedding_dimension,
    )


def _validate_documents(documents: list[SearchDocument]) -> None:
    ids = [item.process_id for item in documents]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate process_id in documents")
    point_ids = [item.point_id for item in documents]
    if len(point_ids) != len(set(point_ids)):
        raise ValueError("duplicate point_id in documents")
    if any(not item.text or not item.text_hash for item in documents):
        raise ValueError("document text or hash is empty")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Index S1-G14 process documents into Qdrant.")
    parser.add_argument("--mode", choices=["dry-run", "mock", "real", "local-bge-m3"], default="dry-run")
    parser.add_argument("--dry-run", action="store_true", help="Report the index plan without embedding or writing.")
    parser.add_argument("--execute-real", action="store_true", help="Required before real OpenAI indexing.")
    parser.add_argument("--execute-local", action="store_true", help="Required before local BGE-M3 indexing.")
    parser.add_argument("--batch-size", type=int, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    args = build_parser().parse_args(argv)
    settings = load_settings()
    if args.mode == "dry-run":
        mode = "mock"
        dry_run = True
    elif args.mode == "local-bge-m3":
        mode = "local-bge-m3"
        dry_run = args.dry_run or not args.execute_local
    else:
        mode = args.mode
        dry_run = args.dry_run
    try:
        documents = load_documents(settings.sqlite_path)
        report = execute_index(
            settings,
            documents,
            mode=mode,
            dry_run=dry_run,
            execute_real=args.execute_real,
            execute_local=args.execute_local,
            batch_size=args.batch_size,
            store=QdrantStore(settings.qdrant_url),
        )
    except (AuthorizationError, IncompatibleCollectionError, EmbeddingError, ValueError, RuntimeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    except Exception as exc:
        LOGGER.exception("indexing failed")
        print(json.dumps({"ok": False, "error": type(exc).__name__}, ensure_ascii=False))
        return 1
    print(json.dumps({"ok": True, **report.to_dict()}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
