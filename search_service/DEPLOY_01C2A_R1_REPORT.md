# DEPLOY-01C.2A-R1 — Neon read-only connection retest

The Linux probe used a read-only transaction. `writes` is 0. `--write` was not used. `S1G14_STAGING_WRITE_APPROVED` is unset. The connection string and password were not printed.

## 1. Environment configuration

PASS. `search_service/.env` is non-empty and contains only `STAGING_DATABASE_URL`. The URL database is `s1g14_staging`. The host is a direct `ep-` Neon endpoint in `ap-southeast-1`, with no `-pooler`. `sslmode=require` and `channel_binding=require`. `.gitignore` ignores `.env` and `.env.*`, and keeps `.env.example`. The process environment does not hold the URL or the write flag.

## 2. Neon connection result

PASS. The existing Linux image ran `scripts/neon_readonly_probe.py` after installing `psycopg[binary]==3.3.9` in that container only. The session reported `transaction_read_only=on` and `ok=true`. Windows psycopg remains blocked by Application Control.

## 3. Database identity

PASS. `current_database()` is `s1g14_staging`. The database owner is `neondb_owner`. `neon.endpoint_id` matches the configured hostname.

## 4. Project and branch identity

NOT VERIFIED for the human-readable names. The server exposes identifiers, not the names `s1g14-semantic-search` and `staging`.

| Field | Server value | Owner label |
| --- | --- | --- |
| Project id | `ancient-frog-45954579` | `s1g14-semantic-search` |
| Branch id | `br-flat-bird-b34at9i8` | `staging` |
| Region in hostname | `ap-southeast-1` | AWS Singapore |
| Database | `s1g14_staging` | `s1g14_staging` |

Region and database match the owner statement. The project and branch names still need the owner to match these two ids in the Neon console. A database name alone is not that proof.

## 5. TLS verification

PASS for the client session. libpq reports `ssl_in_use=true`, `sslmode=require`, and `channel_binding=require`. `pg_stat_ssl.ssl` is false because Neon’s proxy terminates TLS before the Postgres process. The client result is the session proof.

## 6. Database emptiness

PASS. Schemas are `information_schema`, `pg_catalog`, `pg_toast`, and `public`. There are no user tables and no application rows. The only installed extension is `plpgsql` 1.0. Nothing was deleted.

## 7. PostgreSQL and pgvector versions

PostgreSQL `18.7 (a21afb5)`. The earlier staging guide requested PostgreSQL 16; this compute is 18.7.

`vector` is available at default version `0.8.7` and is not installed. That available version matches the local pgvector proof. `CREATE EXTENSION` was not run.

## 8. Role privileges

The connected role is `neondb_owner`: login, inherit, create database, create role, replication, and membership in `neon_superuser`. It is not a superuser. It can connect, create databases, and create objects in `public`. This role can own the later migration window. It must not become the application role. No application role exists yet. No `GRANT` was executed.

## 9. Migration runner security gaps

`scripts/neon_staging_migrate.py` still defaults to dry-run and requires both `--write` and `S1G14_STAGING_WRITE_APPROVED=1`. These additional gates are required before a write, and they were not enabled in this phase:

1. Reject `localhost`, `127.0.0.1`, and `postgres` in `require_tls`. The function currently returns before the TLS check for those hosts.
2. Reject a hostname containing `-pooler`, and accept only an `ep-` host ending in `.neon.tech`.
3. Require the URL database, `--database`, and `current_database()` to be `s1g14_staging`.
4. After connect, require `neon.project_id` and `neon.branch_id` to equal owner-confirmed values supplied outside the repository. Refuse the write when either value is absent.
5. Require `neon.endpoint_id` to match the URL host and require libpq `ssl_in_use`.
6. Refuse `load_destination` unless the source fingerprint matches `75aecb4737a45afa01a135af63eff05ff73953a9b4065f2d481ab1716f6f79ef` and the source audit is ready. The fingerprint is currently reported after the load path is already available.
7. Compare `001_schema.sql` and `002_pgvector.sql` with the approved hashes before apply.
8. Treat any existing `public` table as unexpected data, including tables outside the eleven relational names and `process_embeddings`.
9. Reject the application role as the migration connection.

No search, ranking, SQLite, or Qdrant code was changed.

## 10. Source integrity

PASS.

| Source | Result |
| --- | --- |
| SQLite SHA-256 | `9a80da4111beb44a00c5128c3ffdc10f1e6810825f10a838492981d8e3727808` |
| Qdrant | green, 105 points, 1024 dimensions, cosine |
| Vector fingerprint | `75aecb4737a45afa01a135af63eff05ff73953a9b4065f2d481ab1716f6f79ef` |
| Dictionary script | `8db66ee8ee675e43822e827375a2bba299eeed252063cc2a88f4a130e8e7cc60` |
| ONNX weights | `0826f8c1ab9edf1801db86c61919d4d108e8bfc0b809ec823ad366882ff0b77d` |
| Schema drafts | both approved hashes unchanged |

No cloud data was uploaded.

## 11. Blockers

- The owner must confirm that project id `ancient-frog-45954579` is `s1g14-semantic-search` and branch id `br-flat-bird-b34at9i8` is `staging`.
- The owner must accept PostgreSQL 18.7, or provide a PostgreSQL 16 staging compute. pgvector 0.8.7 is available on this compute and is not installed.
- The runner gates in section 9 are not implemented.
- The stored role is the Neon owner role. The SELECT-only application role is still a later step.

## 12. Recommendation

A. READY FOR WRITE-SAFETY FIXES AND APPROVAL

The read-only target is a direct, encrypted, empty `s1g14_staging` database in AWS Singapore. The next work is the runner gates and the owner’s confirmation of the project id, branch id, and PostgreSQL 18.7. That confirmation is not a write approval.

| Item | Result |
| --- | --- |
| Environment | PASS |
| Connection | PASS |
| Database identity | PASS |
| Project and branch names | NOT VERIFIED |
| Client TLS | PASS |
| Emptiness | PASS |
| PostgreSQL 18.7 and available pgvector 0.8.7 | PASS |
| Extension installed | NOT VERIFIED — not enabled |
| Role is migration-capable and not least privilege | PASS |
| Runner pre-write gates | FAIL |
| Source integrity | PASS |
| Cloud writes | PASS — none |

STATUS: NEON READ-ONLY RETEST COMPLETE — NO CLOUD WRITES PERFORMED
