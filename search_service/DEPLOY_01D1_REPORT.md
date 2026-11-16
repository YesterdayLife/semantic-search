# DEPLOY-01D.1 — Linux Backend Portability and Full API Parity

Local implementation and verification only. No cloud deployment, no database migration, no image push, no model upload, no re-index.

Classification: **PASS** for the confirmed Linux defects.
Recommendation: **A. READY FOR NEON STAGING PREPARATION**

Live PostgreSQL execution remains **NOT VERIFIED**. That is the work of DEPLOY-01C, and it was not started.

## 1. Root cause of each portability defect

### DEFECT A — Catalog

`GET /catalog` called `read_public_catalog()`, whose default path was bound to the Windows absolute file `D:\Final Project\Hee_M3\output\S1-G14_M3.sqlite` at function definition. Inside the container that path does not exist, so the route returned HTTP 503 even when `SQLITE_PATH=/data/S1-G14_M3.sqlite` was set and the file was mounted read-only.

### DEFECT B — Dictionary search

`DictionarySearchAdapter` loaded the course module from a Windows-only default, `D:\Final Project\Hee_M4\ch6 semantic search\src\semantic_search.py`. That file is not in the image. Compare mode calls the same adapter, so it returned `dictionary_unavailable` as well.

A shallow mount such as `/opt/dictionary/semantic_search.py` is not enough. The course file, which was left unchanged, sets its default database at import with `Path(__file__).resolve().parents[3]`. That expression needs three parent directories. The adapter still passes `SQLITE_PATH` into `search()`, and the course function opens that path with `mode=ro`.

### DEFECT C — Model packaging

The approved ONNX snapshot is excluded by `.dockerignore` and is supplied only by a read-only mount at `/models/huggingface-ro`. The image therefore cannot start on a host that does not have that mount. Copying the snapshot into a distributable image was not authorized.

## 2. Files modified

All writes stayed inside `search_service`.

| File | Change |
| --- | --- |
| `app/config.py` | `SQLITE_PATH` and `DICTIONARY_SCRIPT` resolve through settings. Defaults stay the Windows paths when the variables are unset. |
| `app/public_data.py` | `read_configured_catalog()` follows `DATA_BACKEND`. Shared catalog SQL lives in `_catalog_payload`. |
| `app/api/routes.py` | `GET /catalog` calls `read_configured_catalog()`. |
| `app/adapters.py` | Local dictionary adapter takes the configured SQLite path and script path. |
| `app/dictionary_postgres.py` | PostgreSQL dictionary adapter loads `parse_query` from the configured script and does not open SQLite. |
| `app/main.py` | Lifespan passes the configured paths into the selected dictionary adapter. |
| `Dockerfile` | Comments only. The snapshot is still not copied. |
| `scripts/container_api_bench.py` | Mounts the course file at the depth its import expects. |
| `scripts/container_bench.py` | Same dictionary mount. |
| `tests/test_portability.py` | New focused tests for both defects. |

Unchanged on purpose: the canonical SQLite file, the course script, Neo4j files, Qdrant data, `docker-compose.yml`, ONNX weights, `evaluation/reports/evaluation.json`, and `app/evaluate_search.py`. The evaluation CLI still defaults to the Windows database path. The API report route reads the package-relative JSON and does not use that CLI.

## 3. Catalog fix — PASS

`GET /catalog` now uses the configured provider.

LOCAL (`DATA_BACKEND=sqlite`):

- Reads `settings.sqlite_path`.
- Accepts Windows and Linux paths.
- Opens the file read-only.
- Keeps the same response keys and the same `ORDER BY crop_id, region_code, season, spatial_level, source_id, year_ce`.

CLOUD (`DATA_BACKEND=postgres`):

- Calls `PostgresDataProvider.connect()` and the shared catalog SQL.
- Does not open the canonical SQLite file.
- A provider error becomes `postgres_unavailable`. There is no SQLite fallback.

Linux result: `GET /catalog` returned HTTP 200 with `process_count` 105.

## 4. Dictionary fix — PASS

The original course file was not edited and was not copied into the image. LOCAL mode mounts it read-only at the depth `parents[3]` requires:

```
Host:   D:\Final Project\Hee_M4\ch6 semantic search\src\semantic_search.py
Target: /opt/course/Hee_M4/ch6 semantic search/src/semantic_search.py
Env:    DICTIONARY_SCRIPT=/opt/course/Hee_M4/ch6 semantic search/src/semantic_search.py
```

