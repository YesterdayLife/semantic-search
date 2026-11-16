"""Exercise the local Linux API container and record its resource use.

Publish 127.0.0.1:8011 only. SQLite and the model cache are read-only mounts.
The script stops and removes its own container when it finishes.
"""

from __future__ import annotations

import json
import statistics
import subprocess
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "s1g14-search-onnx:local"
NAME = "s1g14-onnx-api"
CACHE = ROOT / ".cache" / "huggingface"
SQLITE = Path(r"D:\Final Project\Hee_M3\output\S1-G14_M3.sqlite")
DICTIONARY = Path(r"D:\Final Project\Hee_M4\ch6 semantic search\src\semantic_search.py")
DICTIONARY_TARGET = "/opt/course/Hee_M4/ch6 semantic search/src/semantic_search.py"
BASE = "http://127.0.0.1:8011"
OUT = ROOT / "artifacts" / "deploy01d"

QUERIES = {
    "north_cassava": {"path": "/search", "body": {"query": "ผลผลิตมันสำปะหลังภาคเหนือปี 2566", "top_k": 5}},
    "multi_crop": {"path": "/hybrid-search", "body": {"query": "มันสำปะหลังและข้าวโพด", "top_k": 5}},
    "numeric": {"path": "/hybrid-search", "body": {"query": "ผลผลิตมากกว่า 1000000 ตัน", "top_k": 5, "numeric": {"metric": "production", "operator": "gt", "threshold": 1000000, "unit": "t"}}},
    "south_cassava": {"path": "/hybrid-search", "body": {"query": "มันสำปะหลังภาคใต้ปี 2566", "top_k": 5}},
    "carbon": {"path": "/search", "body": {"query": "carbon footprint of rice", "top_k": 5}},
    "dictionary": {"path": "/compare", "body": {"query": "ผลผลิตมันสำปะหลังภาคเหนือปี 2566", "top_k": 5, "mode": "dictionary"}},
    "semantic": {"path": "/compare", "body": {"query": "ผลผลิตมันสำปะหลังภาคเหนือปี 2566", "top_k": 5, "mode": "semantic"}},
    "compare": {"path": "/compare", "body": {"query": "ผลผลิตมันสำปะหลังภาคเหนือปี 2566", "top_k": 5, "mode": "compare"}},
    "hybrid": {"path": "/hybrid-search", "body": {"query": "ผลผลิตมันสำปะหลังภาคเหนือปี 2566", "top_k": 5}},
    "maize_central": {"path": "/search", "body": {"query": "maize production in central Thailand 2022", "top_k": 5}},
    "dry_rice": {"path": "/search", "body": {"query": "ข้าวนาปรังปี 2565", "top_k": 5}},
}


def _docker(*args: str, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], check=False, capture_output=True, text=True, timeout=timeout)


def _request(method: str, path: str, body: dict | None = None, timeout: float = 60) -> dict:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(BASE + path, data=data, method=method)
    if data is not None:
        request.add_header("content-type", "application/json")
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()
            status = response.status
    except urllib.error.HTTPError as exc:
        payload = exc.read()
        status = exc.code
    elapsed = (time.perf_counter() - started) * 1000
    try:
        parsed = json.loads(payload.decode("utf-8"))
    except json.JSONDecodeError:
        parsed = {"raw_bytes": len(payload)}
    return {"status": status, "elapsed_ms": round(elapsed, 3), "body": parsed}


