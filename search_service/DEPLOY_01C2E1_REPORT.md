# DEPLOY-01C.2E.1 — Least-privilege application role plan

No role was created. No Neon write ran. `S1G14_STAGING_WRITE_APPROVED` is unset. `STAGING_DATABASE_URL` was not changed. The catalog inspection used one read-only session on `s1g14_staging`.

## 1. Existing role-draft review

`migrations/postgres/003_roles.draft.sql` is not safe to execute as written.

- Both `CREATE ROLE` statements are comments, so the later `GRANT` statements have no role to receive them.
- The password placeholder would be a real password if it were uncommented inside the file.
- `ALTER DEFAULT PRIVILEGES FOR ROLE s1g14_staging_migrator` targets a role that does not exist and does not own the tables. The 12 application tables are owned by `neondb_owner`. That statement would fail, and it would not cover future tables created by the owner.
- `REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER FROM s1g14_staging_app` removes only grants made directly to that role. It does not remove rights inherited through `PUBLIC`, `neon_superuser`, `pg_write_all_data`, or table ownership.
- The comment says the migration role owns the schema. The live `public` schema is owned by `pg_database_owner`. `PUBLIC` already has `USAGE` and does not have `CREATE`.
- The draft does not set `NOREPLICATION` or `NOBYPASSRLS`, and it does not remove the database `TEMPORARY` privilege that `PUBLIC` currently holds.
- `default_transaction_read_only` is only a session default. A role that also has `INSERT` can turn it off with `SET`. The grant list is the real boundary.

The reviewed replacement is `migrations/postgres/003_roles.reviewed.draft.sql`. It was not executed. The original draft and both schema files were left unchanged.

## 2. PostgreSQL 18 compatibility

PASS. The live server is PostgreSQL `18.7 (a21afb5)` with pgvector `0.8.7`.

`CREATE ROLE`, `GRANT`, `REVOKE`, `ALTER DEFAULT PRIVILEGES`, and `ALTER ROLE ... SET` are valid in PostgreSQL 18. Role creation is transactional, so the reviewed script can roll back as one unit. `NOBYPASSRLS` and `CONNECTION LIMIT` are supported. The `public` schema ownership by `pg_database_owner` is the PostgreSQL 15 and later model, and that is what this database uses.

Neon does not provide a login superuser. `neondb_owner` is not a superuser, but it has `CREATEROLE` through membership in `neon_superuser`, so it can create this non-superuser role.

## 3. Required application privileges

The future role `s1g14_staging_app` needs:

- `LOGIN`, with no superuser, createdb, createrole, replication, or bypassrls attribute
- `NOINHERIT`, so a later membership does not become active by itself
- `CONNECT` on `s1g14_staging`
- `USAGE` on schema `public`
- `SELECT` on the 11 relational tables and `process_embeddings`
- Execute rights for the existing `vector` `<=>` operator

The live catalog already gives `PUBLIC` execute on that operator and usage on the `vector` type. No extra function grant is required. There are no sequences in the application schema.

The role must not receive `pg_read_all_data`, `pg_write_all_data`, or membership in `neon_superuser`.

## 4. Effective privilege risks

The read-only catalog shows the effective rights today.

| Object | Current effective grant |
| --- | --- |
| `neondb_owner` | Member of `neon_superuser`, which is a member of `pg_read_all_data` and `pg_write_all_data`. It can read and write every table. |
| `s1g14_staging_app` | Does not exist. |
| `s1g14_staging_migrator` | Does not exist. |
| Database `s1g14_staging` | `PUBLIC` has `CONNECT` and `TEMPORARY`. `PUBLIC` does not have `CREATE`. `neondb_owner` and `neon_superuser` have `CONNECT`, `TEMPORARY`, and `CREATE`. |
| Database `postgres` | `PUBLIC` has `CONNECT` and `TEMPORARY`. |
| Schema `public` | `PUBLIC` has `USAGE` only. `CREATE` belongs to `pg_database_owner`. |
| All 12 application tables | Owner is `neondb_owner`. The access list is empty, so `PUBLIC` has no `SELECT`, `INSERT`, `UPDATE`, `DELETE`, or `TRUNCATE`. |
| Default privileges | `cloud_admin` grants future table and sequence rights to `neon_superuser` only. Nothing grants future rights to an application role. |

