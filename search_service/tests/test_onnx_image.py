"""Static checks for the Linux ONNX image. These tests do not build it."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_linux_requirements_omit_torch_cuda_and_openai():
    lines = [
        line.strip().lower()
        for line in (ROOT / "requirements-linux.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    text = "\n".join(lines)
    assert "onnxruntime==1.32.0" in text
    assert "tokenizers==0.23.3" in text
    for blocked in ("torch", "cuda", "openai", "sentence-transformers", "pytest"):
        assert blocked not in text


def test_dockerfile_fails_closed_and_stays_local():
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "python:3.12-slim-bookworm" in text
    assert "USER appuser" in text
    assert "--workers" not in text
    assert "onnx_entrypoint.py" in text
    assert ".cache" not in text
    assert "COPY app /app/app" in text
    assert "127.0.0.1:8000/health" in text
    assert "DATABASE_URL" not in text
    assert "OPENAI" not in text


def test_dockerignore_keeps_secrets_and_the_model_out_of_the_context():
    text = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    for required in (".env", ".venv", ".cache", "*.sqlite"):
        assert required in text


def test_entrypoint_publishes_a_single_worker_inside_the_container():
    text = (ROOT / "scripts" / "onnx_entrypoint.py").read_text(encoding="utf-8")
    assert '"--workers"' in text
    assert '"1"' in text
    assert "0.0.0.0" in text
    assert "stage_approved_snapshot" in text
