"""Read-only staging precheck. It does not open PostgreSQL or write SQLite, Qdrant, or a vector export."""

from __future__ import annotations

import hashlib
import json
import math
import socket
import sqlite3
import struct
import urllib.request
from pathlib import Path

from app.migration_audit import audit_sqlite

SQLITE = Path(r"D:\Final Project\Hee_M3\output\S1-G14_M3.sqlite")
FILES = [
    SQLITE,
    Path(r"D:\Final Project\Hee_M4\ch6 semantic search\src\semantic_search.py"),
    Path(r"D:\Final Project\Hee_M4\ch6 semantic search\src\build_serving_layer.py"),
    Path(r"D:\Final Project\Hee_M4\ch6 semantic search\graph\import\import.cypher"),
    Path(r"D:\Final Project\final\search_service\docker-compose.yml"),
    Path(r"D:\Final Project\final\search_service\evaluation\reports\evaluation.json"),
    Path(r"D:\Final Project\final\search_service\.cache\huggingface\hub\models--Xenova--bge-m3\snapshots\4de13258303883538bd53b696b452bf8099f0858\onnx\model_quantized.onnx"),
]


def hashes() -> dict:
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in FILES}


def ports() -> dict:
    found = {}
    for port in (5432, 5433, 54329, 3306, 6333):
        sock = socket.socket()
        sock.settimeout(0.4)
        try:
            found[port] = sock.connect_ex(("127.0.0.1", port)) == 0
        finally:
            sock.close()
    return found