A role created by SQL therefore starts with no table access. `GRANT SELECT` supplies the required read path. It does not gain write access unless it is also made a member of `neon_superuser` or receives an explicit write grant.

`ALTER ROLE SET default_transaction_read_only` remains useful defense in depth. It is not a substitute for the missing write grant. The reviewed script still sets it, and sets `statement_timeout` to 5 seconds. The current queries are small enough for that limit: 3,573 relational rows and 105 vectors.

`PUBLIC` can still connect to the `postgres` maintenance database. That is the normal PostgreSQL default, not an elevated membership. The application role will not own objects there and will not receive application-table rights there. Revoking `CONNECT` on `postgres` from `PUBLIC` is not part of this plan because Neon service roles may rely on that default.

## 5. Neon-specific role limitations

Roles are branch-scoped, with a limit of 500 roles on a branch. A child branch copies roles from its parent. Neon-managed roles such as `neon_service` are outside this plan and must not be altered.

The creation path changes the privilege result:

- Neon Console, the Neon API, and `neon roles create` without `--access` add the role to `neon_superuser`. That membership inherits database creation, role creation, replication, bypassrls, read-all-data, and write-all-data. That path must not be used for `s1g14_staging_app`.
- SQL `CREATE ROLE` does not add `neon_superuser`. The reviewed script uses this path.
- `neon roles create --access read_only` is also a limited role, but it does not express the connection limit, `NOINHERIT`, read-only default, statement timeout, or `TEMPORARY` revoke required here. The approved path is the reviewed SQL.

Neon requires a plaintext password with at least 60 bits of entropy and stores the SCRAM verifier itself. A pre-hashed password is not the planned input. `neon_superuser` cannot log in and must not be altered. The application role must own no objects, so a later `DROP ROLE` does not cascade into the tables.

## 6. Secure password-handling plan

During the later approved phase:

1. Generate the password in the client process with `secrets.token_urlsafe(32)`. That is 256 bits and satisfies Neon's 60-bit minimum.
2. Pass it only as a bound parameter to `CREATE ROLE`. Do not put it in `003_roles.reviewed.draft.sql`, the report, the shell history, or chat.
3. Store it once in `search_service/.env.app`. The existing `.gitignore` rule `.env.*` ignores that name while still allowing `.env.example`.
4. Leave `search_service/.env` and `STAGING_DATABASE_URL` unchanged. That file remains the owner connection for administrative work.
5. Do not send the password to the frontend, a `VITE_` variable, a Docker image layer, or a Git commit.

## 7. Backend environment configuration

The deployed FastAPI process needs three settings and no owner credential:

- `DATA_BACKEND=postgres`
- `VECTOR_BACKEND=pgvector`
- `DATABASE_URL` set to the direct `s1g14_staging_app` connection string

`DATABASE_URL` is the only connection variable the provider reads. `load_settings()` does not treat `STAGING_DATABASE_URL` as `DATABASE_URL`. If the cloud pair is selected without `DATABASE_URL`, startup fails and does not open SQLite. Unset values still default to SQLite and Qdrant. This plan does not change those defaults.

The current provider opens one short connection per operation and then runs `SET default_transaction_read_only = on`. It does not use a connection pool. The first deployment should use the direct Neon endpoint, not a hostname containing `-pooler`. A transaction-mode pooler can discard session settings between statements. Pooling can be tested later; it is not part of role creation.

Every current backend route that touches PostgreSQL uses `SELECT`: catalog, dictionary, eligibility, hydration, and pgvector ranking. Startup loads the local ONNX model and embeds a probe string. It does not issue `CREATE`, `INSERT`, `UPDATE`, `DELETE`, or `CREATE EXTENSION`.

