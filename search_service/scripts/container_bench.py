"""Repeatable local benchmark for the Linux ONNX image.

The container is published only on 127.0.0.1. The model cache and SQLite file
are mounted read-only. This script does not push an image or change Qdrant.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "s1g14-search-onnx:local"
CACHE = ROOT / ".cache" / "huggingface"
SQLITE = Path(r"D:\Final Project\Hee_M3\output\S1-G14_M3.sqlite")
HOST_PORT = "127.0.0.1:8011"
CONTAINER = "s1g14-onnx-bench"
QUERIES = (
    "ผลผลิตมันสำปะหลังภาคเหนือปี 2566",
    "มันสำปะหลังและข้าวโพด",
    "ผลผลิตมากกว่า 1000000 ตัน",
    "มันสำปะหลังภาคใต้ปี 2566",
    "carbon footprint of rice",
)


def _docker(*args: str, timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], check=False, capture_output=True, text=True, timeout=timeout)


def _mounts() -> list[str]:
    return [
        "-v", f"{CACHE}:/models/huggingface-ro:ro",
        "-v", f"{SQLITE}:/data/S1-G14_M3.sqlite:ro",
        "-v", r"D:\Final Project\Hee_M4\ch6 semantic search\src\semantic_search.py:/opt/course/Hee_M4/ch6 semantic search/src/semantic_search.py:ro",
        "-e", "DICTIONARY_SCRIPT=/opt/course/Hee_M4/ch6 semantic search/src/semantic_search.py",
        "-e", "ONNX_CACHE_SOURCE=/models/huggingface-ro",
        "-e", "HF_HOME=/tmp/huggingface",
        "-e", "SQLITE_PATH=/data/S1-G14_M3.sqlite",
        "-e", "QDRANT_URL=http://host.docker.internal:6333",
        "-e", "DATA_BACKEND=sqlite",
        "-e", "VECTOR_BACKEND=qdrant",
        "--add-host", "host.docker.internal:host-gateway",
    ]


def run_probe(phase: str) -> dict:
    command = [
        "docker", "run", "--rm", "--memory=2g", "--memory-swap=2g", "--cpus=2",
        "--name", f"{CONTAINER}-{phase}",
        *_mounts(),
        IMAGE,
        "python", "/app/scripts/onnx_probe.py", phase,
    ]
    completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=600)
    if completed.returncode != 0:
        return {"phase": phase, "ok": False, "stderr": completed.stderr[-2000:], "stdout": completed.stdout[-2000:]}
    return {"ok": True, **json.loads(completed.stdout)}


def main() -> int:
    output = ROOT / "artifacts" / "deploy01d"
    output.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    import_phase = run_probe("import")
    prepare_phase = run_probe("prepare")
    embed_phase = run_probe("embed")
    (output / "linux_embed.json").write_text(json.dumps(embed_phase), encoding="utf-8")
    summary = {
        "image": IMAGE,
        "memory_limit": "2g",
        "import": _public(import_phase),
        "prepare": _public(prepare_phase),
        "embed": _public_embed(embed_phase),
        "elapsed_s": round(time.perf_counter() - started, 3),
    }
    (output / "probe_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if embed_phase.get("ok") else 1


def _public(payload: dict) -> dict:
    hidden = {"queries"}
    return {key: value for key, value in payload.items() if key not in hidden}


def _public_embed(payload: dict) -> dict:
    if not payload.get("ok"):
        return _public(payload)
    body = _public(payload)
    body["queries"] = [
        {key: value for key, value in row.items() if key != "vector"}
        for row in payload.get("queries", [])
    ]
    return body


if __name__ == "__main__":
    raise SystemExit(main())
