"""Compare SQLite plus Qdrant with the disposable PostgreSQL database. No report is overwritten."""

from __future__ import annotations

import json
import math
import os
from dataclasses import replace
from pathlib import Path

from app.adapters import DictionarySearchAdapter
from app.config import BGE_COLLECTION, BGE_MODEL, load_settings
from app.dictionary_postgres import PostgresDictionaryAdapter
from app.eligibility import eligible_process_ids
from app.embeddings import ONNX_MODEL_REVISION, LocalBgeM3Provider
from app.hybrid_planner import NumericCondition
from app.hybrid_search import HybridSearch
from app.pgvector_store import PgvectorStore
from app.postgres_provider import PostgresDataProvider
from app.qdrant_store import QdrantRequestError, QdrantStore
from app.schemas import HybridSearchRequest, SearchRequest
from app.search import SearchService
from scripts.onnx_stage import stage_approved_snapshot
from scripts.pg_local_common import connect_migration, redact

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "artifacts" / "deploy01c" / "parity.json"
SAVED = ROOT / "evaluation" / "reports" / "evaluation.json"
SCORE_LIMIT = 1e-5
FOCUS = (
    "ผลผลิตมันสำปะหลังภาคเหนือปี 2566",
    "maize production in central Thailand 2022",
    "ข้าวนาปรังปี 2565",
    "มันสำปะหลังและข้าวโพด",
    "ผลผลิตมากกว่า 1000000 ตัน",
    "มันสำปะหลังภาคใต้ปี 2566",
    "carbon footprint of rice production",
)


def main() -> None:
    stage_approved_snapshot()
    local_settings = load_settings()
    embedder = LocalBgeM3Provider(
        model_name=local_settings.bge_model,
        revision=local_settings.bge_revision,
        dimension=local_settings.bge_dimension,
        batch_size=1,
        device="cpu",
        backend="onnx",
    )
    relational = PostgresDataProvider("postgresql://local-test", connect=connect_migration)
    local = SearchService(local_settings, embedder, QdrantStore(local_settings.qdrant_url))
    cloud_settings = replace(local_settings, data_backend="postgres", vector_backend="pgvector", database_url="postgresql://local-test")
    cloud = SearchService(cloud_settings, embedder, PgvectorStore(relational), relational=relational)
    local.start()
    cloud.started = local.started
    cloud.model_error = local.model_error
    dictionary_path = Path(os.environ["DICTIONARY_SCRIPT"])
    sqlite_path = Path(os.environ["SQLITE_PATH"])
    local_dictionary = DictionarySearchAdapter(db_path=sqlite_path, script_path=dictionary_path)
    cloud_dictionary = PostgresDictionaryAdapter("postgresql://local-test", provider=relational, script_path=dictionary_path)
    queries = _queries()
    comparisons = [_compare(query, local, cloud, local_dictionary, cloud_dictionary) for query in queries]
    report = {
        "queries": len(comparisons),
        "focus": [row for row in comparisons if row["query"] in FOCUS],
        "rank_differences": [row for row in comparisons if row["rank_differences"]],
        "score_violations": [row for row in comparisons if row["score_violations"]],
        "quantity_differences": [row for row in comparisons if row["quantity_differences"]],
        "availability_differences": [row for row in comparisons if row["availability_differences"]],
        "failures": [row for row in comparisons if row["failures"]],
        "controls": _controls(embedder, relational, cloud.store),
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({key: report[key] if key == "controls" else len(report[key]) for key in report}, indent=2, ensure_ascii=False))


def _queries() -> list[dict]:
    saved = json.loads(SAVED.read_text(encoding="utf-8"))
    rows = saved["backends"]["dictionary"]["queries"]
    return [{"query_id": row["query_id"], "query": row["query"]} for row in rows]


