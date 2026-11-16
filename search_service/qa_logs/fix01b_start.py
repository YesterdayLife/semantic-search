"""Start the local API and Vite dev server recorded by pid. Not a search change."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.local_session import describe, start

ROOT = Path(r"D:\Final Project\final\search_service")
FRONTEND = ROOT / "frontend"
LOGS = ROOT / "qa_logs" / "fix01b"
NODE = "node"
VITE = FRONTEND / "node_modules" / "vite" / "bin" / "vite.js"
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"

api = start(
    [str(PYTHON), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"],
    ROOT,
    LOGS / "api.log",
)
dev = start(
    [NODE, str(VITE), "--host", "127.0.0.1", "--port", "5173", "--strictPort"],
    FRONTEND,
    LOGS / "dev.log",
)
payload = {"api": describe(api), "dev": describe(dev)}
(LOGS / "pids.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
print(json.dumps(payload))
