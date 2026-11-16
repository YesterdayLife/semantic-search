"""Exact pgvector ranking for the 105-point BGE-M3 collection.

This store speaks the same search_points contract as QdrantStore. It ranks
only the rows that satisfy the filter, including an eligible process-id list.
It does not create an approximate index and it does not open a database
until a connection factory is supplied or PostgreSQL is explicitly configured.
"""

from __future__ import annotations

from .config import BGE_COLLECTION, BGE_MODEL
from .database import DatabaseError
from .embeddings import ONNX_MODEL_REVISION
from .qdrant_store import CollectionStatus, QdrantRequestError, ScoredPoint

_FILTER_COLUMNS = {
    "process_id",
    "crop_id",
    "year_ce",
    "season",
    "spatial_level",
    "region_code",
    "source_id",
}
_VECTOR_DIMENSION = 1024


class PgvectorStore:
    """Cosine similarity is 1 minus pgvector cosine distance."""

    def __init__(self, relational):
        self.relational = relational

    def close(self) -> None:
        return None

    def collection_status(self, name: str) -> CollectionStatus:
        if name != BGE_COLLECTION:
            return CollectionStatus(False, None, None, None)
        connection = self._connect()
        try:
            row = _one(
                connection,
                """
                SELECT
                  COUNT(*) AS points,
                  COUNT(DISTINCT vector_dimension) AS dimensions,
                  MIN(vector_dimension) AS vector_dimension,
                  COUNT(DISTINCT model_revision) AS revisions
                FROM process_embeddings
                """,
            )
        finally:
            connection.close()
        if row is None or int(row[0]) == 0 or int(row[1]) != 1 or int(row[3]) != 1:
            return CollectionStatus(True, None, "cosine", None if row is None else int(row[0]))
        return CollectionStatus(True, int(row[2]), "cosine", int(row[0]))

    def sample_payload(self, name: str) -> dict | None:
        if name != BGE_COLLECTION:
            return None
        connection = self._connect()
        try:
            row = _one(
                connection,
                """
                SELECT embedding_model, embedding_provider, model_revision, vector_dimension
                FROM process_embeddings
                ORDER BY process_id
                LIMIT 1
                """,
            )
        finally:
            connection.close()
        if row is None:
            return None
        return {
            "embedding_model": row[0],
            "embedding_provider": row[1],
            "model_revision": row[2],
            "vector_dimension": row[3],
        }

    def search_points(self, name: str, vector: list[float], limit: int, query_filter: dict | None) -> list[ScoredPoint]:
        """Rank matching rows before returning them. Ineligible ids are not scored."""
        if name != BGE_COLLECTION:
            raise QdrantRequestError("pgvector search is bound to the BGE-M3 table")
        _require_query_vector(vector)
        where, params = _filter_clause(query_filter)
        if where is None:
            return []
        vector_text = _vector_literal(vector)
        sql = (
            "SELECT process_id, point_id::text, (embedding <=> %s::vector) AS cosine_distance, "
            "crop_id, year_ce, season, spatial_level, region_code, source_id, "
            "embedding_model, embedding_provider, model_revision, vector_dimension, text_hash, "
            "document_schema_version "
            "FROM process_embeddings "
            f"{where} "
            "ORDER BY embedding <=> %s::vector, process_id "
            "LIMIT %s"
        )
        connection = self._connect()
        try:
            rows = _all(connection, sql, [vector_text, *params, vector_text, int(limit)])
        finally:
            connection.close()
        found = []
        for row in rows:
            distance = float(row[2])
            payload = {
                "process_id": row[0],
                "crop_id": row[3],
                "year_ce": row[4],
                "season": row[5],
                "spatial_level": row[6],
                "region_code": row[7],
                "source_id": row[8],
                "embedding_model": row[9],
                "embedding_provider": row[10],
                "model_revision": row[11],
                "vector_dimension": row[12],
                "text_hash": row[13],
                "document_schema_version": row[14],
            }
            if payload["model_revision"] != ONNX_MODEL_REVISION or int(payload["vector_dimension"]) != _VECTOR_DIMENSION:
                raise QdrantRequestError("pgvector row revision or dimension is incompatible")
            if payload["embedding_model"] != BGE_MODEL or payload["embedding_provider"] != "local-bge-m3":
                raise QdrantRequestError("pgvector row model metadata is incompatible")
            found.append(
                ScoredPoint(
                    point_id=str(row[1]),
                    score=1.0 - distance,
                    process_id=str(row[0]),
                    payload=payload,
                )
            )
        return found

    def _connect(self):
        try:
            return self.relational.connect()
        except DatabaseError as exc:
            raise QdrantRequestError("pgvector is unavailable") from exc


def _require_query_vector(vector: list[float]) -> None:
    if len(vector) != _VECTOR_DIMENSION or any(not _finite(value) for value in vector):
        raise QdrantRequestError("query vector dimension is incompatible")


def _finite(value) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return number == number and number not in {float("inf"), float("-inf")}


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(repr(float(value)) for value in vector) + "]"


def _filter_clause(query_filter: dict | None) -> tuple[str, list]:
    """Return a WHERE clause. None means the caller asked for an empty candidate set."""
    if not query_filter:
        return "", []
    must = query_filter.get("must") or []
    clauses = []
    params: list = []
    for item in must:
        key = item.get("key")
        if key not in _FILTER_COLUMNS:
            raise QdrantRequestError("pgvector filter field is not searchable")
        match = item.get("match") or {}
        if "any" in match:
            values = list(match["any"])
            if key != "process_id":
                raise QdrantRequestError("pgvector any-match is limited to process ids")
            if not values:
                return None, []
            clauses.append("process_id = ANY(%s)")
            params.append(values)
        elif "value" in match:
            clauses.append(f"{key} = %s")
            params.append(match["value"])
        else:
            raise QdrantRequestError("pgvector filter match is unsupported")
    if not clauses:
        return "", []
    return "WHERE " + " AND ".join(clauses), params


def _all(connection, sql: str, params: list):
    try:
        return list(connection.execute(sql, params).fetchall())
    except QdrantRequestError:
        raise
    except Exception as exc:
        raise QdrantRequestError("pgvector read failed") from exc


def _one(connection, sql: str):
    rows = _all(connection, sql, [])
    return rows[0] if rows else None