def _summarize(item: dict) -> dict:
    body = item["body"] if isinstance(item["body"], dict) else {}
    results = body.get("results") if isinstance(body.get("results"), list) else []
    first = results[0] if results else {}
    dictionary = body.get("dictionary") if isinstance(body.get("dictionary"), dict) else {}
    semantic = body.get("semantic") if isinstance(body.get("semantic"), dict) else {}
    return {
        "status": item["status"],
        "elapsed_ms": item["elapsed_ms"],
        "count": body.get("count", body.get("process_count")),
        "error": (body.get("error") or {}).get("code") if isinstance(body.get("error"), dict) else None,
        "availability": body.get("availability_status"),
        "ranking_method": body.get("ranking_method"),
        "first_process_id": first.get("process_id"),
        "first_quantity": first.get("production_quantity"),
        "first_unit": first.get("production_unit"),
        "first_score": first.get("similarity_score"),
        "dictionary_backend": dictionary.get("backend"),
        "dictionary_error": (dictionary.get("error") or {}).get("code") if isinstance(dictionary.get("error"), dict) else None,
        "dictionary_first": ((dictionary.get("results") or [{}])[0] or {}).get("process_id") if isinstance(dictionary.get("results"), list) else None,
        "dictionary_quantity": ((dictionary.get("results") or [{}])[0] or {}).get("production_quantity") if isinstance(dictionary.get("results"), list) else None,
        "semantic_first": ((semantic.get("results") or [{}])[0] or {}).get("process_id") if isinstance(semantic.get("results"), list) else None,
        "report_keys": sorted(body)[:12] if "summary" in body or "metrics" in body else None,
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    samples: list[str] = []
    stop = threading.Event()

    def sample() -> None:
        while not stop.is_set():
            stat = _docker("stats", "--no-stream", "--format", "{{.MemUsage}}|{{.CPUPerc}}|{{.Name}}", NAME)
            if stat.stdout.strip():
                samples.append(f"{time.time():.3f}|{stat.stdout.strip()}")
            stop.wait(1)

    _docker("rm", "-f", NAME)
    started = time.perf_counter()
    run = _docker(
        "run", "-d", "--name", NAME, "--memory=2g", "--memory-swap=2g", "--cpus=2",
        "-p", "127.0.0.1:8011:8000",
        "-v", f"{CACHE}:/models/huggingface-ro:ro",
        "-v", f"{SQLITE}:/data/S1-G14_M3.sqlite:ro",
        "-v", f"{DICTIONARY}:{DICTIONARY_TARGET}:ro",
        "-e", f"DICTIONARY_SCRIPT={DICTIONARY_TARGET}",
        "-e", "ONNX_CACHE_SOURCE=/models/huggingface-ro",
        "-e", "HF_HOME=/tmp/huggingface",
        "-e", "HF_HUB_OFFLINE=1",
        "-e", "SQLITE_PATH=/data/S1-G14_M3.sqlite",
        "-e", "QDRANT_URL=http://host.docker.internal:6333",
        "-e", "DATA_BACKEND=sqlite",
        "-e", "VECTOR_BACKEND=qdrant",
        "--add-host", "host.docker.internal:host-gateway",
        IMAGE,
        timeout=60,
    )
    thread = threading.Thread(target=sample, daemon=True)
    thread.start()
    health = None
    deadline = time.perf_counter() + 180
    while time.perf_counter() < deadline:
        try:
            health = _request("GET", "/health", timeout=3)
            if health["status"] == 200:
                break
        except Exception:
            health = None
        time.sleep(0.5)
    cold_ms = (time.perf_counter() - started) * 1000
    routes = {}
    if health and health["status"] == 200:
        routes["health"] = _summarize(health)
        for name, spec in {
            "ready": ("GET", "/ready", None),
            "catalog": ("GET", "/catalog", None),
            "evaluation": ("GET", "/evaluation-report", None),
        }.items():
            routes[name] = _summarize(_request(*spec))
        for name, spec in QUERIES.items():
            routes[name] = _summarize(_request("POST", spec["path"], spec["body"]))
        warm = []
        for _ in range(20):
            warm.append(_request("POST", "/search", {"query": "ผลผลิตมันสำปะหลังภาคเหนือปี 2566", "top_k": 5})["elapsed_ms"])
        concurrent_started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=4) as pool:
            concurrent = list(pool.map(
                lambda _: _request("POST", "/search", {"query": "cassava production", "top_k": 5})["elapsed_ms"],
                range(8),
            ))
        concurrent_ms = (time.perf_counter() - concurrent_started) * 1000
        time.sleep(15)
    else:
        warm = []
        concurrent = []
        concurrent_ms = None
    stop.set()
    thread.join(timeout=3)
    inspect = _docker("inspect", NAME)
    state = {}
    if inspect.returncode == 0:
        info = json.loads(inspect.stdout)[0]
        state = {
            "oom_killed": info.get("State", {}).get("OOMKilled"),
            "status": info.get("State", {}).get("Status"),
            "restart_count": info.get("RestartCount"),
            "error": info.get("State", {}).get("Error"),
        }
    logs = _docker("logs", "--tail", "40", NAME)
    _docker("rm", "-f", NAME)
    report = {
        "cold_start_ms": round(cold_ms, 3),
        "health": health["status"] if health else None,
        "routes": routes,
        "warm_ms": _latency(warm),
        "concurrent_4x8_ms": _latency(concurrent),
        "concurrent_wall_ms": None if concurrent_ms is None else round(concurrent_ms, 3),
        "samples": samples,
        "state": state,
        "log_tail": logs.stderr[-2000:] + logs.stdout[-2000:],
        "run_error": run.stderr[-1000:] if run.returncode != 0 else "",
    }
    (OUT / "api_bench.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key not in {"samples", "log_tail"}}, ensure_ascii=False, indent=2))
    return 0 if health and health["status"] == 200 else 1


def _latency(values: list[float]) -> dict:
    if not values:
        return {"samples": 0}
    ordered = sorted(values)
    def pct(rank: float) -> float:
        index = min(len(ordered) - 1, max(0, math_ceil(rank) - 1))
        return ordered[index]
    return {
        "samples": len(values),
        "p50_ms": ordered[(len(ordered) - 1) // 2],
        "p95_ms": ordered[max(0, math_ceil(0.95 * len(ordered)) - 1)],
        "min_ms": ordered[0],
        "max_ms": ordered[-1],
        "mean_ms": round(statistics.fmean(values), 3),
    }


def math_ceil(value: float) -> int:
    return int(value) if value == int(value) else int(value) + 1


if __name__ == "__main__":
    raise SystemExit(main())
