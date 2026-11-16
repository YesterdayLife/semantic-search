"""Run a Linux client against the disposable database. The host policy blocks psycopg's DLL."""

from __future__ import annotations

import subprocess
import sys

COMMANDS = {
    "load": ["python", "-m", "scripts.pg_local_load"],
    "parity": ["python", "-m", "scripts.pg_local_parity"],
    "focus": ["python", "-m", "scripts.pg_local_focus"],
    "security": ["python", "-m", "scripts.pg_local_security"],
    "serve": ["python", "-m", "scripts.pg_local_serve"],
}


def main() -> None:
    name = sys.argv[1] if len(sys.argv) > 1 else "load"
    inner = COMMANDS[name]
    command = [
        "docker",
        "run",
        "--rm",
        "--user",
        "root",
        "--network",
        "s1g14_pgvector_test",
        "--add-host",
        "host.docker.internal:host-gateway",
    ]
    if name == "serve":
        command[2:2] = ["--name", "s1g14-pg-api", "--detach", "-p", "127.0.0.1:8012:8000"]
    command += [
        "-v",
        r"D:\Final Project\final\search_service:/work",
        "-v",
        r"D:\Final Project\Hee_M4\ch6 semantic search\src\semantic_search.py:/opt/course/Hee_M4/ch6 semantic search/src/semantic_search.py:ro",
        "-v",
        r"D:\Final Project\final\search_service\.cache\huggingface:/models/huggingface-ro:ro",
    ]
    if name != "serve":
        command += [
            "-v",
            r"D:\Final Project\Hee_M3\output\S1-G14_M3.sqlite:/data/S1-G14_M3.sqlite:ro",
            "-e",
            "SQLITE_PATH=/data/S1-G14_M3.sqlite",
            "-e",
            "QDRANT_URL=http://host.docker.internal:6333",
        ]
    command += [
        "-e",
        "DICTIONARY_SCRIPT=/opt/course/Hee_M4/ch6 semantic search/src/semantic_search.py",
        "-e",
        "PGHOST=postgres",
        "-e",
        "PGPORT=5432",
        "-e",
        "ONNX_CACHE_SOURCE=/models/huggingface-ro",
        "-e",
        "HF_HOME=/tmp/huggingface",
        "-e",
        "HF_HUB_OFFLINE=1",
        "-e",
        "PYTHONPATH=/work",
        "-w",
        "/work",
        "s1g14-search-onnx:local",
        "python",
        "-c",
        "import subprocess,sys; subprocess.check_call([sys.executable,'-m','pip','install','--no-cache-dir','psycopg[binary]==3.3.9']); raise SystemExit(subprocess.call(sys.argv[1:]))",
        *inner,
    ]
    raise SystemExit(subprocess.call(command))


if __name__ == "__main__":
    main()
