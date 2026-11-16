# DEPLOY-01C.2A — Neon staging setup and pre-write verification

No Neon connection was opened. No SQL was sent to a cloud database. `S1G14_STAGING_WRITE_APPROVED` remains unset. `--write` was not run.

## 1. Neon account and project configuration

NOT VERIFIED. `STAGING_DATABASE_URL`, `DATABASE_URL`, `NEON_API_KEY`, `NEON_PROJECT_ID`, `NEON_DATABASE_URL`, `PGHOST`, `PGUSER`, and `PGPASSWORD` are unset. The Neon CLI is not installed. The repository has `.env.example` only. The active Neon plan, project, branch, and database were not read because no account credential is available to this session.

## 2. Owner setup instructions

Do these steps in the Neon Console. Do not paste the connection string, password, or API key into chat.

1. Sign in at https://console.neon.tech.
2. Open Billing and record the plan name. This session has not seen the account, so it does not assume Free, Launch, or Scale.
3. Create one project for this course staging database. Suggested project name: `s1g14-staging`.
4. Select PostgreSQL 16. The Neon API default for a new project is 18, so the version must be chosen explicitly. PostgreSQL 16 is the major proven by the local integration.
5. Choose the region closest to the future Linux API host. Record the region id shown by Neon. Region ids and the current list are at https://neon.com/docs/introduction/regions. This guide does not choose one.
6. Set the database name to `s1g14_staging` when the form allows it. If the project is created with the default database `neondb`, add a database named `s1g14_staging` on the default branch and leave `neondb` unused. Source: https://neon.com/docs/manage/databases and https://neon.com/docs/manage/projects.
7. Use only the default root branch. The Console names that branch `production`. A project created by the CLI or API names it `main`. Record both the branch name and the branch id from the branch page. Do not create another branch for this migration.
8. Leave compute at the default 0.25 CU (about 1 GB RAM). Do not turn off scale-to-zero. On the Free plan that behavior is fixed at 5 idle minutes and cannot be disabled. Source: https://neon.com/docs/introduction/scale-to-zero and https://neon.com/docs/introduction/plans.
9. Do not run the SQL Editor sample that creates `playing_with_neon`. Do not enable extensions. Do not create tables.
10. Open Connect for the `s1g14_staging` database on the recorded branch. Turn connection pooling off. The hostname must not contain `-pooler`. Migrations need the direct endpoint. Source: https://neon.com/docs/connect/choose-connection.
11. Keep TLS parameters from the Console string. Neon rejects non-TLS connections. The Console includes `sslmode=require` and `channel_binding=require`. `sslmode=verify-full` is the stronger setting Neon documents. Source: https://neon.com/docs/connect/connect-securely. The `sslinfo` extension is not available on Neon.
12. Store the string as the private environment variable `STAGING_DATABASE_URL` on the machine that will run the later Linux client. Do not commit it, do not put it in the frontend, and do not send it in chat.

Billing, from the Neon plans page retrieved for this session. These are published figures, not a reading of this account:

- Free: $0, 100 projects, 10 branches per project, 100 CU-hours per project per month, 1 GB storage per project and 20 GB per account, 5 GB public transfer per project, scale-to-zero after 5 minutes, autoscaling up to 2 CU. Exceeding the CU-hour or transfer allowance suspends compute until the next period. Exceeding storage blocks growth. Source: https://neon.com/docs/introduction/plans.
- Launch, if that is the active plan: $0.106 per CU-hour and $0.35 per GB-month. A new project on Launch can create charges while compute is awake.
- This dataset is far below 1 GB. That is an estimate from the local SQLite file and 105 vectors of 1024 dimensions, not a Neon storage measurement.

After setup, reply with only these non-secret fields: plan name, project id, project name, branch name, branch id, database name, region id, PostgreSQL major, whether the hostname contains `-pooler`, and whether any SQL was executed.

## 3. Project and branch identification

NOT VERIFIED. No project id or branch id is available. A database name, including the proposed `s1g14_staging`, does not prove which Neon project or branch would be reached.

## 4. Database identity

NOT VERIFIED. `current_database()` and `current_user` were not queried. Connectivity verification stops here because the owner has not configured the staging connection.

## 5. PostgreSQL version

NOT VERIFIED on Neon. The requested target is PostgreSQL 16, matching the local server 16.16. The version on a future compute must be read with `SHOW server_version` before a write.

## 6. TLS verification

NOT VERIFIED. No connection was attempted. The later read-only check must reject a localhost or `postgres` hostname, require `sslmode=require`, `verify-ca`, or `verify-full`, and read `ssl` from `pg_stat_ssl` for the current backend. URL text alone is not session proof.

