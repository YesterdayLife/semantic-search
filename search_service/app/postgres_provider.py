"""PostgreSQL reads for a future cloud backend.

The default API does not construct this provider. LOCAL search keeps using
SQLite. These methods are exercised with fake connections until an authorized
PostgreSQL instance exists. They do not open Neon.
"""

from __future__ import annotations

from .database import DatabaseError
from .eligibility import OPERATOR_SQL
from .hybrid_planner import NumericCondition
from .records import Catalog, IndicatorValue, ProcessRecord, SourceHint, load_catalog

_ALLOWED_COLUMNS = {"region_code", "season", "spatial_level", "source_id"}
_PLACEHOLDERS = {"?", "%s"}


class PostgresDataProvider:
    """Read-only catalog, eligibility, and hydration using driver parameters."""

    def __init__(self, database_url: str, connect=None):
        self.database_url = database_url
        self._connect = connect

    def connect(self):
        """Open a read-only session. The URL is never copied into an error."""
        if not self.database_url and self._connect is None:
            raise DatabaseError("DATABASE_URL is required when DATA_BACKEND is postgres")
        if self._connect is not None:
            connection = self._connect()
        else:
            try:
                import psycopg
            except ImportError as exc:
                raise DatabaseError("PostgreSQL driver is not installed") from exc
            try:
                connection = psycopg.connect(self.database_url, connect_timeout=10)
            except Exception as exc:
                raise DatabaseError("PostgreSQL is unavailable") from exc
        try:
            connection.execute("SET default_transaction_read_only = on")
        except Exception as exc:
            raise DatabaseError("PostgreSQL read-only session could not be started") from exc
        return connection

    def load_catalog(self, connection) -> Catalog:
        crops = frozenset(row[0] for row in _rows(connection, "SELECT crop_id FROM crop"))
        regions = frozenset(row[0] for row in _rows(connection, "SELECT region_code FROM region"))
        seasons = frozenset(row[0] for row in _rows(connection, "SELECT DISTINCT season FROM process"))
        levels = frozenset(row[0] for row in _rows(connection, "SELECT DISTINCT spatial_level FROM process"))
        sources = tuple(
            SourceHint(row[0], row[1], row[2])
            for row in _rows(connection, "SELECT source_id, agency, title FROM data_source ORDER BY source_id")
        )
        count = int(_rows(connection, "SELECT COUNT(*) FROM process")[0][0])
        if count <= 0:
            raise DatabaseError("PostgreSQL process catalog is empty")
        return Catalog(
            crop_ids=crops,
            region_codes=regions,
            seasons=seasons,
            spatial_levels=levels,
            source_ids=frozenset(source.source_id for source in sources),
            sources=sources,
            process_count=count,
        )

    def eligible_process_ids(self, connection, **kwargs) -> list[str]:
        sql, params = eligibility_query(placeholder="%s", **kwargs)
        return [row[0] for row in _rows(connection, sql, params)]

    def process_crops(self, connection, process_ids: list[str]) -> dict[str, str]:
        if not process_ids:
            return {}
        marks = ", ".join("%s" for _ in process_ids)
        rows = _rows(
            connection,
            f"SELECT process_id, crop_id FROM process WHERE process_id IN ({marks})",
            list(process_ids),
        )
        return {row[0]: row[1] for row in rows}

    def fetch_records(self, connection, process_ids: list[str]) -> dict[str, ProcessRecord]:
        if not process_ids:
            return {}
        marks = ", ".join("%s" for _ in process_ids)
        rows = _rows(
            connection,
            f"""
            SELECT
              p.process_id, p.crop_id, c.crop_name, p.year_ce, p.year_original,
              p.calendar, p.season, p.spatial_level, p.region_code, r.region_name,
              p.area, e.quantity, e.unit, f.flow_name, p.source_id, s.agency, s.title
            FROM process AS p
            JOIN crop AS c ON c.crop_id = p.crop_id
            JOIN data_source AS s ON s.source_id = p.source_id
            LEFT JOIN region AS r ON r.region_code = p.region_code
            LEFT JOIN exchange AS e ON e.process_id = p.process_id AND e.direction = 'Output'
            LEFT JOIN flow AS f ON f.flow_id = e.flow_id
            WHERE p.process_id IN ({marks})
            """,
            list(process_ids),
        )
        grouped: dict[str, list] = {}
        for row in rows:
            grouped.setdefault(row[0], []).append(row)
        indicator_rows = _rows(
            connection,
            f"""
            SELECT process_id, metric_code, value, unit
            FROM crop_indicator
            WHERE process_id IN ({marks})
            ORDER BY process_id, metric_code
            """,
            list(process_ids),
        )
        indicators: dict[str, list[IndicatorValue]] = {process_id: [] for process_id in grouped}
        for row in indicator_rows:
            indicators.setdefault(row[0], []).append(IndicatorValue(row[1], float(row[2]), row[3]))
        records: dict[str, ProcessRecord] = {}
        for process_id, group in grouped.items():
            first = group[0]
            conflict = len(group) != 1
            quantity = None if conflict or first[11] is None else float(first[11])
            records[process_id] = ProcessRecord(
                process_id=process_id,
                crop_id=first[1],
                crop_name=first[2],
                year_ce=int(first[3]),
                year_original=str(first[4]),
                calendar=str(first[5]),
                season=str(first[6]),
                spatial_level=str(first[7]),
                region_code=first[8],
                region_name=first[9],
                area=str(first[10]),
                production_quantity=quantity,
                production_unit=None if conflict else first[12],
                production_flow=None if conflict else first[13],
                source_id=first[14],
                agency=first[15],
                title=first[16],
                indicators=tuple(indicators.get(process_id, ())),
                quantity_conflict=conflict,
            )
        return records


