"""HTTP view for side-by-side search. Rankings stay inside each backend."""

from __future__ import annotations

from .adapters import SCORE_NOTE


def comparison_view(payload: dict, query: str, filters: dict | None, total_ms: float) -> dict:
    """Shape a dispatch result for POST /compare without merging scores."""
    dictionary = _public_value(payload.get("dictionary"))
    semantic = _public_value(payload.get("semantic"))
    reasons = _comparability_reasons(dictionary, semantic, filters)
    return {
        "query": query,
        "mode": payload.get("mode"),
        "ok": payload.get("ok"),
        "availability_status": {
            "dictionary": _status(dictionary),
            "semantic": _status(semantic),
        },
        "dictionary": dictionary,
        "semantic": semantic,
        "normalized_results": {
            "dictionary": _results(dictionary),
            "semantic": _results(semantic),
        },
        "original": {
            "dictionary": _public_value((dictionary or {}).get("original")),
            "semantic": _public_value((semantic or {}).get("original")),
        },
        "warnings": _warnings(dictionary, semantic, reasons),
        "errors": _errors(payload, dictionary, semantic),
        "degraded": bool(payload.get("degraded")),
        "fallback_applied": bool(payload.get("fallback_applied")),
        "fallback_reason": payload.get("fallback_reason"),
        "active_backend": payload.get("active_backend"),
        "systems": payload.get("systems"),
        "score_comparison": None,
        "note": payload.get("note") or SCORE_NOTE,
        "filter_comparability": {
            "directly_comparable": not reasons,
            "reasons": reasons,
        },
        "timing_ms": _timing(dictionary, semantic, total_ms),
    }


def _comparability_reasons(dictionary: dict | None, semantic: dict | None, filters: dict | None) -> list[str]:
    reasons = []
    applied = {key: value for key, value in (filters or {}).items() if value is not None}
    if applied:
        reasons.append(
            "Separate filters were applied by semantic search only. "
            "Dictionary search used its original query parser, so the eligible record sets are not directly comparable."
        )
    if dictionary and semantic and dictionary.get("ok") and semantic.get("ok"):
        left = _dictionary_constraints(dictionary)
        right = _semantic_constraints(semantic)
        if left != right:
            reasons.append("The two backends inferred different structured constraints, so they searched different eligible record sets.")
        if _status(dictionary) != _status(semantic):
            reasons.append("The two backends assigned different availability statuses.")
    return reasons


def _dictionary_constraints(section: dict) -> dict:
    intent = ((section.get("original") or {}).get("intent")) or {}
    year = intent.get("year_from") if intent.get("year_from") == intent.get("year_to") else None
    return {
        "crop_id": intent.get("crop_id"),
        "year_ce": year,
        "region_code": intent.get("region_code"),
        "season": intent.get("season"),
        "spatial_level": intent.get("spatial_level"),
    }


def _semantic_constraints(section: dict) -> dict:
    parsed = ((section.get("original") or {}).get("parsed_filters")) or {}
    return {key: parsed.get(key) for key in ("crop_id", "year_ce", "region_code", "season", "spatial_level")}


def _warnings(dictionary: dict | None, semantic: dict | None, reasons: list[str]) -> list[str]:
    found = list(reasons)
    for section in (dictionary, semantic):
        for warning in (section or {}).get("warnings") or []:
            if warning not in found:
                found.append(warning)
    return found


def _errors(payload: dict, dictionary: dict | None, semantic: dict | None) -> dict:
    errors = {}
    if payload.get("error"):
        errors["request"] = payload["error"]
    for name, section in (("dictionary", dictionary), ("semantic", semantic)):
        if section and section.get("error"):
            errors[name] = section["error"]
    return errors


def _timing(dictionary: dict | None, semantic: dict | None, total_ms: float) -> dict:
    semantic_original = ((semantic or {}).get("original") or {}).get("timing_ms") or {}
    return {
        "dictionary": (dictionary or {}).get("timing_ms"),
        "semantic": (semantic or {}).get("timing_ms"),
        "embed": semantic_original.get("embed"),
        "qdrant": semantic_original.get("qdrant"),
        "sqlite": semantic_original.get("sqlite"),
        "total": total_ms,
    }


def _status(section: dict | None):
    if not section:
        return None
    return section.get("availability_status")


def _results(section: dict | None) -> list:
    if not section:
        return []
    return list(section.get("results") or [])


def _public_value(value):
    """Drop filesystem paths from a backend payload before it leaves the API."""
    if isinstance(value, dict):
        return {key: _public_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_public_value(item) for item in value]
    if isinstance(value, str) and ("\\" in value or value.startswith("/") or value.lower().startswith("file:")):
        return None
    return value
