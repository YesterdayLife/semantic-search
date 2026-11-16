"""Ranking metrics for labeled search evaluation.

Empty ground-truth sets are excluded from Precision, Recall, Hit Rate, MRR, and nDCG.
They are scored by empty-result correctness instead, so a division by zero never occurs.
Context rows and rows that do not answer the requested measure are not retrieved answers.
"""

from __future__ import annotations

import math


def answer_ids(section: dict | None) -> list[str]:
    """Process ids that the backend presents as answers, in rank order."""
    if not section:
        return []
    found = []
    for row in section.get("results") or []:
        if row.get("answers_requested_measure") is False:
            continue
        process_id = row.get("process_id")
        if process_id and process_id not in found:
            found.append(process_id)
    return found


def precision_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    if not relevant:
        raise ValueError("precision is undefined for an empty relevant set; use empty_result_correct")
    top = _top(retrieved, k)
    if not top:
        return 0.0
    return _hits(top, relevant) / len(top)


def recall_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    if not relevant:
        raise ValueError("recall is undefined for an empty relevant set; use empty_result_correct")
    return _hits(_top(retrieved, k), relevant) / len(relevant)


def hit_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    if not relevant:
        raise ValueError("hit rate is undefined for an empty relevant set; use empty_result_correct")
    return 1.0 if _hits(_top(retrieved, k), relevant) else 0.0


def reciprocal_rank(retrieved: list[str], relevant: set[str], k: int) -> float:
    if not relevant:
        raise ValueError("MRR is undefined for an empty relevant set; use empty_result_correct")
    for rank, process_id in enumerate(_top(retrieved, k), start=1):
        if process_id in relevant:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(retrieved: list[str], relevant: set[str], k: int, grades: dict[str, float] | None = None) -> float:
    if not relevant and not grades:
        raise ValueError("nDCG is undefined for an empty relevant set; use empty_result_correct")
    relevance = dict(grades or {process_id: 1.0 for process_id in relevant})
    if not any(grade > 0 for grade in relevance.values()):
        raise ValueError("nDCG is undefined when every grade is zero")
    top = _top(retrieved, k)
    ideal = sorted((grade for grade in relevance.values() if grade > 0), reverse=True)[:k]
    ideal_gain = _dcg(ideal)
    if ideal_gain == 0:
        raise ValueError("nDCG is undefined when the ideal gain is zero")
    return _dcg([relevance.get(process_id, 0.0) for process_id in top]) / ideal_gain


def empty_result_correct(retrieved: list[str]) -> float:
    """1 when an empty relevant set is answered with no answer rows."""
    return 1.0 if not retrieved else 0.0


def score_query(retrieved: list[str], relevant: set[str], k: int, grades: dict[str, float] | None = None) -> dict:
    if not relevant:
        correct = empty_result_correct(retrieved)
        return {
            "empty_ground_truth": True,
            "empty_result_correct": correct,
            "precision_at_k": None,
            "recall_at_k": None,
            "hit_at_k": None,
            "reciprocal_rank": None,
            "ndcg_at_k": None,
        }
    return {
        "empty_ground_truth": False,
        "empty_result_correct": None,
        "precision_at_k": precision_at_k(retrieved, relevant, k),
        "recall_at_k": recall_at_k(retrieved, relevant, k),
        "hit_at_k": hit_at_k(retrieved, relevant, k),
        "reciprocal_rank": reciprocal_rank(retrieved, relevant, k),
        "ndcg_at_k": ndcg_at_k(retrieved, relevant, k, grades),
    }


def macro_average(rows: list[dict]) -> dict:
    ranked = [row for row in rows if row.get("relevance_eligible") and not row.get("empty_ground_truth")]
    empty = [row for row in rows if row.get("relevance_eligible") and row.get("empty_ground_truth")]
    return {
        "ranked_queries": len(ranked),
        "empty_ground_truth_queries": len(empty),
        "precision_at_k": _mean(ranked, "precision_at_k"),
        "recall_at_k": _mean(ranked, "recall_at_k"),
        "hit_at_k": _mean(ranked, "hit_at_k"),
        "mrr": _mean(ranked, "reciprocal_rank"),
        "ndcg_at_k": _mean(ranked, "ndcg_at_k"),
        "empty_result_correctness": _mean(empty, "empty_result_correct"),
        "availability_accuracy": _mean(rows, "availability_correct"),
        "filter_correctness": _mean([row for row in rows if row.get("filter_checked")], "filter_correct"),
        "measure_marking_correctness": _mean(rows, "measure_marking_correct"),
        "crop_coverage": _mean(rows, "crop_coverage"),
        "missing_group_correctness": _mean(rows, "missing_group_correct"),
        "numeric_condition_correctness": _mean(rows, "numeric_condition_correct"),
    }


def _top(retrieved: list[str], k: int) -> list[str]:
    return list(retrieved)[:k]


def _hits(retrieved: list[str], relevant: set[str]) -> int:
    return sum(1 for process_id in retrieved if process_id in relevant)


def _dcg(grades: list[float]) -> float:
    return sum((2**grade - 1) / math.log2(index + 2) for index, grade in enumerate(grades))


def _mean(rows: list[dict], key: str):
    values = [row[key] for row in rows if row.get(key) is not None]
    if not values:
        return None
    return round(sum(values) / len(values), 4)
