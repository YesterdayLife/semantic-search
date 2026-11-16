# DEPLOY-01C.2C — First authorized Neon staging migration

Review time: 15 November 2026, 23:35 ICT. Linux client image `s1g14-search-onnx:local`. Windows psycopg remains blocked by Application Control. No write command was issued.

## 1. Execution timestamp and environment

The pre-write review ran in this session. The migration command was not started. `S1G14_STAGING_WRITE_APPROVED` is unset in `.env` and in the process environment. The three `EXPECTED_NEON_*` variables are unset. `.env` contains only `STAGING_DATABASE_URL` and is listed in `.gitignore`.

## 2. Owner approval scope

The owner granted one staging migration to `s1g14_staging` on branch `staging`. The approval does not include a production branch, a retry, a branch reset, `DROP`, `TRUNCATE`, or application deployment.

## 3. Final verified Neon identity

Read-only session, zero writes.

| Item | Result |
| --- | --- |
| Project id | `ancient-frog-45954579` |
| Branch id | `br-flat-bird-b34at9i8` |
| Endpoint id | `ep-orange-voice-b3m1fhia` |
| Hostname matches that endpoint | Yes |
| Region | `ap-southeast-1` |
| Database | `s1g14_staging` |
| Role | `neondb_owner` |
| Direct endpoint | Yes |
| Pooled endpoint | No |
| Client TLS | On |
| `sslmode` | `require` |
| `channel_binding` | `require` |

The production branch was not opened.

## 4. PostgreSQL and pgvector versions

PostgreSQL `18.7 (a21afb5)`. `vector` 0.8.7 is available and is not installed. The only installed extension is `plpgsql` 1.0.

## 5. Source integrity checks

PASS before any write.

| Check | Result |
| --- | --- |
| SQLite SHA-256 | `9a80da4111beb44a00c5128c3ffdc10f1e6810825f10a838492981d8e3727808` |
| Qdrant | green, 105 points, 1024 dimensions, cosine |
| Vector fingerprint | `75aecb4737a45afa01a135af63eff05ff73953a9b4065f2d481ab1716f6f79ef` |
| Dictionary script | `8db66ee8ee675e43822e827375a2bba299eeed252063cc2a88f4a130e8e7cc60` |
| ONNX weights | `0826f8c1ab9edf1801db86c61919d4d108e8bfc0b809ec823ad366882ff0b77d` |

## 6. Schema hash verification

PASS. The files were not edited.

- `001_schema.sql` `e73c2f25342c3210e3ff793427dd763d234ba1d36f8d4e9d3054dece4f2fd17e`
- `002_pgvector.sql` `47afa1781c649e8e1e94026eb25e5401a0a759c2d55abc417bcfb26ed246861f`

Static review found standard `double precision`, keys, foreign keys, checks, and `vector(1024)`. No PostgreSQL 18 syntax defect was identified. The schema was not executed, so runtime compatibility remains unproven.

## 7. Pre-write security gate results

Identity, TLS, direct endpoint, empty `public` schema, role, PostgreSQL 18, pgvector availability, source checksum, fingerprint, and schema hashes passed in the read-only probe.

The transaction gate failed. The runner is not one atomic migration.

`load_destination` calls three helpers, and each helper commits:

1. `_apply_sql` commits `001_schema.sql`.
2. `_apply_sql` commits `002_pgvector.sql`, including `CREATE EXTENSION` and `process_embeddings`.
3. `_copy_tables` commits the relational inserts, and only then checks row counts and the three fractional quantities.
4. `_copy_vectors` commits the embeddings.
5. `load_destination` commits once more.

A failure after the first commit leaves public tables in place. The runner then refuses another write because the destination is no longer empty. This approval forbids `DROP`, `TRUNCATE`, a branch reset, and an automatic retry. Recovery of that partial state is outside the granted approval.

The count and quantity checks in `_copy_tables` run after that commit. A failed check would leave the inserted rows durable and the embedding table empty.

## 8. Actual write command

Not run. The approved command, with no credentials, would have been:

`python -m scripts.neon_staging_migrate --write --database s1g14_staging`

## 9. Number of migration attempts

0.

## 10. Schema creation results

Not started. `s1g14_staging` still has no public tables.

## 11. Extension installation result

Not started. `vector` is not installed.

## 12. Per-table row counts

No application tables exist. No rows were imported.

## 13. Embedding count and dimensions

`process_embeddings` does not exist. Source Qdrant still has 105 vectors of 1024 dimensions.

## 14. Numeric integrity validation

Not run against Neon. The source quantities were not written.

## 15. Foreign-key validation

Not run against Neon. No staging foreign keys were created.

## 16. Source-to-destination comparison

Not run. There is no destination data.

## 17. Transaction and commit status

No migration transaction was opened. The read-only probe used `transaction_read_only=on` and closed without a write.

## 18. Failure or rollback details

No SQLSTATE. The stop happened before invocation. Staging remains empty. Nothing needs to be rolled back.

## 19. Post-migration source integrity

The source was not migrated. The checksums in section 5 were rechecked after the read-only probe and are unchanged. Local defaults remain SQLite and Qdrant.

## 20. Remaining risks

Running the current runner can leave a non-empty staging database that this approval cannot repair. PostgreSQL 18 execution of the schema is still unproven. `neondb_owner` remains the migration role and must not be given to the application.

## 21. Readiness for DEPLOY-01C.2D

Not ready. The staging copy does not exist.

A later migration needs one new owner decision before any write:

Authorize a narrow runner change that applies both schema files, `CREATE EXTENSION`, the relational copy, and the vector copy in one transaction, and that runs the count and quantity checks before the only commit. Then authorize exactly one execution of that revised runner.

The alternative is a separate approval to reset the staging branch if a partial commit occurs. That alternative is a destructive recovery and was not granted here.

## 22. Files modified

`DEPLOY_01C2C_REPORT.md` only. The runner, schema files, `.env`, SQLite, Qdrant, dictionary, and ONNX weights were not changed. The write flag was not saved.

## 23. Production

No production branch was connected or modified.

## Decision

D. PRE-WRITE GATE FAILED — NO CLOUD WRITES PERFORMED

STATUS: DEPLOY-01C.2C COMPLETE — AWAITING OWNER REVIEW
