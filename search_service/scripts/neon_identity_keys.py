"""Report which identity keys exist. Never print secret values."""

from __future__ import annotations

import os
from pathlib import Path

NAMES = (
    "NEON_API_KEY",
    "NEON_PROJECT_ID",
    "EXPECTED_NEON_PROJECT_ID",
    "EXPECTED_NEON_BRANCH_ID",
    "EXPECTED_NEON_ENDPOINT_ID",
    "S1G14_STAGING_WRITE_APPROVED",
    "STAGING_DATABASE_URL",
)
PATH = Path(__file__).resolve().parents[1] / ".env"


def file_keys() -> set[str]:
    if not PATH.is_file():
        return set()
    found = set()
    for raw in PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        found.add(line.split("=", 1)[0].strip())
    return found


def main() -> int:
    present = file_keys()
    print("env_bytes", PATH.stat().st_size if PATH.is_file() else 0)
    print("env_keys", ",".join(sorted(present)) or "-")
    for name in NAMES:
        in_file = name in present
        in_process = bool(os.environ.get(name, "").strip())
        print(f"{name} file={'yes' if in_file else 'no'} process={'yes' if in_process else 'no'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
