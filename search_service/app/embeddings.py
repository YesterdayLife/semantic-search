"""Embedding providers.

Mock embeddings are deterministic test vectors. They are not semantic embeddings
and must never be stored in the crop_process collection.
"""

from __future__ import annotations

import hashlib
import math
import os
import time
from pathlib import Path
from typing import Callable

from .config import EMBEDDING_DIMENSION, MOCK_EMBEDDING_MODEL, OPENAI_MODEL

# Quantized ONNX export of BAAI/bge-m3. Used only when PyTorch cannot load.
ONNX_REPO = "Xenova/bge-m3"
ONNX_REVISION = "4de13258303883538bd53b696b452bf8099f0858"
ONNX_WEIGHTS = "onnx/model_quantized.onnx"
ONNX_MODEL_REVISION = "xenova-4de13258303883538bd53b696b452bf8099f0858-model_quantized.onnx"

VectorCall = Callable[[list[str]], list[list[float]]]


class EmbeddingError(RuntimeError):
    """An embedding batch could not be produced. The message omits secrets and vectors."""


class MockEmbeddingProvider:
    """Deterministic 1536-dimensional vectors for pipeline tests.

    The vectors are an L2-normalized hash expansion of the document text.
    They do not measure meaning and are not a substitute for text-embedding-3-small.
    """

    model_name = MOCK_EMBEDDING_MODEL
    dimension = EMBEDDING_DIMENSION
    semantic = False

    def __repr__(self) -> str:
        return f"MockEmbeddingProvider(model={self.model_name!r}, semantic=False, dimension={self.dimension})"

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        vectors = [_mock_vector(text, self.dimension) for text in texts]
        _validate_vectors(vectors, len(texts), self.dimension)
        return vectors


class OpenAIEmbeddingProvider:
    """Real text-embedding-3-small client. Phase 3 does not invoke this provider."""

    semantic = True
    retriable_error_names = ("RateLimitError", "APITimeoutError", "APIConnectionError")

    def __init__(self, api_key: str, model: str = OPENAI_MODEL, dimension: int = EMBEDDING_DIMENSION, timeout: float = 30.0, attempts: int = 3):
        if not api_key or api_key.strip() in {"your-openai-api-key-here", "replace-with-your-key"}:
            raise EmbeddingError("OPENAI_API_KEY is not configured")
        self.model_name = model
        self.dimension = dimension
        self.timeout = timeout
        self.attempts = attempts
        self._api_key = api_key

    def __repr__(self) -> str:
        return f"OpenAIEmbeddingProvider(model={self.model_name!r}, dimension={self.dimension})"

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        vectors = self._embed_with_retries(texts, self._request)
        _validate_vectors(vectors, len(texts), self.dimension)
        return vectors

    def _embed_with_retries(self, texts: list[str], call: VectorCall) -> list[list[float]]:
        last_name = "EmbeddingError"
        for attempt in range(self.attempts):
            try:
                return call(texts)
            except EmbeddingError:
                raise
            except Exception as exc:
                last_name = type(exc).__name__
                if last_name not in self.retriable_error_names or attempt == self.attempts - 1:
                    raise EmbeddingError(f"OpenAI embedding request failed ({last_name})") from None
                time.sleep(min(2 ** attempt, 8))
        raise EmbeddingError(f"OpenAI embedding request failed ({last_name})")

    def _request(self, texts: list[str]) -> list[list[float]]:
        from openai import OpenAI

        client = OpenAI(api_key=self._api_key, timeout=self.timeout, max_retries=0)
        response = client.embeddings.create(model=self.model_name, input=texts, dimensions=self.dimension)
        ordered = sorted(response.data, key=lambda item: item.index)
        return [list(item.embedding) for item in ordered]


def _mock_vector(text: str, dimension: int) -> list[float]:
    seed = hashlib.sha256(b"s1g14-mock-v1\n" + text.encode("utf-8")).digest()
    values: list[float] = []
    counter = 0
    while len(values) < dimension:
        block = hashlib.sha256(seed + counter.to_bytes(4, "big")).digest()
        counter += 1
        for offset in range(0, len(block), 4):
            chunk = block[offset : offset + 4]
            if len(chunk) < 4:
                continue
            raw = int.from_bytes(chunk, "big")
            values.append((raw / 4294967295) * 2 - 1)
    values = values[:dimension]
    norm = math.sqrt(sum(value * value for value in values))
    if norm == 0:
        raise EmbeddingError("mock embedding norm was zero")
    return [value / norm for value in values]


