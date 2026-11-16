# DEPLOY-01C.2C-FIX01 — Atomic Neon migration runner

Scope: code and local tests only. The previous one-time staging write authorization was not reused. No Neon migration was executed.

## 1. Root cause of the multi-commit problem

The write path called `connection.commit()` inside each helper, and those helpers also entered `connection.transaction()`. In psycopg, `transaction()` commits when it is the statement that starts the transaction. A later `commit()` then commits whatever transaction is still open. The relational checks ran after `_copy_tables()` had already committed.

A failure after the first commit would have left objects in `public`. The runner then refuses a destination that is no longer empty, and this task does not authorize `DROP`, `TRUNCATE`, a branch reset, or a retry. That is why DEPLOY-01C.2C stopped before any cloud write.

## 2. Original transaction boundaries

On the old success path the same connection committed more than once:

1. `_apply_sql()` committed `001_schema.sql`.
2. `_apply_sql()` committed `002_pgvector.sql`, including `CREATE EXTENSION` and `process_embeddings`.
3. `_copy_tables()` committed the 11 relational inserts, and only then checked counts and fractional quantities.
4. `_copy_vectors()` committed the 105 embeddings.
5. `load_destination()` committed again.

Each `connection.transaction()` block was its own commit boundary when it began the transaction. There was no single rollback that could undo the whole migration.

## 3. Changes made

`scripts/neon_staging_migrate.py`

- Removed `connection.transaction()` and the helper `commit()` calls from schema apply, relational copy, and vector copy.
- The staging connection is opened with `autocommit = False`. `load_destination()` refuses an autocommit connection.
- Source checksum, schema hashes, and vector fingerprint still run before the destination is used.
- Identity, TLS, role, PostgreSQL major version, and the empty-public-schema checks still run first. That read is closed with `rollback()`, so it is not a commit and it does not leave the session read-only.
- Schema, extension, both imports, and the data checks then share one uncommitted transaction.
- `connection.commit()` runs once, only after those checks return.
- A failed pre-commit step rolls back and is not retried. The reported text includes SQLSTATE when the driver exception has one. Text containing a URL or password is reduced to the exception type.
- After a confirmed commit, a new read-only transaction repeats the checks and ends with `rollback()`. A failure there is `COMMITTED — POST-COMMIT VALIDATION FAILED`.
- A lost commit acknowledgement (`commit_uncertain`, `OperationalError`, or `InterfaceError`) is `COMMIT OUTCOME UNKNOWN — OWNER REVIEW REQUIRED`. It is not retried.
- Statements whose first token is `DROP` or `TRUNCATE` are still skipped. The runner has no `DROP SCHEMA`, `DROP DATABASE`, or `TRUNCATE TABLE`.

`tests/test_neon_atomic.py`

- Added failure-injection tests T01–T20. They use an in-memory connection and do not import psycopg at import time.

`migrations/postgres/001_schema.sql` and `002_pgvector.sql` were not edited. Their hashes still match the approved values.

## 4. New transaction boundaries

1. Source integrity, before any destination connection.
2. One staging connection. Read-only identity and emptiness checks, then `rollback()`.
3. One write transaction, started by the first schema statement: both schema files, all relational inserts, all 105 vector inserts, and all pre-commit checks.
4. One `connection.commit()`.
5. A separate read-only transaction for post-commit confirmation, ended with `rollback()`.

No savepoints were added. SQLite is opened read-only only as the copy source. It is not a second PostgreSQL write connection.

## 5. Exact number of commits in the success path

One. `connection.commit()` appears once in `load_destination()`. The identity read and the post-commit read both end with `rollback()`.

## 6. Rollback behavior at every failure point

| Point | Before commit | Result |
| --- | --- | --- |
| Source checksum, fingerprint, or schema hash | Yes, and before connect | No destination transaction |
| URL, TLS, channel binding, database name, role, PostgreSQL major, or identity | Yes | No commit |
| Unexpected public table | Yes | No commit |
| Schema statement, `CREATE EXTENSION`, relational insert, or embedding insert | Yes | `rollback()`, no retry |
| Dimension, row count, foreign key, fractional quantity, null-region, constraint, or table-set check | Yes | `rollback()`, no retry |
| Commit acknowledgement lost | Uncertain | No second attempt and no destructive cleanup |
| Post-commit read fails | No | Committed data is left for owner review |

## 7. pgvector extension transaction handling

`CREATE EXTENSION IF NOT EXISTS vector` stays inside the single uncommitted migration transaction. It is not applied on its own connection and it is not followed by its own commit. The approved `002_pgvector.sql` file was not changed.

This task did not execute that statement on PostgreSQL 18. Transactional behavior of this extension was previously seen on the local PostgreSQL 16 image and is not claimed here as a PostgreSQL 18 proof.

## 8. Pre-commit validation results

The checks now run in the open write transaction, before the only commit:

- 11 relational tables and the approved counts (3,573 rows total)
- `process_embeddings` = 105
- every vector has 1024 dimensions
- one embedding per process, no orphan embedding, no duplicate process id
- the existing orphan queries from `app.migration_audit`
- primary, foreign, unique, and check constraint counts 12, 16, 6, and 12
- public tables are exactly the 11 relational tables plus `process_embeddings`
- the three fractional output quantities, compared by the same float equality as the source audit
- country rows with a null region match the source audit

The success-path mock returned those values and then committed once. No PostgreSQL 18 session executed these queries in this task. Source values were not changed.

