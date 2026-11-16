# DEPLOY-01C.0 — Local PostgreSQL and pgvector staging validation

Preparation and static validation only. No PostgreSQL container was started. `psycopg` was not installed. No Neon project, credential, upload, or deployment was created.

Recommendation: **C. NOT READY — INTEGRATION FIXES REQUIRED**

The draft schema and adapters passed the read-only precheck. The required next step is the authorized local database run. That run is still **NOT VERIFIED**, so Neon staging must not start.

## 1. Implementation summary

The cloud pair remains `DATA_BACKEND=postgres` and `VECTOR_BACKEND=pgvector`. The default pair is still `sqlite` and `qdrant`. A postgres setting without `DATABASE_URL` raises `ValueError` and does not open SQLite.

No authorized local PostgreSQL instance exists. The running containers are `s1g14-qdrant` on `127.0.0.1:6333` and `cn230-db-1` on port 3306. Both were left running. Ports 5432, 5433, and 54329 are free.

The proposed isolated configuration is `migrations/postgres/PROPOSED_local_pgvector_test.compose.yml`. It was not started.

| Requirement | Result |
| --- | --- |
| Driver and SQL audit | PASS as a static review |
| Isolated PostgreSQL availability | NOT VERIFIED — not present, and not launched |
| Schema applied on PostgreSQL | NOT VERIFIED |
| Relational copy | NOT VERIFIED — source precheck PASS |
| Vector copy into pgvector | NOT VERIFIED — Qdrant read-only scroll PASS |
| pgvector search parity | NOT VERIFIED |
| FastAPI on the cloud pair | NOT VERIFIED |
| Dictionary parity on PostgreSQL | NOT VERIFIED — parser and SQL shape PASS |
| Saved 61-query rerun on PostgreSQL | NOT VERIFIED |
| Local regression | PASS |
| Integrity | PASS |
| Neon project | Not created |

## 2. Files modified

| File | Change |
| --- | --- |
| `migrations/postgres/PROPOSED_local_pgvector_test.compose.yml` | New proposal. Not started. |
| `scripts/staging_readonly_audit.py` | Read-only SQLite and paginated Qdrant precheck. It does not write a database. |
| `DEPLOY_01C0_REPORT.md` | This report. |

`001_schema.sql`, `002_pgvector.sql`, application code, `docker-compose.yml`, the canonical SQLite file, the course script, Qdrant, the ONNX file, and `evaluation.json` were not modified. The local default provider was not changed.

## 3. PostgreSQL version and pgvector version

**NOT VERIFIED.** No server was started, so there is no `SELECT version()` result.

Proposed image, to be used only after authorization: `pgvector/pgvector:0.8.7-pg16`. That tag is PostgreSQL 16 with pgvector 0.8.7. Exact `<=>` cosine search does not need an HNSW or IVFFlat index. 1024 dimensions are inside the type limit. The pinned image digest must be recorded at the authorized pull. This phase did not pull the image.

Proposed driver, also not installed: `psycopg[binary]==3.3.9` inside `search_service\.venv` only. PyPI publishes a Windows `cp314` wheel and a manylinux `cp312` wheel, matching the host Python 3.14 and the Linux image Python 3.12. The vector store sends the query as a parameter cast with `::vector`, so the separate `pgvector` Python package is not required. Do not install this as a system package, and do not add it to the Linux image until that image rebuild is separately authorized.

## 4. Schema verification — static PASS, server NOT VERIFIED

Apply order when authorized:

1. Empty database.
2. `001_schema.sql` in one transaction (`psql --single-transaction -v ON_ERROR_STOP=1`).
3. `002_pgvector.sql` in a second transaction. It creates `vector` and `process_embeddings`, which references `process`.

The 11 relational tables are `crop`, `region`, `data_source`, `source_file`, `flow`, `province_region_map`, `process`, `exchange`, `crop_indicator`, `regional_aggregate`, and `regional_contribution`. `process_embeddings` is the twelfth table. Primary keys, unique keys, foreign keys, nullability, and the three indexes match the draft. `embedding` is `vector(1024)` with `vector_dimension = 1024`.

Insert order is the foreign-key order: `crop`, `region`, `data_source`, and `flow`; then `source_file` and `province_region_map`; then `process`; then `exchange`, `crop_indicator`, and `regional_aggregate`; then `regional_contribution`; then `process_embeddings`.

A second run of either file fails because the tables are created without `IF NOT EXISTS`. That is the intended failure. Rollback of a failed local load is `docker compose ... down -v` on the proposed file only, or `DROP DATABASE` of `s1g14_migration_test`. Do not drop the Qdrant volume.

