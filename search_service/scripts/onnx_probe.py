"""Print one JSON record for the local quantized ONNX runtime.

This script embeds fixed queries. It does not write Qdrant, SQLite, or the
model cache, and it does not download weights.
"""

from __future__ import annotations

import json
import math
import platform
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.onnx_stage import stage_approved_snapshot

QUERIES = (
    "ผลผลิตมันสำปะหลังภาคเหนือปี 2566",
    "cassava production",
)


def _rss_bytes() -> int | None:
    status = Path("/proc/self/status")
    if not status.is_file():
        return None
    for line in status.read_text(encoding="utf-8").splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) * 1024
    return None


def main() -> int:
    phase = sys.argv[1] if len(sys.argv) > 1 else "embed"
    cache, stage_ms = stage_approved_snapshot()
    if phase == "import":
        import fastapi
        import onnxruntime

        print(json.dumps({
            "phase": "import",
            "fastapi": fastapi.__version__,
            "onnxruntime": onnxruntime.__version__,
            "rss_bytes": _rss_bytes(),
            "stage_ms": round(stage_ms, 3),
        }))
        return 0
    started = time.perf_counter()
    from app.embeddings import ONNX_MODEL_REVISION, LocalBgeM3Provider

    provider = LocalBgeM3Provider(backend="onnx", device="cpu", cache_dir=cache)
    provider.prepare()
    prepared_ms = (time.perf_counter() - started) * 1000
    if phase == "prepare":
        print(json.dumps({
            "phase": "prepare",
            "revision": provider.model_revision,
            "backend": provider.backend,
            "rss_bytes": _rss_bytes(),
            "prepare_ms": round(prepared_ms, 3),
            "stage_ms": round(stage_ms, 3),
        }))
        return 0
    load_started = time.perf_counter()
    provider.embed_query(QUERIES[0])
    load_ms = (time.perf_counter() - load_started) * 1000
    session = provider._model
    providers = list(session.session.get_providers())
    rows = []
    for query in QUERIES:
        encode_started = time.perf_counter()
        vector = provider.embed_query(query)
        elapsed = (time.perf_counter() - encode_started) * 1000
        norm = math.sqrt(sum(value * value for value in vector))
        rows.append({
            "query": query,
            "token_ids": list(session.tokenizer.encode(query).ids),
            "dimension": len(vector),
            "finite": all(math.isfinite(value) for value in vector),
            "norm": norm,
            "elapsed_ms": round(elapsed, 3),
            "vector": vector,
        })
    print(json.dumps({
        "phase": "embed",
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "revision": provider.model_revision,
        "expected_revision": ONNX_MODEL_REVISION,
        "providers": providers,
        "rss_bytes": _rss_bytes(),
        "stage_ms": round(stage_ms, 3),
        "prepare_ms": round(prepared_ms, 3),
        "first_load_ms": round(load_ms, 3),
        "queries": rows,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
