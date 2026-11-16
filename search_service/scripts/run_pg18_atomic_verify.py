"""Start the disposable PostgreSQL 18 database and run the local atomic check.

The existing PostgreSQL 16 container and volume are not used. Neon variables are
not passed into either container.
"""

from __future__ import annotations

import secrets
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "pgvector/pgvector:0.8.7-pg18"
CONTAINER = "s1g14-pg18-atomic"
VOLUME = "s1g14_pg18_atomic_data"
NETWORK = "s1g14-pg18-net"
PORT = "54330"
PROTECTED = {"s1g14-pgvector-test", "s1g14-qdrant", "cn230-db-1"}


def main() -> int:
    if CONTAINER in PROTECTED:
        return 1
    _ensure("network", NETWORK)
    _ensure("volume", VOLUME)
    password = _start_database()
    try:
        if not _wait_ready():
            print("postgresql 18 did not become ready", file=sys.stderr)
            return 1
        return _run_check(password)
    finally:
        subprocess.run(["docker", "stop", CONTAINER], check=False, stdout=subprocess.DEVNULL)


def _ensure(kind: str, name: str) -> None:
    inspect = subprocess.run(["docker", kind, "inspect", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if inspect.returncode != 0:
        subprocess.run(["docker", kind, "create", name], check=True, stdout=subprocess.DEVNULL)


def _start_database() -> str:
    existing = subprocess.run(["docker", "inspect", CONTAINER], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if existing.returncode != 0:
        password = secrets.token_hex(24)
        subprocess.run(
            [
                "docker",
                "run",
                "-d",
                "--name",
                CONTAINER,
                "--network",
                NETWORK,
                "-p",
                f"127.0.0.1:{PORT}:5432",
                "-v",
                f"{VOLUME}:/var/lib/postgresql",
                "-e",
                "POSTGRES_USER=s1g14_pg18",
                "-e",
                f"POSTGRES_PASSWORD={password}",
                "-e",
                "POSTGRES_DB=postgres",
                IMAGE,
            ],
            check=True,
            stdout=subprocess.DEVNULL,
        )
        return password
    subprocess.run(["docker", "start", CONTAINER], check=True, stdout=subprocess.DEVNULL)
    return _container_password()


def _container_password() -> str:
    completed = subprocess.run(
        ["docker", "inspect", "--format", "{{range .Config.Env}}{{println .}}{{end}}", CONTAINER],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    for line in completed.stdout.splitlines():
        if line.startswith("POSTGRES_PASSWORD="):
            return line.split("=", 1)[1]
    raise RuntimeError("the local PostgreSQL 18 container has no password")


def _wait_ready() -> bool:
    for _attempt in range(60):
        ready = subprocess.run(
            ["docker", "exec", CONTAINER, "pg_isready", "-U", "s1g14_pg18", "-d", "postgres"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if ready.returncode == 0:
            return True
        time.sleep(1)
    return False


def _run_check(password: str) -> int:
    completed = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--user",
            "root",
            "--network",
            NETWORK,
            "--add-host",
            "host.docker.internal:host-gateway",
            "-e",
            "HOME=/tmp",
            "-e",
            "PIP_CACHE_DIR=/tmp/pip",
            "-e",
            "PYTHONDONTWRITEBYTECODE=1",
            "-e",
            "S1G14_PG18_LOCAL_TEST=1",
            "-e",
            "PGHOST=s1g14-pg18-atomic",
            "-e",
            "PGPORT=5432",
            "-e",
            "PGUSER=s1g14_pg18",
            "-e",
            f"PGPASSWORD={password}",
            "-e",
            "SQLITE_PATH=/sqlite/S1-G14_M3.sqlite",
            "-e",
            "QDRANT_URL=http://host.docker.internal:6333",
            "-v",
            r"D:\Final Project\final\search_service:/work:ro",
            "-v",
            r"D:\Final Project\Hee_M3\output\S1-G14_M3.sqlite:/sqlite/S1-G14_M3.sqlite:ro",
            "-w",
            "/work",
            "s1g14-search-onnx:local",
            "sh",
            "-c",
            "pip install --disable-pip-version-check -q 'psycopg[binary]==3.3.9' && python -m scripts.pg18_atomic_verify",
        ],
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)
    return completed.returncode


if __name__ == "__main__":
    sys.exit(main())
