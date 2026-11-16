"""Start one Uvicorn worker after the approved ONNX snapshot is staged.

Inside the container the process listens on 0.0.0.0:8000. Publish that port
only on 127.0.0.1 of the host. This file does not read or print credentials.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.onnx_stage import stage_approved_snapshot


def main() -> int:
    cache, stage_ms = stage_approved_snapshot()
    os.environ["HF_HOME"] = str(cache)
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ.setdefault("DATA_BACKEND", "sqlite")
    os.environ.setdefault("VECTOR_BACKEND", "qdrant")
    print(f"onnx snapshot staged in {stage_ms:.0f} ms", file=sys.stderr)
    os.execv(
        sys.executable,
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "0.0.0.0",
            "--port",
            "8000",
            "--workers",
            "1",
        ],
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
