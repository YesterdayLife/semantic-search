"""Create and verify a SELECT-only role in the disposable database."""

from __future__ import annotations

import json
import secrets
from pathlib import Path

from psycopg import sql

from scripts.pg_local_common import APP_SECRET, APP_USER, DATABASE, connect_app, connect_migration, redact

REPORT = Path(__file__).resolve().parents[1] / "artifacts" / "deploy01c" / "security.json"


def main() -> None:
    password = secrets.token_urlsafe(24)
    APP_SECRET.parent.mkdir(parents=True, exist_ok=True)
    APP_SECRET.write_text(password, encoding="utf-8")
    with connect_migration() as connection:
        connection.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(APP_USER)))
        connection.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE").format(
                sql.Identifier(APP_USER),
                sql.Literal(password),
            )
        )
        connection.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(DATABASE), sql.Identifier(APP_USER)))
        connection.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(APP_USER)))
        connection.execute(sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA public TO {}").format(sql.Identifier(APP_USER)))
        connection.execute(sql.SQL("ALTER ROLE {} SET default_transaction_read_only = on").format(sql.Identifier(APP_USER)))
        connection.execute(sql.SQL("ALTER ROLE {} SET statement_timeout = '5s'").format(sql.Identifier(APP_USER)))
        connection.commit()
    report = {"role": APP_USER, "select_count": None, "insert_rejected": False, "create_rejected": False, "read_only": None, "timeout_rejected": False}
    with connect_app() as connection:
        report["select_count"] = int(connection.execute("SELECT COUNT(*) FROM process").fetchone()[0])
        report["read_only"] = connection.execute("SHOW default_transaction_read_only").fetchone()[0]
        report["statement_timeout"] = connection.execute("SHOW statement_timeout").fetchone()[0]
        report["insert_rejected"] = _rejected(connection, "INSERT INTO crop (crop_id, crop_name) VALUES ('NO', 'no')")
        report["create_rejected"] = _rejected(connection, "CREATE TABLE local_probe (id integer)")
        report["timeout_rejected"] = _rejected(connection, "SELECT pg_sleep(6)")
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


def _rejected(connection, statement: str) -> bool:
    try:
        with connection.transaction():
            connection.execute(statement)
    except Exception as exc:
        connection.rollback()
        text = redact(str(exc)).lower()
        return "permission" in text or "read-only" in text or "cancel" in text or "timeout" in text
    return False


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        raise SystemExit(redact(str(exc))) from None
