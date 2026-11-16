"""Build one searchable document per process without embedding quantities."""

from __future__ import annotations

import hashlib
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path

from .database import connect_readonly, verify_catalog

# Fixed namespace. Point IDs are uuid5(POINT_ID_NAMESPACE, process_id).
# POINT_ID_NAMESPACE itself is uuid5(NAMESPACE_URL, POINT_NAMESPACE_URN),
# so every machine derives the same identifiers.
POINT_NAMESPACE_URN = "urn:s1-g14:crop-process:v1"
POINT_ID_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, POINT_NAMESPACE_URN)
DOCUMENT_SCHEMA_VERSION = "1"

# Validated aliases copied from the existing dictionary search.
# That script is intentionally not imported, so this package cannot change it.
CROP_ALIASES = {
    "CAS": ("มันสำปะหลัง", "cassava", "tapioca"),
    "MAI": ("ข้าวโพดเลี้ยงสัตว์", "ข้าวโพด", "maize", "corn"),
    "RIC": ("ข้าวนาปรัง", "ข้าวนาปี", "ข้าว", "rice"),
    "SUG": ("อ้อยโรงงาน", "อ้อย", "sugarcane"),
}
REGION_ALIASES = {
    "NEA": ("ตะวันออกเฉียงเหนือ", "ภาคอีสาน", "อีสาน", "northeast"),
    "NOR": ("ภาคเหนือ", "เหนือ", "north"),
    "SOU": ("ภาคใต้", "ใต้", "south"),
    "EAS": ("ภาคตะวันออก", "ตะวันออก", "east"),
    "WES": ("ภาคตะวันตก", "ตะวันตก", "west"),
    "CEN": ("ภาคกลาง", "กลาง", "central"),
}
COUNTRY_ALIASES = ("ทั่วประเทศ", "ระดับประเทศ", "ประเทศไทย", "ทั้งประเทศ", "thailand", "national", "country")
DRY_ALIASES = ("ข้าวนาปรัง", "นาปรัง", "ฤดูแล้ง", "dry season", "dry rice")
WET_ALIASES = ("ข้าวนาปี", "นาปี", "ฤดูฝน", "wet season", "wet rice")

PAYLOAD_FIELDS = (
    "process_id",
    "crop_id",
    "year_ce",
    "season",
    "spatial_level",
    "region_code",
    "source_id",
    "text_hash",
    "embedding_model",
    "document_schema_version",
)

PROCESS_SQL = """
SELECT
  p.process_id,
  p.crop_id,
  p.year_ce,
  p.year_original,
  p.calendar,
  p.season,
  p.spatial_level,
  p.region_code,
  p.area,
  p.product_name,
  p.source_id,
  c.crop_name,
  r.region_name,
  s.agency,
  s.title,
  ra.method
FROM process AS p
JOIN crop AS c ON c.crop_id = p.crop_id
JOIN data_source AS s ON s.source_id = p.source_id
LEFT JOIN region AS r ON r.region_code = p.region_code
LEFT JOIN regional_aggregate AS ra ON ra.process_id = p.process_id
ORDER BY p.process_id
"""

FLOW_SQL = """
SELECT e.process_id, f.flow_name, f.flow_type, e.unit
FROM exchange AS e
JOIN flow AS f ON f.flow_id = e.flow_id
WHERE e.direction = 'Output'
ORDER BY e.process_id, f.flow_name, f.flow_type, e.unit
"""

INDICATOR_SQL = """
SELECT process_id, metric_code, unit
FROM crop_indicator
ORDER BY process_id, metric_code, unit
"""


class DocumentBuildError(RuntimeError):
    """Documents could not be built from the validated tables."""


@dataclass(frozen=True)
class SearchDocument:
    process_id: str
    point_id: str
    text: str
    text_hash: str
    payload: dict

    def point_payload(self, embedding_model: str, schema_version: str | None = None, extra: dict | None = None) -> dict:
        """Payload stored in Qdrant. Numeric measures stay out of this object."""
        payload = {
            "process_id": self.process_id,
            "crop_id": self.payload["crop_id"],
            "year_ce": self.payload["year_ce"],
            "season": self.payload["season"],
            "spatial_level": self.payload["spatial_level"],
            "region_code": self.payload["region_code"],
            "source_id": self.payload["source_id"],
            "text_hash": self.text_hash,
            "embedding_model": embedding_model,
            "document_schema_version": schema_version or self.payload["document_schema_version"],
        }
        if tuple(payload) != PAYLOAD_FIELDS:
            raise DocumentBuildError("payload fields drifted from the documented contract")
        if extra:
            for key, value in extra.items():
                if key in payload:
                    raise DocumentBuildError(f"extra payload field collides with {key}")
                payload[key] = value
        return payload


def point_id_for(process_id: str) -> str:
    return str(uuid.uuid5(POINT_ID_NAMESPACE, process_id))


