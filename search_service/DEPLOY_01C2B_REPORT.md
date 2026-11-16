# DEPLOY-01C.2B — Migration runner security hardening

No Neon write was performed. `--write` was not used against the staging database. `S1G14_STAGING_WRITE_APPROVED` was not set. The connection string and password were not printed.

## 1. Runner security changes

PASS. `scripts/neon_staging_migrate.py` now refuses a write unless every gate below passes. A dry-run does not open the destination. The load path remains behind those gates for a later approved session.

## 2. Files modified

- `scripts/neon_staging_migrate.py`
- `tests/test_neon_staging_migrate.py`
- `tests/test_neon_write_gates.py`
- `DEPLOY_01C2B_REPORT.md`

Schema SQL, the role draft, search ranking, eligibility, SQLite, Qdrant, ONNX weights, Compose, and the evaluation report were not changed.

## 3. Host and TLS validation

PASS. Before a write, the URL must use a direct `ep-*.aws.neon.tech` host. `localhost`, `127.0.0.1`, `::1`, `postgres`, and `*.docker.internal` are rejected. A hostname containing `-pooler` is rejected. The database name must be `s1g14_staging`. `sslmode` must be `require`, `verify-ca`, or `verify-full`. `channel_binding=require` is required. Query parameters outside the TLS and keepalive allowlist are rejected. After connect, libpq `ssl_in_use` must be true. Error text does not include the URL or password.

## 4. Project, branch, and endpoint identity

PASS as a fail-closed gate. NOT VERIFIED as an owner-confirmed mapping.

The repository does not store `EXPECTED_NEON_PROJECT_ID`, `EXPECTED_NEON_BRANCH_ID`, or `EXPECTED_NEON_ENDPOINT_ID`. A write is refused while any of them is absent. When the owner supplies the Console-confirmed values, the runner compares them with `neon.project_id`, `neon.branch_id`, `neon.endpoint_id`, and the URL host label. The database name is not accepted as that proof. No control-plane API key is present, and none was invented.

The read-only probe still reports project id `ancient-frog-45954579` and branch id `br-flat-bird-b34at9i8`. Those values remain pending the owner’s confirmation that they belong to `s1g14-semantic-search` and `staging`.

## 5. Source integrity gate results

PASS. A write checks the canonical SQLite SHA-256, the Qdrant fingerprint, 105 vectors, 1024 finite dimensions, unique process IDs, unique point UUIDs, the approved ONNX revision, and zero relational orphans before any connection is used for a load. The dry-run matched all of those values and performed 0 writes.

## 6. Schema hash gate results

PASS. Both files match the approved hashes:

- `001_schema.sql` `e73c2f25342c3210e3ff793427dd763d234ba1d36f8d4e9d3054dece4f2fd17e`
- `002_pgvector.sql` `47afa1781c649e8e1e94026eb25e5401a0a759c2d55abc417bcfb26ed246861f`

A mismatched hash stops the write before a connection is opened. `DROP` statements inside the schema text are still skipped. There is no cleanup or overwrite path.

## 7. Destination emptiness checks

PASS in the read-only probe. `s1g14_staging` has no public tables and no application rows. Installed extensions are only `plpgsql` 1.0. `vector` is available at 0.8.7 and is not installed. The runner treats any public table, including an empty one, as unexpected migration state and refuses the write. Provider schemas are not treated as application tables.

## 8. PostgreSQL 18 compatibility assessment

NOT VERIFIED for execution. The schema was not applied to PostgreSQL 18. Static review: the drafts use `double precision`, standard primary keys, foreign keys, unique constraints, checks, and `vector(1024)`. They do not use syntax removed in PostgreSQL 18. On PostgreSQL 15 and later, only the database owner can create objects in `public`; `neondb_owner` owns this database, so that owner can apply the schema in a later approved session. The local proof remains PostgreSQL 16.16. The runner accepts only major version 18, which is the version the owner recorded for this staging compute.