def qdrant() -> dict:
    with urllib.request.urlopen("http://127.0.0.1:6333/collections/crop_process_bge_m3", timeout=5) as response:
        result = json.load(response)["result"]
    vectors = result["config"]["params"]["vectors"]
    offset = None
    points = []
    while True:
        body = {"limit": 64, "with_payload": True, "with_vector": True}
        if offset is not None:
            body["offset"] = offset
        request = urllib.request.Request(
            "http://127.0.0.1:6333/collections/crop_process_bge_m3/points/scroll",
            data=json.dumps(body).encode(),
            headers={"content-type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            page = json.load(response)["result"]
        points.extend(page.get("points") or [])
        offset = page.get("next_page_offset")
        if not offset:
            break
    process_ids = []
    point_ids = []
    bad_dim = 0
    nonfinite = 0
    missing_payload = []
    revisions = set()
    models = set()
    providers = set()
    dimensions = set()
    payload_keys = set()
    digest = hashlib.sha256()
    required = {
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
        "embedding_provider",
        "model_revision",
        "vector_dimension",
    }
    ordered = sorted(points, key=lambda point: str((point.get("payload") or {}).get("process_id")))
    for point in ordered:
        payload = point.get("payload") or {}
        vector = point.get("vector") or []
        process_ids.append(payload.get("process_id"))
        point_ids.append(point.get("id"))
        payload_keys.update(payload)
        if set(required) - set(payload):
            missing_payload.append(payload.get("process_id"))
        if len(vector) != 1024:
            bad_dim += 1
        if any(not isinstance(value, (int, float)) or not math.isfinite(float(value)) for value in vector):
            nonfinite += 1
        revisions.add(payload.get("model_revision"))
        models.add(payload.get("embedding_model"))
        providers.add(payload.get("embedding_provider"))
        dimensions.add(payload.get("vector_dimension"))
        digest.update(str(payload.get("process_id")).encode())
        digest.update(struct.pack("<1024d", *[float(value) for value in vector]))
    return {
        "status": result.get("status"),
        "points_count": result.get("points_count"),
        "scrolled": len(points),
        "size": vectors.get("size"),
        "distance": vectors.get("distance"),
        "unique_process_ids": len(set(process_ids)),
        "unique_point_ids": len(set(point_ids)),
        "bad_dimension": bad_dim,
        "nonfinite": nonfinite,
        "missing_payload": missing_payload,
        "revisions": sorted(str(item) for item in revisions),
        "models": sorted(str(item) for item in models),
        "providers": sorted(str(item) for item in providers),
        "declared_dimensions": sorted(dimensions),
        "payload_keys": sorted(payload_keys),
        "ordered_vector_sha256": digest.hexdigest(),
    }


def constraints() -> dict:
    uri = SQLITE.resolve().as_uri().replace("file:///", "file:/") + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.execute("PRAGMA query_only=ON")
    statements = {
        "flow_type": "SELECT COUNT(*) FROM flow WHERE flow_type NOT IN ('Product','Material','Energy','Water')",
        "spatial_level": "SELECT COUNT(*) FROM process WHERE spatial_level NOT IN ('country','region')",
        "spatial_rule": (
            "SELECT COUNT(*) FROM process WHERE NOT ("
            "(spatial_level = 'country' AND area = 'Thailand' AND region_code IS NULL) "
            "OR (spatial_level = 'region' AND region_code IS NOT NULL))"
        ),
        "direction": "SELECT COUNT(*) FROM exchange WHERE direction NOT IN ('Input','Output')",
        "quantity_nonpositive": "SELECT COUNT(*) FROM exchange WHERE quantity <= 0",
        "review_status": "SELECT COUNT(*) FROM exchange WHERE review_status <> 'validated'",
        "indicator_nonpositive": "SELECT COUNT(*) FROM crop_indicator WHERE value <= 0",
        "aggregate_counts": "SELECT COUNT(*) FROM regional_aggregate WHERE reporting_provinces <= 0 OR provinces_in_region <= 0",
        "aggregate_flag": "SELECT COUNT(*) FROM regional_aggregate WHERE national_reconciled NOT IN (0, 1)",
        "contribution_flag": "SELECT COUNT(*) FROM regional_contribution WHERE used_in_formula NOT IN (0, 1)",
        "natural_process_key": (
            "SELECT COUNT(*) FROM (SELECT 1 FROM process "
            "GROUP BY crop_id, source_id, year_ce, season, spatial_level, area HAVING COUNT(*) > 1)"
        ),
        "exchange_key": (
            "SELECT COUNT(*) FROM (SELECT 1 FROM exchange GROUP BY process_id, flow_id, direction HAVING COUNT(*) > 1)"
        ),
        "indicator_key": (
            "SELECT COUNT(*) FROM (SELECT 1 FROM crop_indicator GROUP BY process_id, metric_code HAVING COUNT(*) > 1)"
        ),
    }
    found = {name: int(connection.execute(sql).fetchone()[0]) for name, sql in statements.items()}
    codes = {
        "crops": [row[0] for row in connection.execute("SELECT crop_id FROM crop ORDER BY crop_id")],
        "regions": [row[0] for row in connection.execute("SELECT region_code FROM region ORDER BY region_code")],
        "years": [row[0] for row in connection.execute("SELECT DISTINCT year_ce FROM process ORDER BY year_ce")],
        "exchange_units": [row[0] for row in connection.execute("SELECT DISTINCT unit FROM exchange ORDER BY unit")],
        "sources": [row[0] for row in connection.execute("SELECT source_id FROM data_source ORDER BY source_id")],
        "indicators": [row[0] for row in connection.execute("SELECT DISTINCT metric_code FROM crop_indicator ORDER BY metric_code")],
    }
    connection.close()
    return {"violations": found, "codes": codes}


def main() -> None:
    report = audit_sqlite(SQLITE)
    summary = {
        "hashes": hashes(),
        "ports": ports(),
        "relational": {
            "counts": report["counts"],
            "count_mismatches": report["count_mismatches"],
            "orphan_total": report["orphan_total"],
            "country_null_regions": report["country_null_regions"],
            "output_exchanges": report["output_exchanges"],
            "duplicate_process_ids": report["duplicate_process_ids"],
            "fractional_quantities": report["fractional_quantities"],
        },
        "constraints": constraints(),
        "qdrant": qdrant(),
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