## 7. Database emptiness

NOT VERIFIED. No catalog query was run. A new Neon database contains the `public` schema, system catalogs, and provider roles such as the database owner and `neon_superuser`. Those are not application data. Any user table, including a sample table, blocks the migration. Nothing is deleted by this phase.

## 8. pgvector availability

NOT VERIFIED in a database. Documented on 4 November 2026 at https://neon.com/docs/extensions/pg-extensions: the extension `vector` is available on every listed major, installed with `CREATE EXTENSION vector`, and is not an extra paid feature. The published package is 0.8.0 on PostgreSQL 16 and 0.8.6 on PostgreSQL 18. The local proof used 0.8.7. `vector(1024)` and exact cosine distance are part of the 0.8.0 package. No HNSW index is required for 105 vectors.

The later read-only query is:

```sql
SELECT name, default_version, installed_version
FROM pg_available_extensions
WHERE name = 'vector';
```

The later authorized install, not run now, is:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

## 9. Migration role readiness

NOT VERIFIED. The draft in `migrations/postgres/003_roles.draft.sql` was not executed.

On PostgreSQL 15 and later, only the database owner has `CREATE` on `public`. Neon also grants privileges to `neon_superuser` for a database created in the Console. The load must use that owner, or a migration role that owns the database, on the direct endpoint. The application role must not be that owner and must not be `neon_superuser`.

Create the migration password in the Neon Console. Keep the password out of SQL files and chat. Use the role only for the approved load window, then disable its login. `ALTER DEFAULT PRIVILEGES` must name the role that creates the tables. A session `SET default_transaction_read_only` does not replace grants.

## 10. Application role readiness

NOT VERIFIED. The draft defines `s1g14_staging_app` as `NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT`, with `SELECT` only, `default_transaction_read_only=on`, and `statement_timeout=5s`. It revokes `CREATE` on `public` from `PUBLIC` and from the application role, and it revokes `INSERT`, `UPDATE`, `DELETE`, `TRUNCATE`, `REFERENCES`, and `TRIGGER`. The application role is not a member of the migration role. Create it only after the schema and data exist. The placeholder database name must be replaced with the approved name. Do not run the file before that approval.

## 11. Migration runner safeguards

The runner remains dry-run by default. These gates are present and were not exercised against Neon:

| Safeguard | Result |
| --- | --- |
| Default mode is dry-run | PASS |
| A write requires `--write` | PASS |
| A write requires `S1G14_STAGING_WRITE_APPROVED=1` | PASS |
| `current_database()` must match `--database` | PASS |
| Known application tables with rows block the write | PASS |
| `DROP` statements in the schema files are skipped | PASS |
| SQLite opens read-only and Qdrant is only scrolled | PASS |
| Passwords are redacted from runner errors | PASS |
| Source fingerprint is calculated | PASS |
| Schema file hashes are calculated | PASS |

These required cloud gates are missing. They are blockers for a write:

- Project id and branch id are not checked. The database name is the only destination identity.
- Localhost and the Docker hostname `postgres` are accepted without TLS.
- A pooled hostname containing `-pooler` is accepted.
- `current_user` and `pg_stat_ssl` are not checked.
- A fingerprint mismatch changes the exit code after `load_destination`; it does not stop the load.
- Schema hashes are reported and are not compared with the approved hashes before apply.
- Public tables other than the eleven relational tables and `process_embeddings` do not block the write.
- The connection role is not rejected when it is the application role.

## 12. Source integrity

PASS.

| Source | Result |
| --- | --- |
| SQLite SHA-256 | `9a80da4111beb44a00c5128c3ffdc10f1e6810825f10a838492981d8e3727808` |
| Dictionary script | `8db66ee8ee675e43822e827375a2bba299eeed252063cc2a88f4a130e8e7cc60` |
| `001_schema.sql` | `e73c2f25342c3210e3ff793427dd763d234ba1d36f8d4e9d3054dece4f2fd17e` |
| `002_pgvector.sql` | `47afa1781c649e8e1e94026eb25e5401a0a759c2d55abc417bcfb26ed246861f` |
| `evaluation.json` | `bf72a8ba7ae98365d4b1658d5bdbbd05b7d48f3c4d6db4f6771524b19720800e` |
| ONNX weights | `0826f8c1ab9edf1801db86c61919d4d108e8bfc0b809ec823ad366882ff0b77d` |
| Qdrant `crop_process_bge_m3` | green, 105 points, 1024 dimensions, cosine |
| Local defaults | `DATA_BACKEND=sqlite`, `VECTOR_BACKEND=qdrant` |