The frontend client reads `VITE_API_BASE` and otherwise calls `/api`. It has no database credential. The Linux service should receive `DATABASE_URL` from its process environment or from `.env.app`, never from the frontend build.

## 8. Proposed SQL and testing plan

The executable statement list is `migrations/postgres/003_roles.reviewed.draft.sql`.

Before it runs, the approved session must confirm the database, user, project, branch, and endpoint, confirm that `s1g14_staging_app` is absent, and confirm that the 12 tables are still owned by `neondb_owner`.

After it commits, run these checks with the new role. Denial tests belong to the approved role-creation phase. Each denial test must run inside its own transaction and end with `ROLLBACK`. If a denial statement unexpectedly succeeds, roll it back, set the role to `NOLOGIN`, and stop.

| Test | Expected result |
| --- | --- |
| T01 | The role logs in. |
| T02 | Database is `s1g14_staging` on the approved project, branch, and endpoint. |
| T03 | Client TLS is in use and channel binding is required. |
| T04 | `SELECT` succeeds on all 12 application tables. |
| T05 | A parameterized `embedding <=>` query returns rows. |
| T06 | Dictionary search returns a known rice result. |
| T07 | Hybrid search returns the same eligible process as the current staging check. |
| T08 | Semantic search returns a pgvector top-5 result. |
| T09 | `INSERT` is denied. |
| T10 | `UPDATE` is denied. |
| T11 | `DELETE` is denied. |
| T12 | `TRUNCATE` is denied. |
| T13 | `CREATE TABLE` is denied. |
| T14 | `ALTER TABLE` is denied. |
| T15 | `DROP TABLE` is denied. |
| T16 | `CREATE EXTENSION` is denied. |
| T17 | `CREATE ROLE` is denied. |
| T18 | The role has no membership, including `neon_superuser`. |
| T19 | SQLite, Qdrant, schema files, and row counts are unchanged. |
| T20 | Logs and responses contain no password or connection string. |

The owner catalog session should also repeat `has_table_privilege` for `SELECT`, `INSERT`, `UPDATE`, `DELETE`, and `TRUNCATE`, plus schema `CREATE` and database `CREATE` and `TEMPORARY`.

## 9. Failure and recovery plan

- Run the reviewed statements as one transaction. If any statement fails, roll it back. PostgreSQL removes the new role with that rollback.
- Do not drop, truncate, or rewrite application tables.
- Do not change `STAGING_DATABASE_URL`.
- If the transaction commits and a validation test fails, set `s1g14_staging_app` to `NOLOGIN`, revoke its table and database grants, and drop the role only after confirming it owns nothing. Do not retry through the Neon Console.
- If an inspection shows membership in `neon_superuser`, treat that as a failed role creation: disable login, drop that role, and stop. Do not use it for the backend.
- A failed denial test that actually changes a row must be rolled back before any other action. No test row may remain.
- Role creation does not change the 3,573 rows or 105 embeddings. Recovery of the data copy is not required.

## 10. Remaining blockers

- The application role does not exist yet. Creating it needs a separate owner write approval.
- Until that approval, the only login is `neondb_owner`, which can write. It must not be the runtime role.
- The backend is not deployed, and local search still defaults to SQLite and Qdrant.
- `PUBLIC` can still connect to the `postgres` maintenance database. That is recorded residual access, not a reason to use an administrator role.

## 11. Recommendation for DEPLOY-01C.2E.2

The live privileges, PostgreSQL 18 behavior, and Neon role rules agree with the reviewed SQL. The next phase may be requested. It is one transaction that creates `s1g14_staging_app` by SQL, grants `SELECT` only, and then runs T01 through T20. It does not deploy the backend.

A. ROLE PLAN VERIFIED — READY TO REQUEST OWNER WRITE APPROVAL

STATUS: DEPLOY-01C.2E.1 COMPLETE — NO NEON WRITES PERFORMED