The read-only SQLite precheck found zero rows that would violate the draft checks: flow type, spatial rule, direction, positive quantities, `review_status = validated`, positive indicators, aggregate bounds, 0/1 flags, and the natural unique keys. Orphan count is 0. This does not replace executing the SQL on PostgreSQL.

## 5. Relational migration verification — source PASS, copy NOT VERIFIED

The canonical file stayed read-only. `scripts/staging_readonly_audit.py` reported:

| Table | Rows |
| --- | --- |
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

Output exchanges: 105. Country processes with NULL `region_code`: 45. Duplicate process ids: 0. Crop codes: CAS, MAI, RIC, SUG. Region codes: CEN, EAS, NEA, NOR, SOU, WES. Years: 2019–2024. Exchange unit: `t`. Sources: SRC-01, SRC-02, SRC-04, SRC-05, SRC-06. Indicators: `area_harvested`, `area_planted`, `yield_harvested`, `yield_planted`.

Fractional tonnes match the Python values exactly: `32882932.48`, `33851579.48`, and `33551336.65`. The future copy must pass these through psycopg as float8 parameters. It must not format them as rounded decimal text.

The copy itself was not executed.

## 6. Vector migration verification — source PASS, import NOT VERIFIED

Paginated read-only scroll of `crop_process_bge_m3`:

- Collection status green, 105 points, size 1024, distance Cosine.
- 105 scrolled points, 105 distinct process ids, 105 distinct point UUIDs.
- 0 bad dimensions, 0 non-finite values, 0 missing payload fields.
- One revision: `xenova-4de13258303883538bd53b696b452bf8099f0858-model_quantized.onnx`.
- Model `BAAI/bge-m3`, provider `local-bge-m3`, declared dimension 1024.
- Payload keys match the columns on `process_embeddings`.
- Ordered fingerprint SHA-256 `75aecb4737a45afa01a135af63eff05ff73953a9b4065f2d481ab1716f6f79ef`. This is the process id plus little-endian float64 of the scrolled JSON numbers. It is a source fingerprint, not a pgvector float32 digest.

No point was upserted. No embedding was generated. No vector was normalized again. Nothing was sent to Neon.

pgvector stores `vector` as float32. The import must reject duplicate process ids and non-finite values inside the load transaction. Proposed comparison after an authorized import: each component within `1e-6` absolute, and each cosine similarity within `1e-5` absolute. `similarity = 1 - (embedding <=> query_vector)`. Every process-id rank difference is reported even when the scores are inside that tolerance. These tolerances were not measured.

## 7. Cloud provider API results — NOT VERIFIED

FastAPI was not started with the cloud pair. There is no database URL to give it.

Code review of the routes:

- `GET /catalog` uses `PostgresDataProvider` when `DATA_BACKEND=postgres` and does not open SQLite on a PostgreSQL error.
- `GET /evaluation-report` reads `evaluation/reports/evaluation.json` and does not open SQLite. The saved file was not recomputed. It still contains 61 dictionary, 61 semantic, and 61 hybrid query rows.
- Search hydration and hybrid eligibility use `PostgresDataProvider` when the relational provider is attached.
- Hybrid order is eligibility SQL, then `search_points` restricted with `process_id = ANY(%s)`, then quantity hydration. An empty eligible set returns before embedding.
- `PgvectorStore` raises the existing store error type. A pgvector failure is therefore reported as `qdrant_unavailable` with the message `Qdrant is unavailable`. That is the current response contract. It does not open the Qdrant collection.
- `/ready` still uses the field names `sqlite` and `qdrant` while the counts come from the selected backends. Those names were left unchanged so the response contract stays as it is.

No Windows path is required for the PostgreSQL catalog or eligibility SQL. Dictionary loading still needs `DICTIONARY_SCRIPT` or the Windows default of the course file. Connection errors tested in `test_t03_connection_errors_do_not_reveal_the_url` do not include the URL.

## 8. Dictionary parity — static PASS, server NOT VERIFIED

`PostgresDictionaryAdapter` calls `parse_query` from the unchanged course file and runs the same SELECT, WHERE, `ORDER BY p.year_ce, p.area, p.source_id`, and LIMIT. Placeholders are `%s`. The course file still uses `?` and was not edited. Its SHA-256 is unchanged. Live PostgreSQL dictionary results were not compared.

## 9. Search parity — NOT VERIFIED on PostgreSQL

The seven demonstration queries and the 61-query set were not executed against pgvector. Ranking and eligibility rules were not changed. The previous Windows and Linux SQLite plus Qdrant parity remains the baseline. This phase did not overwrite `evaluation.json`.

## 10. Python tests — PASS

**154 passed** in 50.32 s. No PostgreSQL integration test was added, because no server was available.

