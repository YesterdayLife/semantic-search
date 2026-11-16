"""Payloads and searchable text must not carry secrets, paths, or private logs."""

from __future__ import annotations

import json

from app.config import DEFAULT_SQLITE_PATH
from app.database import connect_readonly
from app.documents import PAYLOAD_FIELDS, load_documents

CANONICAL = DEFAULT_SQLITE_PATH
PRIVATE_MARKERS = (
    "password",
    "email",
    "ip_address",
    "firstname",
    "lastname",
    "openai_api_key",
    "api_key",
    "mysql_root_password",
)


def test_payload_contains_only_the_documented_fields():
    documents = load_documents(CANONICAL)
    for document in documents:
        payload = document.point_payload("mock-deterministic-v1")
        assert tuple(payload) == PAYLOAD_FIELDS
        encoded = json.dumps(payload, ensure_ascii=False).lower()
        for marker in PRIVATE_MARKERS:
            assert marker not in encoded
        assert "\\" not in encoded
        assert ".sqlite" not in encoded


def test_search_text_excludes_local_paths_and_credentials():
    documents = load_documents(CANONICAL)
    connection = connect_readonly(CANONICAL)
    try:
        paths = [row[0] for row in connection.execute("SELECT file_path FROM source_file")]
        urls = [row[0] for row in connection.execute("SELECT url FROM data_source")]
    finally:
        connection.close()
    blob = "\n".join(document.text for document in documents)
    lowered = blob.lower()
    for marker in PRIVATE_MARKERS:
        assert marker not in lowered
    assert "D:\\" not in blob
    assert "Hee_M3" not in blob
    assert ".sqlite" not in blob
    for path in paths:
        assert path not in blob
    for url in urls:
        if url:
            assert url not in blob
