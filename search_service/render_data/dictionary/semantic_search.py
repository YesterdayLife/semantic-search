"""Concept-aware search over the implemented S1-G14 M3 SQLite database.

This is a transparent, dictionary-based semantic layer. It does not use
embeddings or claim to infer missing LCI inputs.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import unicodedata
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parents[3] / "Hee_M3" / "output" / "S1-G14_M3.sqlite"

CROPS = {
    "CAS": ("มันสำปะหลัง", "cassava", "tapioca"),
    "MAI": ("ข้าวโพดเลี้ยงสัตว์", "ข้าวโพด", "maize", "corn"),
    "RIC": ("ข้าวนาปรัง", "ข้าวนาปี", "ข้าว", "rice"),
    "SUG": ("อ้อยโรงงาน", "อ้อย", "sugarcane"),
}
REGIONS = {
    "NEA": ("ตะวันออกเฉียงเหนือ", "ภาคอีสาน", "อีสาน", "northeast"),
    "NOR": ("ภาคเหนือ", "เหนือ", "north"),
    "SOU": ("ภาคใต้", "ใต้", "south"),
    "EAS": ("ภาคตะวันออก", "ตะวันออก", "east"),
    "WES": ("ภาคตะวันตก", "ตะวันตก", "west"),
    "CEN": ("ภาคกลาง", "กลาง", "central"),
}
COUNTRY = ("ทั่วประเทศ", "ระดับประเทศ", "ประเทศไทย", "ทั้งประเทศ", "thailand", "national", "country")
DRY = ("ข้าวนาปรัง", "นาปรัง", "ฤดูแล้ง", "dry season", "dry rice")
WET = ("ข้าวนาปี", "นาปี", "ฤดูฝน", "wet season", "wet rice")
UNSUPPORTED_INPUT = ("ปุ๋ย", "น้ำที่ใช้", "พลังงานที่ใช้", "คาร์บอนฟุตพริ้นท์", "fertilizer", "energy input", "carbon footprint")


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower()
    thai_digits = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")
    return text.translate(thai_digits)


def has_term(text: str, term: str) -> bool:
    term = normalize(term)
    if re.fullmatch(r"[a-z ]+", term):
        return re.search(r"(?<![a-z])" + re.escape(term) + r"(?![a-z])", text) is not None
    return term in text


def concept(text: str, values: dict[str, tuple[str, ...]]) -> str | None:
    # Longest aliases first prevents a generic word from masking a specific one.
    choices = sorted(((alias, key) for key, aliases in values.items() for alias in aliases),
                     key=lambda pair: len(pair[0]), reverse=True)
    return next((key for alias, key in choices if has_term(text, alias)), None)


def parse_query(query: str) -> dict:
    text = normalize(query)
    crop = concept(text, CROPS)
    region = concept(text, REGIONS)
    country = any(has_term(text, term) for term in COUNTRY)
    years = []
    for raw in re.findall(r"(?<!\d)(?:20\d{2}|25\d{2})(?!\d)", text):
        year = int(raw)
        if year >= 2500:
            year -= 543
        if year not in years:
            years.append(year)
    season = "dry" if any(has_term(text, t) for t in DRY) else "wet" if any(has_term(text, t) for t in WET) else None
    return {
        "crop_id": crop,
        "region_code": region,
        "spatial_level": "region" if region else "country" if country else None,
        "season": season,
        "year_from": min(years) if years else None,
        "year_to": max(years) if years else None,
        "unsupported_input": any(has_term(text, term) for term in UNSUPPORTED_INPUT),
    }


def search(query: str, db_path: Path = DEFAULT_DB, limit: int = 50) -> dict:
    intent = parse_query(query)
    if intent["unsupported_input"]:
        return {"query": query, "intent": intent, "count": 0, "results": [],
                "message": "ฐานข้อมูลนี้ยังไม่มีปริมาณ Input LCI หรือค่าผลกระทบที่ตรวจยืนยันแล้ว"}
    if not intent["crop_id"]:
        return {"query": query, "intent": intent, "count": 0, "results": [],
                "message": "กรุณาระบุชนิดพืชเพื่อให้ผลการค้นชัดเจน"}
    if not db_path.is_file():
        raise FileNotFoundError(db_path)
    where = ["p.crop_id = ?"]
    params: list = [intent["crop_id"]]
    for column, key in [("p.region_code", "region_code"), ("p.spatial_level", "spatial_level"),
                        ("p.season", "season")]:
        if intent[key] is not None:
            where.append(f"{column} = ?")
            params.append(intent[key])
    if intent["year_from"] is not None:
        where.append("p.year_ce BETWEEN ? AND ?")
        params.extend([intent["year_from"], intent["year_to"]])
    sql = """
        SELECT p.process_id, c.crop_name, p.spatial_level, p.area, p.year_ce,
               p.season, e.quantity AS output_quantity, e.unit AS output_unit,
               p.source_id, p.source_file
        FROM process AS p
        JOIN crop AS c ON c.crop_id = p.crop_id
        JOIN exchange AS e ON e.process_id = p.process_id AND e.direction = 'Output'
        WHERE """ + " AND ".join(where) + " ORDER BY p.year_ce, p.area, p.source_id LIMIT ?"
    uri = db_path.resolve().as_uri().replace("file:///", "file:/") + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as db:
        db.row_factory = sqlite3.Row
        results = [dict(row) for row in db.execute(sql, [*params, limit])]
    message = "พบข้อมูลที่ตรงเงื่อนไข" if results else "ไม่พบข้อมูลตามเงื่อนไขในชุดข้อมูลที่มี"
    return {"query": query, "intent": intent, "count": len(results), "results": results,
            "message": message}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", help="Thai or English natural-language search phrase")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()
    print(json.dumps(search(args.query, args.db, args.limit), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
