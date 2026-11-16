"""Read-only catalog and saved evaluation endpoints."""

import hashlib
import json

from fastapi.testclient import TestClient

from app.main import create_app
from app.public_data import read_evaluation_report, read_public_catalog

CANONICAL = r"D:\Final Project\Hee_M3\output\S1-G14_M3.sqlite"


class _Quiet:
    def start(self):
        return None

    def close(self):
        return None


def test_catalog_lists_sqlite_values_without_paths():
    before = hashlib.sha256(open(CANONICAL, "rb").read()).hexdigest()
    payload = read_public_catalog()
    after = hashlib.sha256(open(CANONICAL, "rb").read()).hexdigest()
    assert after == before
    assert {item["crop_id"] for item in payload["crops"]} == {"CAS", "MAI", "RIC", "SUG"}
    assert payload["process_count"] == 180
    assert _path_free(payload)
    assert "sqlite" not in json.dumps(payload).lower()


def test_evaluation_report_is_saved_data_without_paths():
    payload = read_evaluation_report()
    assert payload["query_count"] >= 60
    assert payload["backends"]["hybrid"]["aggregate"]["precision_at_k"] == 1.0
    assert "queries" not in payload["backends"]["dictionary"]
    assert "safety" not in payload
    assert _path_free(payload)


def _path_free(value) -> bool:
    if isinstance(value, dict):
        return all(_path_free(item) for item in value.values())
    if isinstance(value, list):
        return all(_path_free(item) for item in value)
    if isinstance(value, str):
        return "\\" not in value and ":/" not in value and not value.lower().startswith("file:")
    return True


def test_new_routes_do_not_replace_search(monkeypatch):
    monkeypatch.setattr("app.public_data.DEFAULT_SQLITE_PATH", __import__("pathlib").Path(CANONICAL))
    client = TestClient(create_app(_Quiet(), _Quiet(), _Quiet()))
    catalog = client.get("/catalog")
    report = client.get("/evaluation-report")
    rejected = client.post("/search", json={"query": "rice", "unknown": 1})
    assert catalog.status_code == 200
    assert catalog.json()["process_count"] == 180
    assert report.status_code == 200
    assert report.json()["top_k"] == 5
    assert rejected.status_code == 422
