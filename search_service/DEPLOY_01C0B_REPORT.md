# DEPLOY-01C.0B — Real local PostgreSQL and pgvector integration

The isolated database was created, loaded, and queried. It is now stopped. Its volume is still present. No Neon resource was created.

Recommendation: **B. READY WITH NON-BLOCKING ISSUES**

## 1. Preflight — PASS

`migrations/postgres/PROPOSED_local_pgvector_test.compose.yml` passed the safety checks before it was started:

- One new container, `s1g14-pgvector-test`.
- No name clash with `s1g14-qdrant` or `cn230-db-1`.
- Published only as `127.0.0.1:54329`.
- Ports 3306, 6333, and 8000 were not used.
- Volume `s1g14_pgvector_test_data` is dedicated to this test.
- SQLite and Qdrant are not mounted into the database container.
- The password came from a local secret file and is not in the Compose file.
- Compose project `s1g14-pgvector-test`, separate from `s1g14-search`.
- Image `pgvector/pgvector:0.8.7-pg16`.

`psycopg[binary]==3.3.9` was installed in `search_service\.venv`. Windows Application Control blocks that wheel's `pq` DLL, so the host process cannot import it. The same version was used from an ephemeral Linux client on the test network. That client was removed. No system-wide package was installed.

## 2. Files modified

| File | Change |
| --- | --- |
| `requirements.txt` | Pin `psycopg[binary]==3.3.9`. |
| `app/migration_audit.py` | Use `vector_norm(embedding)`. pgvector 0.8.7 has no `l2_norm(vector)`. |
| `migrations/postgres/PROPOSED_local_pgvector_test.compose.yml` | Authorization comment only. |
| `scripts/pg_local_common.py` | Disposable connection helper. It does not print secrets. |
| `scripts/pg_local_load.py` | Schema apply, read-only copy, and vector comparison. |
| `scripts/pg_local_client.py` | Ephemeral Linux runner. |
| `scripts/pg_local_parity.py` | 61-query comparison. |
| `scripts/pg_local_focus.py` | Four demonstration queries absent from the saved set. |
| `scripts/pg_local_security.py` | SELECT-only role check. |
| `scripts/pg_local_serve.py` | Temporary API process. |
| `scripts/pg_local_api_check.py` | Local HTTP checks. |
| `tests/test_cloud_adapters.py` | Locks the pgvector 0.8 norm function name. |
| `DEPLOY_01C0B_REPORT.md` | This report. |

Schema drafts `001_schema.sql` and `002_pgvector.sql` did not need edits. Ranking and eligibility rules were not changed.

## 3. Versions — PASS

| Item | Value |
| --- | --- |
| PostgreSQL | 16.16 (Debian 16.16-1.pgdg12+1) |
| pgvector | 0.8.7 |
| psycopg | 3.3.9 |
| Container | `s1g14-pgvector-test` |
| Host port | `127.0.0.1:54329` |
| Database | `s1g14_migration_test` |
| Compose project | `s1g14-pgvector-test` |

## 4. Schema execution — PASS

Each file ran in its own transaction. `vector` 0.8.7 is installed. `process_embeddings.embedding` has typmod 1024. All 11 relational tables exist, plus `process_embeddings`.

Constraint counts: 12 primary keys, 16 foreign keys, 6 unique constraints, 12 checks.

A second apply fails and rolls back:

- `001_schema.sql`: `DuplicateTable`, `relation "crop" already exists`
- `002_pgvector.sql`: `DuplicateTable`, `relation "process_embeddings" already exists`

The first apply stays in place. No HNSW index was created.

## 5. Relational import — PASS

The canonical SQLite file was opened with `mode=ro`. Counts match: crop 4, region 6, data_source 5, source_file 8, flow 4, province_region_map 77, process 105, exchange 105, crop_indicator 324, regional_aggregate 60, regional_contribution 2875.

Orphan total 0. Country NULL regions 45. Output exchanges 105. Unit `t`. Integer flags outside 0/1: 0. Crops CAS, MAI, RIC, SUG. Regions CEN, EAS, NEA, NOR, SOU, WES.

