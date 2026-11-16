"""Side-by-side adapters for dictionary search and local BGE-M3 search.

The dictionary module is loaded from the course file and called as-is.
This module does not change that file, its SQL, or its result ordering.
"""

from __future__ import annotations

import importlib.util
import time
from pathlib import Path

from pydantic import ValidationError

from .config import DEFAULT_DICTIONARY_SCRIPT, configured_dictionary_script, configured_sqlite_path
from .schemas import MAX_TOP_K, FilterSet, SearchRequest
from .search import SearchFailure, SearchService

DICTIONARY_SCRIPT = DEFAULT_DICTIONARY_SCRIPT
MODES = ("dictionary", "semantic", "compare", "semantic-fallback")
SYSTEMS = {
    "dictionary": "dictionary-sqlite",
    "semantic": "local-bge-m3",
    "neo4j_ngram_demo": "not-invoked",
}
SCORE_NOTE = "Dictionary match reasons and semantic similarity scores are separate and are not ranked against each other."
INFRASTRUCTURE_CODES = {
    "model_unavailable",
    "qdrant_unavailable",
    "sqlite_unavailable",
    "collection_unavailable",
    "collection_incompatible",
    "semantic_unavailable",
}


class DictionaryUnavailable(RuntimeError):
    """The original dictionary search could not be called."""


