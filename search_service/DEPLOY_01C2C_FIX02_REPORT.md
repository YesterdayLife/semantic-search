# DEPLOY-01C.2C-FIX02 — PostgreSQL 18 atomic migration verification

Scope: isolated local integration testing. The Neon staging migration was not run. The existing PostgreSQL 16 container and volume were not used.

## 1. PostgreSQL 18 Docker environment

The tag `pgvector/pgvector:0.8.7-pg18` was confirmed with `docker manifest inspect` and then pulled. Its image digest is `sha256:38681dc6eaf55308e2a4c6de392d131652dcfac70e1263e35cd9b5ea3fe39782`. The image environment reports `PG_MAJOR=18` and `PG_VERSION=18.7-1.pgdg12+2`.

A new container was started with its own volume and its own Docker network. The published port is bound to loopback only: `127.0.0.1:54330 -> 5432`. The test client used the Docker network name, not the Neon URL and not `STAGING_DATABASE_URL`.

The harness refuses to start when `STAGING_DATABASE_URL`, `DATABASE_URL`, or `S1G14_STAGING_WRITE_APPROVED=1` is present, and it accepts only the local container host. It calls `load_destination()` from the staging runner. It does not call `connect_staging()`, `run()`, or `--write`. The cloud identity, TLS, endpoint, approval, and schema gates in `scripts/neon_staging_migrate.py` were not edited.

## 2. Exact PostgreSQL version

`18.7 (Debian 18.7-1.pgdg12+2)`, queried with `SHOW server_version` inside the disposable database.

## 3. Exact pgvector version

`0.8.7`. Before the migration, `pg_available_extensions` reported default version `0.8.7`. After the successful commit, `pg_extension.extversion` for `vector` was `0.8.7`.

## 4. Container and volume names

- Container: `s1g14-pg18-atomic`
- Volume: `s1g14_pg18_atomic_data`
- Network: `s1g14-pg18-net`
- Image: `pgvector/pgvector:0.8.7-pg18`
- Local role and maintenance database: `s1g14_pg18` / `postgres`
- Success database: `s1g14_pg18_success`
- Rollback databases: `s1g14_pg18_b01` through `s1g14_pg18_b10`

Untouched: `s1g14-pgvector-test`, `s1g14_pgvector_test_data`, `s1g14-qdrant`, and `cn230-db-1`.

## 5. Migration implementation tested

The local harness opened one non-autocommit session and called the production function `load_destination()`. That function applies `001_schema.sql`, applies `002_pgvector.sql`, copies the 11 relational tables, copies the 105 embeddings, validates, and then calls `connection.commit()` once. A pre-commit exception rolls that same transaction back.

Rollback points were injected by raising before the next real statement was sent. Every statement before the injection had already been executed by PostgreSQL 18.

## 6. Successful real migration results

The fresh database `s1g14_pg18_success` was empty before the run. After one commit, a second read-only connection observed:

- Public tables: the 11 relational tables plus `process_embeddings`
- Installed `vector` extension: `0.8.7`
- Relational counts: crop 4, region 6, data_source 5, source_file 8, flow 4, province_region_map 77, process 105, exchange 105, crop_indicator 324, regional_aggregate 60, regional_contribution 2875
- Relational total: 3,573
- Embeddings: 105, all with 1024 dimensions
- Orphan embeddings: 0
- Duplicate process embeddings: 0
- Constraints: 12 primary keys, 16 foreign keys, 6 unique constraints, 12 check constraints
- All 11 relational tables matched the SQLite rows, with maximum numeric absolute difference `0.0`
- All 105 vectors matched the Qdrant values, with maximum component absolute difference `0.0`
- Point id and process id associations: 0 mismatches
- The three fractional output quantities matched exactly
- Country rows with a null region: 45, matching the source audit
- Autocommit statements during the migration: 0

## 7. Actual commit count

The migration session called `connection.commit()` once. The PostgreSQL log for that run contains one `COMMIT` statement, at `2026-11-15 17:02:43 UTC`, after the schema, extension, relational rows, embeddings, and pre-commit checks.

`pg_stat_database.xact_commit` increased by 3 on the success database. A separate local probe showed that this counter also moves when a backend connects and disconnects, and that it does not publish the user transaction until the session ends. It is not the count of migration commits. The statement log and the single `commit()` call are the migration count: 1.

No intermediate `COMMIT` was logged. The post-commit check used `SET TRANSACTION READ ONLY` and ended with `ROLLBACK`.

## 8. All 10 real rollback tests

Each test used a newly created database, raised before commit, propagated the exception, and was attempted once.

| Test | Injection point | Result |
| --- | --- | --- |
| B01 | After `001_schema.sql`, before `CREATE EXTENSION` | PASS |
| B02 | After `CREATE EXTENSION vector`, before `process_embeddings` | PASS |
| B03 | After `process_embeddings` was created, before row import | PASS |
| B04 | During relational import, after the first table | PASS |
| B05 | After all relational rows, before embeddings | PASS |
| B06 | During embedding import, after the first embedding | PASS |
| B07 | After all 105 embeddings, before validation | PASS |
| B08 | At the pre-commit row-count query | PASS |
| B09 | At the pre-commit fractional-quantity query | PASS |
| B10 | At the pre-commit vector-dimension query | PASS |

