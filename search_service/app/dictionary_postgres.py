"""Dictionary search against PostgreSQL using the course parser.

The course file is loaded and its parse_query function is called. Its SQL
file is not edited. LOCAL dictionary search still calls that file's search
function. This adapter runs only when DATA_BACKEND is postgres.
"""

from __future__ import annotations

import time
from pathlib import Path

from .adapters import (
    DictionaryUnavailable,
    _from_dictionary,
    load_dictionary_module,
    validate_request,
    _backend_envelope,
    _error,
)
from .database import DatabaseError
from .postgres_provider import PostgresDataProvider

_PLACEHOLDERS = {"?", "%s"}


class PostgresDictionaryAdapter:
    """Same parser, filters, sort, and limit as the course script, on PostgreSQL."""

    backend = "dictionary-postgres"

    def __init__(self, database_url: str, provider: PostgresDataProvider | None = None, module=None, script_path: Path | None = None):
        self.provider = provider or PostgresDataProvider(database_url)
        self.module = module
        self.script_path = script_path

    def search(self, query: str, filters: dict | None = None, top_k: int = 5) -> dict:
        started = time.perf_counter()
        problem = validate_request(query, top_k, filters)
        if problem:
            return _backend_envelope("dictionary", self.backend, query, False, problem, started)
        warnings = []
        if filters and any(value is not None for value in filters.values()):
            warnings.append("Separate filters were not applied. Dictionary search used only its original query parser.")
        try:
            module = self._module()
            intent = module.parse_query(query)
            original = self._original(module, query, intent, top_k)
        except DictionaryUnavailable as exc:
            return _backend_envelope("dictionary", self.backend, query, False, _error("dictionary_unavailable", str(exc)), started)
        except DatabaseError:
            return _backend_envelope(
                "dictionary",
                self.backend,
                query,
                False,
                _error("dictionary_unavailable", "Dictionary search is unavailable"),
                started,
            )
        except Exception:
            return _backend_envelope(
                "dictionary",
                self.backend,
                query,
                False,
                _error("dictionary_unavailable", "Dictionary search is unavailable"),
                started,
            )
        payload = _from_dictionary(query, original, warnings, started, backend=self.backend)
        return payload

    def _original(self, module, query: str, intent: dict, top_k: int) -> dict:
        if intent["unsupported_input"]:
            return {
                "query": query,
                "intent": intent,
                "count": 0,
                "results": [],
                "message": "ฐานข้อมูลนี้ยังไม่มีปริมาณ Input LCI หรือค่าผลกระทบที่ตรวจยืนยันแล้ว",
            }
        if not intent["crop_id"]:
            return {
                "query": query,
                "intent": intent,
                "count": 0,
                "results": [],
                "message": "กรุณาระบุชนิดพืชเพื่อให้ผลการค้นชัดเจน",
            }
        sql, params = dictionary_statement(intent, top_k, "%s")
        connection = self.provider.connect()
        try:
            rows = list(connection.execute(sql, params).fetchall())
        finally:
            connection.close()
        results = [
            {
                "process_id": row[0],
                "crop_name": row[1],
                "spatial_level": row[2],
                "area": row[3],
                "year_ce": row[4],
                "season": row[5],
                "output_quantity": row[6],
                "output_unit": row[7],
                "source_id": row[8],
                "source_file": row[9],
            }
            for row in rows
        ]
        message = "พบข้อมูลที่ตรงเงื่อนไข" if results else "ไม่พบข้อมูลตามเงื่อนไขในชุดข้อมูลที่มี"
        return {"query": query, "intent": intent, "count": len(results), "results": results, "message": message}

    def _module(self):
        if self.module is None:
            from .config import configured_dictionary_script

            self.module = load_dictionary_module(self.script_path or configured_dictionary_script())
        return self.module


def dictionary_statement(intent: dict, limit: int, placeholder: str = "%s") -> tuple[str, list]:
    """Reproduce the course SELECT, WHERE, ORDER BY, and LIMIT with bound parameters."""
    if placeholder not in _PLACEHOLDERS:
        raise ValueError("unsupported SQL placeholder")
    where = [f"p.crop_id = {placeholder}"]
    params: list = [intent["crop_id"]]
    for column, key in (
        ("p.region_code", "region_code"),
        ("p.spatial_level", "spatial_level"),
        ("p.season", "season"),
    ):
        if intent[key] is not None:
            where.append(f"{column} = {placeholder}")
            params.append(intent[key])
    if intent["year_from"] is not None:
        where.append(f"p.year_ce BETWEEN {placeholder} AND {placeholder}")
        params.extend([intent["year_from"], intent["year_to"]])
    sql = (
        "SELECT p.process_id, c.crop_name, p.spatial_level, p.area, p.year_ce, "
        "p.season, e.quantity AS output_quantity, e.unit AS output_unit, "
        "p.source_id, p.source_file "
        "FROM process AS p "
        "JOIN crop AS c ON c.crop_id = p.crop_id "
        "JOIN exchange AS e ON e.process_id = p.process_id AND e.direction = 'Output' "
        "WHERE " + " AND ".join(where) + f" ORDER BY p.year_ce, p.area, p.source_id LIMIT {placeholder}"
    )
    params.append(limit)
    return sql, params