def _compare(query, local, cloud, local_dictionary, cloud_dictionary) -> dict:
    item = {"query_id": query["query_id"], "query": query["query"], "modes": {}, "rank_differences": [], "score_violations": [], "quantity_differences": [], "availability_differences": [], "failures": []}
    runners = {
        "dictionary": lambda: (local_dictionary.search(query["query"], top_k=5), cloud_dictionary.search(query["query"], top_k=5)),
        "semantic": lambda: (local.search(SearchRequest(query=query["query"], top_k=5)), cloud.search(SearchRequest(query=query["query"], top_k=5))),
        "hybrid": lambda: (HybridSearch(local).search(HybridSearchRequest(query=query["query"], top_k=5)), HybridSearch(cloud).search(HybridSearchRequest(query=query["query"], top_k=5))),
    }
    for mode, run in runners.items():
        try:
            left, right = run()
        except Exception as exc:
            item["failures"].append({"mode": mode, "error": type(exc).__name__})
            continue
        packed_left = _pack(left)
        packed_right = _pack(right)
        item["modes"][mode] = {"sqlite_qdrant": packed_left, "postgres_pgvector": packed_right}
        if [row["process_id"] for row in packed_left["rows"]] != [row["process_id"] for row in packed_right["rows"]]:
            item["rank_differences"].append(mode)
        for source, found in zip(packed_left["rows"], packed_right["rows"]):
            if source["process_id"] != found["process_id"]:
                continue
            if source["quantity"] != found["quantity"] or source["unit"] != found["unit"]:
                item["quantity_differences"].append(mode)
            if source["score"] is not None and found["score"] is not None and abs(source["score"] - found["score"]) > SCORE_LIMIT:
                item["score_violations"].append({"mode": mode, "process_id": source["process_id"], "difference": abs(source["score"] - found["score"])})
        if packed_left["availability"] != packed_right["availability"] or packed_left["unavailable"] != packed_right["unavailable"]:
            item["availability_differences"].append(mode)
    return item


def _pack(body: dict) -> dict:
    rows = []
    for row in body.get("results") or []:
        rows.append(
            {
                "process_id": row.get("process_id"),
                "quantity": row.get("production_quantity"),
                "unit": row.get("production_unit"),
                "score": row.get("similarity_score"),
            }
        )
    return {
        "count": body.get("count"),
        "availability": body.get("availability_status"),
        "unavailable": body.get("unavailable_measures"),
        "eligible_count": body.get("eligible_count"),
        "error": (body.get("error") or {}).get("code") if isinstance(body.get("error"), dict) else None,
        "rows": rows,
    }


def _controls(embedder, relational, store) -> dict:
    vector = embedder.embed_query("cassava production")
    with connect_migration() as connection:
        rows = connection.execute(
            """
            SELECT process_id, (embedding <=> %s::vector) AS cosine_distance
            FROM process_embeddings
            ORDER BY embedding <=> %s::vector, process_id
            """,
            (_literal(vector), _literal(vector)),
        ).fetchall()
        ordered = [(row[0], float(row[1])) for row in rows]
        ties = sum(1 for left, right in zip(ordered, ordered[1:]) if left[1] == right[1] and left[0] > right[0])
        numeric_pg = relational.eligible_process_ids(connection, numeric=(NumericCondition("production", "gt", 1_000_000, "t", True),))
    from app.database import connect_readonly

    sqlite = connect_readonly(Path(os.environ["SQLITE_PATH"]))
    try:
        numeric_sqlite = eligible_process_ids(sqlite, numeric=(NumericCondition("production", "gt", 1_000_000, "t", True),))
    finally:
        sqlite.close()
    empty = store.search_points(BGE_COLLECTION, vector, 5, {"must": [{"key": "process_id", "match": {"any": []}}]})
    bad_dimension = _raises(lambda: store.search_points(BGE_COLLECTION, [0.0] * 1023, 5, None))
    bad_value = _raises(lambda: store.search_points(BGE_COLLECTION, [math.nan] * 1024, 5, None))
    sample = store.sample_payload(BGE_COLLECTION)
    return {
        "top_k_process_ids": [row[0] for row in ordered[:5]],
        "tie_order_violations": ties,
        "numeric_eligible_match": numeric_pg == numeric_sqlite,
        "numeric_eligible_count": len(numeric_pg),
        "empty_candidate_count": len(empty),
        "bad_dimension_rejected": bad_dimension,
        "nonfinite_rejected": bad_value,
        "model_revision": None if sample is None else sample.get("model_revision"),
        "revision_matches": sample is not None and sample.get("model_revision") == ONNX_MODEL_REVISION,
        "model": BGE_MODEL,
    }


def _raises(call) -> bool:
    try:
        call()
    except QdrantRequestError:
        return True
    return False


def _literal(vector: list[float]) -> str:
    return "[" + ",".join(repr(float(value)) for value in vector) + "]"


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        raise SystemExit(redact(str(exc))) from None