## 11. Frontend tests — PASS

**29 passed.** `tsc -b` and the Vite production build passed. Bundle names were unchanged.

## 12. SQLite and Qdrant integrity — PASS

| Item | Value |
| --- | --- |
| Canonical SQLite SHA-256 | `9a80da4111beb44a00c5128c3ffdc10f1e6810825f10a838492981d8e3727808` |
| Course `semantic_search.py` | `8db66ee8ee675e43822e827375a2bba299eeed252063cc2a88f4a130e8e7cc60` |
| `build_serving_layer.py` | `b770300f8835ab5c58f40d32132d4dd65530bfd2ac4692082fd3fd7caef0ca78` |
| `import.cypher` | `5286e190259a123aaed76fda427851a62bf126e69c71ad0a4e013070e2b3ab1d` |
| `docker-compose.yml` | `109b813ad1d1e246c2fc7eef6590d1bcccfa94155299ad67fbbc903499e92b49` |
| `evaluation.json` | `bf72a8ba7ae98365d4b1658d5bdbbd05b7d48f3c4d6db4f6771524b19720800e` |
| ONNX SHA-256 | `0826f8c1ab9edf1801db86c61919d4d108e8bfc0b809ec823ad366882ff0b77d` |
| Qdrant | green, 105 points, 1024, Cosine |

No re-index. No OpenAI call. No cloud upload. Local mode remains the default.

## 13. Known limitations

- Live PostgreSQL, pgvector, the cloud API, and score parity are **NOT VERIFIED**.
- `SET default_transaction_read_only = on` runs inside the first transaction. It does not by itself make that transaction read-only, and closing without commit rolls it back. The staging application role must be `SELECT`-only. That role setting is the control that matters.
- `/ready` and vector-store errors still use the names `sqlite` and `qdrant` in the public contract.
- `app/evaluate_search.py` still defaults to the Windows SQLite path. The API report route does not use that default.
- The SQL files are not idempotent. A partial load is discarded by dropping the disposable database.
- pgvector float32 storage can differ from a Qdrant score. The proposed gates are `1e-6` per component and `1e-5` per similarity, with every rank change reported.

## 14. Neon staging prerequisites

Do not create the project until the local proof passes.

- Region: the Neon region closest to the future API host. Not selected here.
- Extension: `CREATE EXTENSION IF NOT EXISTS vector` once, in the staging database. pgvector is available on the Neon Free plan.
- Schema sequence: empty database, `001_schema.sql`, then `002_pgvector.sql`, each in one transaction.
- Migration role: `CREATE` and `INSERT` only for the load window, on the direct connection, not the pooler. Revoke it after validation.
- Application role: `CONNECT` and `SELECT` on the 12 tables. No `CREATE`, `INSERT`, `UPDATE`, `DELETE`, or `DROP`. `ALTER ROLE ... SET default_transaction_read_only = on`. Statement timeout of 5 seconds. `sslmode=require`.
- Secrets stay in the host secret store. They are not `VITE_` variables and they are not written into this repository.
- Relational copy and vector copy use the procedure above. Validation repeats the counts, the 45 null regions, the three exact quantities, 105 vectors, 1024 dimensions, the revision, and the seven queries plus the 61-query set.
- API cutover is a configuration change to the cloud pair. Unset it to return to SQLite and Qdrant. Rollback of Neon is dropping that branch or project. SQLite and Qdrant stay in place until parity is accepted.
- Free plan, published 3–4 November 2026: $0, 100 projects, 100 CU-hours per project per month, 1 GB storage per project, 5 GB public transfer, scale to zero after 5 idle minutes, up to 2 CU. This dataset is far below 1 GB. Launch plan rates, if later needed, are $0.106 per CU-hour and $0.35 per GB-month of database storage. No Neon resource was created, so no charge was incurred.

## 15. Owner decisions required

1. Authorize or reject the proposed Compose file and a venv-only install of `psycopg[binary]==3.3.9`.
2. Accept or replace the `1e-6` / `1e-5` comparison gates before parity is judged.
3. Keep the current `/ready` field names, or schedule a contract change later.
4. Choose a Neon region only after the local proof passes.
5. Do not approve a Neon write in this phase.

## 16. Recommended next phase

**C. NOT READY — INTEGRATION FIXES REQUIRED**

The blocking item is the unexecuted local PostgreSQL proof, not a failed static check. Authorize the isolated container and the venv driver, then rerun schema apply, the read-only copy, vector comparison, and the seven queries plus the 61-query set. Neon staging stays closed until that local evidence exists.

STATUS: DEPLOY-01C.0 COMPLETE — AWAITING OWNER APPROVAL FOR NEON STAGING