Every rollback test recorded `python_commits = 0` and `attempts = 1`.

## 9. Post-rollback catalog inspection

A new read-only connection inspected each rollback database after the failed session had closed.

- Public relations: none in B01–B10
- `vector` extension: not installed in B01–B10
- Imported rows: none, because no migration tables remained
- No second attempt was started

`xact_commit` also increased by 1 on B04–B10. Those sessions did not call `commit()`, and their catalogs were empty, so the counter movement is the same session-lifecycle accounting seen in the probe, not a committed migration.

## 10. Relational data counts

Confirmed on the read-only connection after the successful commit: 4, 6, 5, 8, 4, 77, 105, 105, 324, 60, and 2,875. Total 3,573. Row-by-row comparison with SQLite found no mismatched table.

## 11. Vector integrity

105 stored embeddings, 1024 dimensions, maximum absolute component difference `0.0` against Qdrant. No missing process, no orphan embedding, and no duplicate process id. Each of the 105 vectors was its own nearest neighbor under pgvector cosine distance.

## 12. Numeric integrity

Maximum absolute difference across numeric columns was `0.0`. The output quantities `32882932.48`, `33851579.48`, and `33551336.65` matched exactly. Null region handling matched the source.

## 13. Search-equivalence results

Representative stored-vector searches matched Qdrant on all 6 sampled process ids, including the three fractional rice processes. The largest similarity gap on those samples was `3.85e-7`.

All 61 saved query texts were embedded with the local ONNX BGE-M3 model and ranked in both pgvector and Qdrant. Rank agreement was 61 of 61. The largest similarity gap was `1.97e-7`, inside the existing `1e-5` limit. This was the semantic top-5 comparison. Dictionary and hybrid modes were not re-executed, so this is not a three-mode parity claim.

Post-commit validation failure and an uncertain commit acknowledgement were not simulated by killing a real server. Those two outcomes remain covered by the existing mock tests T15 and T16, which report `COMMITTED — POST-COMMIT VALIDATION FAILED` and `COMMIT OUTCOME UNKNOWN — OWNER REVIEW REQUIRED`.

## 14. Security gate regression

The cloud runner file was not changed. The full Python run included the existing migration security tests and atomic tests T01–T20, plus four new guards that reject a Neon host, the staging URL, and the cloud approval flag. All of those tests passed.

## 15. Python test results

208 passed in 47.67 seconds. The previous baseline was 204. The four added tests are the local-harness guards. The live source dry-run test passed inside this run: no destination connection and zero writes.

## 16. Frontend test results

29 frontend tests passed. `tsc -b` and the production build passed. Bundle names are unchanged: `index-VZ4YOCg0.js`, `index-BvubhxAm.css`, `ProductionChart-Czm7FBFm.js`, `EvaluationPage-BTWqH6K8.js`, and `BarChart-BqrT--3E.js`.

## 17. Source integrity

After the tests:

- SQLite checksum matches `9a80da4111beb44a00c5128c3ffdc10f1e6810825f10a838492981d8e3727808`
- Qdrant fingerprint matches `75aecb4737a45afa01a135af63eff05ff73953a9b4065f2d481ab1716f6f79ef`, count 105
- `001_schema.sql` and `002_pgvector.sql` match the approved hashes
- ONNX weight hash matches the approved value
- Course dictionary hash matches the approved value
- Local defaults remain SQLite and Qdrant

The read-only Neon probe reported `writes: 0`, no public tables, and `vector` not installed. PostgreSQL on Neon remains `18.7 (a21afb5)`. Production was not contacted.

## 18. Docker cleanup status

`s1g14-pg18-atomic` is stopped and was not removed. Its volume `s1g14_pg18_atomic_data` remains, including `s1g14_pg18_success`, so the loaded database can be inspected. No Docker prune was run. The PostgreSQL 16 container and volume are still present and were not started.

## 19. Files modified

- `search_service/scripts/pg18_atomic_verify.py`
- `search_service/scripts/run_pg18_atomic_verify.py`
- `search_service/tests/test_pg18_local_guard.py`
- `search_service/DEPLOY_01C2C_FIX02_REPORT.md`

No schema file, source database, model, ranking module, or Neon runner gate was edited.

## 20. Remaining risks

- This proof is local PostgreSQL 18.7 with pgvector 0.8.7. It does not include the Neon proxy, Neon roles, or a cloud commit.
- Dictionary and hybrid execution of the saved 61 queries was not repeated.
- The mock tests still cover a lost commit acknowledgement and a failed post-commit check. Those two cases were not forced on the real server.
- `pg_stat_database.xact_commit` includes session connect and disconnect activity, so it must not be read as the number of migration commits.

## 21. Recommendation

The approved schema, pgvector 0.8.7, the full relational copy, and all 105 embeddings committed once on PostgreSQL 18.7. All 10 injected pre-commit failures rolled back to an empty public schema with the vector extension absent. The cloud write gates remain in place.

A. ATOMIC MIGRATION VERIFIED ON POSTGRESQL 18 — READY TO REQUEST NEW NEON WRITE APPROVAL

STATUS: DEPLOY-01C.2C-FIX02 COMPLETE — NO NEON CLOUD WRITES PERFORMED