The three fractional tonnes match the source float64 bits: `32882932.48`, `33851579.48`, `33551336.65`.

## 6. Vector import — PASS

105 Qdrant points were scrolled and inserted. 105 distinct process ids, 105 distinct UUIDs. Revision `xenova-4de13258303883538bd53b696b452bf8099f0858-model_quantized.onnx`. Dimension 1024. All 105 norms are nonzero. Payload fields match. The source fingerprint matches `75aecb4737a45afa01a135af63eff05ff73953a9b4065f2d481ab1716f6f79ef`. No embedding was regenerated and Qdrant was not written.

## 7. Exact vector comparison — PASS

Maximum absolute component difference after round-trip: **0.0**. Threshold `1e-6`. No deviation.

## 8. pgvector ranking — PASS

Exact `embedding <=> query_vector`, similarity `1 - cosine_distance`, ordered by distance then `process_id`. No approximate index.

Controls: empty candidate list returns 0; a 1023-dimension query is rejected; a non-finite query is rejected; revision matches; numeric `production > 1000000 t` returns the same 81 ids as SQLite; tie-order violations on equal distances: 0.

No similarity difference on aligned rows exceeded `1e-5`. Observed gaps on the demonstration rows are about `1e-8`.

## 9. FastAPI PostgreSQL mode — PASS

The temporary API used `DATA_BACKEND=postgres`, `VECTOR_BACKEND=pgvector`, and the SELECT-only role. SQLite was not mounted. Qdrant was not configured. Responses did not contain the password.

| Check | Result |
| --- | --- |
| `GET /health` | served |
| `GET /ready` | 105 points, 1024, cosine, 105 processes |
| `GET /catalog` | 105; crops CAS, MAI, RIC, SUG |
| `GET /evaluation-report` | saved report, not recomputed |
| `POST /search` | seven queries matched the baseline ids and quantities |
| `POST /compare` | dictionary backend `dictionary-postgres`; both sides `P-REG-SRC-06-CAS-NOR-2023`, `7707851.0` t |
| `POST /hybrid-search` | `P-REG-SRC-06-CAS-EAS-2019`, `3415285.0` t |

`/ready` still returns the field names `sqlite` and `qdrant`. Those names were left in place. In this mode the counts come from PostgreSQL and pgvector.

## 10. Dictionary parity — PASS with one unspecified tie

Northern cassava 2023 matches on both sides: `P-REG-SRC-06-CAS-NOR-2023`, `7707851.0` t. Quantities and units matched for every compared dictionary row.

Three of the 61 queries (`ข้าว`, `rice in Thailand`, `ผลผลิตข้าวกับอ้อย`) swap `P-SRC-04-RIC-wet-2020` and `P-SRC-04-RIC-dry-2020`. Both rows have year 2020, area Thailand, and source SRC-04. The course `ORDER BY p.year_ce, p.area, p.source_id` does not separate them. SQLite and PostgreSQL each return a valid order. The course statement was not changed.

## 11. Seven-query parity — PASS

| Query | First process | Quantity (t) | Notes |
| --- | --- | --- | --- |
| ผลผลิตมันสำปะหลังภาคเหนือปี 2566 | `P-REG-SRC-06-CAS-NOR-2023` | 7707851.0 | score 0.5816793 |
| maize production in central Thailand 2022 | `P-REG-SRC-05-MAI-CEN-2022` | 431024.0 | score 0.5366615 |
| ข้าวนาปรังปี 2565 | `P-SRC-04-RIC-dry-2022` | 6171197.0 | score 0.5325025 |
| มันสำปะหลังและข้าวโพด | `P-REG-SRC-06-CAS-EAS-2019` | 3415285.0 | hybrid and semantic agree |
| ผลผลิตมากกว่า 1000000 ตัน | `P-SRC-01-SUG-all-2020` | 74968070.0 | score 0.48755878 |
| มันสำปะหลังภาคใต้ปี 2566 | none | — | count 0 |
| carbon footprint of rice production | `P-SRC-04-RIC-wet-2021` | 26806578.0 | `unavailable_measures: ["carbon_footprint"]` |

