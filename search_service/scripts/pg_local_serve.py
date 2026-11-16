"""Serve FastAPI against the disposable database. The URL is built here and not logged."""

from __future__ import annotations

import os

from scripts.onnx_stage import stage_approved_snapshot
from scripts.pg_local_common import APP_USER, DATABASE, HOST, PORT, app_password

stage_approved_snapshot()
os.environ["DATA_BACKEND"] = "postgres"
os.environ["VECTOR_BACKEND"] = "pgvector"
os.environ["DATABASE_URL"] = f"postgresql://{APP_USER}:{app_password()}@{HOST}:{PORT}/{DATABASE}"
os.environ.setdefault("HF_HUB_OFFLINE", "1")

import uvicorn

uvicorn.run("app.main:app", host="0.0.0.0", port=8000, log_level="warning", access_log=False)
