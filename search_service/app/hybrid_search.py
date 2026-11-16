"""Eligibility-first hybrid search. Dictionary scores are not combined with cosine similarity."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time

from .config import BGE_MODEL
from .database import DatabaseError
from .eligibility import eligible_process_ids, process_crops
from .embeddings import ONNX_MODEL_REVISION
from .hybrid_planner import METRIC_UNITS, HybridIntent, NumericCondition, plan_query
from .schemas import HybridSearchRequest
from .search import SearchFailure, SearchService, build_service

RANKING_METHOD = "eligibility-first-bge-m3"


class HybridSearch:
    """Plan, restrict to SQLite-eligible ids, then rank those ids with the existing BGE-M3 index."""

    def __init__(self, service: SearchService):
        self.service = service

    def search(self, request: HybridSearchRequest) -> dict:
        started = time.perf_counter()
        timings = {
            "parse": None,
            "eligibility": None,
            "embed": None,
            "collection_validation": None,
            "qdrant": None,
            "sqlite": None,
            "total": None,
        }
        catalog = self.service._catalog()
        explicit = request.effective_filters()
        self.service._validate_explicit(explicit, catalog)
        parse_started = time.perf_counter()
        intent = plan_query(request.query, catalog.sources, explicit)
        if request.numeric is not None:
            intent = _replace_numeric(intent, request.numeric)
        timings["parse"] = _elapsed(parse_started)
        if intent.availability() == "unsupported":
            return _response(request, intent, [], [], [], timings, started, embedded=False)
        eligibility_started = time.perf_counter()
        try:
            connection = self.service.open_relational()
            try:
                if self.service.relational is None:
                    eligible = eligible_process_ids(
                        connection,
                        crop_ids=intent.crops,
                        year_from=intent.year_from,
                        year_to=intent.year_to,
                        region_code=intent.region_code,
                        season=intent.season,
                        spatial_level=intent.spatial_level,
                        source_id=intent.source_id,
                        numeric=intent.applied_numeric,
                    )
                    crop_of = process_crops(connection, eligible)
                else:
                    eligible = self.service.relational.eligible_process_ids(
                        connection,
                        crop_ids=intent.crops,
                        year_from=intent.year_from,
                        year_to=intent.year_to,
                        region_code=intent.region_code,
                        season=intent.season,
                        spatial_level=intent.spatial_level,
                        source_id=intent.source_id,
                        numeric=intent.applied_numeric,
                    )
                    crop_of = self.service.relational.process_crops(connection, eligible)
            finally:
                connection.close()
        except (DatabaseError, sqlite3.Error) as exc:
            raise self.service._relational_failure() from exc
        timings["eligibility"] = _elapsed(eligibility_started)
        if not eligible:
            missing = list(intent.crops) if intent.grouped else []
            if missing:
                intent.warnings.append("No eligible records exist for: " + ", ".join(missing) + ".")
            return _response(request, intent, eligible, [], missing, timings, started, embedded=False)
        embed_started = time.perf_counter()
        vector = self.service.embed_query_vector(request.query)
        timings["embed"] = _elapsed(embed_started)
        timings["collection_validation"] = self.service.ensure_compatible_collection()
        qdrant_started = time.perf_counter()
        hits = self.service.search_eligible_ids(vector, eligible)
        timings["qdrant"] = _elapsed(qdrant_started)
        allowed = set(eligible)
        ranked = sorted(
            (hit for hit in hits if hit.process_id in allowed),
            key=lambda hit: (-hit.score, hit.process_id),
        )
        if len(ranked) < min(len(eligible), request.top_k) and len(hits) < len(eligible):
            intent.warnings.append("Qdrant did not return every eligible process, so only the returned eligible rows were ranked.")
        selected, missing_groups, omitted_groups = _select(ranked, crop_of, intent.crops, intent.grouped, request.top_k)
        if omitted_groups:
            intent.warnings.append(
                "top_k is smaller than the number of requested crops with data, so these crops were omitted: "
                + ", ".join(omitted_groups)
                + "."
            )
        if missing_groups:
            intent.warnings.append("No eligible records exist for: " + ", ".join(missing_groups) + ".")
        sqlite_started = time.perf_counter()
        records = self.service.hydrate_records([hit.process_id for hit in selected])
        timings["sqlite"] = _elapsed(sqlite_started)
        results = []
        for hit in selected:
            record = records.get(hit.process_id)
            if record is None:
                intent.warnings.append("An eligible ranked id had no SQLite record and was omitted.")
                continue
            results.append(_result(hit.score, record, intent))
        return _response(request, intent, eligible, results, missing_groups, timings, started, embedded=True, omitted_groups=omitted_groups)

    def search_text(self, query: str, top_k: int = 5, filters: dict | None = None) -> dict:
        from .schemas import FilterSet

        present = {key: value for key, value in (filters or {}).items() if value is not None}
        body = HybridSearchRequest(query=query, top_k=top_k, filters=FilterSet(**present) if present else None)
        return self.search(body)


def _replace_numeric(intent: HybridIntent, numeric) -> HybridIntent:
    expected_unit = METRIC_UNITS[numeric.metric]
    if numeric.unit != expected_unit:
        raise SearchFailure(422, "invalid_filter", "The numeric unit does not match the metric stored in SQLite.")
    if intent.numeric:
        intent.warnings.append("The explicit numeric constraint overrides a comparison found in the query.")
    intent.numeric = (
        NumericCondition(numeric.metric, numeric.operator, float(numeric.threshold), numeric.unit, True, None),
    )
    return intent


def _select(ranked, crop_of: dict[str, str], crops: tuple[str, ...], grouped: bool, top_k: int):
    ranked = [hit for hit in ranked if hit.process_id in crop_of]
    if not grouped or len(crops) <= 1:
        return ranked[:top_k], [], []
    present = [crop for crop in crops if any(crop_of[hit.process_id] == crop for hit in ranked)]
    missing = [crop for crop in crops if crop not in present]
    chosen = []
    used = set()
    for crop in present:
        for hit in ranked:
            if crop_of[hit.process_id] == crop and hit.process_id not in used:
                chosen.append(hit)
                used.add(hit.process_id)
                break
    omitted = []
    if len(chosen) > top_k:
        omitted = [crop_of[hit.process_id] for hit in chosen[top_k:]]
        chosen = chosen[:top_k]
    else:
        for hit in ranked:
            if hit.process_id not in used:
                chosen.append(hit)
                used.add(hit.process_id)
            if len(chosen) >= top_k:
                break
    chosen = sorted(chosen, key=lambda hit: (-hit.score, hit.process_id))
    return chosen, missing, omitted


def _result(score: float, record, intent: HybridIntent) -> dict:
    quantity = None if record.quantity_conflict else record.production_quantity
    unit = None if record.quantity_conflict else record.production_unit
    if record.quantity_conflict:
        intent.warnings.append("A process had more than one output quantity, so that quantity was omitted.")
    answers = intent.availability() == "supported"
    return {
        "process_id": record.process_id,
        "crop": {"crop_id": record.crop_id, "crop_name": record.crop_name},
        "year": {"year_ce": record.year_ce, "year_original": record.year_original, "calendar": record.calendar},
        "region": {"region_code": record.region_code, "region_name": record.region_name, "area": record.area},
        "season": record.season,
        "spatial_level": record.spatial_level,
        "production_quantity": quantity,
        "production_unit": unit,
        "indicators": [
            {"metric_code": item.metric_code, "value": item.value, "unit": item.unit} for item in record.indicators
        ],
        "source": {"source_id": record.source_id, "agency": record.agency, "title": record.title},
        "similarity_score": score,
        "eligibility_reason": _reason(intent),
        "answers_requested_measure": answers,
    }


def _reason(intent: HybridIntent) -> str:
    filters = intent.applied_filters()
    parts = []
    if filters["crop_ids"]:
        parts.append("crop_id=" + ",".join(filters["crop_ids"]))
    if filters["year_from"] is not None:
        parts.append(f"year_from={filters['year_from']}")
        parts.append(f"year_to={filters['year_to']}")
    for key in ("region_code", "season", "spatial_level", "source_id"):
        if filters[key] is not None:
            parts.append(f"{key}={filters[key]}")
    for condition in intent.applied_numeric:
        parts.append(f"{condition.metric}{condition.operator}{format_threshold(condition.threshold)}{condition.unit}")
    return "eligible:" + ",".join(parts) if parts else "eligible:all-processes"


def format_threshold(value: float) -> str:
    """Render a threshold for an explanation. The numeric comparison still uses the original float."""
    text = format(float(value), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _response(request, intent, eligible, results, missing_groups, timings, started, embedded: bool, omitted_groups=None) -> dict:
    timings["total"] = _elapsed(started)
    return {
        "ok": True,
        "query": request.query,
        "search_mode": "hybrid",
        "availability_status": intent.availability(),
        "parsed_intent": intent.as_dict(),
        "requested_measure": list(intent.measures) or ["production"],
        "applied_filters": intent.applied_filters(),
        "applied_numeric": [item.as_dict() for item in intent.applied_numeric],
        "unapplied_conditions": list(intent.unapplied_conditions),
        "eligible_count": len(eligible),
        "count": len(results),
        "results": results,
        "context_results": [],
        "missing_groups": missing_groups,
        "omitted_groups": list(omitted_groups or []),
        "warnings": list(dict.fromkeys(intent.warnings)),
        "ranking_method": RANKING_METHOD,
        "embedding_model": BGE_MODEL,
        "model_revision": ONNX_MODEL_REVISION,
        "embedding_skipped": not embedded,
        "score_comparison": None,
        "timing_ms": timings,
    }


def _elapsed(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run eligibility-first hybrid search.")
    parser.add_argument("--query", required=True)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--crop-id", default=None)
    parser.add_argument("--year-ce", type=int, default=None)
    parser.add_argument("--region-code", default=None)
    parser.add_argument("--season", default=None)
    parser.add_argument("--spatial-level", default=None)
    parser.add_argument("--source-id", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    service = build_service()
    try:
        payload = HybridSearch(service).search_text(
            args.query,
            args.top_k,
            {
                "crop_id": args.crop_id,
                "year_ce": args.year_ce,
                "region_code": args.region_code,
                "season": args.season,
                "spatial_level": args.spatial_level,
                "source_id": args.source_id,
            },
        )
    except SearchFailure as exc:
        payload = {"ok": False, "search_mode": "hybrid", "error": {"code": exc.code, "message": exc.message}}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 1
    finally:
        service.close()
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
