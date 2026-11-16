"""Read-only live API and SQLite fact check for final QA. Does not write vectors or SQL."""

from __future__ import annotations

import json
import time
from pathlib import Path

import httpx

from app.config import load_settings
from app.database import connect_readonly
from app.search import build_service

BASE = "http://127.0.0.1:8000"
OUT = Path(__file__).with_name("live_check.json")
QUERIES = [
    "ผลผลิตมันสำปะหลังภาคเหนือปี 2566",
    "maize production in central Thailand 2022",
    "ข้าวนาปรังปี 2565",
    "มันสำปะหลังและข้าวโพด",
    "ผลผลิตมากกว่า 1,000,000 ตัน",
    "มันสำปะหลังภาคใต้ปี 2566",
    "carbon footprint of rice production",
    "ปริมาณปุ๋ยที่ใช้ปลูกมันสำปะหลัง",
]


def elapsed(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)


def walk_strings(value, found: list[str]) -> None:
    if isinstance(value, str):
        lowered = value.lower()
        if "\\" in value or value.startswith("/") or "file:" in lowered or "traceback" in lowered or "hee_m3" in lowered or ".sqlite" in lowered:
            found.append(value[:180])
    elif isinstance(value, dict):
        for item in value.values():
            walk_strings(item, found)
    elif isinstance(value, list):
        for item in value:
            walk_strings(item, found)


def call(client: httpx.Client, method: str, path: str, body: dict | None = None) -> dict:
    started = time.perf_counter()
    response = client.request(method, BASE + path, json=body)
    text = response.text
    try:
        payload = response.json()
    except json.JSONDecodeError:
        payload = {"_raw": text[:500]}
    leaks = []
    walk_strings(payload, leaks)
    return {
        "status": response.status_code,
        "ms": elapsed(started),
        "payload": payload,
        "leaks": leaks,
        "traceback": "Traceback" in text or "File \"" in text,
    }


def sqlite_row(connection, process_id: str) -> dict | None:
    rows = connection.execute(
        """
        SELECT p.process_id, p.crop_id, p.year_ce, p.region_code, p.season, p.spatial_level,
               e.quantity, e.unit
        FROM process AS p
        LEFT JOIN exchange AS e ON e.process_id = p.process_id AND e.direction = 'Output'
        WHERE p.process_id = ?
        """,
        (process_id,),
    ).fetchall()
    if not rows:
        return None
    first = rows[0]
    return {
        "process_id": first["process_id"],
        "crop_id": first["crop_id"],
        "year_ce": int(first["year_ce"]),
        "region_code": first["region_code"],
        "season": first["season"],
        "spatial_level": first["spatial_level"],
        "quantity": None if first["quantity"] is None or len(rows) != 1 else float(first["quantity"]),
        "unit": None if first["unit"] is None or len(rows) != 1 else first["unit"],
        "output_rows": len(rows),
    }


def summarize_hybrid(connection, payload: dict) -> dict:
    mismatches = []
    rows = []
    for item in payload.get("results") or []:
        fact = sqlite_row(connection, item["process_id"])
        match = fact is not None and fact["quantity"] == item["production_quantity"] and fact["unit"] == item["production_unit"] and fact["crop_id"] == item["crop"]["crop_id"]
        if not match:
            mismatches.append({"api": item["process_id"], "sqlite": fact, "api_quantity": item.get("production_quantity"), "api_unit": item.get("production_unit")})
        rows.append(
            {
                "process_id": item["process_id"],
                "crop_id": item["crop"]["crop_id"],
                "year_ce": item["year"]["year_ce"],
                "region_code": item["region"]["region_code"],
                "season": item["season"],
                "spatial_level": item["spatial_level"],
                "quantity": item["production_quantity"],
                "unit": item["production_unit"],
                "answers": item["answers_requested_measure"],
                "indicators": item["indicators"],
                "sqlite_match": match,
            }
        )
    intent = payload.get("parsed_intent") or {}
    return {
        "availability": payload.get("availability_status"),
        "count": payload.get("count"),
        "eligible_count": payload.get("eligible_count"),
        "embedding_skipped": payload.get("embedding_skipped"),
        "filters": payload.get("applied_filters"),
        "numeric": payload.get("applied_numeric"),
        "warnings": payload.get("warnings"),
        "measures": payload.get("requested_measure"),
        "crops": intent.get("crops"),
        "timing_ms": payload.get("timing_ms"),
        "rows": rows,
        "mismatches": mismatches,
        "context_count": len(payload.get("context_results") or []),
    }


def times(client: httpx.Client, method: str, path: str, body: dict, reps: int = 5) -> dict:
    samples = []
    for _ in range(reps):
        item = call(client, method, path, body)
        timing = (item["payload"] or {}).get("timing_ms")
        samples.append({"client_ms": item["ms"], "status": item["status"], "server": timing})
    return {"n": reps, "samples": samples}


