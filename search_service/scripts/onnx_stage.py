"""Stage the approved ONNX snapshot into a private writable directory.

The image does not contain the model. A read-only mount supplies it.
huggingface_hub may create lock files, so the running process copies the
Xenova snapshot into its own temporary directory and leaves the mount unchanged.
"""

from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

REVISION = "4de13258303883538bd53b696b452bf8099f0858"
MODEL_DIR = Path("hub") / "models--Xenova--bge-m3"
WEIGHT = MODEL_DIR / "snapshots" / REVISION / "onnx" / "model_quantized.onnx"


def stage_approved_snapshot() -> tuple[Path, float]:
    """Return the cache directory the embedder should use, and the copy time.

    When ONNX_CACHE_SOURCE is unset, the existing local cache is used in place.
    """
    source_root = os.environ.get("ONNX_CACHE_SOURCE", "").strip()
    if not source_root:
        configured = os.environ.get("HF_HOME", "").strip()
        return (Path(configured) if configured else Path(__file__).resolve().parents[1] / ".cache" / "huggingface"), 0.0
    source = Path(source_root)
    weight = source / WEIGHT
    if not weight.is_file() or weight.stat().st_size < 1_000_000:
        print("approved ONNX snapshot is not mounted", file=sys.stderr)
        raise SystemExit(1)
    target = Path(os.environ.get("HF_HOME", "/tmp/huggingface"))
    destination = target / MODEL_DIR
    staged_weight = destination / "snapshots" / REVISION / "onnx" / "model_quantized.onnx"
    started = time.perf_counter()
    if not staged_weight.is_file():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source / MODEL_DIR, destination, dirs_exist_ok=True)
    os.environ["HF_HOME"] = str(target)
    os.environ["HF_HUB_CACHE"] = str(target / "hub")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    if not staged_weight.is_file() or staged_weight.stat().st_size < 1_000_000:
        print("approved ONNX snapshot could not be staged", file=sys.stderr)
        raise SystemExit(1)
    return target, (time.perf_counter() - started) * 1000