def eligibility_query(
    crop_ids: tuple[str, ...] | list[str] | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    region_code: str | None = None,
    season: str | None = None,
    spatial_level: str | None = None,
    source_id: str | None = None,
    numeric: tuple[NumericCondition, ...] | list[NumericCondition] | None = None,
    placeholder: str = "%s",
) -> tuple[str, list]:
    """Build a parameterized eligibility statement. Column names are fixed."""
    if placeholder not in _PLACEHOLDERS:
        raise ValueError("unsupported SQL placeholder")
    clauses: list[str] = []
    params: list[object] = []
    crops = [crop for crop in (crop_ids or []) if crop]
    if crops:
        clauses.append("p.crop_id IN (" + ", ".join(placeholder for _ in crops) + ")")
        params.extend(crops)
    if year_from is not None:
        clauses.append(f"p.year_ce >= {placeholder}")
        params.append(year_from)
    if year_to is not None:
        clauses.append(f"p.year_ce <= {placeholder}")
        params.append(year_to)
    values = {
        "region_code": region_code,
        "season": season,
        "spatial_level": spatial_level,
        "source_id": source_id,
    }
    for column in ("region_code", "season", "spatial_level", "source_id"):
        value = values[column]
        if value is not None:
            if column not in _ALLOWED_COLUMNS:
                raise ValueError("unsupported eligibility column")
            clauses.append(f"p.{column} = {placeholder}")
            params.append(value)
    for condition in numeric or []:
        if not condition.applied:
            continue
        operator = OPERATOR_SQL.get(condition.operator)
        if operator is None:
            raise ValueError("unsupported numeric operator")
        if condition.metric == "production":
            clauses.append(
                "EXISTS (SELECT 1 FROM exchange AS e "
                "WHERE e.process_id = p.process_id AND e.direction = 'Output' "
                f"AND e.unit = {placeholder} AND e.quantity {operator} {placeholder})"
            )
            params.extend([condition.unit, condition.threshold])
        else:
            clauses.append(
                "EXISTS (SELECT 1 FROM crop_indicator AS i "
                "WHERE i.process_id = p.process_id "
                f"AND i.metric_code = {placeholder} AND i.unit = {placeholder} "
                f"AND i.value {operator} {placeholder})"
            )
            params.extend([condition.metric, condition.unit, condition.threshold])
    sql = "SELECT p.process_id FROM process AS p"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY p.process_id"
    return sql, params


def _rows(connection, sql: str, params: list | tuple | None = None) -> list:
    try:
        cursor = connection.execute(sql, params or ())
        return list(cursor.fetchall())
    except DatabaseError:
        raise
    except Exception as exc:
        raise DatabaseError("PostgreSQL read failed") from exc


def sqlite_catalog_unchanged() -> bool:
    """The SQLite catalog function remains the local implementation."""
    return load_catalog.__module__ == "app.records"