def main() -> None:
    settings = load_settings()
    connection = connect_readonly(settings.sqlite_path)
    report: dict = {"sqlite_query_only": connection.execute("PRAGMA query_only").fetchone()[0]}
    client = httpx.Client(timeout=60)
    report["health"] = call(client, "GET", "/health")
    report["ready"] = call(client, "GET", "/ready")
    report["catalog"] = call(client, "GET", "/catalog")
    report["evaluation"] = call(client, "GET", "/evaluation-report")
    report["unknown_route"] = call(client, "GET", "/does-not-exist")
    report["search_unknown_field"] = call(client, "POST", "/search", {"query": "มันสำปะหลัง", "extra": 1})
    report["search_empty"] = call(client, "POST", "/search", {"query": ""})
    report["hybrid_conflict"] = call(
        client,
        "POST",
        "/hybrid-search",
        {"query": "มันสำปะหลัง", "filters": {"region_code": "NOR", "spatial_level": "country"}},
    )
    report["hybrid_bad_unit"] = call(
        client,
        "POST",
        "/hybrid-search",
        {"query": "มันสำปะหลัง", "numeric": {"metric": "production", "operator": "gt", "threshold": 1, "unit": "kg"}},
    )
    report["get_search"] = call(client, "GET", "/search?query=มันสำปะหลังภาคเหนือ&top_k=1")
    saved = json.loads(Path("evaluation/reports/evaluation.json").read_text(encoding="utf-8"))
    public = report["evaluation"]["payload"]
    report["evaluation_match"] = {
        "query_count": public.get("query_count") == saved.get("query_count") == 61,
        "top_k": public.get("top_k") == saved.get("top_k") == 5,
        "precision_note": (public.get("policy") or {}).get("precision_denominator"),
        "has_safety": "safety" in public,
        "has_queries": any("queries" in (public.get("backends") or {}).get(name, {}) for name in ("dictionary", "semantic", "hybrid")),
        "metrics": {
            name: (public.get("backends") or {}).get(name, {}).get("aggregate")
            for name in ("dictionary", "semantic", "hybrid")
        },
        "saved_metrics": {
            name: (saved.get("backends") or {}).get(name, {}).get("aggregate")
            for name in ("dictionary", "semantic", "hybrid")
        },
        "benchmark_model_ms": (public.get("benchmark") or {}).get("model_initialization_ms"),
        "saved_model_ms": (saved.get("benchmark") or {}).get("model_initialization_ms"),
    }
    hybrids = []
    for query in QUERIES:
        item = call(client, "POST", "/hybrid-search", {"query": query, "top_k": 5})
        hybrids.append({"query": query, "status": item["status"], "ms": item["ms"], "leaks": item["leaks"], "traceback": item["traceback"], "summary": summarize_hybrid(connection, item["payload"])})
    report["hybrids"] = hybrids
    north = "ผลผลิตมันสำปะหลังภาคเหนือปี 2566"
    call(client, "POST", "/search", {"query": north, "top_k": 5})
    call(client, "POST", "/compare", {"query": north, "mode": "dictionary", "top_k": 5})
    call(client, "POST", "/compare", {"query": north, "mode": "compare", "top_k": 5})
    call(client, "POST", "/hybrid-search", {"query": north, "top_k": 5})
    report["warm"] = {
        "semantic": times(client, "POST", "/search", {"query": north, "top_k": 5}),
        "dictionary": times(client, "POST", "/compare", {"query": north, "mode": "dictionary", "top_k": 5}),
        "compare": times(client, "POST", "/compare", {"query": north, "mode": "compare", "top_k": 5}),
        "hybrid": times(client, "POST", "/hybrid-search", {"query": north, "top_k": 5}),
        "hybrid_empty": times(client, "POST", "/hybrid-search", {"query": "มันสำปะหลังภาคใต้ปี 2566", "top_k": 5}),
        "hybrid_fertilizer": times(client, "POST", "/hybrid-search", {"query": "ปริมาณปุ๋ยที่ใช้ปลูกมันสำปะหลัง", "top_k": 5}),
    }
    dictionary = call(
        client,
        "POST",
        "/compare",
        {"query": north, "mode": "dictionary", "top_k": 5, "filters": {"crop_id": "MAI"}},
    )
    report["dictionary_ignores_explicit_filter"] = {
        "status": dictionary["status"],
        "warnings": (dictionary["payload"].get("warnings") or [])[:4],
        "dictionary_count": (dictionary["payload"].get("dictionary") or {}).get("count"),
        "first_crop": (((dictionary["payload"].get("dictionary") or {}).get("results") or [{}])[0].get("crop") or {}).get("crop_id"),
    }
    compare = call(client, "POST", "/compare", {"query": north, "mode": "compare", "top_k": 5})
    report["compare"] = {
        "status": compare["status"],
        "keys": sorted(compare["payload"].keys()),
        "score_comparison": compare["payload"].get("score_comparison"),
        "dictionary_count": (compare["payload"].get("dictionary") or {}).get("count"),
        "semantic_count": (compare["payload"].get("semantic") or {}).get("count"),
        "ms": compare["ms"],
        "leaks": compare["leaks"],
    }
    started = time.perf_counter()
    service = build_service()
    built = elapsed(started)
    start = time.perf_counter()
    service.start()
    probed = elapsed(start)
    ready = service.ready()
    service.close()
    report["cold_process"] = {
        "build_service_ms": built,
        "start_with_probe_embed_ms": probed,
        "ready_points": ready.get("points"),
        "ready_dimension": ready.get("vector_dimension"),
        "model_revision": ready.get("model_revision"),
    }
    connection.close()
    client.close()
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "health": report["health"]["status"],
        "ready": report["ready"]["status"],
        "ready_points": report["ready"]["payload"].get("points"),
        "catalog": report["catalog"]["status"],
        "evaluation": report["evaluation"]["status"],
        "query_count_match": report["evaluation_match"]["query_count"],
        "hybrid_statuses": [item["status"] for item in hybrids],
        "mismatches": sum(len(item["summary"]["mismatches"]) for item in hybrids),
        "cold_start_ms": probed,
        "out": str(OUT),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
