"""Read-only SQLite hydration for ranked process identifiers."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from .database import verify_catalog

@dataclass(frozen=True)
class SourceHint:
    source_id: str
    agency: str
    title: str


@dataclass(frozen=True)
class IndicatorValue:
    metric_code: str
    value: float
    unit: str


@dataclass(frozen=True)
class ProcessRecord:
    process_id: str
    crop_id: str
    crop_name: str
    year_ce: int
    year_original: str
    calendar: str
    season: str
    spatial_level: str
    region_code: str | None
    region_name: str | None
    area: str
    production_quantity: float | None
    production_unit: str | None
    production_flow: str | None
    source_id: str
    agency: str
    title: str
    indicators: tuple[IndicatorValue, ...]
    quantity_conflict: bool = False


@dataclass(frozen=True)
class Catalog:
    crop_ids: frozenset[str]
    region_codes: frozenset[str]
    seasons: frozenset[str]
    spatial_levels: frozenset[str]
    source_ids: frozenset[str]
    sources: tuple[SourceHint, ...]
    process_count: int


def load_catalog(connection: sqlite3.Connection) -> Catalog:
    """Read allowed filter values from the validated database."""
    verify_catalog(connection)
    crops = frozenset(row[0] for row in connection.execute("SELECT crop_id FROM crop"))
    regions = frozenset(row[0] for row in connection.execute("SELECT region_code FROM region"))
    seasons = frozenset(row[0] for row in connection.execute("SELECT DISTINCT season FROM process"))
    levels = frozenset(row[0] for row in connection.execute("SELECT DISTINCT spatial_level FROM process"))
    sources = tuple(
        SourceHint(row[0], row[1], row[2])
        for row in connection.execute("SELECT source_id, agency, title FROM data_source ORDER BY source_id")
    )
    count = int(connection.execute("SELECT COUNT(*) FROM process").fetchone()[0])
    return Catalog(
        crop_ids=crops,
        region_codes=regions,
        seasons=seasons,
        spatial_levels=levels,
        source_ids=frozenset(source.source_id for source in sources),
        sources=sources,
        process_count=count,
    )


def fetch_records(connection: sqlite3.Connection, process_ids: list[str]) -> dict[str, ProcessRecord]:
    """Load one factual record per process. Quantities come only from SQLite."""
    if not process_ids:
        return {}
    placeholders = ",".join("?" for _ in process_ids)
    rows = connection.execute(
        f"""
        SELECT
          p.process_id,
          p.crop_id,
          c.crop_name,
          p.year_ce,
          p.year_original,
          p.calendar,
          p.season,
          p.spatial_level,
          p.region_code,
          r.region_name,
          p.area,
          e.quantity AS production_quantity,
          e.unit AS production_unit,
          f.flow_name AS production_flow,
          p.source_id,
          s.agency,
          s.title
        FROM process AS p
        JOIN crop AS c ON c.crop_id = p.crop_id
        JOIN data_source AS s ON s.source_id = p.source_id
        LEFT JOIN region AS r ON r.region_code = p.region_code
        LEFT JOIN exchange AS e ON e.process_id = p.process_id AND e.direction = 'Output'
        LEFT JOIN flow AS f ON f.flow_id = e.flow_id
        WHERE p.process_id IN ({placeholders})
        """,
        process_ids,
    ).fetchall()
    grouped: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        grouped.setdefault(row["process_id"], []).append(row)
    indicators: dict[str, list[IndicatorValue]] = {process_id: [] for process_id in grouped}
    indicator_rows = connection.execute(
        f"""
        SELECT process_id, metric_code, value, unit
        FROM crop_indicator
        WHERE process_id IN ({placeholders})
        ORDER BY process_id, metric_code
        """,
        process_ids,
    )
    for row in indicator_rows:
        indicators.setdefault(row["process_id"], []).append(
            IndicatorValue(row["metric_code"], float(row["value"]), row["unit"])
        )
    records: dict[str, ProcessRecord] = {}
    for process_id, group in grouped.items():
        first = group[0]
        conflict = len(group) != 1
        quantity = None if conflict or first["production_quantity"] is None else float(first["production_quantity"])
        records[process_id] = ProcessRecord(
            process_id=process_id,
            crop_id=first["crop_id"],
            crop_name=first["crop_name"],
            year_ce=int(first["year_ce"]),
            year_original=str(first["year_original"]),
            calendar=str(first["calendar"]),
            season=str(first["season"]),
            spatial_level=str(first["spatial_level"]),
            region_code=first["region_code"],
            region_name=first["region_name"],
            area=str(first["area"]),
            production_quantity=quantity,
            production_unit=None if conflict else first["production_unit"],
            production_flow=None if conflict else first["production_flow"],
            source_id=first["source_id"],
            agency=first["agency"],
            title=first["title"],
            indicators=tuple(indicators.get(process_id, ())),
            quantity_conflict=conflict,
        )
    return records
