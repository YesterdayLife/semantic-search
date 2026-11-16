"""Connections for the disposable local pgvector test. Secrets stay out of output."""

from __future__ import annotations

import os
from pathlib import Path

import psycopg

SECRET = Path(__file__).resolve().parents[1] / "artifacts" / "deploy01c" / "pgtest.secret"
APP_SECRET = Path(__file__).resolve().parents[1] / "artifacts" / "deploy01c" / "pgapp.secret"
HOST = os.environ.get("PGHOST", "127.0.0.1")
PORT = int(os.environ.get("PGPORT", "54329"))
DATABASE = "s1g14_migration_test"
MIGRATION_USER = "s1g14_test"
APP_USER = "s1g14_app"


def migration_password() -> str:
    return SECRET.read_text(encoding="utf-8").strip()


def app_password() -> str:
    return APP_SECRET.read_text(encoding="utf-8").strip()


def connect_migration():
    return psycopg.connect(
        host=HOST,
        port=PORT,
        dbname=DATABASE,
        user=MIGRATION_USER,
        password=migration_password(),
        connect_timeout=10,
    )


def connect_app():
    return psycopg.connect(
        host=HOST,
        port=PORT,
        dbname=DATABASE,
        user=APP_USER,
        password=app_password(),
        connect_timeout=10,
    )


def redact(text: str) -> str:
    hidden = text
    for secret in (migration_password(), _optional(APP_SECRET)):
        if secret:
            hidden = hidden.replace(secret, "[redacted]")
    return hidden


def _optional(path: Path) -> str:
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8").strip()
