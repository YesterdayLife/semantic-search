"""Live contract and timing check. Does not write evaluation reports or vectors."""

from __future__ import annotations

import json
import statistics
import time
import urllib.request

BASE = "http://127.0.0.1:8000"
QUERIES = [
    "ผลผลิตมันสำปะหลังภาคเหนือปี 2566",
    "มันสำปะหลังและข้าวโพด",
    "ผลผลิตมากกว่า 10000000 ตัน",
    "มันสำปะหลังภาคใต้ปี 2566",
    "carbon footprint of rice production",
]


def post(path: str, body: dict) -> tuple[float, dict]:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(BASE + path, data=data, headers={"Content-Type": "application/json"})
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=120) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return round((time.perf_counter() - started) * 1000, 3), payload


def get(path: str) -> dict:
    with urllib.request.urlopen(BASE + path, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def rows(payload: dict, mode: str) -> list[dict]:
    if mode == "hybrid":
        source = payload.get("results") or []
    elif mode == "semantic":
        source = payload.get("results") or []
    elif mode == "dictionary":
        source = ((payload.get("dictionary") or {}).get("results")) or []
    else:
        source = ((payload.get("dictionary") or {}).get("results")) or []
    return [
        {
            "process_id": row.get("process_id"),
            "quantity": row.get("production_quantity"),
            "unit": row.get("production_unit"),
            "score": row.get("similarity_score"),
        }
        for row in source[:3]
    ]


def call(mode: str, query: str) -> tuple[float, dict]:
    if mode == "semantic":
        return post("/search", {"query": query, "top_k": 5})
    if mode == "hybrid":
        return post("/hybrid-search", {"query": query, "top_k": 5})
    return post("/compare", {"query": query, "top_k": 5, "mode": "dictionary" if mode == "dictionary" else "compare"})


def latency(values: list[float]) -> dict:
    ordered = sorted(values)
    index = max(0, round(0.95 * (len(ordered) - 1)))
    return {
        "samples": len(values),
        "mean_ms": round(statistics.fmean(values), 3),
        "median_ms": round(statistics.median(values), 3),
        "p95_ms": round(ordered[index], 3),
    }


def main() -> None:
    catalog = get("/catalog")
    report = get("/evaluation-report")
    summary = {
        "catalog_crops": [item.get("crop_id") for item in catalog.get("crops", [])],
        "report_note": report.get("report_note"),
        "modes": {},
    }
    for mode in ("dictionary", "semantic", "hybrid", "compare"):
        cold_ms, cold = call(mode, QUERIES[0])
        samples = []
        components: dict[str, list[float]] = {}
        identities = []
        for _ in range(3):
            for query in QUERIES:
                elapsed, payload = call(mode, query)
                samples.append(elapsed)
                timing = payload.get("timing_ms") or {}
                if mode == "compare":
                    timing = timing if isinstance(timing, dict) else {}
                elif mode == "dictionary":
                    timing = (payload.get("dictionary") or {}).get("timing_ms")
                    timing = {"dictionary": timing} if not isinstance(timing, dict) else timing
                if isinstance(timing, dict):
                    for key, value in timing.items():
                        if isinstance(value, (int, float)):
                            components.setdefault(key, []).append(float(value))
                identities.append({"query": query, "rows": rows(payload, mode), "availability": payload.get("availability_status") or payload.get("dictionary", {}).get("availability_status")})
        summary["modes"][mode] = {
            "cold_ms": cold_ms,
            "cold_timing": cold.get("timing_ms"),
            "end_to_end": latency(samples),
            "components": {key: latency(values) for key, values in components.items()},
            "first_rows": identities[0],
            "stable": len({json.dumps(item["rows"], sort_keys=True) for item in identities if item["query"] == QUERIES[0]}) == 1,
        }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
