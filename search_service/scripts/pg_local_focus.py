"""Run the demonstration queries that are outside the saved 61-query file."""

from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path

from app.adapters import DictionarySearchAdapter
from app.config import load_settings
from app.dictionary_postgres import PostgresDictionaryAdapter
from app.embeddings import LocalBgeM3Provider
from app.hybrid_search import HybridSearch
from app.pgvector_store import PgvectorStore
from app.postgres_provider import PostgresDataProvider
from app.qdrant_store import QdrantStore
from app.schemas import HybridSearchRequest, SearchRequest
from app.search import SearchService
from scripts.onnx_stage import stage_approved_snapshot
from scripts.pg_local_common import connect_migration, redact
from scripts.pg_local_parity import _compare

QUERIES = (
    {"query_id": "DEMO-MAIZE", "query": "maize production in central Thailand 2022"},
    {"query_id": "DEMO-DRY-RICE", "query": "ข้าวนาปรังปี 2565"},
    {"query_id": "DEMO-THRESHOLD", "query": "ผลผลิตมากกว่า 1000000 ตัน"},
    {"query_id": "DEMO-CARBON", "query": "carbon footprint of rice production"},
)
REPORT = Path(__file__).resolve().parents[1] / "artifacts" / "deploy01c" / "focus.json"


def main() -> None:
    stage_approved_snapshot()
    settings = load_settings()
    embedder = LocalBgeM3Provider(
        model_name=settings.bge_model,
        revision=settings.bge_revision,
        dimension=settings.bge_dimension,
        batch_size=1,
        device="cpu",
        backend="onnx",
    )
    relational = PostgresDataProvider("postgresql://local-test", connect=connect_migration)
    local = SearchService(settings, embedder, QdrantStore(settings.qdrant_url))
    cloud = SearchService(
        replace(settings, data_backend="postgres", vector_backend="pgvector", database_url="postgresql://local-test"),
        embedder,
        PgvectorStore(relational),
        relational=relational,
    )
    local.start()
    cloud.started = local.started
    cloud.model_error = local.model_error
    script = Path(os.environ["DICTIONARY_SCRIPT"])
    sqlite_path = Path(os.environ["SQLITE_PATH"])
    rows = [
        _compare(
            query,
            local,
            cloud,
            DictionarySearchAdapter(db_path=sqlite_path, script_path=script),
            PostgresDictionaryAdapter("postgresql://local-test", provider=relational, script_path=script),
        )
        for query in QUERIES
    ]
    REPORT.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps([
        {
            "id": row["query_id"],
            "ranks": row["rank_differences"],
            "scores": row["score_violations"],
            "quantities": row["quantity_differences"],
            "availability": row["availability_differences"],
            "failures": row["failures"],
            "semantic": [item["process_id"] for item in row["modes"]["semantic"]["sqlite_qdrant"]["rows"]],
            "semantic_score": [item["score"] for item in row["modes"]["semantic"]["sqlite_qdrant"]["rows"][:1]],
            "pg_score": [item["score"] for item in row["modes"]["semantic"]["postgres_pgvector"]["rows"][:1]],
            "quantity": [item["quantity"] for item in row["modes"]["semantic"]["sqlite_qdrant"]["rows"][:1]],
            "unavailable": row["modes"]["semantic"]["sqlite_qdrant"]["unavailable"],
        }
        for row in rows
    ], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        raise SystemExit(redact(str(exc))) from None
