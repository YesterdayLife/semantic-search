"""Read-only process eligibility. Filters are parameterized and never written back."""

from __future__ import annotations

import sqlite3

from .hybrid_planner import NumericCondition

OPERATOR_SQL = {"gt": ">", "gte": ">=", "lt": "<", "lte": "<="}


def eligible_process_ids(
    connection: sqlite3.Connection,
    crop_ids: tuple[str, ...] | list[str] | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    region_code: str | None = None,
    season: str | None = None,
    spatial_level: str | None = None,
    source_id: str | None = None,
    numeric: tuple[NumericCondition, ...] | list[NumericCondition] | None = None,
) -> list[str]:
    """Return every process id that satisfies the structured constraints."""
    clauses = []
    params: list[object] = []
    crops = [crop for crop in (crop_ids or []) if crop]
    if crops:
        clauses.append("p.crop_id IN (" + ",".join("?" for _ in crops) + ")")
        params.extend(crops)
    if year_from is not None:
        clauses.append("p.year_ce >= ?")
        params.append(year_from)
    if year_to is not None:
        clauses.append("p.year_ce <= ?")
        params.append(year_to)
    for column, value in (
        ("region_code", region_code),
        ("season", season),
        ("spatial_level", spatial_level),
        ("source_id", source_id),
    ):
        if value is not None:
            clauses.append(f"p.{column} = ?")
            params.append(value)
    for condition in numeric or []:
        if not condition.applied:
            continue
        operator = OPERATOR_SQL[condition.operator]
        if condition.metric == "production":
            clauses.append(
                "EXISTS (SELECT 1 FROM exchange AS e "
                "WHERE e.process_id = p.process_id AND e.direction = 'Output' "
                f"AND e.unit = ? AND e.quantity {operator} ?)"
            )
            params.extend([condition.unit, condition.threshold])
        else:
            clauses.append(
                "EXISTS (SELECT 1 FROM crop_indicator AS i "
                "WHERE i.process_id = p.process_id AND i.metric_code = ? AND i.unit = ? "
                f"AND i.value {operator} ?)"
            )
            params.extend([condition.metric, condition.unit, condition.threshold])
    sql = "SELECT p.process_id FROM process AS p"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY p.process_id"
    return [row[0] for row in connection.execute(sql, params)]


def process_crops(connection: sqlite3.Connection, process_ids: list[str]) -> dict[str, str]:
    if not process_ids:
        return {}
    placeholders = ",".join("?" for _ in process_ids)
    rows = connection.execute(
        f"SELECT process_id, crop_id FROM process WHERE process_id IN ({placeholders})",
        process_ids,
    )
    return {row[0]: row[1] for row in rows}
