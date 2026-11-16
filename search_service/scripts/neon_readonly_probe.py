"""Read-only Neon staging probe. Prints identity and catalog facts, never the URL."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def endpoint_facts(url: str) -> dict:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    query = {key.lower(): (item[-1].lower() if item else "") for key, item in parse_qs(parsed.query).items()}
    database = (parsed.path or "").lstrip("/")
    sslmode = query.get("sslmode", "")
    if host in {"localhost", "127.0.0.1", "postgres"}:
        raise RuntimeError("localhost is not a cloud staging target")
    if not host.endswith(".neon.tech"):
        raise RuntimeError("the host is not a Neon endpoint")
    if "-pooler" in host:
        raise RuntimeError("the endpoint is pooled")
    if sslmode not in {"require", "verify-ca", "verify-full"}:
        raise RuntimeError("the URL does not require TLS")
    if database != "s1g14_staging":
        raise RuntimeError("the URL database is not the staging database")
    return {
        "database_in_url": database,
        "neon_endpoint": True,
        "direct_endpoint": host.startswith("ep-") and "-pooler" not in host,
        "aws_singapore": "ap-southeast-1" in host,
        "sslmode": sslmode,
        "channel_binding": query.get("channel_binding", ""),
    }


def main() -> int:
    report: dict = {"writes": 0, "statements": "select-only"}
    try:
        values = load_env(ENV_PATH)
        if values.get("S1G14_STAGING_WRITE_APPROVED", "") not in {"", "0"}:
            raise RuntimeError("the write approval flag is set")
        url = values.get("STAGING_DATABASE_URL", "").strip()
        if not url:
            raise RuntimeError("STAGING_DATABASE_URL is not configured")
        report["endpoint"] = endpoint_facts(url)
        import psycopg
        from psycopg import sql

        connection = psycopg.connect(url, connect_timeout=20, autocommit=True)
        try:
            connection.execute("SET default_transaction_read_only = on")
            connection.execute("SET statement_timeout = '15s'")
            connection.autocommit = False
            connection.read_only = True
            report["session"] = query_session(connection)
            report["client_ssl"] = client_ssl(connection)
            report["endpoint_id_matches_host"] = endpoint_matches(connection, url)
            report["catalog"] = query_catalog(connection, sql)
            connection.rollback()
        finally:
            connection.close()
        report["ok"] = True
    except Exception as exc:
        report["ok"] = False
        report["error_type"] = type(exc).__name__
        report["sqlstate"] = getattr(exc, "sqlstate", None)
        report["reason"] = safe_reason(exc)
    print(json.dumps(report, indent=2, default=str))
    return 0 if report.get("ok") else 1


def client_ssl(connection) -> dict:
    parameters = connection.info.get_parameters()
    return {
        "ssl_in_use": bool(connection.pgconn.ssl_in_use),
        "sslmode": parameters.get("sslmode", ""),
        "channel_binding": parameters.get("channel_binding", ""),
    }


def endpoint_matches(connection, url: str) -> bool:
    endpoint_id = connection.execute("SELECT current_setting('neon.endpoint_id')").fetchone()[0]
    host = (urlparse(url).hostname or "").lower()
    return bool(endpoint_id) and host.startswith(str(endpoint_id).lower() + ".")


def query_session(connection) -> dict:
    database, user, version, read_only = connection.execute(
        """
        SELECT current_database(), current_user, current_setting('server_version'),
               current_setting('transaction_read_only')
        """
    ).fetchone()
    ssl = connection.execute(
        """
        SELECT ssl, version, cipher, bits
        FROM pg_stat_ssl
        WHERE pid = pg_backend_pid()
        """
    ).fetchone()
    owner = connection.execute(
        """
        SELECT pg_catalog.pg_get_userbyid(datdba)
        FROM pg_database
        WHERE datname = current_database()
        """
    ).fetchone()[0]
    return {
        "database": database,
        "user": user,
        "server_version": version,
        "transaction_read_only": read_only,
        "ssl": None if ssl is None else {"on": bool(ssl[0]), "version": ssl[1], "cipher": ssl[2], "bits": ssl[3]},
        "database_owner": owner,
    }


def query_catalog(connection, sql) -> dict:
    schemas = [row[0] for row in connection.execute(
        "SELECT nspname FROM pg_namespace ORDER BY 1"
    )]
    tables = [
        {"schema": row[0], "table": row[1]}
        for row in connection.execute(
            """
            SELECT schemaname, tablename
            FROM pg_tables
            WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
            ORDER BY 1, 2
            """
        )
    ]
    counts = []
    for item in tables:
        query = sql.SQL("SELECT COUNT(*) FROM {}.{}").format(sql.Identifier(item["schema"]), sql.Identifier(item["table"]))
        counts.append({**item, "rows": int(connection.execute(query).fetchone()[0])})
    extensions = [
        {"name": row[0], "version": row[1]}
        for row in connection.execute("SELECT extname, extversion FROM pg_extension ORDER BY 1")
    ]
    vector = connection.execute(
        """
        SELECT default_version, installed_version
        FROM pg_available_extensions
        WHERE name = 'vector'
        """
    ).fetchone()
    role = connection.execute(
        """
        SELECT rolsuper, rolcreatedb, rolcreaterole, rolinherit, rolcanlogin, rolreplication
        FROM pg_roles
        WHERE rolname = current_user
        """
    ).fetchone()
    membership = [
        row[0]
        for row in connection.execute(
            """
            SELECT granted.rolname
            FROM pg_auth_members member
            JOIN pg_roles granted ON granted.oid = member.roleid
            JOIN pg_roles subject ON subject.oid = member.member
            WHERE subject.rolname = current_user
            ORDER BY 1
            """
        )
    ]
    privileges = {
        "database_connect": bool(connection.execute(
            "SELECT has_database_privilege(current_user, current_database(), 'CONNECT')"
        ).fetchone()[0]),
        "database_create": bool(connection.execute(
            "SELECT has_database_privilege(current_user, current_database(), 'CREATE')"
        ).fetchone()[0]),
        "database_temp": bool(connection.execute(
            "SELECT has_database_privilege(current_user, current_database(), 'TEMP')"
        ).fetchone()[0]),
        "public_usage": bool(connection.execute(
            "SELECT has_schema_privilege(current_user, 'public', 'USAGE')"
        ).fetchone()[0]),
        "public_create": bool(connection.execute(
            "SELECT has_schema_privilege(current_user, 'public', 'CREATE')"
        ).fetchone()[0]),
    }
    identity = {}
    for name in ("neon.project_id", "neon.branch_id", "neon.endpoint_id"):
        identity[name] = connection.execute("SELECT current_setting(%s)", (name,)).fetchone()[0]
    return {
        "schemas": schemas,
        "tables": counts,
        "extensions": extensions,
        "vector": None if vector is None else {"default_version": vector[0], "installed_version": vector[1]},
        "role": None if role is None else {
            "superuser": role[0],
            "createdb": role[1],
            "createrole": role[2],
            "inherit": role[3],
            "login": role[4],
            "replication": role[5],
            "member_of": membership,
        },
        "privileges": privileges,
        "neon_identity": identity,
    }


def safe_reason(exc: BaseException) -> str:
    text = str(exc)
    lowered = text.lower()
    if "://" in text or "password" in lowered or "@" in text:
        return type(exc).__name__
    if len(text) > 180:
        return type(exc).__name__
    return text


if __name__ == "__main__":
    raise SystemExit(main())