def text_hash_for(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _clean(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _build_text(row: sqlite3.Row, flows: list[tuple[str, str, str]], indicators: list[tuple[str, str]]) -> str:
    crop_id = _clean(row["crop_id"])
    lines = [
        f"Crop: {_clean(row['crop_name'])} ({crop_id}).",
    ]
    aliases = CROP_ALIASES.get(crop_id)
    if aliases:
        lines.append("Crop aliases: " + ", ".join(aliases) + ".")
    lines.append(f"Geographic level: {_clean(row['spatial_level'])}.")
    lines.append(f"Area: {_clean(row['area'])}.")
    if row["spatial_level"] == "country":
        lines.append("Country aliases: " + ", ".join(COUNTRY_ALIASES) + ".")
    region_code = row["region_code"] or None
    if region_code:
        region_name = _clean(row["region_name"])
        if region_name:
            lines.append(f"Region: {region_name} ({region_code}).")
        else:
            lines.append(f"Region code: {region_code}.")
        region_aliases = REGION_ALIASES.get(region_code)
        if region_aliases:
            lines.append("Region aliases: " + ", ".join(region_aliases) + ".")
    year_ce = int(row["year_ce"])
    lines.append(f"Year: {year_ce} CE.")
    year_original = _clean(row["year_original"])
    if year_original and year_original != str(year_ce):
        lines.append(f"Source year label: {year_original} {_clean(row['calendar'])}.")
    season = _clean(row["season"])
    lines.append(f"Season: {season}.")
    if season == "dry":
        lines.append("Season aliases: " + ", ".join(DRY_ALIASES) + ".")
    elif season == "wet":
        lines.append("Season aliases: " + ", ".join(WET_ALIASES) + ".")
    lines.append(f"Source agency: {_clean(row['agency'])}.")
    lines.append(f"Source title: {_clean(row['title'])}.")
    lines.append(f"Product: {_clean(row['product_name'])}.")
    if flows:
        rendered = "; ".join(f"{name} ({flow_type}), unit {unit}" for name, flow_type, unit in flows)
        lines.append(f"Flows: {rendered}.")
    if indicators:
        rendered = "; ".join(f"{metric} ({unit})" for metric, unit in indicators)
        lines.append(f"Indicators: {rendered}.")
    method = _clean(row["method"])
    if method:
        lines.append(f"Regional aggregate method: {method}.")
    return "\n".join(lines)


def _group_flows(connection: sqlite3.Connection) -> dict[str, list[tuple[str, str, str]]]:
    grouped: dict[str, list[tuple[str, str, str]]] = {}
    seen: dict[str, set[tuple[str, str, str]]] = {}
    for row in connection.execute(FLOW_SQL):
        item = (_clean(row["flow_name"]), _clean(row["flow_type"]), _clean(row["unit"]))
        bucket = seen.setdefault(row["process_id"], set())
        if item in bucket:
            continue
        bucket.add(item)
        grouped.setdefault(row["process_id"], []).append(item)
    for items in grouped.values():
        items.sort()
    return grouped


def _group_indicators(connection: sqlite3.Connection) -> dict[str, list[tuple[str, str]]]:
    grouped: dict[str, list[tuple[str, str]]] = {}
    seen: dict[str, set[tuple[str, str]]] = {}
    for row in connection.execute(INDICATOR_SQL):
        item = (_clean(row["metric_code"]), _clean(row["unit"]))
        bucket = seen.setdefault(row["process_id"], set())
        if item in bucket:
            continue
        bucket.add(item)
        grouped.setdefault(row["process_id"], []).append(item)
    for items in grouped.values():
        items.sort()
    return grouped


def documents_from_connection(connection: sqlite3.Connection) -> list[SearchDocument]:
    verify_catalog(connection)
    process_ids = [row[0] for row in connection.execute("SELECT process_id FROM process ORDER BY process_id")]
    flows = _group_flows(connection)
    indicators = _group_indicators(connection)
    documents: list[SearchDocument] = []
    seen: set[str] = set()
    for row in connection.execute(PROCESS_SQL):
        process_id = _clean(row["process_id"])
        if process_id in seen:
            raise DocumentBuildError(f"join multiplied rows for {process_id}")
        seen.add(process_id)
        text = _build_text(row, flows.get(process_id, []), indicators.get(process_id, []))
        digest = text_hash_for(text)
        region_code = row["region_code"] or None
        payload = {
            "process_id": process_id,
            "crop_id": _clean(row["crop_id"]),
            "year_ce": int(row["year_ce"]),
            "season": _clean(row["season"]),
            "spatial_level": _clean(row["spatial_level"]),
            "region_code": region_code,
            "source_id": _clean(row["source_id"]),
            "text_hash": digest,
            "document_schema_version": DOCUMENT_SCHEMA_VERSION,
        }
        documents.append(
            SearchDocument(
                process_id=process_id,
                point_id=point_id_for(process_id),
                text=text,
                text_hash=digest,
                payload=payload,
            )
        )
    if len(documents) != len(process_ids) or seen != set(process_ids):
        missing = sorted(set(process_ids) - seen)
        raise DocumentBuildError(f"document build dropped processes: {missing}")
    return documents


def load_documents(path: Path) -> list[SearchDocument]:
    connection = connect_readonly(path)
    try:
        return documents_from_connection(connection)
    finally:
        connection.close()