Process order, quantities, units, and availability matched between SQLite/Qdrant and PostgreSQL/pgvector.

## 12. 61-query evaluation — PASS

The saved dictionary, semantic, and hybrid lists are the same 61 query strings. All three modes were run. Semantic and hybrid process order matched on every query. Quantities, units, and availability matched. No score exceeded the `1e-5` gate. `evaluation.json` was not rewritten. Its SHA-256 is unchanged.

The only order difference is the dictionary tie in section 10.

## 13. Python tests — PASS

**155 passed** in 42.10 s. That is the previous 154 plus one test that locks `vector_norm`. The default suite does not require the disposable database. Local SQLite and Qdrant tests passed in that run.

## 14. Frontend tests — PASS

**29 passed.** `tsc -b` and the Vite production build passed. Bundle names were unchanged.

## 15. Security — PASS

Role `s1g14_app` was created in the disposable database and checked:

- `SELECT` returned 105 processes.
- `INSERT` was rejected.
- `CREATE TABLE` was rejected.
- `default_transaction_read_only` is `on`.
- `statement_timeout` is `5s`, and `pg_sleep(6)` was rejected.

The migration connection was the database owner and was used for schema and copy. The API used the SELECT-only role. No production credential was used.

## 16. Integrity — PASS

| Item | Value |
| --- | --- |
| SQLite SHA-256 | `9a80da4111beb44a00c5128c3ffdc10f1e6810825f10a838492981d8e3727808` |
| Qdrant | green, 105, 1024, Cosine |
| ONNX SHA-256 | `0826f8c1ab9edf1801db86c61919d4d108e8bfc0b809ec823ad366882ff0b77d` |
| Course script | `8db66ee8ee675e43822e827375a2bba299eeed252063cc2a88f4a130e8e7cc60` |
| `import.cypher` | `5286e190259a123aaed76fda427851a62bf126e69c71ad0a4e013070e2b3ab1d` |
| `docker-compose.yml` | `109b813ad1d1e246c2fc7eef6590d1bcccfa94155299ad67fbbc903499e92b49` |
| `evaluation.json` | `bf72a8ba7ae98365d4b1658d5bdbbd05b7d48f3c4d6db4f6771524b19720800e` |

No re-index. Default providers remain `sqlite` and `qdrant`. No cloud resource was created.

## 17. Cleanup — PASS

`s1g14-pg-api` was stopped and removed. `s1g14-pgvector-test` was stopped and left in the exited state. Volume `s1g14_pgvector_test_data` remains for inspection. `s1g14-qdrant` and `cn230-db-1` were left running. The volume was not deleted.

## 18. Remaining blockers

None that prevent a Neon staging migration of this dataset. Non-blocking items:

- The course dictionary sort does not define an order when year, area, and source are equal. Three queries show that tie.
- `/ready` still uses the names `sqlite` and `qdrant`. Keep them until a versioned contract change.
- This Windows host cannot load the psycopg binary DLL. A Linux process can. The Linux API image does not yet include `psycopg`.
- The disposable volume still holds the test data and the SELECT-only role.

## 19. Neon staging readiness

**B. READY WITH NON-BLOCKING ISSUES**

The schema, relational copy, vector copy, and search parity have been proven on PostgreSQL 16.16 and pgvector 0.8.7. Neon staging can use the same two SQL files, the same copy order, float8 parameters for the three fractional quantities, and exact cosine search without an HNSW index. Create a migration role for the load and a SELECT-only application role with `sslmode=require` afterward. Add `psycopg[binary]==3.3.9` to the Linux image before switching the API. Do not drop SQLite or Qdrant until that switch has been accepted.

STATUS: DEPLOY-01C.0B COMPLETE — AWAITING OWNER APPROVAL FOR NEON STAGING
