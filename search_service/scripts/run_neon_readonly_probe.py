"""Run the read-only Neon probe inside the existing Linux image."""

from __future__ import annotations

import subprocess
import sys

COMMAND = [
    "docker",
    "run",
    "--rm",
    "--user",
    "root",
    "--network",
    "bridge",
    "-e",
    "HOME=/tmp",
    "-e",
    "PIP_CACHE_DIR=/tmp/pip",
    "-e",
    "PYTHONDONTWRITEBYTECODE=1",
    "-v",
    r"D:\Final Project\final\search_service:/work:ro",
    "-w",
    "/work",
    "s1g14-search-onnx:local",
    "sh",
    "-c",
    "pip install --disable-pip-version-check -q 'psycopg[binary]==3.3.9' && python scripts/neon_readonly_probe.py",
]


def main() -> int:
    completed = subprocess.run(COMMAND, check=False)
    return completed.returncode


if __name__ == "__main__":
    sys.exit(main())