`parents[3]` is `/opt/course`. The adapter passes `SQLITE_PATH=/data/S1-G14_M3.sqlite`, and the course function opens that URI with `mode=ro`, so the canonical database cannot be written by the script. The container does not need the course file's own default database to exist.

CLOUD mode keeps `PostgresDictionaryAdapter`. It uses `parse_query` from the same course module and runs PostgreSQL `%s` SQL. A cloud process must receive `DICTIONARY_SCRIPT` pointing at that one standard-library file. It does not need the Windows path. The script imports only the standard library, so no extra parser package is required. Live PostgreSQL execution of that adapter is **NOT VERIFIED**.

Inside Linux, dictionary mode and compare mode both returned `error: null` for the northern cassava query, process `P-REG-SRC-06-CAS-NOR-2023`, quantity `7707851.0` t.

## 5. Model provisioning design — PASS as a design; snapshot not moved

The verified local behavior is unchanged:

- Read-only mount at `/models/huggingface-ro`.
- Entrypoint copies the tree into `HF_HOME=/tmp/huggingface` because the hub may write locks.
- `HF_HUB_OFFLINE=1`.
- Missing snapshot exits 1 with `approved ONNX snapshot is not mounted`.
- One Uvicorn worker. No torch, CUDA, or OpenAI in the Linux requirements.

The snapshot stays out of the image. `.dockerignore` still excludes `.cache`. No upload and no registry push were performed.

Later authorized provisioning, in the order to consider:

1. **Private artifact store.** Keep the revision `4de13258303883538bd53b696b452bf8099f0858` and the file `onnx/model_quantized.onnx` (569,694,530 bytes, SHA-256 `0826f8c1ab9edf1801db86c61919d4d108e8bfc0b809ec823ad366882ff0b77d`) together with `tokenizer.json` and the rest of that snapshot. Download once into a persistent volume. Verify the hash before the process starts. Do not download again on later boots.
2. **Read-only persistent volume.** An operator populates the volume once. Startup checks the revision path and the SHA-256, then refuses to start on a mismatch. Credentials for the store stay in the host secret manager, not in the image and not in frontend variables.
3. **Image-layer inclusion.** Only after a separate written authorization. The cache has no LICENSE file, so placing the weights in a registry image is redistribution. The layer would add about 570 MB. Startup would still verify the hash and stay offline.

## 6. Linux API verification — PASS

Image `s1g14-search-onnx:local`, manifest list `sha256:1e1f9ce01a58ee1e9221e71b0b9302be86f8b1b924be307bab08cba1664577f9`.

Runtime: SQLite `:ro`, Qdrant at `http://host.docker.internal:6333`, ONNX cache `:ro`, dictionary mount above, 2 GB memory, 2 CPUs, published only as `127.0.0.1:8011:8000`. Container removed after the run. No OOM.

| Endpoint | Result |
| --- | --- |
| `GET /health` | 200 |
| `GET /ready` | 200, count 105 |
| `GET /catalog` | 200, count 105 |
| `GET /evaluation-report` | 200 |
| `POST /search` | 200 |
| `POST /hybrid-search` | 200 |
| `POST /compare` | 200, dictionary and semantic both present |

Modes checked: Dictionary, Semantic, Hybrid, Compare.

## 7. Search parity results — PASS

Windows `TestClient` and the Linux container returned the same first process, quantity, and score. Ranking rules were not changed.

| Query | Mode | First process | Quantity (t) | Score |
| --- | --- | --- | --- | --- |
| ผลผลิตมันสำปะหลังภาคเหนือปี 2566 | search, dictionary, compare | `P-REG-SRC-06-CAS-NOR-2023` | 7707851.0 | 0.5816793 |
| maize production in central Thailand 2022 | search | `P-REG-SRC-05-MAI-CEN-2022` | 431024.0 | 0.5366615 |
| ข้าวนาปรังปี 2565 | search | `P-SRC-04-RIC-dry-2022` | 6171197.0 | 0.5325025 |
| มันสำปะหลังและข้าวโพด | hybrid | `P-REG-SRC-06-CAS-EAS-2019` | 3415285.0 | 0.53229153 |
| ผลผลิตมากกว่า 1000000 ตัน | hybrid | `P-SRC-01-SUG-all-2020` | 74968070.0 | 0.48755878 |
| มันสำปะหลังภาคใต้ปี 2566 | hybrid | count 0 | — | — |
| carbon footprint of rice production | search | `P-SRC-04-RIC-wet-2021` | 26806578.0 | 0.50707567 |

