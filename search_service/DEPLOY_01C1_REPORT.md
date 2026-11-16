# DEPLOY-01C.1 — Neon staging migration preparation

Preparation only. No Neon project was created, no destination was contacted, and no write mode was run.

## 1. Preparation summary

PASS. The staging runner, role draft, validation plan, and Linux driver pin are in the repository. The local SQLite and Qdrant stack is unchanged and remains the default.

## 2. Files created or modified

Created:

- `scripts/neon_staging_migrate.py`
- `migrations/postgres/003_roles.draft.sql`
- `tests/test_neon_staging_migrate.py`
- `DEPLOY_01C1_REPORT.md`

Modified:

- `requirements-linux.txt` — added `psycopg[binary]==3.3.9`
- `requirements-linux.lock.txt` — added `psycopg==3.3.9` and `psycopg_binary==3.3.9`
- `scripts/pg_local_load.py` — refuses any host other than `127.0.0.1`, `localhost`, or `postgres`, and any database other than `s1g14_migration_test`

The Linux image was not rebuilt and was not pushed. `Dockerfile`, `docker-compose.yml`, the course dictionary script, schema checks, ranking code, and the saved evaluation report were not changed.

## 3. Neon configuration status

NOT VERIFIED. `DATABASE_URL`, `NEON_API_KEY`, `NEON_PROJECT_ID`, `NEON_DATABASE_URL`, `PGHOST`, and `PGPASSWORD` are unset. The `neon` CLI is not installed. `.env.example` has no Neon URL. The frontend uses `VITE_API_BASE` and holds no database credential.

No project identifier, region, compute size, scale-to-zero setting, storage limit, connection limit, or account bill can be read because no Neon resource exists. Published Neon Free-plan figures are planning context only, not a charge against this project: $0, 100 CU-hours per project per month, 1 GB storage per project, scale-to-zero after 5 idle minutes, TLS required, and `pgvector` available with `CREATE EXTENSION`. This dataset is far under 1 GB. No charge was incurred in this phase.

## 4. Migration runner design

PASS. `python -m scripts.neon_staging_migrate` defaults to dry-run. A write requires both `--write` and `S1G14_STAGING_WRITE_APPROVED=1`. The destination URL is read from `STAGING_DATABASE_URL` and is redacted from errors. `psycopg` is imported only inside the connection function.

The runner reads SQLite through the existing read-only connection and reads Qdrant with a paginated scroll. It preserves process IDs, point UUIDs, float components, and model metadata. It does not regenerate embeddings or re-normalize vectors. It refuses system databases, names containing `production`, and names ending in `_prod`. It checks `current_database()` against `--database` and refuses a destination that already has rows. It does not `DROP` a schema or database. Remote hosts must use `sslmode=require`, `verify-ca`, or `verify-full`.

The older local loader still drops `public` and is now limited to the disposable local database.

## 5. Dry-run results

PASS. The CLI ran with no destination URL and no write flag.

- Mode: `dry-run`
- Writes: `0`
- Destination: `NOT CONNECTED`
- Source ready: `true`
- Fingerprint: `75aecb4737a45afa01a135af63eff05ff73953a9b4065f2d481ab1716f6f79ef`
- Vector count: 105 unique process IDs, 105 unique point UUIDs, 1024 dimensions, 0 non-finite values
- Revision: `xenova-4de13258303883538bd53b696b452bf8099f0858-model_quantized.onnx`
- Orphans: 0
- Fractional quantities exact: true
- Country rows with a null region: 45

Row counts: crop 4, region 6, data_source 5, source_file 8, flow 4, province_region_map 77, process 105, exchange 105, crop_indicator 324, regional_aggregate 60, regional_contribution 2875.

Schema identity:

- `001_schema.sql` `e73c2f25342c3210e3ff793427dd763d234ba1d36f8d4e9d3054dece4f2fd17e`
- `002_pgvector.sql` `47afa1781c649e8e1e94026eb25e5401a0a759c2d55abc417bcfb26ed246861f`

## 6. Security role design

PASS as a draft. `003_roles.draft.sql` was not executed.

Migration role `s1g14_staging_migrator`: login only for the load window, `NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT`, owner of the empty staging database, then login revoked or the role dropped.

Application role `s1g14_staging_app`: `SELECT` only, `NOINHERIT`, not a member of the migration role, `default_transaction_read_only=on`, `statement_timeout=5s`. The draft revokes `CREATE` on `public` from `PUBLIC` and from the application role, and revokes `INSERT`, `UPDATE`, `DELETE`, `TRUNCATE`, `REFERENCES`, and `TRIGGER`. The migration role keeps create rights as schema owner. Passwords stay outside the file. The database name `s1g14_staging` is a placeholder and must be replaced with the approved name.

TLS is required for any remote host. Credentials stay in the server environment. The frontend has none. Nothing in this phase was committed.

## 7. Database and vector validation plan

PASS as a plan. After a future approved import, the same runner checks the eleven table counts, foreign-key orphans, the three fractional tonne values, 105 vectors, unique process IDs, unique point UUIDs, 1024 dimensions, the approved revision, finite values, and nonzero norms.

Acceptance thresholds: maximum component difference `1e-6`, maximum cosine-similarity difference `1e-5`. Every ranking difference is reported. Ranking uses exact pgvector cosine distance and `process_id`, with no HNSW.

