"""Read the local Qdrant collection and print only the vector fingerprint."""

from __future__ import annotations

from scripts.neon_staging_migrate import FINGERPRINT, fingerprint, scroll_qdrant

points = scroll_qdrant("http://127.0.0.1:6333")
found = fingerprint(points)
print("count", len(points))
print("fingerprint", found)
print("matches", found == FINGERPRINT)