The exact carbon query returns `unavailable_measures: ["carbon_footprint"]` on both platforms. Compare for the northern cassava query used the same process id and the same quantity on the dictionary side and the semantic side.

## 8. Python tests — PASS

Full suite earlier in this phase: **154 passed** (148 existing + 6 new portability tests).

After the Dockerfile comment update, `tests/test_onnx_image.py` and `tests/test_portability.py` were run again: **10 passed**.

New coverage: Windows SQLite path and catalog order, Linux path, missing SQLite file, PostgreSQL mode refusing to open SQLite, shared catalog SQL parity, catalog route configuration, and a configurable read-only dictionary script. The northern cassava dictionary result in that test is `P-REG-SRC-06-CAS-NOR-2023`, `7707851.0` t.

## 9. Frontend tests — PASS

`npm test`: **29 passed**.
`npm run build`: `tsc -b` and the Vite production build passed. Bundle names were unchanged.

## 10. Docker build — PASS

`docker build -t s1g14-search-onnx:local .` completed. The final build was cache-only after the comment edit.

Manifest list: `sha256:1e1f9ce01a58ee1e9221e71b0b9302be86f8b1b924be307bab08cba1664577f9`.

The image was not pushed. The model snapshot is not in the image.

## 11. SQLite and Qdrant integrity — PASS

| Item | Result |
| --- | --- |
| Canonical SQLite SHA-256 | `9a80da4111beb44a00c5128c3ffdc10f1e6810825f10a838492981d8e3727808` |
| Course `semantic_search.py` | `8db66ee8ee675e43822e827375a2bba299eeed252063cc2a88f4a130e8e7cc60` (6,380 bytes) |
| `build_serving_layer.py` | `b770300f8835ab5c58f40d32132d4dd65530bfd2ac4692082fd3fd7caef0ca78` |
| `import.cypher` | `5286e190259a123aaed76fda427851a62bf126e69c71ad0a4e013070e2b3ab1d` |
| `docker-compose.yml` | `109b813ad1d1e246c2fc7eef6590d1bcccfa94155299ad67fbbc903499e92b49` |
| `evaluation.json` | `bf72a8ba7ae98365d4b1658d5bdbbd05b7d48f3c4d6db4f6771524b19720800e` |
| `model_quantized.onnx` | `0826f8c1ab9edf1801db86c61919d4d108e8bfc0b809ec823ad366882ff0b77d` (569,694,530 bytes) |
| Qdrant `crop_process_bge_m3` | green, 105 points, 1024 dimensions, Cosine |

No re-index. No OpenAI call. No Neon, Vercel, Railway, or Render deployment.

## 12. Remaining PostgreSQL integration blockers — NOT VERIFIED

- `psycopg` is not installed, and the Linux image has no `DATABASE_URL`.
- PostgreSQL catalog and dictionary code paths are covered by unit tests. They have not been executed against a live server.
- A PostgreSQL connection error must stay `postgres_unavailable`. It must not fall back to the canonical SQLite file.
- Cloud dictionary still needs the course file available through `DICTIONARY_SCRIPT` so `parse_query` stays the original parser.
- `app/evaluate_search.py` still defaults to the Windows SQLite path. The API does not use that default.

## 13. DEPLOY-01C readiness — PASS to prepare

The two confirmed Linux API defects are fixed and matched Windows on all seven required queries. Catalog ordering, dictionary quantities, and semantic scores were preserved.

DEPLOY-01C can be prepared. It should not be started until the owner approves it. Preparation still has to include a live PostgreSQL check and the authorized model-volume step before any host that cannot use the local read-only mounts.

## 14. Recommended next phase

**A. READY FOR NEON STAGING PREPARATION**

Non-blocking items to carry into that preparation:

- Live PostgreSQL catalog and dictionary execution is **NOT VERIFIED**.
- The ONNX snapshot still requires the local read-only mount or a later authorized private volume.
- The evaluation CLI default path was left unchanged because it is outside the API defects.

STATUS: DEPLOY-01D.1 COMPLETE — AWAITING OWNER APPROVAL FOR DEPLOY-01C
