# Local Linux CPU image for FastAPI and the quantized BGE-M3 ONNX runtime.
# The model snapshot is not copied into this image. Mount it read-only at
# /models/huggingface-ro. The entrypoint refuses to start when that snapshot
# is missing. Publish the container port only on 127.0.0.1.
#
# Other runtime mounts, also absent from the image:
#   /data/S1-G14_M3.sqlite                 read-only, SQLITE_PATH
#   /opt/course/Hee_M4/ch6 semantic search/src/semantic_search.py
#       read-only course file, DICTIONARY_SCRIPT
#   The course file computes its default database from parents[3] at import,
#   so the mounted path keeps that depth. The adapter still passes SQLITE_PATH.

FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HUB_DISABLE_TELEMETRY=1 \
    HF_HUB_OFFLINE=1 \
    TOKENIZERS_PARALLELISM=false \
    DATA_BACKEND=sqlite \
    VECTOR_BACKEND=qdrant \
    BGE_DEVICE=cpu

WORKDIR /app

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin appuser

COPY requirements-linux.txt /app/requirements-linux.txt
RUN pip install --no-cache-dir -r /app/requirements-linux.txt \
    && pip check

COPY app /app/app
COPY evaluation/reports/evaluation.json /app/evaluation/reports/evaluation.json
COPY scripts/onnx_stage.py /app/scripts/onnx_stage.py
COPY scripts/onnx_probe.py /app/scripts/onnx_probe.py
COPY scripts/onnx_entrypoint.py /app/scripts/onnx_entrypoint.py
RUN chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=180s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"]

CMD ["python", "/app/scripts/onnx_entrypoint.py"]
