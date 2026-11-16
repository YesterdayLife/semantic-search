"""Evaluate dictionary search and local BGE-M3 search on labeled queries.

Ground-truth process ids are read from SQLite at evaluation time.
The command writes reports only under this service directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import statistics
import time
from pathlib import Path

import httpx

from .adapters import BGEM3SearchAdapter, DictionarySearchAdapter, dispatch
from .comparison import _dictionary_constraints, _semantic_constraints
from .config import DEFAULT_SQLITE_PATH
from .database import connect_readonly
from .metrics import answer_ids, macro_average, score_query
from .search import build_service

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "evaluation" / "queries.json"
DEFAULT_OUTPUT = ROOT / "evaluation" / "reports"
CATEGORIES = (
    "exact_crop",
    "thai_alias",
    "english_alias",
    "calendar_year",
    "region",
    "northeast_versus_north",
    "country_versus_region",
    "rice_season",
    "multiple_crop",
    "ambiguous",
    "missing_combination",
    "unsupported_measure",
    "unfiltered_query",
    "paraphrase",
    "numeric_condition",
)
AVAILABILITY = {"supported", "partially_supported", "unsupported"}
MEASUREMENTS = {"production", "fertilizer", "energy", "water", "carbon_footprint"}
FILTER_KEYS = ("crop_id", "year_ce", "region_code", "season", "spatial_level", "source_id")
BENCHMARK_QUERIES = (
    "มันสำปะหลังภาคเหนือปี 2566",
    "how much cassava was produced in the north in 2023",
    "fertilizer",
)
PROTECTED = {
    Path(r"D:\Final Project\Hee_M4\ch6 semantic search\src\semantic_search.py"):
        "8db66ee8ee675e43822e827375a2bba299eeed252063cc2a88f4a130e8e7cc60",
    Path(r"D:\Final Project\Hee_M4\ch6 semantic search\src\build_serving_layer.py"):
        "b770300f8835ab5c58f40d32132d4dd65530bfd2ac4692082fd3fd7caef0ca78",
    Path(r"D:\Final Project\Hee_M4\ch6 semantic search\graph\import\import.cypher"):
        "5286e190259a123aaed76fda427851a62bf126e69c71ad0a4e013070e2b3ab1d",
    ROOT / "docker-compose.yml": "109b813ad1d1e246c2fc7eef6590d1bcccfa94155299ad67fbbc903499e92b49",
}


def load_dataset(path: Path) -> list[dict]:
    cases = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(cases, list) or len(cases) < 30:
        raise ValueError("The evaluation dataset must contain at least 30 queries.")
    seen = set()
    categories = set()
    for case in cases:
        query_id = case["query_id"]
        if query_id in seen:
            raise ValueError(f"Duplicate query id {query_id}")
        seen.add(query_id)
        if case["category"] not in CATEGORIES:
            raise ValueError(f"{query_id} has an unknown category")
        categories.add(case["category"])
        for backend, status in case["expected_availability"].items():
            if status not in AVAILABILITY:
                raise ValueError(f"{query_id} has an unknown availability label")
        if case["measurement"] not in MEASUREMENTS:
            raise ValueError(f"{query_id} has an unknown measurement")
        for key in FILTER_KEYS:
            if key not in case["expected_filters"]:
                raise ValueError(f"{query_id} is missing expected filter {key}")
    missing = [category for category in CATEGORIES if category not in categories]
    if missing:
        raise ValueError("The dataset is missing categories: " + ", ".join(missing))
    return cases


def sqlite_process_ids(filters: dict, db_path: Path = DEFAULT_SQLITE_PATH) -> list[str]:
    """Return process ids matching the labeled filters. No filter means no definitive set."""
    clauses = []
    params = []
    for key in FILTER_KEYS:
        value = filters.get(key)
        if value is not None:
            clauses.append(f"{key} = ?")
            params.append(value)
    if not clauses:
        return []
    sql = "SELECT process_id FROM process WHERE " + " AND ".join(clauses) + " ORDER BY process_id"
    connection = connect_readonly(db_path)
    try:
        return [row["process_id"] for row in connection.execute(sql, params)]
    finally:
        connection.close()


def evaluate(cases: list[dict], dictionary, semantic, top_k: int, backends: set[str], db_path: Path = DEFAULT_SQLITE_PATH, hybrid=None) -> dict:
    per_backend = {}
    for backend in ("dictionary", "semantic", "hybrid"):
        if backend not in backends:
            continue
        rows = [_evaluate_case(case, backend, dictionary, semantic, top_k, db_path, hybrid) for case in cases]
        phase6 = [row for row in rows if row["phase"] == 6]
        per_backend[backend] = {
            "aggregate": macro_average(rows),
            "phase6_subset": macro_average(phase6),
            "by_category": {category: macro_average([row for row in rows if row["category"] == category]) for category in CATEGORIES},
            "queries": rows,
        }
    report = {
        "top_k": top_k,
        "query_count": len(cases),
        "policy": {
            "precision_denominator": "number of answer rows returned, at most k",
            "empty_ground_truth": "Excluded from precision, recall, hit rate, MRR, and nDCG. Scored only by empty-result correctness.",
            "context_results": "Excluded from relevance. Rows with answers_requested_measure false are not answers.",
            "partially_supported": "Excluded from relevance so related production rows are not rewarded as the requested measure.",
            "grades": "Binary membership in the SQLite result set unless a query supplies graded labels.",
            "scores": "Dictionary match reasons and cosine scores are not compared.",
        },
        "backends": per_backend,
        "comparison": _comparison(per_backend),
    }
    report["hybrid_recommendation"] = recommend(report)
    return report


def benchmark(dictionary, semantic, repetitions: int, warmup: int, hybrid=None) -> dict:
    """Time a fresh model load separately from repeated warm queries."""
    errors = []
    environment = {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "processor": platform.processor(),
        "cpu_count": __import__("os").cpu_count(),
    }
    result = {
        "environment": environment,
        "repetitions": repetitions,
        "warmup": warmup,
        "queries": list(BENCHMARK_QUERIES),
        "errors": errors,
    }
    if dictionary is not None:
        result["dictionary_first_ms"] = _time_call(lambda: dictionary.search(BENCHMARK_QUERIES[0], top_k=5), errors, "dictionary_first")
        result["dictionary_warm"] = _latency(
            [
                _time_call(lambda query=query: dictionary.search(query, top_k=5), errors, "dictionary_warm")
                for _ in range(repetitions)
                for query in BENCHMARK_QUERIES
            ]
        )
    if semantic is None:
        return result
    started = time.perf_counter()
    semantic.service.start()
    result["model_initialization_ms"] = round((time.perf_counter() - started) * 1000, 3)
    result["semantic_first_after_initialization_ms"] = _time_call(
        lambda: semantic.search(BENCHMARK_QUERIES[0], top_k=5), errors, "semantic_first"
    )
    for _ in range(warmup):
        semantic.search(BENCHMARK_QUERIES[0], top_k=5)
    semantic_samples = []
    component = {"embed": [], "qdrant": [], "sqlite": []}
    for _ in range(repetitions):
        for query in BENCHMARK_QUERIES:
            elapsed, payload = _timed_payload(lambda query=query: semantic.search(query, top_k=5), errors, "semantic_warm")
            semantic_samples.append(elapsed)
            timing = ((payload or {}).get("original") or {}).get("timing_ms") or {}
            for key in component:
                if timing.get(key) is not None:
                    component[key].append(timing[key])
    result["semantic_warm"] = _latency(semantic_samples)
    result["components_warm"] = {key: _latency(values) for key, values in component.items()}
    if dictionary is not None:
        for _ in range(warmup):
            dispatch("compare", BENCHMARK_QUERIES[0], 5, None, dictionary, semantic)
        compare_samples = [
            _time_call(lambda query=query: dispatch("compare", query, 5, None, dictionary, semantic), errors, "compare_warm")
            for _ in range(repetitions)
            for query in BENCHMARK_QUERIES
        ]
        result["compare_warm"] = _latency(compare_samples)
    if hybrid is not None:
        for _ in range(warmup):
            hybrid.search_text(BENCHMARK_QUERIES[0], top_k=5)
        hybrid_samples = []
        hybrid_parts = {"parse": [], "eligibility": [], "embed": [], "qdrant": [], "sqlite": []}
        for _ in range(repetitions):
            for query in BENCHMARK_QUERIES:
                elapsed, payload = _timed_payload(lambda query=query: hybrid.search_text(query, top_k=5), errors, "hybrid_warm")
                hybrid_samples.append(elapsed)
                timing = (payload or {}).get("timing_ms") or {}
                for key in hybrid_parts:
                    if timing.get(key) is not None:
                        hybrid_parts[key].append(timing[key])
        result["hybrid_warm"] = _latency(hybrid_samples)
        result["hybrid_components_warm"] = {key: _latency(values) for key, values in hybrid_parts.items()}
    result["errors"] = errors
    return result


def write_reports(report: dict, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "evaluation.json"
    markdown_path = output_dir / "evaluation.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(_markdown(report), encoding="utf-8")
    return json_path, markdown_path


def recommend(report: dict) -> str:
    comparison = report.get("comparison") or {}
    benchmark_report = report.get("benchmark") or {}
    both = comparison.get("both_hit", 0)
    dictionary_only = comparison.get("dictionary_only_hit", 0)
    semantic_only = comparison.get("semantic_only_hit", 0)
    neither = comparison.get("both_miss", 0)
    if semantic_only > dictionary_only:
        difference = "Semantic search hits relevant rows that dictionary search misses on this set, so a dictionary-only candidate list would drop those rows."
    elif dictionary_only > semantic_only:
        difference = "Dictionary search hits relevant rows that semantic search misses on this set, so a semantic-only candidate list would drop those rows."
    else:
        difference = "On this set, neither backend is the sole source of the hits that the other misses."
    init = benchmark_report.get("model_initialization_ms")
    dictionary_warm = ((benchmark_report.get("dictionary_warm") or {}).get("median_ms"))
    semantic_warm = ((benchmark_report.get("semantic_warm") or {}).get("median_ms"))
    latency = ""
    if init is not None and dictionary_warm is not None and semantic_warm is not None:
        latency = (
            f" Model initialization measured {init} ms and is kept separate from warm queries. "
            f"Warm median latency was {dictionary_warm} ms for dictionary search and {semantic_warm} ms for semantic search."
        )
    hybrid_present = "hybrid" in (report.get("backends") or {})
    opening = (
        [
            "Hybrid search ranks only the SQLite-eligible process ids with local BGE-M3. Dictionary match reasons are not added to cosine similarity.",
            "Reciprocal Rank Fusion is not part of this ranker. It remains a later experiment and cannot decide availability or numeric eligibility.",
        ]
        if hybrid_present
        else [
            "Hybrid search is not implemented in this phase.",
            "Dictionary match reasons and cosine similarity stay on separate scales. A future ranker must not add those numbers together.",
        ]
    )
    return "\n\n".join(
        [
            *opening,
            (
                f"Among ranked queries with a nonempty relevant set, both backends hit {both}, "
                f"dictionary only {dictionary_only}, semantic only {semantic_only}, and neither {neither}. "
                f"Their top-k sets differed for {comparison.get('different_top_sets', 0)} of those queries "
                f"(mean Jaccard {comparison.get('mean_retrieved_jaccard')}). {difference}"
            ),
            (
                "Recommended architecture: use the structured crop, year, region, season, and spatial constraints as the eligibility filter, "
                "then rank that eligible set with local BGE-M3. Keep dictionary search as the exact audit path when its parser accepts the question. "
                "Call the embedding model after the cheap structured constraints are known, or in parallel when the latency budget allows it."
                + latency
            ),
            (
                "Reciprocal Rank Fusion is a later experiment, not the first hybrid. It would fuse ranks rather than raw scores, "
                "and it is useful when the miss sets are complementary. It does not decide availability, and it cannot turn an unavailable fertilizer, "
                "energy, water, or carbon measurement into a production answer."
            ),
            (
                "Dictionary-first retrieval is the fastest exact path, and it is the wrong sole retriever for ambiguous multi-crop questions and for wording its parser does not accept. "
                "Semantic-first retrieval is already filtered inside the BGE-M3 service. A hybrid should not compare that filtered list with a dictionary list that ignored a separate filter."
            ),
            "This recommendation describes the measured labeled set. It is not a claim of statistical superiority.",
        ]
    )


def safety_snapshot() -> dict:
    path = DEFAULT_SQLITE_PATH
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    qdrant = _qdrant_snapshot()
    protected = {str(item): hashlib.sha256(item.read_bytes()).hexdigest() == expected for item, expected in PROTECTED.items()}
    return {
        "sqlite_sha256": digest,
        "sqlite_bytes": path.stat().st_size,
        "qdrant": qdrant,
        "protected_files_unchanged": protected,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate dictionary and BGE-M3 search quality.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--backends", choices=("dictionary", "semantic", "hybrid", "both", "all"), default="both")
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--warmup", type=int, default=2)
    args = parser.parse_args(argv)
    if not 1 <= args.top_k <= 105:
        print("top-k must be from 1 through 105")
        return 1
    if args.repetitions < 0 or args.warmup < 0:
        print("repetitions and warmup must be zero or greater")
        return 1
    output_dir = args.output_dir if args.output_dir.is_absolute() else ROOT / args.output_dir
    if ROOT.resolve() not in output_dir.resolve().parents and output_dir.resolve() != ROOT.resolve():
        print("The output directory must stay inside search_service.")
        return 1
    cases = load_dataset(args.dataset if args.dataset.is_absolute() else ROOT / args.dataset)
    if args.backends == "both":
        selected = {"dictionary", "semantic"}
    elif args.backends == "all":
        selected = {"dictionary", "semantic", "hybrid"}
    else:
        selected = {args.backends}
    before = safety_snapshot()
    semantic = None
    service = None
    dictionary = DictionarySearchAdapter() if "dictionary" in selected else None
    hybrid = None
    try:
        if "semantic" in selected or "hybrid" in selected:
            service = build_service()
        if "semantic" in selected:
            semantic = BGEM3SearchAdapter(service)
        if "hybrid" in selected:
            from .hybrid_search import HybridSearch

            hybrid = HybridSearch(service)
        timed = benchmark(dictionary, semantic, args.repetitions, args.warmup, hybrid) if args.repetitions else None
        report = evaluate(cases, dictionary, semantic, args.top_k, selected, hybrid=hybrid)
        if timed is not None:
            report["benchmark"] = timed
            report["hybrid_recommendation"] = recommend(report)
        after = safety_snapshot()
        report["safety"] = {"before": before, "after": after, "sqlite_unchanged": before["sqlite_sha256"] == after["sqlite_sha256"]}
        report["dataset_path"] = str(args.dataset)
        json_path, markdown_path = write_reports(report, output_dir)
    finally:
        if service is not None:
            service.close()
    print(json.dumps({"json": str(json_path), "markdown": str(markdown_path)}, ensure_ascii=False))
    return 0


def _evaluate_case(case: dict, backend: str, dictionary, semantic, top_k: int, db_path: Path, hybrid=None) -> dict:
    adapter = {"dictionary": dictionary, "semantic": semantic, "hybrid": hybrid}[backend]
    section = adapter.search_text(case["query"], top_k=top_k) if backend == "hybrid" and adapter is not None else None
    if backend != "hybrid":
        section = adapter.search(case["query"], top_k=top_k) if adapter is not None else None
    expected_status = case["expected_availability"].get(backend)
    if expected_status is None and backend == "hybrid":
        expected_status = case["expected_availability"]["semantic"]
    sqlite_ids = _ground_truth_ids(case, db_path)
    if expected_status == "unsupported":
        relevant = set()
    elif expected_status == "partially_supported":
        relevant = set()
    else:
        relevant = set(sqlite_ids)
    relevance_flag = (case.get("relevance_by_backend") or {}).get(backend, case["evaluate_relevance"])
    eligible = bool(relevance_flag) and expected_status != "partially_supported"
    retrieved = answer_ids(section)
    scored = score_query(retrieved, relevant, top_k, case.get("grades")) if eligible else {
        "empty_ground_truth": not relevant,
        "empty_result_correct": None,
        "precision_at_k": None,
        "recall_at_k": None,
        "hit_at_k": None,
        "reciprocal_rank": None,
        "ndcg_at_k": None,
    }
    actual = _actual_filters(section or {}, backend)
    expected = {key: case["expected_filters"].get(key) for key in ("crop_id", "year_ce", "region_code", "season", "spatial_level")}
    filter_checked = bool((case.get("check_filters_by_backend") or {}).get(backend, case["check_filters"])) and bool(section and section.get("ok"))
    coverage, missing_correct = _coverage(case, section, db_path)
    return {
        "query_id": case["query_id"],
        "phase": 6 if int(case["query_id"][1:]) <= 45 else 7,
        "query": case["query"],
        "category": case["category"],
        "measurement": case["measurement"],
        "backend": backend,
        "expected_availability": expected_status,
        "actual_availability": None if not section else section.get("availability_status"),
        "availability_correct": bool(section and section.get("availability_status") == expected_status),
        "filter_checked": filter_checked,
        "filter_correct": _filters_match(actual, expected, case) if filter_checked else None,
        "expected_filters": expected,
        "actual_filters": actual,
        "measure_marking_correct": _marking_correct(section, expected_status),
        "relevance_eligible": eligible,
        "sqlite_match_ids": sqlite_ids,
        "relevant_ids": sorted(relevant),
        "retrieved_answer_ids": retrieved,
        "context_ids": [row.get("process_id") for row in (section or {}).get("context_results") or []],
        "ambiguity": case.get("ambiguity"),
        "grading_rationale": case.get("grading_rationale"),
        "crop_coverage": coverage,
        "missing_group_correct": missing_correct,
        "numeric_condition_correct": _numeric_correct(case, section, retrieved, set(sqlite_ids)),
        **scored,
    }


def _ground_truth_ids(case: dict, db_path: Path) -> list[str]:
    filters = case["expected_filters"]
    needs_eligibility = bool(filters.get("crop_ids") or filters.get("year_from") or filters.get("year_to") or case.get("numeric_ground_truth"))
    if not needs_eligibility:
        return sqlite_process_ids(filters, db_path)
    from .eligibility import eligible_process_ids
    from .hybrid_planner import NumericCondition

    numeric = ()
    if case.get("numeric_ground_truth") and case.get("numeric"):
        spec = case["numeric"]
        numeric = (NumericCondition(spec["metric"], spec["operator"], float(spec["threshold"]), spec["unit"], True),)
    crops = tuple(filters.get("crop_ids") or (() if not filters.get("crop_id") else (filters["crop_id"],)))
    year_from = filters.get("year_from")
    year_to = filters.get("year_to")
    if year_from is None and year_to is None:
        year_from = year_to = filters.get("year_ce")
    connection = connect_readonly(db_path)
    try:
        return eligible_process_ids(
            connection,
            crop_ids=crops,
            year_from=year_from,
            year_to=year_to,
            region_code=filters.get("region_code"),
            season=filters.get("season"),
            spatial_level=filters.get("spatial_level"),
            source_id=filters.get("source_id"),
            numeric=numeric,
        )
    finally:
        connection.close()


def _actual_filters(section: dict, backend: str) -> dict:
    if backend == "dictionary":
        return _dictionary_constraints(section)
    if backend == "semantic":
        return _semantic_constraints(section)
    applied = section.get("applied_filters") or {}
    actual = {key: applied.get(key) for key in ("crop_id", "year_ce", "region_code", "season", "spatial_level")}
    actual["year_from"] = applied.get("year_from")
    actual["year_to"] = applied.get("year_to")
    return actual


def _filters_match(actual: dict, expected: dict, case: dict) -> bool:
    for key in ("crop_id", "region_code", "season", "spatial_level"):
        if (actual.get(key) or None) != (expected.get(key) or None):
            return False
    bounds = case["expected_filters"]
    if bounds.get("year_from") is not None or bounds.get("year_to") is not None:
        return actual.get("year_from") == bounds.get("year_from") and actual.get("year_to") == bounds.get("year_to")
    year = expected.get("year_ce")
    if actual.get("year_from") is not None or actual.get("year_to") is not None:
        if year is None:
            return actual.get("year_from") is None and actual.get("year_to") is None
        return actual.get("year_from") == year and actual.get("year_to") == year
    return actual.get("year_ce") == year


def _coverage(case: dict, section: dict | None, db_path: Path):
    crops = case.get("expected_crops") or []
    if not crops or not section or not section.get("ok"):
        return None, None
    counts = {}
    for crop in crops:
        filters = dict(case["expected_filters"])
        filters["crop_id"] = crop
        narrowed = {**case, "expected_filters": {**filters, "crop_ids": [crop]}, "numeric_ground_truth": case.get("numeric_ground_truth")}
        counts[crop] = len(_ground_truth_ids(narrowed, db_path))
    present = set()
    for row in section.get("results") or []:
        if row.get("answers_requested_measure") is False:
            continue
        crop = (row.get("crop") or {}).get("crop_id")
        if crop:
            present.add(crop)
    with_data = [crop for crop in crops if counts[crop] > 0]
    coverage = None if not with_data else sum(crop in present for crop in with_data) / len(with_data)
    missing = [crop for crop in crops if counts[crop] == 0]
    reported = set(section.get("missing_groups") or [])
    missing_correct = set(missing) <= reported and all(crop not in present for crop in missing)
    return coverage, missing_correct


def _numeric_correct(case: dict, section: dict | None, retrieved: list[str], relevant: set[str]):
    spec = case.get("numeric")
    if not spec or not section or not section.get("ok"):
        return None
    applied = section.get("applied_numeric") or []
    if case.get("numeric_ground_truth"):
        return bool(
            len(applied) == 1
            and applied[0].get("metric") == spec["metric"]
            and applied[0].get("operator") == spec["operator"]
            and float(applied[0].get("threshold")) == float(spec["threshold"])
            and applied[0].get("unit") == spec["unit"]
            and set(retrieved).issubset(relevant)
        )
    return not applied and bool(section.get("unapplied_conditions"))


def _marking_correct(section: dict | None, expected_status: str) -> bool:
    if not section or not section.get("ok"):
        return False
    answers = answer_ids(section)
    context = section.get("context_results") or []
    results = section.get("results") or []
    if expected_status == "unsupported":
        return not answers and all(row.get("answers_requested_measure") is False for row in context)
    if expected_status == "partially_supported":
        return not answers and all(row.get("answers_requested_measure") is False for row in results) and not context
    return all(row.get("answers_requested_measure") is not False for row in results) and not context


def _jaccard(left: list[str], right: list[str]) -> float:
    first, second = set(left), set(right)
    if not first and not second:
        return 1.0
    return len(first & second) / len(first | second)


def _comparison(per_backend: dict) -> dict:
    dictionary_rows = {row["query_id"]: row for row in (per_backend.get("dictionary") or {}).get("queries") or []}
    semantic_rows = {row["query_id"]: row for row in (per_backend.get("semantic") or {}).get("queries") or []}
    summary = {"both_hit": 0, "dictionary_only_hit": 0, "semantic_only_hit": 0, "both_miss": 0, "ranked_queries": 0, "different_top_sets": 0}
    jaccard_values = []
    for query_id, left in dictionary_rows.items():
        right = semantic_rows.get(query_id)
        if right is None or left.get("empty_ground_truth") or right.get("empty_ground_truth"):
            continue
        if not left.get("relevance_eligible") or not right.get("relevance_eligible"):
            continue
        summary["ranked_queries"] += 1
        left_ids = left.get("retrieved_answer_ids") or []
        right_ids = right.get("retrieved_answer_ids") or []
        if set(left_ids) != set(right_ids):
            summary["different_top_sets"] += 1
        jaccard_values.append(_jaccard(left_ids, right_ids))
        left_hit = left.get("hit_at_k") == 1.0
        right_hit = right.get("hit_at_k") == 1.0
        if left_hit and right_hit:
            summary["both_hit"] += 1
        elif left_hit:
            summary["dictionary_only_hit"] += 1
        elif right_hit:
            summary["semantic_only_hit"] += 1
        else:
            summary["both_miss"] += 1
    summary["mean_retrieved_jaccard"] = round(sum(jaccard_values) / len(jaccard_values), 4) if jaccard_values else None
    summary["note"] = "Hit counts use each backend's own ranking. Cosine scores are not compared with dictionary match reasons. Equal hit rates can still hide different top-k process ids."
    return summary


def _time_call(func, errors: list[dict], stage: str) -> float:
    elapsed, _payload = _timed_payload(func, errors, stage)
    return elapsed


def _timed_payload(func, errors: list[dict], stage: str):
    started = time.perf_counter()
    try:
        payload = func()
    except Exception:
        errors.append({"stage": stage, "message": "The timed call failed."})
        payload = None
    elapsed = round((time.perf_counter() - started) * 1000, 3)
    if isinstance(payload, dict) and payload.get("ok") is False:
        errors.append({"stage": stage, "message": (payload.get("error") or {}).get("code", "backend_error")})
    return elapsed, payload


def _latency(samples: list[float]) -> dict | None:
    if not samples:
        return None
    ordered = sorted(samples)
    count = len(ordered)
    index = min(count - 1, max(0, int(__import__("math").ceil(0.95 * count)) - 1))
    median = statistics.median(ordered)
    return {
        "count": count,
        "mean_ms": round(sum(ordered) / count, 3),
        "median_ms": round(median, 3),
        "p95_ms": round(ordered[index], 3),
        "min_ms": ordered[0],
        "max_ms": ordered[-1],
    }


def _qdrant_snapshot() -> dict:
    try:
        response = httpx.get("http://127.0.0.1:6333/collections/crop_process_bge_m3", timeout=5)
    except httpx.HTTPError:
        return {"reachable": False}
    if response.status_code != 200:
        return {"reachable": True, "status_code": response.status_code}
    result = response.json().get("result") or {}
    vectors = ((result.get("config") or {}).get("params") or {}).get("vectors") or {}
    return {
        "reachable": True,
        "points_count": result.get("points_count"),
        "vector_size": vectors.get("size"),
        "distance": vectors.get("distance"),
    }


def _markdown(report: dict) -> str:
    lines = [
        "# Search quality evaluation",
        "",
        f"Queries: {report['query_count']}. Top-k: {report['top_k']}.",
        "",
        "Precision uses the number of answer rows actually returned, up to k. "
        "Queries with an empty relevant set are omitted from precision, recall, hit rate, MRR, and nDCG, "
        "and are scored by empty-result correctness. Context rows are not answers. "
        "Partially supported measurement queries are omitted from relevance so production rows are not treated as the requested measure. "
        "The figures below describe this labeled set and are not a statistical ranking of the two systems.",
        "",
    ]
    for backend, body in report["backends"].items():
        lines.extend([f"## {backend}", "", _metric_table(body["aggregate"]), ""])
        if body.get("phase6_subset"):
            lines.extend(["Phase 6 subset (original 45 queries):", "", _metric_table(body["phase6_subset"]), ""])
        lines.extend(["### By category", ""])
        for category, aggregate in body["by_category"].items():
            if aggregate["ranked_queries"] or aggregate["empty_ground_truth_queries"] or aggregate["availability_accuracy"] is not None:
                lines.append(f"- {category}: {_compact(aggregate)}")
        lines.append("")
    comparison = report["comparison"]
    lines.extend(
        [
            "## Comparison",
            "",
            (
                f"Ranked nonempty queries: {comparison['ranked_queries']}. "
                f"Both hit: {comparison['both_hit']}. Dictionary only: {comparison['dictionary_only_hit']}. "
                f"Semantic only: {comparison['semantic_only_hit']}. Neither: {comparison['both_miss']}. "
                f"Different top-k sets: {comparison.get('different_top_sets')}. "
                f"Mean Jaccard: {comparison.get('mean_retrieved_jaccard')}."
            ),
            "",
            comparison["note"],
            "",
        ]
    )
    if report.get("benchmark"):
        bench = report["benchmark"]
        lines.extend(["## Latency", "", f"Environment: {bench['environment']['platform']}; Python {bench['environment']['python']}; {bench['environment']['processor']}.", ""])
        lines.append(f"Warm-up queries: {bench['warmup']}. Repetitions per benchmark query: {bench['repetitions']}.")
        lines.append(f"Model initialization: {bench.get('model_initialization_ms')} ms.")
        lines.append(f"Dictionary first query: {bench.get('dictionary_first_ms')} ms. Warm: {_latency_text(bench.get('dictionary_warm'))}.")
        lines.append(f"Semantic first query after initialization: {bench.get('semantic_first_after_initialization_ms')} ms. Warm: {_latency_text(bench.get('semantic_warm'))}.")
        components = bench.get("components_warm") or {}
        lines.append(
            "Warm semantic components: "
            f"embed {_latency_text(components.get('embed'))}; "
            f"Qdrant {_latency_text(components.get('qdrant'))}; "
            f"SQLite {_latency_text(components.get('sqlite'))}."
        )
        lines.append(f"Warm compare: {_latency_text(bench.get('compare_warm'))}.")
        lines.append(f"Benchmark errors: {len(bench.get('errors') or [])}.")
        lines.append("")
    lines.extend(["## Hybrid search recommendation", "", report.get("hybrid_recommendation") or "", ""])
    safety = report.get("safety") or {}
    if safety:
        lines.extend(
            [
                "## Safety snapshot",
                "",
                f"SQLite unchanged during the run: {safety['sqlite_unchanged']}.",
                f"SQLite SHA-256: {safety['after']['sqlite_sha256']}.",
                f"Qdrant after the run: {safety['after']['qdrant']}.",
                "",
            ]
        )
    return "\n".join(lines)


def _metric_table(aggregate: dict) -> str:
    return "\n".join(
        [
            "| Metric | Value |",
            "| --- | --- |",
            f"| Ranked queries | {aggregate['ranked_queries']} |",
            f"| Empty ground-truth queries | {aggregate['empty_ground_truth_queries']} |",
            f"| Precision@k | {aggregate['precision_at_k']} |",
            f"| Recall@k | {aggregate['recall_at_k']} |",
            f"| Hit rate@k | {aggregate['hit_at_k']} |",
            f"| MRR | {aggregate['mrr']} |",
            f"| nDCG@k | {aggregate['ndcg_at_k']} |",
            f"| Empty-result correctness | {aggregate['empty_result_correctness']} |",
            f"| Availability accuracy | {aggregate['availability_accuracy']} |",
            f"| Filter correctness | {aggregate['filter_correctness']} |",
            f"| Measure marking | {aggregate['measure_marking_correctness']} |",
        ]
    )


def _compact(aggregate: dict) -> str:
    return (
        f"ranked {aggregate['ranked_queries']}, empty {aggregate['empty_ground_truth_queries']}, "
        f"P {aggregate['precision_at_k']}, R {aggregate['recall_at_k']}, hit {aggregate['hit_at_k']}, "
        f"availability {aggregate['availability_accuracy']}"
    )


def _latency_text(summary: dict | None) -> str:
    if not summary:
        return "not measured"
    return f"mean {summary['mean_ms']} ms, median {summary['median_ms']} ms, p95 {summary['p95_ms']} ms, n {summary['count']}"


if __name__ == "__main__":
    raise SystemExit(main())
