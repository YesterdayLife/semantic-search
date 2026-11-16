"""Runtime configuration. Secrets come from the environment, never from code."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

SEARCH_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SQLITE_PATH = Path(r"D:\Final Project\Hee_M3\output\S1-G14_M3.sqlite")
DEFAULT_DICTIONARY_SCRIPT = Path(r"D:\Final Project\Hee_M4\ch6 semantic search\src\semantic_search.py")
PLACEHOLDER_API_KEYS = {"", "your-openai-api-key-here", "replace-with-your-key"}

DOCUMENT_SCHEMA_VERSION = "1"
MOCK_EMBEDDING_MODEL = "mock-deterministic-v1"
REAL_COLLECTION = "crop_process"
MOCK_COLLECTION = "crop_process_mock"
BGE_COLLECTION = "crop_process_bge_m3"
EMBEDDING_DIMENSION = 1536
BGE_DIMENSION = 1024
OPENAI_MODEL = "text-embedding-3-small"
BGE_MODEL = "BAAI/bge-m3"
# Latest main revision of the official BAAI/bge-m3 repository as of this phase.
BGE_REVISION = "5617a9f61b028005a4858fdac845db406aefb181"
BGE_PROVIDER = "local-bge-m3"


def load_dotenv(path: Path | None = None) -> None:
    """Load search_service/.env without overriding variables already set."""
    env_path = path or (SEARCH_ROOT / ".env")
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


@dataclass(frozen=True)
class Settings:
    sqlite_path: Path
    qdrant_url: str
    qdrant_collection: str
    qdrant_mock_collection: str
    openai_model: str
    embedding_dimension: int
    openai_api_key: str
    document_schema_version: str
    batch_size: int
    qdrant_bge_collection: str
    bge_model: str
    bge_revision: str
    bge_dimension: int
    bge_batch_size: int
    bge_device: str
    data_backend: str
    vector_backend: str
    database_url: str
    dictionary_script: Path

    @property
    def api_key_configured(self) -> bool:
        return self.openai_api_key.strip() not in PLACEHOLDER_API_KEYS

    def collection_for(self, mode: str) -> str:
        if mode == "real":
            return self.qdrant_collection
        if mode == "mock":
            return self.qdrant_mock_collection
        if mode == "local-bge-m3":
            return self.qdrant_bge_collection
        raise ValueError(f"unsupported mode: {mode}")


def load_settings() -> Settings:
    load_dotenv()
    batch_size = _int_env("EMBEDDING_BATCH_SIZE", 64)
    if not 1 <= batch_size <= 256:
        raise ValueError("EMBEDDING_BATCH_SIZE must be between 1 and 256")
    bge_batch_size = _int_env("BGE_BATCH_SIZE", 8)
    if not 1 <= bge_batch_size <= 32:
        raise ValueError("BGE_BATCH_SIZE must be between 1 and 32")
    dimension = _int_env("EMBEDDING_DIMENSION", EMBEDDING_DIMENSION)
    if dimension != EMBEDDING_DIMENSION:
        raise ValueError(f"EMBEDDING_DIMENSION must be {EMBEDDING_DIMENSION}")
    bge_dimension = _int_env("BGE_EMBEDDING_DIMENSION", BGE_DIMENSION)
    if bge_dimension != BGE_DIMENSION:
        raise ValueError(f"BGE_EMBEDDING_DIMENSION must be {BGE_DIMENSION}")
    data_backend = os.environ.get("DATA_BACKEND", "sqlite").strip().lower() or "sqlite"
    vector_backend = os.environ.get("VECTOR_BACKEND", "qdrant").strip().lower() or "qdrant"
    database_url = os.environ.get("DATABASE_URL", "").strip()
    _validate_backends(data_backend, vector_backend, database_url)
    return Settings(
        sqlite_path=configured_sqlite_path(),
        qdrant_url=os.environ.get("QDRANT_URL", "http://127.0.0.1:6333").rstrip("/"),
        qdrant_collection=os.environ.get("QDRANT_COLLECTION", REAL_COLLECTION),
        qdrant_mock_collection=os.environ.get("QDRANT_MOCK_COLLECTION", MOCK_COLLECTION),
        openai_model=os.environ.get("OPENAI_MODEL", OPENAI_MODEL),
        embedding_dimension=dimension,
        openai_api_key=os.environ.get("OPENAI_API_KEY", ""),
        document_schema_version=os.environ.get("DOCUMENT_SCHEMA_VERSION", DOCUMENT_SCHEMA_VERSION),
        batch_size=batch_size,
        qdrant_bge_collection=os.environ.get("QDRANT_BGE_COLLECTION", BGE_COLLECTION),
        bge_model=os.environ.get("BGE_MODEL", BGE_MODEL),
        bge_revision=os.environ.get("BGE_MODEL_REVISION", BGE_REVISION),
        bge_dimension=bge_dimension,
        bge_batch_size=bge_batch_size,
        bge_device=os.environ.get("BGE_DEVICE", "auto"),
        data_backend=data_backend,
        vector_backend=vector_backend,
        database_url=database_url,
        dictionary_script=configured_dictionary_script(),
    )


def configured_sqlite_path() -> Path:
    """SQLite location for this process. SQLITE_PATH overrides the Windows default."""
    raw = os.environ.get("SQLITE_PATH", "").strip()
    return Path(raw) if raw else DEFAULT_SQLITE_PATH


def configured_dictionary_script() -> Path:
    """Course dictionary file for this process. DICTIONARY_SCRIPT overrides the Windows default."""
    raw = os.environ.get("DICTIONARY_SCRIPT", "").strip()
    return Path(raw) if raw else DEFAULT_DICTIONARY_SCRIPT


def _validate_backends(data_backend: str, vector_backend: str, database_url: str) -> None:
    """Accept only the local pair or the explicit cloud pair.

    A postgres setting without DATABASE_URL fails here. It does not fall
    back to SQLite. The URL itself is never included in the error.
    """
    if data_backend not in {"sqlite", "postgres"}:
        raise ValueError("DATA_BACKEND must be sqlite or postgres")
    if vector_backend not in {"qdrant", "pgvector"}:
        raise ValueError("VECTOR_BACKEND must be qdrant or pgvector")
    if (data_backend, vector_backend) not in {("sqlite", "qdrant"), ("postgres", "pgvector")}:
        raise ValueError("DATA_BACKEND and VECTOR_BACKEND combination is not supported")
    if data_backend == "postgres" and not database_url:
        raise ValueError("DATABASE_URL is required when DATA_BACKEND is postgres")
