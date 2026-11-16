# DEPLOY-01C.2C-R1 — First Neon staging atomic migration

## 1. Execution date and environment

16 November 2026, workspace `D:\Final Project\final\search_service`.

The migration client was the existing Linux image `s1g14-search-onnx:local`, because the Windows host cannot load the PostgreSQL client library. The container was removed when the command finished. SQLite and the service tree were mounted read-only. Qdrant was reached at the local collection `crop_process_bge_m3`. The staging URL was read from the private `.env` inside that container and was not printed.

## 2. Exact scope of owner authorization

One staging migration attempt was approved: apply the two approved schema files, install pgvector, import the relational rows and 105 vectors, validate, and commit once.

Not approved and not done: a second attempt, a retry, cleanup, a production connection, a backend or frontend deployment, a new application role, or a change to ranking or source files.

## 3. Project, branch, and endpoint verification

PASS. A read-only probe before the write, the migration session, and a later independent read-only session all reported:

- Project `ancient-frog-45954579`
- Branch `br-flat-bird-b34at9i8`
- Endpoint `ep-orange-voice-b3m1fhia`
- Direct AWS Singapore host, pooling off
- `sslmode=require`
- `channel_binding=require`
- Client TLS in use

## 4. Database identity

PASS. `current_database()` is `s1g14_staging`. `current_user` is `neondb_owner`. The database owner is `neondb_owner`.

## 5. PostgreSQL and pgvector versions

PASS. PostgreSQL `18.7 (a21afb5)`. Before the write, pgvector `0.8.7` was available and not installed. After the commit, the independent session reads installed version `0.8.7`.

## 6. Source SQLite checksum

PASS. `9a80da4111beb44a00c5128c3ffdc10f1e6810825f10a838492981d8e3727808` before and after the migration.

## 7. Source vector fingerprint

PASS. `75aecb4737a45afa01a135af63eff05ff73953a9b4065f2d481ab1716f6f79ef`, 105 points, before and after the migration.

## 8. Approved schema hashes

PASS. Unchanged.

- `001_schema.sql`: `e73c2f25342c3210e3ff793427dd763d234ba1d36f8d4e9d3054dece4f2fd17e`
- `002_pgvector.sql`: `47afa1781c649e8e1e94026eb25e5401a0a759c2d55abc417bcfb26ed246861f`

`003_roles.draft.sql` was not executed.

## 9. Pre-write gate results

PASS. The runner file still has one write connection, autocommit disabled, both schema files inside one transaction, validation before the only `connection.commit()`, rollback on a pre-commit exception, and no retry after a lost commit acknowledgement. Cloud identity, TLS, direct-endpoint, empty-destination, `--write`, and approval gates are still present. Secrets are redacted. That file was not edited for this run.

| Check | Result |
| --- | --- |
| B01 SQLite exists | PASS |
| B02 SQLite checksum | PASS |
| B03 Qdrant reachable | PASS |
| B04 105 points | PASS |
| B05 1024 finite dimensions | PASS |
| B06 distinct process ids | PASS |
| B07 distinct point ids | PASS |
| B08 no source orphans | PASS |
| B09 fingerprint | PASS |
| B10 schema hashes | PASS |
| B11 model revision `xenova-4de13258303883538bd53b696b452bf8099f0858-model_quantized.onnx` | PASS |
| B12 relational inventory and zero count mismatches | PASS |
| B13 fractional quantities exact | PASS |
| B14 source not mutated | PASS |
| B15 source-only dry-run | PASS, destination `NOT CONNECTED`, writes 0 |
| Staging empty before write | PASS, no public tables, vector not installed |
| `.env` Git-ignored | PASS, `.gitignore` lists `.env` |
| Production database name | PASS, the requested database is `s1g14_staging` |

The dry-run counts were crop 4, region 6, data_source 5, source_file 8, flow 4, province_region_map 77, process 105, exchange 105, crop_indicator 324, regional_aggregate 60, regional_contribution 2875. Country null regions: 45.

## 10. Whether the write command was actually invoked

PASS. It was invoked once:

`python -m scripts.neon_staging_migrate --write --database s1g14_staging`

No `--force`, `--reset`, `--drop`, `--truncate`, or `--skip-validation` was added. The approval flag and the three expected Neon ids were process environment values for that container only. They were not written to `.env`. `.env` remains 175 bytes.

## 11. Number of actual migration attempts

1. The command exited 0. It was not repeated.

## 12. Number of actual commits

1. The runner returned `"commits": 1` and `"writes": 1` after its post-commit read-only check. The implementation contains one `connection.commit()`, placed after schema, copy, and validation. Neon server logs were not available, so this count is the client transaction count confirmed by the committed data being visible to a new session.

## 13. Transaction outcome

PASS. The pre-write snapshot inside the same session showed an empty `s1g14_staging`, matching project, branch, and endpoint, role `neondb_owner`, and PostgreSQL 18.7. The transaction then committed. A separate read-only session sees the loaded data.

## 14. Schema creation results

