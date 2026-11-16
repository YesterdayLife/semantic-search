"""Rule-based query parsing for crop, place, season, and year.

Aliases match the existing dictionary search. That module is not imported.
Ambiguous matches stay unfiltered and are reported as warnings.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .documents import COUNTRY_ALIASES, CROP_ALIASES, DRY_ALIASES, REGION_ALIASES, WET_ALIASES
from .records import SourceHint

SEASON_ALIASES = {"dry": DRY_ALIASES, "wet": WET_ALIASES}
UNAVAILABLE_MEASURES = (
    ("fertiliser", "fertilizer"),
    ("fertilizer", "fertilizer"),
    ("ปุ๋ย", "fertilizer"),
    ("carbon footprint", "carbon_footprint"),
    ("carbon emission", "carbon_footprint"),
    ("ก๊าซเรือนกระจก", "carbon_footprint"),
    ("คาร์บอน", "carbon_footprint"),
    ("energy consumption", "energy"),
    ("energy input", "energy"),
    ("พลังงาน", "energy"),
    ("water consumption", "water"),
    ("water use", "water"),
    ("การใช้น้ำ", "water"),
    ("น้ำที่ใช้", "water"),
)
FILTER_FIELDS = ("crop_id", "year_ce", "region_code", "season", "spatial_level", "source_id")


@dataclass(frozen=True)
class ParsedQuery:
    crop_id: str | None = None
    year_ce: int | None = None
    region_code: str | None = None
    season: str | None = None
    spatial_level: str | None = None
    source_id: str | None = None
    warnings: tuple[str, ...] = ()
    unavailable_measures: tuple[str, ...] = ()

    def as_filters(self) -> dict:
        return {field_name: getattr(self, field_name) for field_name in FILTER_FIELDS}


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower()
    return text.translate(str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789"))


def has_term(text: str, term: str) -> bool:
    term = normalize(term)
    if re.fullmatch(r"[a-z ]+", term):
        return re.search(r"(?<![a-z])" + re.escape(term) + r"(?![a-z])", text) is not None
    return term in text


def parse_query(query: str, sources: tuple[SourceHint, ...] = ()) -> ParsedQuery:
    """Identify explicit concepts. Uncertain fields are left empty."""
    text = normalize(query)
    warnings: list[str] = []
    crop_id = _one_concept(text, CROP_ALIASES, "crop", warnings)
    region_code = _one_concept(text, REGION_ALIASES, "region", warnings)
    season = _one_concept(text, SEASON_ALIASES, "season", warnings)
    spatial_level = None
    if region_code:
        spatial_level = "region"
    elif any(has_term(text, term) for term in COUNTRY_ALIASES):
        spatial_level = "country"
    year_ce = _year(text, warnings)
    source_id = _source(text, sources, warnings)
    unavailable = []
    for term, measure in UNAVAILABLE_MEASURES:
        if measure not in unavailable and has_term(text, term):
            unavailable.append(measure)
    return ParsedQuery(
        crop_id=crop_id,
        year_ce=year_ce,
        region_code=region_code,
        season=season,
        spatial_level=spatial_level,
        source_id=source_id,
        warnings=tuple(warnings),
        unavailable_measures=tuple(unavailable),
    )


def _one_concept(text: str, mapping: dict[str, tuple[str, ...]], label: str, warnings: list[str]) -> str | None:
    keys = _independent_keys(text, mapping)
    if len(keys) > 1:
        warnings.append(f"The {label} is ambiguous, so no {label} filter was applied.")
        return None
    if len(keys) == 1:
        return keys[0]
    return None


def _independent_keys(text: str, mapping: dict[str, tuple[str, ...]]) -> list[str]:
    found: list[tuple[str, str]] = []
    for key, aliases in mapping.items():
        for alias in aliases:
            if has_term(text, alias):
                found.append((key, normalize(alias)))
    keys: list[str] = []
    for key, alias in found:
        if any(len(other) > len(alias) and alias in other for _, other in found):
            continue
        if key not in keys:
            keys.append(key)
    return keys


def _year(text: str, warnings: list[str]) -> int | None:
    years: list[int] = []
    for raw in re.findall(r"(?<!\d)(?:20\d{2}|25\d{2})(?!\d)", text):
        year = int(raw)
        if year >= 2500:
            original = year
            year -= 543
            warnings.append(f"Year {original} was converted from Buddhist Era to {year} CE.")
        if year not in years:
            years.append(year)
    if len(years) > 1:
        warnings.append("The year is ambiguous, so no year filter was applied.")
        return None
    if not years:
        return None
    year = years[0]
    if not 1900 <= year <= 2100:
        warnings.append("The year is outside the supported Common Era range, so no year filter was applied.")
        return None
    return year


def _source(text: str, sources: tuple[SourceHint, ...], warnings: list[str]) -> str | None:
    if not sources:
        return None
    title_ids = []
    for source in sources:
        if has_term(text, source.title) and source.source_id not in title_ids:
            title_ids.append(source.source_id)
    if len(title_ids) == 1:
        return title_ids[0]
    if len(title_ids) > 1:
        warnings.append("The source is ambiguous, so no source filter was applied.")
        return None
    agencies: dict[str, list[str]] = {}
    for source in sources:
        agencies.setdefault(normalize(source.agency), [])
        if source.source_id not in agencies[normalize(source.agency)]:
            agencies[normalize(source.agency)].append(source.source_id)
    unique_hits = []
    shared_hit = False
    for agency, source_ids in agencies.items():
        if len(agency) < 3 or not has_term(text, agency):
            continue
        if len(source_ids) == 1:
            unique_hits.append(source_ids[0])
        else:
            shared_hit = True
    if len(unique_hits) == 1:
        return unique_hits[0]
    if len(unique_hits) > 1 or shared_hit:
        warnings.append("The source is ambiguous, so no source filter was applied.")
    return None
