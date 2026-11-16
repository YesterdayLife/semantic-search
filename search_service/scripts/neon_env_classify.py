"""Print non-secret facts about the private staging URL. Never print the URL."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PATH = Path(__file__).resolve().parents[1] / ".env"


def load(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    text = path.read_text(encoding="utf-8")
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def main() -> int:
    print("exists", PATH.exists())
    print("bytes", PATH.stat().st_size if PATH.exists() else 0)
    values = load(PATH) if PATH.exists() else {}
    print("keys", ",".join(values))
    url = values.get("STAGING_DATABASE_URL", "")
    print("url_configured", bool(url))
    parsed = urlparse(url) if url else None
    if parsed is not None:
        host = (parsed.hostname or "").lower()
        query = {key.lower(): (item[-1].lower() if item else "") for key, item in parse_qs(parsed.query).items()}
        print("scheme", parsed.scheme)
        print("database", (parsed.path or "").lstrip("/"))
        print("user_present", bool(parsed.username))
        print("password_present", bool(parsed.password))
        print("port", parsed.port)
        print("host_neon", host.endswith(".neon.tech"))
        print("host_pooler", "-pooler" in host)
        print("host_direct_prefix", host.startswith("ep-"))
        print("host_singapore", "ap-southeast-1" in host)
        print("sslmode", query.get("sslmode", "MISSING"))
        print("channel_binding", query.get("channel_binding", "MISSING"))
    approval = values.get("S1G14_STAGING_WRITE_APPROVED", "UNSET")
    print("approval_in_file", "SET" if approval not in {"", "UNSET"} else "UNSET")
    print("process_approval", os.environ.get("S1G14_STAGING_WRITE_APPROVED", "UNSET") or "UNSET")
    print("process_url", "SET" if os.environ.get("STAGING_DATABASE_URL", "").strip() else "UNSET")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
