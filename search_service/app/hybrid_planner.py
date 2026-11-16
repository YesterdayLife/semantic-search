"""Deterministic intent planning for eligibility-first hybrid search.

Structured constraints come from aliases and explicit comparisons.
Similarity is not used to decide a crop, year, region, season, or number.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .documents import CROP_ALIASES
from .query_parser import FILTER_FIELDS, has_term, normalize, parse_query
from .query_parser import _independent_keys, _year

OPERATORS = (
    ("มากกว่าหรือเท่ากับ", "gte"),
    ("ไม่น้อยกว่า", "gte"),
    ("ไม่ต่ำกว่า", "gte"),
    ("อย่างน้อย", "gte"),
    ("greater than or equal to", "gte"),
    ("at least", "gte"),
    ("no less than", "gte"),
    (">=", "gte"),
    ("ไม่มากกว่า", "lte"),
    ("น้อยกว่าหรือเท่ากับ", "lte"),
    ("ไม่เกิน", "lte"),
    ("อย่างมาก", "lte"),
    ("less than or equal to", "lte"),
    ("at most", "lte"),
    ("no more than", "lte"),
    ("<=", "lte"),
    ("มากกว่า", "gt"),
    ("เกิน", "gt"),
    ("greater than", "gt"),
    ("more than", "gt"),
    ("above", "gt"),
    ("over", "gt"),
    (">", "gt"),
    ("น้อยกว่า", "lt"),
    ("ต่ำกว่า", "lt"),
    ("less than", "lt"),
    ("below", "lt"),
    ("under", "lt"),
    ("<", "lt"),
)
PRODUCTION_UNITS = (
    ("ตัน", "t"),
    ("tonnes", "t"),
    ("tonne", "t"),
    ("tons", "t"),
    ("ton", "t"),
)
YIELD_UNITS = (
    ("kg/rai", "kg/rai"),
    ("kg per rai", "kg/rai"),
    ("กิโลกรัมต่อไร่", "kg/rai"),
    ("กก.ต่อไร่", "kg/rai"),
    ("กก./ไร่", "kg/rai"),
)
AREA_UNITS = (
    ("ไร่", "rai"),
    ("rai", "rai"),
)
MASS_UNITS = (
    ("kilograms", "kg"),
    ("kilogram", "kg"),
    ("กิโลกรัม", "kg"),
    ("กก.", "kg"),
    ("kg", "kg"),
)
METRIC_UNITS = {
    "production": "t",
    "yield_harvested": "kg/rai",
    "yield_planted": "kg/rai",
    "area_harvested": "rai",
    "area_planted": "rai",
}
COORDINATORS = ("และ", "กับ", "หรือ", "compare", "versus", "vs", "and", "with", "plus", "or")


@dataclass(frozen=True)
class NumericCondition:
    metric: str
    operator: str
    threshold: float
    unit: str
    applied: bool
    reason: str | None = None

    def as_dict(self) -> dict:
        return {
            "metric": self.metric,
            "operator": self.operator,
            "threshold": self.threshold,
            "unit": self.unit,
            "applied": self.applied,
            "reason": self.reason,
        }


@dataclass
class HybridIntent:
    crops: tuple[str, ...] = ()
    grouped: bool = False
    crop_ambiguous: bool = False
    year_from: int | None = None
    year_to: int | None = None
    year_ambiguous: bool = False
    region_code: str | None = None
    season: str | None = None
    season_ambiguous: bool = False
    spatial_level: str | None = None
    source_id: str | None = None
    measures: tuple[str, ...] = ()
    numeric: tuple[NumericCondition, ...] = ()
    warnings: list[str] = field(default_factory=list)

    @property
    def applied_numeric(self) -> tuple[NumericCondition, ...]:
        return tuple(item for item in self.numeric if item.applied)

    @property
    def unapplied_conditions(self) -> tuple[str, ...]:
        return tuple(item.reason or item.metric for item in self.numeric if not item.applied)

    def has_scope(self) -> bool:
        return bool(
            self.crops
            or self.year_from is not None
            or self.region_code
            or self.season
            or self.spatial_level
            or self.source_id
            or self.applied_numeric
        )

    def availability(self) -> str:
        if self.measures and not self.has_scope():
            return "unsupported"
        if self.measures:
            return "partially_supported"
        return "supported"

    def applied_filters(self) -> dict:
        year = self.year_from if self.year_from is not None and self.year_from == self.year_to else None
        return {
            "crop_id": self.crops[0] if len(self.crops) == 1 else None,
            "crop_ids": list(self.crops),
            "year_ce": year,
            "year_from": self.year_from,
            "year_to": self.year_to,
            "region_code": self.region_code,
            "season": self.season,
            "spatial_level": self.spatial_level,
            "source_id": self.source_id,
        }

    def as_dict(self) -> dict:
        return {
            "crops": list(self.crops),
            "grouped": self.grouped,
            "crop_ambiguous": self.crop_ambiguous,
            "year_from": self.year_from,
            "year_to": self.year_to,
            "year_ambiguous": self.year_ambiguous,
            "region_code": self.region_code,
            "season": self.season,
            "season_ambiguous": self.season_ambiguous,
            "spatial_level": self.spatial_level,
            "source_id": self.source_id,
            "measures": list(self.measures),
            "availability": self.availability(),
            "numeric": [item.as_dict() for item in self.numeric],
        }


def plan_query(query: str, sources=(), explicit: dict | None = None) -> HybridIntent:
    """Plan a hybrid query. Explicit non-null filters replace inferred values."""
    text = _without_thousands(normalize(query))
    parsed = parse_query(query, sources)
    crops = _ordered_crops(text)
    grouped = len(crops) > 1 and _coordinated(text)
    ambiguous_crop = len(crops) > 1 and not grouped
    selected = crops if grouped or len(crops) == 1 else ()
    year_from, year_to, year_ambiguous = _year_bounds(text)
    if year_from is None and not year_ambiguous:
        year_from = year_to = parsed.year_ce
    warnings = list(parsed.warnings)
    if grouped:
        warnings = [warning for warning in warnings if not warning.startswith("The crop is ambiguous")]
        warnings.append("Multiple crops were requested: " + ", ".join(selected) + ".")
    if year_from is not None and year_to is not None and year_from != year_to:
        warnings = [warning for warning in warnings if not warning.startswith("The year is ambiguous")]
        warnings.append(f"The year range {year_from} through {year_to} CE was applied.")
    numeric = _numeric_conditions(text)
    intent = HybridIntent(
        crops=selected,
        grouped=grouped,
        crop_ambiguous=ambiguous_crop,
        year_from=year_from,
        year_to=year_to,
        year_ambiguous=year_ambiguous,
        region_code=parsed.region_code,
        season=parsed.season,
        season_ambiguous=parsed.season is None and "The season is ambiguous" in " ".join(parsed.warnings),
        spatial_level=parsed.spatial_level,
        source_id=parsed.source_id,
        measures=parsed.unavailable_measures,
        numeric=tuple(numeric),
        warnings=warnings,
    )
    return _apply_explicit(intent, explicit or {})


def _apply_explicit(intent: HybridIntent, explicit: dict) -> HybridIntent:
    for key in FILTER_FIELDS:
        value = explicit.get(key)
        if value is None:
            continue
        if key == "crop_id":
            if intent.crops and value not in intent.crops:
                intent.warnings.append("The explicit crop_id filter overrides the crops inferred from the query.")
            elif intent.crops and intent.crops != (value,):
                intent.warnings.append("The explicit crop_id filter overrides the crops inferred from the query.")
            intent.crops = (value,)
            intent.grouped = False
            intent.crop_ambiguous = False
        elif key == "year_ce":
            if intent.year_from is not None and (intent.year_from != value or intent.year_to != value):
                intent.warnings.append("The explicit year_ce filter overrides the year inferred from the query.")
            intent.year_from = value
            intent.year_to = value
            intent.year_ambiguous = False
        else:
            current = getattr(intent, key)
            if current is not None and current != value:
                intent.warnings.append(f"The explicit {key} filter overrides the value inferred from the query.")
            setattr(intent, key, value)
    if intent.spatial_level == "country" and intent.region_code and not explicit.get("region_code"):
        intent.region_code = None
        intent.warnings.append("A country-level filter cleared the inferred region.")
    return intent


def _ordered_crops(text: str) -> tuple[str, ...]:
    keys = _independent_keys(text, CROP_ALIASES)

    def position(crop_id: str) -> int:
        places = []
        for alias in CROP_ALIASES[crop_id]:
            alias_text = normalize(alias)
            if has_term(text, alias) and alias_text in text:
                places.append(text.find(alias_text))
        return min(places) if places else 10**9

    return tuple(sorted(keys, key=position))


def _coordinated(text: str) -> bool:
    for marker in COORDINATORS:
        if re.fullmatch(r"[a-z ]+", marker):
            if has_term(text, marker):
                return True
        elif marker in text:
            return True
    return False


def _year_bounds(text: str) -> tuple[int | None, int | None, bool]:
    raw_years = []
    for raw in re.findall(r"(?<!\d)(?:20\d{2}|25\d{2})(?!\d)", text):
        year = int(raw)
        if year >= 2500:
            year -= 543
        if year not in raw_years:
            raw_years.append(year)
    if len(raw_years) > 2:
        return None, None, True
    if len(raw_years) == 2:
        ranged = bool(re.search(r"ถึง|ระหว่าง|through|between|(?<![a-z])to(?![a-z])", text)) or bool(
            re.search(r"(?:20\d{2}|25\d{2})\s*-\s*(?:20\d{2}|25\d{2})", text)
        )
        if ranged:
            return min(raw_years), max(raw_years), False
        return None, None, True
    if len(raw_years) == 1 and 1900 <= raw_years[0] <= 2100:
        return raw_years[0], raw_years[0], False
    single = _year(text, [])
    if single is None:
        return None, None, False
    return single, single, False


def _numeric_conditions(text: str) -> list[NumericCondition]:
    conditions = []
    for start, end, operator in _operator_spans(text):
        window = text[end : end + 80]
        number = _threshold(window)
        if number is None:
            conditions.append(NumericCondition("", operator, 0.0, "", False, "A comparison had no explicit threshold, so it was not applied."))
            continue
        metric, unit, reason = _metric_and_unit(text, window)
        if reason:
            conditions.append(NumericCondition(metric or "", operator, number, unit or "", False, reason))
            continue
        conditions.append(NumericCondition(metric, operator, number, unit, True, None))
    return conditions


def _operator_spans(text: str) -> list[tuple[int, int, str]]:
    found = []
    for phrase, operator in OPERATORS:
        needle = normalize(phrase)
        if needle in {">", "<", ">=", "<="}:
            start = 0
            while True:
                index = text.find(needle, start)
                if index < 0:
                    break
                found.append((index, index + len(needle), operator, len(needle)))
                start = index + len(needle)
            continue
        if re.fullmatch(r"[a-z ]+", needle):
            for match in re.finditer(r"(?<![a-z])" + re.escape(needle) + r"(?![a-z])", text):
                found.append((match.start(), match.end(), operator, len(needle)))
        else:
            start = 0
            while True:
                index = text.find(needle, start)
                if index < 0:
                    break
                found.append((index, index + len(needle), operator, len(needle)))
                start = index + len(needle)
    found.sort(key=lambda item: (-item[3], item[0]))
    chosen = []
    occupied: list[tuple[int, int]] = []
    for start, end, operator, _length in found:
        if any(not (end <= left or start >= right) for left, right in occupied):
            continue
        chosen.append((start, end, operator))
        occupied.append((start, end))
    chosen.sort()
    return chosen


def _threshold(window: str) -> float | None:
    for match in re.finditer(r"(?<!\d)(\d+(?:\.\d+)?)(?!\d)", window):
        token = match.group(1)
        if _year_token(token):
            continue
        return float(token) if "." in token else float(int(token))
    return None


def _year_token(token: str) -> bool:
    if not re.fullmatch(r"\d{4}", token):
        return False
    value = int(token)
    return 1900 <= value <= 2100 or 2500 <= value <= 2599


def _metric_and_unit(text: str, window: str) -> tuple[str | None, str | None, str | None]:
    yield_unit = _first_unit(window, YIELD_UNITS)
    production_unit = _first_unit(window, PRODUCTION_UNITS)
    area_unit = None if yield_unit else _first_unit(window, AREA_UNITS)
    mass_unit = None if yield_unit or production_unit else _first_unit(window, MASS_UNITS)
    harvested = has_term(text, "harvested") or "เก็บเกี่ยว" in text
    planted = has_term(text, "planted") or "พื้นที่ปลูก" in text or "ผลผลิตปลูก" in text
    if yield_unit:
        if harvested and not planted:
            return "yield_harvested", "kg/rai", None
        if planted and not harvested:
            return "yield_planted", "kg/rai", None
        return None, "kg/rai", "Yield was not applied because harvested yield and planted yield differ. Name which one."
    if production_unit:
        return "production", "t", None
    if mass_unit:
        return None, "kg", "The kilogram unit was not applied. Production is stored in tonnes and was not converted."
    if area_unit:
        if harvested and not planted:
            return "area_harvested", "rai", None
        if planted and not harvested:
            return "area_planted", "rai", None
        return None, "rai", "Area was not applied because harvested area and planted area differ. Name which one."
    return None, None, "A comparison had no recognized unit, so it was not applied."


def _first_unit(window: str, units: tuple[tuple[str, str], ...]) -> str | None:
    best_length = -1
    best_unit = None
    for phrase, unit in units:
        needle = normalize(phrase)
        if re.fullmatch(r"[a-z]+", needle):
            matched = has_term(window, needle)
        else:
            matched = needle in window
        if matched and len(needle) > best_length:
            best_length = len(needle)
            best_unit = unit
    return best_unit


def _without_thousands(text: str) -> str:
    return re.sub(r"(?<=\d),(?=\d)", "", text)