class LocalBgeM3Provider:
    """Local dense embeddings from BAAI/bge-m3. No network call is made after the weights are cached."""

    semantic = True
    provider_id = "local-bge-m3"

    def __init__(
        self,
        model_name: str = "BAAI/bge-m3",
        revision: str = "5617a9f61b028005a4858fdac845db406aefb181",
        dimension: int = 1024,
        batch_size: int = 8,
        device: str = "auto",
        cache_dir: Path | None = None,
        backend: str | None = None,
    ):
        self.model_name = model_name
        self.model_revision = revision
        self.dimension = dimension
        self.batch_size = batch_size
        self.requested_device = device
        self.device = device
        self.backend = "sentence-transformers"
        self.backend_preference = backend
        self.cache_dir = cache_dir or _bge_cache_dir()
        self._model = None
        self._prepared = False

    def __repr__(self) -> str:
        return (
            f"LocalBgeM3Provider(model={self.model_name!r}, revision={self.model_revision!r}, "
            f"dimension={self.dimension}, device={self.device!r})"
        )

    def prepare(self) -> None:
        """Choose the local runtime before indexing so the stored revision matches the vectors."""
        if self._prepared:
            return
        if (self.backend_preference or "").strip().lower() == "onnx":
            if not _onnx_cached(self.cache_dir):
                raise EmbeddingError("local BGE-M3 ONNX weights are not in the local cache")
            self.model_revision = ONNX_MODEL_REVISION
            self.backend = "onnx"
            self.device = "onnx-cpu"
            self._prepared = True
            return
        self._prepared = True
        revision, device, backend = planned_bge_runtime(self.cache_dir, self.model_revision, self.requested_device)
        self.model_revision = revision
        self.backend = backend
        if device:
            self.device = device

    def embed_query(self, text: str) -> list[float]:
        """Embed one query with the same model, revision, and normalization as documents."""
        return self.embed_texts([text])[0]

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            raw = self._encode(list(texts))
        except EmbeddingError:
            raise
        except Exception as exc:
            raise EmbeddingError(f"local BGE-M3 embedding failed ({type(exc).__name__})") from None
        vectors = [_as_unit_vector(row, self.dimension) for row in raw]
        _validate_vectors(vectors, len(texts), self.dimension)
        return vectors

    def _encode(self, texts: list[str]):
        model = self._load()
        if self.backend == "onnx":
            return model.encode(texts, self.batch_size)
        output = model.encode(
            texts,
            batch_size=self.batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        if isinstance(output, dict):
            output = output.get("dense_vecs", output.get("sentence_embedding"))
        return output

    def _load(self):
        if self._model is not None:
            return self._model
        self.prepare()
        if self.backend == "onnx":
            self._model = _OnnxBgeSession(self.cache_dir)
            self.device = "onnx-cpu"
            return self._model
        os.environ.setdefault("HF_HOME", str(self.cache_dir))
        os.environ.setdefault("HF_HUB_CACHE", str(self.cache_dir / "hub"))
        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
        try:
            from sentence_transformers import SentenceTransformer
        except Exception as exc:
            raise EmbeddingError(f"sentence-transformers is not available ({type(exc).__name__})") from None
        devices = _candidate_devices(self.requested_device)
        failures: list[str] = []
        for device in devices:
            try:
                model = SentenceTransformer(
                    self.model_name,
                    device=device,
                    revision=self.model_revision,
                    cache_folder=str(self.cache_dir / "hub"),
                    local_files_only=_revision_cached(self.cache_dir, self.model_revision),
                )
                width = int(model.get_sentence_embedding_dimension())
                if width != self.dimension:
                    raise EmbeddingError(f"BGE-M3 returned dimension {width}")
                self._model = model
                self.device = device
                return model
            except EmbeddingError:
                raise
            except Exception as exc:
                failures.append(f"{device}:{type(exc).__name__}")
                self._model = None
        raise EmbeddingError("local BGE-M3 model load failed (" + ", ".join(failures) + ")")


def planned_bge_runtime(cache_dir: Path, configured_revision: str, requested_device: str) -> tuple[str, str, str]:
    """Return revision, device label, and backend for the runtime this machine can execute."""
    choice = (requested_device or "auto").strip().lower()
    if choice not in {"auto", "cpu", "cuda"}:
        raise EmbeddingError("BGE_DEVICE must be auto, cpu, or cuda")
    torch_ready = _torch_runtime_available(cache_dir)
    if choice == "cuda" and not torch_ready:
        raise EmbeddingError("CUDA was requested but PyTorch cannot be loaded")
    if torch_ready:
        return configured_revision, choice, "sentence-transformers"
    return ONNX_MODEL_REVISION, "onnx-cpu", "onnx"


def _torch_runtime_available(cache_dir: Path) -> bool:
    marker = cache_dir / "torch_dll_blocked"
    if marker.is_file():
        return False
    try:
        import torch
    except OSError as exc:
        text = str(exc)
        if getattr(exc, "winerror", None) == 4551 or "Application Control" in text:
            cache_dir.mkdir(parents=True, exist_ok=True)
            marker.write_text(text, encoding="utf-8")
            return False
        raise EmbeddingError(f"PyTorch could not be imported ({type(exc).__name__})") from None
    return torch is not None


class _OnnxBgeSession:
    """CLS-pooled dense vectors from the quantized BGE-M3 ONNX graph."""

    def __init__(self, cache_dir: Path):
        os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
        try:
            from huggingface_hub import snapshot_download
            from tokenizers import Tokenizer
            import onnxruntime as ort
        except Exception as exc:
            raise EmbeddingError(f"ONNX BGE-M3 runtime is not available ({type(exc).__name__})") from None
        try:
            snapshot = snapshot_download(
                repo_id=ONNX_REPO,
                revision=ONNX_REVISION,
                allow_patterns=[ONNX_WEIGHTS, "tokenizer.json", "tokenizer_config.json", "special_tokens_map.json", "config.json"],
                cache_dir=str(cache_dir / "hub"),
                local_files_only=_onnx_cached(cache_dir),
            )
        except Exception as exc:
            raise EmbeddingError(f"local BGE-M3 ONNX weights could not be opened ({type(exc).__name__})") from None
        snapshot_path = Path(snapshot)
        self.tokenizer = Tokenizer.from_file(str(snapshot_path / "tokenizer.json"))
        self.tokenizer.enable_truncation(max_length=8192)
        self.tokenizer.enable_padding(pad_id=1, pad_token="<pad>")
        options = ort.SessionOptions()
        options.intra_op_num_threads = max(1, min(4, os.cpu_count() or 1))
        self.session = ort.InferenceSession(
            str(snapshot_path / ONNX_WEIGHTS),
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )

    def encode(self, texts: list[str], batch_size: int):
        import numpy as np

        rows = []
        step = max(1, batch_size)
        for start in range(0, len(texts), step):
            encoded = self.tokenizer.encode_batch(texts[start : start + step])
            inputs = {
                "input_ids": np.asarray([item.ids for item in encoded], dtype=np.int64),
                "attention_mask": np.asarray([item.attention_mask for item in encoded], dtype=np.int64),
            }
            hidden = self.session.run(None, inputs)[0]
            rows.extend(hidden[:, 0, :])
        return rows


def _onnx_cached(cache_dir: Path) -> bool:
    snapshot = cache_dir / "hub" / "models--Xenova--bge-m3" / "snapshots" / ONNX_REVISION / ONNX_WEIGHTS
    return snapshot.is_file() and snapshot.stat().st_size > 1_000_000


def _bge_cache_dir() -> Path:
    configured = os.environ.get("HF_HOME", "").strip()
    path = Path(configured) if configured else Path(__file__).resolve().parents[1] / ".cache" / "huggingface"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _revision_cached(cache_dir: Path, revision: str) -> bool:
    snapshot = cache_dir / "hub" / "models--BAAI--bge-m3" / "snapshots" / revision
    return snapshot.is_dir() and any(snapshot.iterdir())


def _candidate_devices(requested: str) -> list[str]:
    choice = (requested or "auto").strip().lower()
    cuda = False
    try:
        import torch

        cuda = bool(torch.cuda.is_available())
    except Exception:
        cuda = False
    if choice == "cpu":
        return ["cpu"]
    if choice == "cuda":
        if not cuda:
            raise EmbeddingError("CUDA was requested but is not available")
        return ["cuda", "cpu"]
    if choice != "auto":
        raise EmbeddingError("BGE_DEVICE must be auto, cpu, or cuda")
    return ["cuda", "cpu"] if cuda else ["cpu"]


def _as_unit_vector(row, dimension: int) -> list[float]:
    values = [float(value) for value in list(row)]
    if len(values) != dimension or any(not math.isfinite(value) for value in values):
        raise EmbeddingError("local BGE-M3 returned a vector with the wrong shape")
    norm = math.sqrt(sum(value * value for value in values))
    if norm == 0:
        raise EmbeddingError("local BGE-M3 returned a zero vector")
    if abs(norm - 1.0) > 1e-3:
        values = [value / norm for value in values]
    return values


def _validate_vectors(vectors: list[list[float]], expected_count: int, dimension: int) -> None:
    if len(vectors) != expected_count:
        raise EmbeddingError("embedding provider returned an unexpected batch size")
    for vector in vectors:
        if len(vector) != dimension or any(not math.isfinite(value) for value in vector):
            raise EmbeddingError("embedding provider returned a vector with the wrong shape")
