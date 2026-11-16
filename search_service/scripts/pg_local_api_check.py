"""Call the temporary PostgreSQL-mode API. This file does not print the database URL."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8012"
SECRET = Path(__file__).resolve().parents[1] / "artifacts" / "deploy01c" / "pgapp.secret"
QUERIES = (
    "ผลผลิตมันสำปะหลังภาคเหนือปี 2566",
    "maize production in central Thailand 2022",
    "ข้าวนาปรังปี 2565",
    "มันสำปะหลังและข้าวโพด",
    "ผลผลิตมากกว่า 1000000 ตัน",
    "มันสำปะหลังภาคใต้ปี 2566",
    "carbon footprint of rice production",
)


def main() -> None:
    secret = SECRET.read_text(encoding="utf-8").strip()
    ready = _wait("/ready")
    catalog = _get("/catalog")
    report = _get("/evaluation-report")
    searches = {query: _post("/search", {"query": query, "top_k": 5}) for query in QUERIES}
    compared = _post("/compare", {"query": QUERIES[0], "top_k": 5, "mode": "compare"})
    hybrid = _post("/hybrid-search", {"query": QUERIES[3], "top_k": 5})
    body = json.dumps(
        {
            "ready_keys": sorted(ready),
            "ready_points": ready.get("points"),
            "ready_dimension": ready.get("vector_dimension"),
            "ready_distance": ready.get("distance"),
            "ready_process_count": ready.get("process_count"),
            "catalog_count": catalog.get("process_count"),
            "catalog_crops": [row.get("crop_id") for row in catalog.get("crops") or []],
            "report_note": report.get("report_note"),
            "searches": {query: _brief(payload) for query, payload in searches.items()},
            "compare_dictionary": _brief((compared.get("dictionary") or {})),
            "compare_semantic": _brief((compared.get("semantic") or {})),
            "hybrid": _brief(hybrid),
        },
        ensure_ascii=False,
        indent=2,
    )
    if secret and secret in body:
        raise SystemExit("response contained a credential")
    print(body)


def _wait(path: str) -> dict:
    deadline = time.perf_counter() + 150
    last = ""
    while time.perf_counter() < deadline:
        try:
            return _get(path)
        except Exception as exc:
            last = str(exc)
            time.sleep(1)
    raise SystemExit(f"ready timed out: {last}")


def _get(path: str) -> dict:
    with urllib.request.urlopen(BASE + path, timeout=30) as response:
        return json.loads(response.read().decode())


def _post(path: str, payload: dict) -> dict:
    request = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode(),
        headers={"content-type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        return json.loads(exc.read().decode())


def _brief(payload: dict) -> dict:
    rows = payload.get("results") or []
    first = rows[0] if rows else {}
    return {
        "count": payload.get("count"),
        "error": (payload.get("error") or {}).get("code") if isinstance(payload.get("error"), dict) else None,
        "availability": payload.get("availability_status"),
        "unavailable": payload.get("unavailable_measures"),
        "first": first.get("process_id"),
        "quantity": first.get("production_quantity"),
        "unit": first.get("production_unit"),
        "score": first.get("similarity_score"),
        "backend": payload.get("backend"),
    }


if __name__ == "__main__":
    main()