## 9. Security test results

PASS. T01 through T18 passed. The tests use fixtures and do not open Neon.

| Test | Result |
| --- | --- |
| T01 localhost | PASS |
| T02 pooled host | PASS |
| T03 database name | PASS |
| T04 missing TLS | PASS |
| T05 missing project id | PASS |
| T06 missing branch id | PASS |
| T07 endpoint mismatch | PASS |
| T08 schema hash | PASS |
| T09 fingerprint | PASS |
| T10 unexpected public table | PASS |
| T11 application role | PASS |
| T12 PostgreSQL major | PASS |
| T13 write without approval | PASS |
| T14 approval without `--write` | PASS |
| T15 missing target metadata | PASS |
| T16 dry-run, zero writes | PASS |
| T17 credential redaction | PASS |
| T18 SQLite and Qdrant defaults | PASS |

## 10. Python regression

PASS. 184 passed in 52.81 s. That is the previous 166 tests plus the 18 new gate tests.

## 11. Frontend regression

PASS. 29 frontend tests passed. `tsc` and the production build passed. Bundle names are unchanged.

## 12. Read-only Neon verification

PASS. The Linux probe ran in a read-only transaction. `writes` is 0. Database `s1g14_staging`, direct Singapore endpoint, client TLS on, `channel_binding=require`, PostgreSQL 18.7, no public tables, `vector` not installed. `pg_stat_ssl` remains false because Neon’s proxy terminates TLS before Postgres.

## 13. Source integrity

PASS. SQLite SHA-256 remains `9a80da4111beb44a00c5128c3ffdc10f1e6810825f10a838492981d8e3727808`. Qdrant fingerprint remains `75aecb4737a45afa01a135af63eff05ff73953a9b4065f2d481ab1716f6f79ef`, with 105 cosine vectors of 1024 dimensions. Local defaults remain SQLite and Qdrant. No cloud upload occurred.

## 14. Remaining blockers

- The owner has not yet confirmed that project id `ancient-frog-45954579` is `s1g14-semantic-search` and branch id `br-flat-bird-b34at9i8` is `staging`.
- The endpoint id is intentionally absent from the repository. The write stays blocked until the owner supplies the Console value.
- PostgreSQL 18 schema execution has not been performed.
- The connected role is still `neondb_owner`, a member of `neon_superuser`. The SELECT-only application role does not exist yet.

## 15. Explicit owner decisions required

1. Confirm the project id, branch id, and endpoint id from the Neon console for project `s1g14-semantic-search`, branch `staging`.
2. Accept PostgreSQL 18.7 as the staging major, with pgvector 0.8.7 installed only during the approved write.
3. Approve one write session. That session sets the three expected ids in the process environment, sets `S1G14_STAGING_WRITE_APPROVED=1`, and passes `--write --database s1g14_staging`.
4. Keep the URL out of Git and chat. Do not use `s1g14_staging_app` for the load.
5. After the load, create the SELECT-only role from the unexecuted draft. Do not drop SQLite, Qdrant, or the local test volume.

## 16. Readiness for the first Neon staging write

The runner will refuse the write until those owner values are present and match the server. This phase did not supply them and did not start the load.

| Item | Result |
| --- | --- |
| Runner gates | PASS |
| Host and TLS rules | PASS |
| Identity gate | PASS |
| Owner-confirmed project and branch mapping | NOT VERIFIED |
| Source and schema gates | PASS |
| Destination emptiness | PASS |
| PostgreSQL 18 execution | NOT VERIFIED |
| Security tests | PASS |
| Python, frontend, and build | PASS |
| Read-only Neon probe | PASS |
| Source integrity | PASS |
| Cloud writes | PASS — none |

Final recommendation:

A. READY TO REQUEST FIRST NEON STAGING WRITE APPROVAL

STATUS: DEPLOY-01C.2B COMPLETE — AWAITING OWNER APPROVAL FOR FIRST NEON WRITE