def load_dictionary_module(path: Path = DICTIONARY_SCRIPT):
    """Load the course search module without adding its directory to the import path."""
    if not path.is_file():
        raise DictionaryUnavailable("Dictionary search is unavailable")
    spec = importlib.util.spec_from_file_location("s1g14_dictionary_search", path)
    if spec is None or spec.loader is None:
        raise DictionaryUnavailable("Dictionary search is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_request(query: str, top_k: int, filters: dict | None) -> dict | None:
    if not isinstance(query, str) or not query.strip():
        return _error("invalid_request", "query must not be empty")
    if not isinstance(top_k, int) or not 1 <= top_k <= MAX_TOP_K:
        return _error("invalid_request", "top_k must be an integer from 1 through 105")
    if filters:
        unknown = sorted(set(filters) - set(FilterSet.model_fields))
        if unknown:
            return _error("invalid_request", "Unknown filter fields were provided.")
    return None


class DictionarySearchAdapter:
    """Call the original dictionary search function. SQL and ordering stay in that function."""

    backend = "dictionary-sqlite"

    def __init__(self, module=None, db_path: Path | None = None, script_path: Path | None = None):
        self.module = module
        self.db_path = configured_sqlite_path() if db_path is None else db_path
        self.script_path = configured_dictionary_script() if script_path is None else script_path

    def report_backend_status(self) -> dict:
        try:
            self._module()
        except DictionaryUnavailable as exc:
            return {"backend": self.backend, "available": False, "message": str(exc)}
        return {"backend": self.backend, "available": True, "message": "ready"}

    def search(self, query: str, filters: dict | None = None, top_k: int = 5) -> dict:
        started = time.perf_counter()
        problem = validate_request(query, top_k, filters)
        if problem:
            return _backend_envelope("dictionary", "dictionary-sqlite", query, False, problem, started)
        warnings = []
        applied = _present_filters(filters)
        if applied:
            warnings.append("Separate filters were not applied. Dictionary search used only its original query parser.")
        try:
            original = self._module().search(query, self.db_path, top_k)
        except DictionaryUnavailable as exc:
            return _backend_envelope("dictionary", "dictionary-sqlite", query, False, _error("dictionary_unavailable", str(exc)), started)
        except Exception:
            return _backend_envelope(
                "dictionary",
                "dictionary-sqlite",
                query,
                False,
                _error("dictionary_unavailable", "Dictionary search is unavailable"),
                started,
            )
        return _from_dictionary(query, original, warnings, started)

    def _module(self):
        if self.module is None:
            self.module = load_dictionary_module(self.script_path)
        return self.module


class BGEM3SearchAdapter:
    """Reuse the Phase 4 search service. This adapter does not embed documents or write to Qdrant."""

    backend = "local-bge-m3"

    def __init__(self, service: SearchService):
        self.service = service

    def report_backend_status(self) -> dict:
        try:
            ready = self.service.ready()
        except SearchFailure as exc:
            return {"backend": self.backend, "available": False, "message": exc.message}
        return {"backend": self.backend, "available": True, "message": ready["status"]}

    def search(self, query: str, filters: dict | None = None, top_k: int = 5) -> dict:
        started = time.perf_counter()
        problem = validate_request(query, top_k, filters)
        if problem:
            return _backend_envelope("semantic", self.backend, query, False, problem, started)
        try:
            self.service.start()
            request = _semantic_request(query, top_k, filters)
            payload = self.service.search(request)
        except ValidationError:
            return _backend_envelope("semantic", self.backend, query, False, _error("invalid_filter", "One or more filters are invalid."), started)
        except SearchFailure as exc:
            return _backend_envelope("semantic", self.backend, query, False, _error(exc.code, exc.message), started)
        return _from_semantic(query, payload, started)

    def close(self) -> None:
        self.service.close()


def dispatch(mode: str, query: str, top_k: int = 5, filters: dict | None = None, dictionary=None, semantic=None) -> dict:
    """Run one explicit mode. Semantic mode does not call the dictionary adapter."""
    if mode not in MODES:
        return _dispatch_error(mode, _error("invalid_request", "mode must be dictionary, semantic, compare, or semantic-fallback"))
    problem = validate_request(query, top_k, filters)
    if problem:
        return _dispatch_error(mode, problem)
    if mode == "dictionary":
        return _package(mode, dictionary.search(query, filters, top_k) if dictionary else _missing("dictionary"), None)
    if mode == "semantic":
        return _package(mode, None, semantic.search(query, filters, top_k) if semantic else _missing("semantic"))
    if mode == "compare":
        dictionary_result = dictionary.search(query, filters, top_k) if dictionary else _missing("dictionary")
        semantic_result = semantic.search(query, filters, top_k) if semantic else _missing("semantic")
        return _package(mode, dictionary_result, semantic_result)
    semantic_result = semantic.search(query, filters, top_k) if semantic else _missing("semantic")
    if semantic_result.get("ok") or not _infrastructure_failure(semantic_result):
        return _package(
            mode,
            None,
            semantic_result,
            degraded=False,
            fallback_applied=False,
            active_backend="local-bge-m3" if semantic_result.get("ok") else None,
        )
    dictionary_result = dictionary.search(query, filters, top_k) if dictionary else _missing("dictionary")
    return _package(
        mode,
        dictionary_result,
        semantic_result,
        degraded=True,
        fallback_applied=True,
        fallback_reason=semantic_result.get("error"),
        active_backend="dictionary-sqlite" if dictionary_result.get("ok") else None,
    )


def _package(mode, dictionary_result, semantic_result, degraded=False, fallback_applied=False, fallback_reason=None, active_backend=None) -> dict:
    return {
        "ok": _dispatch_ok(mode, dictionary_result, semantic_result, fallback_applied),
        "mode": mode,
        "degraded": degraded,
        "fallback_applied": fallback_applied,
        "fallback_reason": fallback_reason,
        "active_backend": active_backend,
        "systems": dict(SYSTEMS),
        "score_comparison": None,
        "note": SCORE_NOTE,
        "dictionary": dictionary_result,
        "semantic": semantic_result,
    }


def _dispatch_ok(mode, dictionary_result, semantic_result, fallback_applied: bool) -> bool:
    if mode == "dictionary":
        return bool(dictionary_result and dictionary_result.get("ok"))
    if mode == "semantic":
        return bool(semantic_result and semantic_result.get("ok"))
    if mode == "compare":
        return bool(dictionary_result and dictionary_result.get("ok")) or bool(semantic_result and semantic_result.get("ok"))
    if fallback_applied:
        return bool(dictionary_result and dictionary_result.get("ok"))
    return bool(semantic_result and semantic_result.get("ok"))


def _dispatch_error(mode: str, problem: dict) -> dict:
    return _package(mode, None, None) | {"ok": False, "error": problem}


def _infrastructure_failure(result: dict) -> bool:
    code = (result.get("error") or {}).get("code")
    return code in INFRASTRUCTURE_CODES


def _missing(backend: str) -> dict:
    return _backend_envelope(backend, backend, "", False, _error(f"{backend}_unavailable", f"{backend} search is unavailable"), time.perf_counter())
    return _backend_envelope(backend, backend, "", False, _error(f"{backend}_unavailable", f"{backend} search is unavailable"), time.perf_counter())


def _semantic_request(query: str, top_k: int, filters: dict | None) -> SearchRequest:
    applied = _present_filters(filters)
    if not applied:
        return SearchRequest(query=query, top_k=top_k)
    return SearchRequest(query=query, top_k=top_k, filters=FilterSet(**applied))


def _present_filters(filters: dict | None) -> dict:
    if not filters:
        return {}
    return {key: value for key, value in filters.items() if value is not None}


def _from_dictionary(query: str, original: dict, warnings: list[str], started: float, backend: str = "dictionary-sqlite") -> dict:
    intent = original.get("intent") or {}
    message = original.get("message")
    if message:
        warnings = [*warnings, str(message)]
    unsupported = bool(intent.get("unsupported_input"))
    if unsupported or not intent.get("crop_id"):
        status = "unsupported"
        answers = False
    else:
        status = "supported"
        answers = True
    reason = _dictionary_reason(intent)
    results = [
        _row(
            query,
            "dictionary",
            backend,
            row.get("process_id"),
            intent.get("crop_id"),
            row.get("crop_name"),
            row.get("year_ce"),
            None,
            None,
            intent.get("region_code") if row.get("spatial_level") == "region" else None,
            row.get("area") if row.get("spatial_level") == "region" else None,
            row.get("area"),
            row.get("season"),
            row.get("spatial_level"),
            row.get("output_quantity"),
            row.get("output_unit"),
            row.get("source_id"),
            None,
            None,
            None,
            reason,
            answers,
            status,
        )
        for row in original.get("results") or []
    ]
    return {
        "ok": True,
        "backend": backend,
        "search_mode": "dictionary",
        "query": query,
        "availability_status": status,
        "count": len(results),
        "results": results,
        "context_results": [],
        "warnings": warnings,
        "message": message,
        "original": original,
        "error": None,
        "timing_ms": _elapsed(started),
    }


def _from_semantic(query: str, payload: dict, started: float) -> dict:
    measures = list(payload.get("unavailable_measures") or [])
    filters = payload.get("parsed_filters") or {}
    scoped = any(value is not None for value in filters.values())
    if measures and scoped:
        status = "partially_supported"
    elif measures:
        status = "unsupported"
    else:
        status = "supported"
    answers = not measures
    rows = [
        _row(
            query,
            "semantic",
            "local-bge-m3",
            item.get("process_id"),
            (item.get("crop") or {}).get("crop_id"),
            (item.get("crop") or {}).get("crop_name"),
            (item.get("year") or {}).get("year_ce"),
            (item.get("year") or {}).get("year_original"),
            (item.get("year") or {}).get("calendar"),
            (item.get("region") or {}).get("region_code"),
            (item.get("region") or {}).get("region_name"),
            (item.get("region") or {}).get("area"),
            item.get("season"),
            item.get("spatial_level"),
            item.get("production_quantity"),
            item.get("production_unit"),
            (item.get("source") or {}).get("source_id"),
            (item.get("source") or {}).get("agency"),
            (item.get("source") or {}).get("title"),
            item.get("similarity_score"),
            None,
            answers,
            status,
        )
        for item in payload.get("results") or []
    ]
    context = rows if status == "unsupported" else []
    visible = [] if status == "unsupported" else rows
    return {
        "ok": True,
        "backend": "local-bge-m3",
        "search_mode": "semantic",
        "query": query,
        "availability_status": status,
        "count": len(visible),
        "results": visible,
        "context_results": context,
        "warnings": list(payload.get("warnings") or []),
        "message": None,
        "original": payload,
        "error": None,
        "timing_ms": _elapsed(started),
    }


def _dictionary_reason(intent: dict) -> str | None:
    parts = []
    for key in ("crop_id", "region_code", "spatial_level", "season", "year_from", "year_to"):
        value = intent.get(key)
        if value is not None:
            parts.append(f"{key}={value}")
    if not parts:
        return None
    return "dictionary:" + ",".join(parts)


def _row(query, mode, backend, process_id, crop_id, crop_name, year_ce, year_original, calendar, region_code, region_name, area, season, spatial_level, quantity, unit, source_id, agency, title, score, reason, answers, status) -> dict:
    return {
        "query": query,
        "search_mode": mode,
        "backend": backend,
        "process_id": process_id,
        "crop": {"crop_id": crop_id, "crop_name": crop_name},
        "year": {"year_ce": year_ce, "year_original": year_original, "calendar": calendar},
        "region": {"region_code": region_code, "region_name": region_name, "area": area},
        "season": season,
        "spatial_level": spatial_level,
        "production_quantity": quantity,
        "production_unit": unit,
        "source": {"source_id": source_id, "agency": agency, "title": title},
        "similarity_score": score,
        "match_reason": reason,
        "answers_requested_measure": answers,
        "availability_status": status,
    }


def _backend_envelope(mode: str, backend: str, query: str, ok: bool, error: dict, started: float) -> dict:
    return {
        "ok": ok,
        "backend": backend,
        "search_mode": mode,
        "query": query,
        "availability_status": None,
        "count": 0,
        "results": [],
        "context_results": [],
        "warnings": [],
        "message": None,
        "original": None,
        "error": error,
        "timing_ms": _elapsed(started),
    }


def _error(code: str, message: str) -> dict:
    return {"code": code, "message": message}


def _elapsed(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)