Search parity covers dictionary, semantic, hybrid, compare, catalog, and the saved evaluation report. The seven demonstration queries and the 61-query file are listed in the runner. The evaluation file is read and not rewritten. Compared fields are process IDs, order, quantities, units, availability, numeric filters, missing-data behavior, and similarity scores.

## 8. Linux dependency readiness

PASS for the pin. NOT VERIFIED inside a rebuilt image. `requirements-linux.txt` and the lock now pin `psycopg[binary]==3.3.9`. The pin does not add torch, CUDA, sentence-transformers, or an OpenAI client. One Uvicorn worker, `CPUExecutionProvider`, the 2 GB plan, the approved ONNX revision, and the offline model mount are unchanged. The current image `s1g14-search-onnx:local` does not yet contain this driver. Rebuild and push remain unauthorized.

## 9. Local regression results

PASS.

- Python: 166 passed in 50.01 s, including the 11 new staging safety tests
- Frontend: 29 passed
- Production build: passed in 869 ms; bundle names unchanged
- Staging dry-run: passed, writes 0
- Configuration: default backends remain SQLite and Qdrant

No Neon transfer, public deployment, or ranking change was made.

## 10. Source integrity results

PASS.

| Source | SHA-256 |
| --- | --- |
| `S1-G14_M3.sqlite` | `9a80da4111beb44a00c5128c3ffdc10f1e6810825f10a838492981d8e3727808` |
| `semantic_search.py` | `8db66ee8ee675e43822e827375a2bba299eeed252063cc2a88f4a130e8e7cc60` |
| `build_serving_layer.py` | `b770300f8835ab5c58f40d32132d4dd65530bfd2ac4692082fd3fd7caef0ca78` |
| `import.cypher` | `5286e190259a123aaed76fda427851a62bf126e69c71ad0a4e013070e2b3ab1d` |
| `docker-compose.yml` | `109b813ad1d1e246c2fc7eef6590d1bcccfa94155299ad67fbbc903499e92b49` |
| `evaluation.json` | `bf72a8ba7ae98365d4b1658d5bdbbd05b7d48f3c4d6db4f6771524b19720800e` |
| `model_quantized.onnx` | `0826f8c1ab9edf1801db86c61919d4d108e8bfc0b809ec823ad366882ff0b77d` (569,694,530 bytes) |

Qdrant `crop_process_bge_m3` is green, 105 points, 1024 dimensions, cosine. `s1g14-qdrant` and `cn230-db-1` are running. `s1g14-pgvector-test` is stopped. Volume `s1g14_pgvector_test_data` remains.

## 11. Known dictionary tie behavior

`ข้าว`, `rice in Thailand`, and `ผลผลิตข้าวกับอ้อย` can place `P-SRC-04-RIC-dry-2020` and `P-SRC-04-RIC-wet-2020` in either order. Both rows are year 2020, area Thailand, source `SRC-04`. The course statement orders by `p.year_ce, p.area, p.source_id` and does not define the remaining order. This is recorded separately from semantic and hybrid ranking. The course SQL was not changed.

## 12. Cloud migration blockers

- Neon project, region, database name, and emptiness are NOT VERIFIED.
- `STAGING_DATABASE_URL` and `S1G14_STAGING_WRITE_APPROVED` are intentionally unset.
- The Linux image still needs a later rebuild before an API cutover. That does not block the database write request.
- Windows Application Control still blocks the local `psycopg` binary. The dry-run does not import it. A future write session uses the Linux client.

## 13. Exact owner decisions required

Before any Neon write, supply:

1. Staging project identifier.
2. Exact staging database name.
3. Region.
4. Acceptance of the published Free-plan charge estimate, or the actual plan if it differs.
5. Confirmation that the destination is empty.
6. Acceptance of schema hashes in section 5.
7. Acceptance of the row counts and the 105-vector count.
8. Migration role scope: schema and import for the load window only.
9. Application role scope: `SELECT`, read-only transactions, 5-second statement timeout, no membership in the migration role.
10. Rollback: keep SQLite, Qdrant, and `s1g14_pgvector_test_data`. A bad Neon branch is dropped only under a separate approval. No existing database is dropped by the runner.
11. Validation and parity plan in section 7, including the dictionary tie as a known ordering case.

## 14. Next authorized execution step

Stop. The next step is an owner decision that names the empty staging database and authorizes one write session. That session must set `STAGING_DATABASE_URL` outside Git and `S1G14_STAGING_WRITE_APPROVED=1`, then run `python -m scripts.neon_staging_migrate --write --database <approved-name>` from the Linux client. This phase does not start that session and does not deploy the backend.

## Classification

| Item | Result |
| --- | --- |
| Preparation | PASS |
| Neon connectivity | NOT VERIFIED |
| Runner and dry-run | PASS |
| Role draft | PASS |
| Validation plan | PASS |
| Linux pin | PASS |
| Linux image rebuild | NOT VERIFIED |
| Local regression | PASS |
| Source integrity | PASS |

Final recommendation:

A. READY TO REQUEST NEON STAGING WRITE APPROVAL

STATUS: DEPLOY-01C.1 PREPARATION COMPLETE — AWAITING OWNER APPROVAL FOR NEON WRITE