PASS. The independent session sees these public tables and no others: `crop`, `region`, `data_source`, `source_file`, `flow`, `province_region_map`, `process`, `exchange`, `crop_indicator`, `regional_aggregate`, `regional_contribution`, `process_embeddings`.

## 15. pgvector installation results

PASS. `pg_extension.extversion` for `vector` is `0.8.7`.

## 16. Per-table relational row counts

PASS, from the independent read-only session.

| Table | Rows |
| --- | ---: |
| crop | 4 |
| region | 6 |
| data_source | 5 |
| source_file | 8 |
| flow | 4 |
| province_region_map | 77 |
| process | 105 |
| exchange | 105 |
| crop_indicator | 324 |
| regional_aggregate | 60 |
| regional_contribution | 2875 |

## 17. Total relational row count

PASS. 3,573.

## 18. Embedding count and dimensions

PASS. 105 `process_embeddings` rows. Vector comparison found 105 stored vectors, 0 missing, and maximum component absolute difference `0.0` against Qdrant, so every stored vector has the source length of 1024.

## 19. Vector integrity results

PASS. Association mismatches: 0. Processes without an embedding: 0. Maximum absolute component difference: `0.0`.

## 20. Numeric integrity results

PASS. Every relational table matched SQLite row for row. Maximum numeric absolute difference: `0.0`. The approved fractional output quantities were inside that exact match.

## 21. Foreign-key and orphan checks

PASS. Public constraints: 12 primary keys, 16 foreign keys, 6 unique constraints, 12 checks. No orphan embedding and no process without an embedding. Source orphan total before the copy was 0.

## 22. Independent post-commit verification

PASS. A new container opened a new session with `default_transaction_read_only=on`, `transaction_read_only=on`, and client TLS in use. It did not use the write approval flag. It reported `writes: 0`. That session confirmed identity, version, extension, tables, counts, constraints, numeric equality, and vector equality.

The migration runner had already run its own post-commit check on the original connection. The result above is the separate session.

## 23. Semantic evaluation results

PASS for the semantic top-5 comparison. All 61 saved query texts were embedded with the local ONNX model and searched in Neon pgvector and in Qdrant. Rank agreement: 61 of 61. Rank mismatches: none. Maximum similarity gap: `2.89e-7`, inside the established `1e-5` limit. The local FIX02 gap was `1.97e-7`; both are inside the same limit.

## 24. Dictionary and Hybrid validation status

PENDING. Neither mode was executed in FIX02 or in this migration. They remain for a later validation phase.

## 25. Any errors or SQLSTATE

The migration command returned no error and no SQLSTATE.

One later read-only confirmation attempt failed in the client before its data queries, with `ProgrammingError` and no SQLSTATE, because the session tried to change read-only mode after a transaction had started. That attempt reported `writes: 0` and was not a migration command. The confirmation was run again with the read-only mode set before the transaction. That second read-only session is the one recorded above.

## 26. Rollback or uncertain commit handling

Not used. The commit was acknowledged, and the independent session can read the committed rows. No rollback, cleanup, or retry was performed.

## 27. Source integrity after execution

PASS.

- SQLite checksum unchanged
- Qdrant count 105 and fingerprint unchanged
- Both approved schema hashes unchanged
- ONNX weight hash unchanged
- Course dictionary hash unchanged
- Local defaults remain SQLite and Qdrant
- `s1g14-pgvector-test` is still stopped
- `s1g14_pgvector_test_data` is still present
- `s1g14-pg18-atomic` is still stopped
- `s1g14_pg18_atomic_data` is still present

## 28. Production isolation confirmation

PASS for the connection that was opened. The only database session was `s1g14_staging` on endpoint `ep-orange-voice-b3m1fhia`, branch `br-flat-bird-b34at9i8`. No production branch or production database connection was opened. Production contents were not inspected.

## 29. Files created or modified

Created: `search_service/DEPLOY_01C2C_R1_REPORT.md`.

No application, schema, test, or environment file was modified. The temporary read-only confirmation script lived outside the repository and has been removed. The host process does not have `S1G14_STAGING_WRITE_APPROVED` set.

## 30. Remaining risks and blockers

- Dictionary and hybrid results are still pending.
- The application has not been pointed at Neon. Local SQLite and Qdrant remain the default.
- The commit count is the client count of one `commit()` plus a new session that can read the data. Neon did not provide a statement log for this session.
- No application role was created. The migration role remains `neondb_owner`.

There is no data blocker in the staging copy.

## 31. Readiness for DEPLOY-01C.2D

The staging database now holds the approved schema, pgvector 0.8.7, 3,573 relational rows, and 105 embeddings. An independent read-only session confirmed that copy. Semantic top-5 agreement is 61 of 61. Dictionary and hybrid checks are still pending and belong in the next validation phase.

A. MIGRATION SUCCESSFUL — READY FOR INDEPENDENT NEON VALIDATION

STATUS: DEPLOY-01C.2C-R1 COMPLETE — AWAITING OWNER REVIEW
