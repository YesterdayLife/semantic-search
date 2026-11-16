"""Locate a staging URL configuration without printing secret values."""

from __future__ import annotations

import os
from pathlib import Path

ROOTS = (
    Path(r"D:\Final Project\final"),
    Path(r"D:\Final Project"),
)
NAMES = {".env", ".env.local", ".env.staging"}


def keys_of(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ["unreadable"]
    found = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        found.append(line.split("=", 1)[0].strip())
    return found


def main() -> None:
    seen = set()
    for root in ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.name not in NAMES or not path.is_file():
                continue
            if path in seen:
                continue
            seen.add(path)
            print(f"{path} bytes={path.stat().st_size} keys={','.join(keys_of(path)) or '-'}")
    for scope in ("Process", "User", "Machine"):
        print(scope, "STAGING_DATABASE_URL", "SET" if os.environ.get("STAGING_DATABASE_URL") and scope == "Process" else "checked-process-only")


if __name__ == "__main__":
    main()
