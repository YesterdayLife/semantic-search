"""Import archived OAE rice observations, with a backup and one SQLite transaction.

No invented zero records. National observations and province sums are kept distinct.
Run --database PATH for a dry run; add --apply to commit the reviewed update.
The XLSX reader only accepts a single, flat, formula-free worksheet.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "data" / "oae_rice_2026-11-16"
METRICS = {
    "ผลผลิต": ("production", "ตัน", "t"),
    "เนื้อที่เพาะปลูก": ("area_planted", "ไร่", "rai"),
    "เนื้อที่เก็บเกี่ยว": ("area_harvested", "ไร่", "rai"),
    "ผลผลิตต่อเนื้อที่เพาะปลูก": ("yield_planted", "กิโลกรัมต่อไร่", "kg/rai"),
    "ผลผลิตต่อเนื้อที่เก็บเกี่ยว": ("yield_harvested", "กิโลกรัมต่อไร่", "kg/rai"),
}
ADDITIVE = ("production", "area_planted", "area_harvested")
NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def source_rows(path):
    if path.suffix == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as stream:
            yield from enumerate(csv.DictReader(stream), 2)
        return
    with zipfile.ZipFile(path) as archive:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        if len(workbook.findall("s:sheets/s:sheet", NS)) != 1:
            raise ValueError("Expected a single source worksheet")
        shared = ET.fromstring(archive.read("xl/sharedStrings.xml"))
        strings = ["".join(t.text or "" for t in si.findall(".//s:t", NS)) for si in shared]
        sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        headers = None
        for row in sheet.findall("s:sheetData/s:row", NS):
            values = {}
            for cell in row:
                if cell.find("s:f", NS) is not None:
                    raise ValueError("Source formulas require separate validation")
                column = "".join(c for c in cell.attrib["r"] if c.isalpha())
                value = cell.find("s:v", NS)
                text = value.text if value is not None else ""
                if cell.get("t") == "s":
                    text = strings[int(text)]
                elif cell.get("t") == "inlineStr":
                    text = "".join(t.text or "" for t in cell.findall(".//s:t", NS))
                values[column] = text
            if headers is None:
                headers = values
            elif any(values.values()):
                yield int(row.attrib["r"]), {name: values.get(col, "") for col, name in headers.items()}


def prepare(connection, archive=ARCHIVE):
    mapping = dict(connection.execute("SELECT province,region_code FROM province_region_map"))
    sizes = Counter(mapping.values())
    names = dict(connection.execute("SELECT region_code,region_name FROM region"))
    manifest = json.loads((archive / "manifest.json").read_text(encoding="utf-8"))
    groups = defaultdict(dict)
    countries = defaultdict(dict)
    files = {}
    for item in manifest:
        path = archive / item["file"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
            raise ValueError(f"Source checksum mismatch: {path.name}")
        season, level = item["season"], item["level"]
        # Store the immutable public URL as the source_file key. The manifest maps it to local bytes.
        files[season, level] = item
        for number, row in source_rows(path):
            year = int(row["year"]) - 543
            if not 2019 <= year <= 2024:
                continue
            metric, unit, canonical = METRICS[row["item"]]
            value = Decimal(row["data"].replace(",", ""))
            if row["unit"] != unit or not value.is_finite() or value < 0:
                raise ValueError(f"Invalid measure at {path.name}:{number}")
            observation = (value, number, unit, canonical, row["crop_year"])
            province = row["prov_dsc"].strip()
            if level == "country":
                if province != "ประเทศไทย":
                    raise ValueError(f"Unexpected national geography: {province}")
                bucket = countries[season, year]
            else:
                if province not in mapping:
                    raise ValueError(f"Unmapped province: {province}")
                bucket = groups[season, year, mapping[province]].setdefault(province, {})
            if metric in bucket:
                raise ValueError(f"Duplicate measure at {path.name}:{number}")
            bucket[metric] = observation
    expected = {value[0] for value in METRICS.values()}
    if set(countries) != {(s, y) for s in ("wet", "dry") for y in range(2019, 2025)}:
        raise ValueError("National rice coverage is incomplete")
    for key, values in countries.items():
        if set(values) != expected or any(v[0] <= 0 for v in values.values()):
            raise ValueError(f"Incomplete/nonpositive national measures: {key}")
    for key, provinces in groups.items():
        for province, values in provinces.items():
            if set(values) != expected:
                raise ValueError(f"Incomplete provincial measures: {key} {province}")
    if set(groups) != {(s, y, r) for s, y in countries for r in names}:
        raise ValueError("Expected all six regions in each rice season/year")
    reconciliation = []
    totals = {}
    for key, provinces in groups.items():
        sums = {m: sum((v[m][0] for v in provinces.values()), Decimal(0)) for m in ADDITIVE}
        if any(value <= 0 for value in sums.values()):
            raise ValueError(f"Cannot construct a positive regional record: {key}")
        sums["yield_planted"] = sums["production"] * 1000 / sums["area_planted"]
        sums["yield_harvested"] = sums["production"] * 1000 / sums["area_harvested"]
        totals[key] = sums
    for (season, year), national in sorted(countries.items()):
        for metric in ADDITIVE:
            summed = sum((v[metric] for (s, y, _), v in totals.items() if (s, y) == (season, year)), Decimal(0))
            difference = summed - national[metric][0]
            reconciliation.append({"season": season, "year_ce": year, "metric": metric,
                                   "province_sum": str(summed), "national": str(national[metric][0]),
                                   "difference": str(difference), "exact": difference == 0})
    if not all(row["exact"] for row in reconciliation):
        raise ValueError("Province sums do not exactly reconcile with the national source")
    return files, countries, groups, totals, names, sizes, reconciliation


def apply_rows(connection, prepared):
    files, countries, groups, totals, names, sizes, reconciliation = prepared
    for item in files.values():
        connection.execute("INSERT INTO source_file VALUES (?,?,?) ON CONFLICT(file_path) DO UPDATE SET title=excluded.title",
                           (item["url"], "SRC-04", f"OAE rice {item['season']} {item['level']} archived 2026-11-16"))
    for (season, year), observations in sorted(countries.items()):
        pid = f"P-SRC-04-RIC-{season}-{year}"
        put_process(connection, pid, season, year, observations["production"][4], "Thailand", None,
                    files[season, "country"]["url"])
        put_measures(connection, pid, {m: v[0] for m, v in observations.items()}, observations)
    for (season, year, region), provinces in sorted(groups.items()):
        pid = f"P-REG-SRC-04-RIC-{season}-{region}-{year}"
        url = files[season, "province"]["url"]
        labels = {v[4] for values in provinces.values() for v in values.values()}
        if len(labels) != 1:
            raise ValueError("Mixed crop years in one regional aggregate")
        put_process(connection, pid, season, year, labels.pop(), names[region], region, url)
        put_measures(connection, pid, totals[season, year, region])
        reconciled = all(r["exact"] for r in reconciliation if r["season"] == season and r["year_ce"] == year)
        connection.execute("INSERT INTO regional_aggregate VALUES (?,?,?,?,?) ON CONFLICT(process_id) DO UPDATE SET reporting_provinces=excluded.reporting_provinces,national_reconciled=excluded.national_reconciled,method=excluded.method",
                           (pid, len(provinces), sizes[region], int(reconciled), "sum production and area; derive yields from regional totals"))
        connection.execute("DELETE FROM regional_contribution WHERE process_id=?", (pid,))
        for province, values in provinces.items():
            for metric, (value, number, unit, _, _) in values.items():
                connection.execute("INSERT INTO regional_contribution VALUES (?,?,?,?,?,?,?,?)",
                                   (pid, metric, province, url, number, float(value), unit, int(metric in ADDITIVE)))


def put_process(connection, pid, season, year, label, area, region, url):
    connection.execute("""INSERT INTO process VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(process_id) DO UPDATE SET year_original=excluded.year_original,source_file=excluded.source_file""",
        (pid, "RIC", "SRC-04", area, year, label, "BE", "cultivation_and_harvest", season,
         "rice", url, "region" if region else "country", region))


def put_measures(connection, pid, values, observations=None):
    for metric, value in values.items():
        number = observations[metric][1] if observations else None
        if metric == "production":
            connection.execute("""INSERT INTO exchange VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(process_id,flow_id,direction) DO UPDATE SET quantity=excluded.quantity,source_row=excluded.source_row""",
                (f"{pid}-{metric}", pid, "F-RIC", "SRC-04", "Output", float(value), "t", number, "validated"))
        else:
            connection.execute("""INSERT INTO crop_indicator VALUES (?,?,?,?,?,?,?,?)
                ON CONFLICT(process_id,metric_code) DO UPDATE SET value=excluded.value,source_row=excluded.source_row,moisture_basis=excluded.moisture_basis""",
                (f"{pid}-{metric}", pid, "SRC-04", metric, float(value), "rai" if metric.startswith("area") else "kg/rai", number, None))


def run(database, apply=False, report_path=None):
    database = database.resolve(strict=True)
    connection = sqlite3.connect(database.as_uri() + ("?mode=rw" if apply else "?mode=ro"), uri=True)
    connection.execute("PRAGMA foreign_keys=ON")
    prepared = prepare(connection)
    report = {"database": str(database), "applied": apply, "before": connection.execute("SELECT count(*) FROM process").fetchone()[0],
              "rice_national_records": len(prepared[1]), "rice_regional_records": len(prepared[2]),
              "reconciliation": prepared[-1]}
    if apply:
        backups = ROOT / "artifacts" / "database_backups"
        backups.mkdir(parents=True, exist_ok=True)
        backup = backups / f"{database.stem}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}.sqlite"
        with sqlite3.connect(backup) as dest:
            connection.backup(dest)
        report["backup"] = str(backup)
        with connection:
            apply_rows(connection, prepared)
            if connection.execute("PRAGMA foreign_key_check").fetchall():
                raise ValueError("Foreign key validation failed")
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Database integrity check failed")
            count = connection.execute("SELECT count(*) FROM process WHERE crop_id='RIC' AND source_id='SRC-04'").fetchone()[0]
            if count != 84:
                raise ValueError(f"Unexpected seasonal rice count: {count}")
        report["after"] = connection.execute("SELECT count(*) FROM process").fetchone()[0]
        report["south_records"] = connection.execute("SELECT count(*) FROM process WHERE region_code='SOU'").fetchone()[0]
    connection.close()
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    run(args.database, args.apply, args.report)