## 9. Post-commit validation behavior

After the single commit, the same connection starts a read-only transaction, repeats the checks, and rolls that read back. A failure exits 4 with `COMMITTED — POST-COMMIT VALIDATION FAILED` and does not start another migration. An uncertain commit exits 5 with `COMMIT OUTCOME UNKNOWN — OWNER REVIEW REQUIRED` and `writes` null. Neither path drops or truncates data.

## 10. Failure-injection test results

`tests/test_neon_atomic.py` passed T01–T20 against a mock connection. Neon was not used.

- T01 schema failure rolls back, SQLSTATE reported, commit calls = 0
- T02 extension failure rolls back after earlier schema statements, commit calls = 0
- T03 relational insert failure rolls back, commit calls = 0
- T04 foreign-key validation failure rolls back, commit calls = 0
- T05 embedding insert failure rolls back, commit calls = 0
- T06 bad vector dimension rolls back, commit calls = 0
- T07 row-count mismatch rolls back, commit calls = 0
- T08 fractional quantity mismatch rolls back, commit calls = 0
- T09 fingerprint mismatch does not connect
- T10 schema hash mismatch does not connect
- T11 project identity mismatch does not commit
- T12 unexpected public table does not commit
- T13 success path commits exactly once
- T14 copy and validation helpers contain no `commit()` and no `transaction()`
- T15 post-commit failure is reported as committed, with one commit call
- T16 uncertain commit is reported for owner review; one invocation connects once
- T17 a failed run connects once and `run()` has no retry loop
- T18 the failure path executes no `DROP` or `TRUNCATE`
- T19 a URL in a driver error is not present in the reported reason
- T20 dry-run with the approval flag and destination URL removed stays disconnected

These tests prove the Python call sequence. They do not prove that a real PostgreSQL catalog is empty after rollback.

## 11. PostgreSQL 18 integration test results

NOT VERIFIED.

Local Docker images contain `pgvector/pgvector:0.8.7-pg16` and do not contain a PostgreSQL 18 image. That PostgreSQL 16 container was not started. No disposable PostgreSQL 18.7 database with pgvector 0.8.7 was available. Mock tests are not a substitute for that server.

## 12. Full Python and frontend regression

- Python: 204 passed in 55.22s. The previous baseline was 184. The additional 20 are T01–T20.
- Existing security tests T01–T18 in `tests/test_neon_write_gates.py` passed in the same run.
- Frontend: 29 passed.
- `tsc -b` and the production build passed. Bundle names are unchanged: `index-VZ4YOCg0.js`, `index-BvubhxAm.css`, `ProductionChart-Czm7FBFm.js`, `EvaluationPage-BTWqH6K8.js`, `BarChart-BqrT--3E.js`.
- Local defaults remain `DATA_BACKEND=sqlite` and `VECTOR_BACKEND=qdrant`.

## 13. Source integrity

- SQLite checksum matches the approved value.
- Schema hashes for `001_schema.sql` and `002_pgvector.sql` match the approved values.
- Vector fingerprint `75aecb4737a45afa01a135af63eff05ff73953a9b4065f2d481ab1716f6f79ef` matches, count 105.
- The live source dry-run inside `test_live_source_dry_run_matches_the_approved_fingerprint` passed: `writes` 0, destination `NOT CONNECTED`, fingerprint match, 105 processes, 105 vectors, orphan total 0, fractional quantities exact. The approval flag and destination URL were removed for that test.
- Canonical SQLite, Qdrant, ONNX weights, ranking, and eligibility were not modified.

## 14. Neon read-only confirmation

The read-only probe completed with `writes` 0 and `statements` select-only.

- Database `s1g14_staging`, user and owner `neondb_owner`
- Server `18.7 (a21afb5)`
- Session `transaction_read_only` on
- Client `ssl_in_use` true, `sslmode` require, `channel_binding` require
- Direct endpoint in AWS Singapore
- Server endpoint id matches the host label
- Project `ancient-frog-45954579`, branch `br-flat-bird-b34at9i8`, endpoint `ep-orange-voice-b3m1fhia`
- Public tables: none
- Installed extensions: `plpgsql` 1.0 only
- Available `vector` default version 0.8.7, installed version null

No cloud write was performed.

## 15. Modified files

- `search_service/scripts/neon_staging_migrate.py`
- `search_service/tests/test_neon_atomic.py`
- `search_service/DEPLOY_01C2C_FIX01_REPORT.md`

## 16. Remaining risks

- Rollback of schema, extension, and rows was not observed on PostgreSQL 18.7. A mock cannot show the catalog after `ROLLBACK`.
- `CREATE EXTENSION` inside this transaction was not executed on Neon or on PostgreSQL 18.
- Constraint counts are taken from the approved SQL and the earlier PostgreSQL 16 load. They were not recounted on PostgreSQL 18.
- If a commit acknowledgement is lost, the staging database might contain the migration. The runner will not retry and will not clean it up. The owner has to inspect it.
- A post-commit check failure also leaves the committed data in place.

## 17. Readiness for a new staging migration

The runner now has one write transaction and one commit, and the existing security gates remain. A real PostgreSQL 18 transactional run was not available, so this task does not treat the runner as verified for a cloud write.

B. ATOMIC RUNNER IMPLEMENTED — INTEGRATION NOT VERIFIED

STATUS: DEPLOY-01C.2C-FIX01 COMPLETE — NO NEON CLOUD WRITES PERFORMED