No source file, vector, ranking rule, or evaluation report was changed.

## 13. Known blockers

- No Neon project, branch, database, region, or plan can be verified.
- The runner cannot yet prove that a URL reaches the approved project and branch.
- The runner does not yet refuse localhost, a pooled endpoint, a fingerprint mismatch, a schema-hash mismatch, or unexpected public tables before a write.
- Neon PostgreSQL 16 provides pgvector 0.8.0 in the current extensions catalog. The local proof used 0.8.7. The live availability and version still need a read-only catalog query.
- Windows Application Control still blocks the local psycopg binary. The future session belongs on the Linux client.

## 14. Exact owner approval checklist

Approve a write only after every line is true:

1. Plan name is recorded, and Launch or Scale charges are accepted if that plan is active.
2. Project id and project name identify `s1g14-staging` or the name the owner actually created.
3. Branch name and branch id identify the one default branch.
4. Database name is exactly `s1g14_staging`, or the owner records a different empty name and the runner is given that name.
5. Region id is the region selected for the API host.
6. PostgreSQL major is 16.
7. The stored URL is the direct endpoint, with no `-pooler`, and it is not in chat or Git.
8. A read-only session shows `current_database()`, `current_user()`, `server_version`, and `pg_stat_ssl.ssl = true`.
9. Project and branch metadata independently match the URL endpoint. The database name alone is not sufficient.
10. No application tables or rows exist. Provider schemas and roles may exist.
11. `pg_available_extensions` shows `vector` for this Postgres major.
12. Schema hashes still match section 12.
13. Expected load remains 11 tables and 105 vectors, with the counts from DEPLOY-01C.1.
14. The migration connection is the database owner for the load window only.
15. The application role is created later, is SELECT-only, and is not a member of the owner role.
16. The runner blocks the gaps in section 11 before `--write` is permitted.
17. Rollback remains: keep SQLite, Qdrant, and the local test volume. A bad Neon branch is dropped only under a separate approval.

## 15. Proposed DEPLOY-01C.2B execution plan

01C.2B is still a pre-write session.

1. Close the runner gaps in section 11 without opening a write.
2. After the owner stores `STAGING_DATABASE_URL` privately, run a read-only inspection: database, user, server version, SSL, direct-versus-pooled host, project id, branch id, public tables, and available `vector` version.
3. Compare that identity with the checklist in section 14.
4. Stop. Do not set `S1G14_STAGING_WRITE_APPROVED`, apply schema, enable `vector`, or import rows.

The first cloud write is a later phase and uses this order only after that approval:

1. Owner approves project, branch, database, and region.
2. Confirm the destination has no application rows.
3. Confirm TLS and the migration owner role on the direct endpoint.
4. Apply `001_schema.sql` as the database owner.
5. Run `CREATE EXTENSION IF NOT EXISTS vector` and apply `002_pgvector.sql`.
6. Import the 11 tables in dependency order.
7. Import the 105 original vectors.
8. Check row counts and foreign keys.
9. Check vector components, norms, and metadata against the source fingerprint.
10. Check exact cosine ranking, with no HNSW index.
11. Create and test the SELECT-only application role.
12. Run dictionary, semantic, hybrid, compare, catalog, and the 61-query parity checks.
13. Write the acceptance report.

Schema, extension, grants, and imports require the database owner. Search parity uses the application role. Neither action is part of 01C.2A or the proposed read-only 01C.2B.

## Classification

| Criterion | Result |
| --- | --- |
| Account and project configuration | NOT VERIFIED |
| Owner setup guide | PASS |
| Project and branch identity | NOT VERIFIED |
| Database identity | NOT VERIFIED |
| PostgreSQL version on Neon | NOT VERIFIED |
| TLS session | NOT VERIFIED |
| Emptiness | NOT VERIFIED |
| pgvector on the target database | NOT VERIFIED |
| pgvector documented for PostgreSQL 16 | PASS |
| Migration role executed | NOT VERIFIED |
| Application role executed | NOT VERIFIED |
| Role draft | PASS |
| Runner dry-run gates | PASS |
| Runner project, endpoint, and pre-write gates | FAIL |
| Source integrity | PASS |
| Cloud writes in this phase | PASS — none |

Final recommendation:

C. NOT READY — SECURITY OR CONFIGURATION ISSUES

STATUS: DEPLOY-01C.2A COMPLETE — AWAITING OWNER APPROVAL FOR FIRST NEON WRITE
