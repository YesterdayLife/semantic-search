# S1-G14 Qdrant service

**Current data update (16 November 2026):** the active local catalog and semantic
index contain 180 records, including wet/dry rice in all six regions for
2019–2024. See [RICE_DATA_UPDATE.md](RICE_DATA_UPDATE.md) for sources, validation,
backups and repeatable import instructions. Older phase reports below describe
the original 105-record snapshot.

Standalone vector database for the agricultural semantic-search service.
This Compose project runs only Qdrant. It does not mount the SQLite database,
does not join the CN230 MySQL network, and does not create collections.

Image: `qdrant/qdrant:v1.20.0`  
HTTP: `http://127.0.0.1:6333`  
Project name: `s1g14-search`  
Container name: `s1g14-qdrant`  
Volume: `s1g14_qdrant_storage` mounted at `/qdrant/storage`

## Local release handover

The proposed local identifier is `v1.0.0-local`. That tag has not been created, and this service is not a public deployment.

- [RELEASE_NOTES.md](RELEASE_NOTES.md) — features, evaluation figures, and limits
- [DEMO_GUIDE.md](DEMO_GUIDE.md) — startup, the eight example queries, and shutdown
- [FINAL_ACCEPTANCE.md](FINAL_ACCEPTANCE.md) — acceptance record, including the owner’s keyboard checks
- [ARCHITECTURE.md](ARCHITECTURE.md) — component boundaries and the eligibility-first Hybrid ranker

Run every command below from PowerShell. The working directory must be this folder so Compose does not touch `D:\TU\HW\CN230\cn230`.

```powershell
Set-Location "D:\Final Project\final\search_service"
```

## Start Qdrant

```powershell
docker compose config
docker compose pull
docker compose up -d
```

`docker compose config` checks the file before anything starts. `up -d` starts only this project.

## Stop Qdrant safely

Stop the container and keep its data:

```powershell
docker compose stop
```

Start it again later:

```powershell
docker compose start
```

Remove the container but keep the named volume:

```powershell
docker compose down
```

Do not run `docker compose down -v`. The `-v` flag deletes `s1g14_qdrant_storage`.
Do not run Compose from the CN230 directory. That project owns the MySQL container `cn230-db-1`.

## Inspect status

```powershell
docker compose ps
docker inspect s1g14-qdrant --format "Status={{.State.Status}} StartedAt={{.State.StartedAt}}"
docker volume inspect s1g14_qdrant_storage
```

Port 6333 must show `127.0.0.1`, not `0.0.0.0`:

```powershell
docker port s1g14-qdrant
netstat -ano | findstr ":6333"
```

## Dashboard

Open [http://127.0.0.1:6333/dashboard](http://127.0.0.1:6333/dashboard) in a browser on this machine.
The dashboard is the Qdrant web UI served by the same HTTP port.

## Inspect collections

Phase 2 starts with no collections. Phase 3 mock indexing may add `crop_process_mock`.
`crop_process` is reserved for approved OpenAI embeddings and is not created by mock mode.

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:6333/collections"
Invoke-RestMethod -Uri "http://127.0.0.1:6333/readyz"
```

An empty result looks like `collections` with an empty list.

## Where data persists

Qdrant writes its storage to the named Docker volume `s1g14_qdrant_storage`.
The volume survives `docker compose stop` and `docker compose down`.
It is removed only by an explicit volume delete, such as `docker compose down -v`.

The SQLite file stays outside this service:

```text
D:\Final Project\Hee_M3\output\S1-G14_M3.sqlite
```

## Verify SQLite connectivity

This check is read-only. It does not change journal mode, schema, or rows.

```powershell
@'
import sqlite3
from pathlib import Path
p = Path(r"D:\Final Project\Hee_M3\output\S1-G14_M3.sqlite")
db = sqlite3.connect(p.resolve().as_uri() + "?mode=ro", uri=True)
tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
print(",".join(tables))
print(db.execute("SELECT COUNT(*) FROM process").fetchone()[0])
'@ | python -
```

Expected process count: `105`.

Checksum and size:

```powershell
Get-Item "D:\Final Project\Hee_M3\output\S1-G14_M3.sqlite" | Select-Object FullName, Length, LastWriteTime
Get-FileHash "D:\Final Project\Hee_M3\output\S1-G14_M3.sqlite" -Algorithm SHA256
```

## Port conflicts

If startup reports that port 6333 is already allocated:

```powershell
Get-NetTCPConnection -LocalPort 6333 -ErrorAction SilentlyContinue | Format-List
netstat -ano | findstr ":6333"
```

The last column of `netstat` is the process id. Identify it with:

```powershell
Get-Process -Id <process-id>
```

Free the port by stopping the program that owns it, or ask before changing the host port in `docker-compose.yml`. Do not stop `cn230-db-1`; that container publishes 3306, not 6333.

## Failed startup

```powershell
docker compose ps
docker compose logs --tail 100 qdrant
docker inspect s1g14-qdrant --format "Status={{.State.Status}} Error={{.State.Error}} OOM={{.State.OOMKilled}}"
```

Typical recovery, without deleting volumes:

```powershell
docker compose stop
docker compose up -d
```

If the container never becomes healthy, leave it stopped and keep the volume. Do not delete `s1g14_qdrant_storage`, `cn230-db-1`, or the MySQL volume.

Confirm MySQL was not changed:

```powershell
docker inspect cn230-db-1 --format "Status={{.State.Status}} StartedAt={{.State.StartedAt}} RestartCount={{.RestartCount}}"
```

## Index process documents

The indexer reads SQLite with `mode=ro` and `PRAGMA query_only=ON`. It does not modify the database.
Qdrant is called through its HTTP API on `127.0.0.1:6333`. The gRPC client library is not used.
Mock vectors are deterministic test vectors named `mock-deterministic-v1`. They are not semantic embeddings.
Real OpenAI indexing is a separate command and is not part of setup or tests.

Create the virtual environment from this folder. Python 3.12 is the intended runtime. If it is not installed, use the available Python 3.12+ interpreter.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m app.index_sqlite --mode dry-run
.\.venv\Scripts\python.exe -m app.index_sqlite --mode mock
```

Dry-run does not create a collection, upload vectors, or call OpenAI.
Mock mode writes only `crop_process_mock`. Running it again upserts the same UUIDv5 point ids and does not duplicate points.

## Local BGE-M3 indexing

Local embeddings use `BAAI/bge-m3`. The preferred runtime is sentence-transformers with the official revision `5617a9f61b028005a4858fdac845db406aefb181`.
On this machine Windows Application Control blocks `torch_python.dll`, so indexing uses ONNX Runtime on CPU instead.
The ONNX weights are the quantized dense graph `Xenova/bge-m3` revision `4de13258303883538bd53b696b452bf8099f0858`, file `onnx/model_quantized.onnx`.
Pooling matches the official model: CLS token, then L2 normalization. Vectors have 1024 dimensions and are stored only in `crop_process_bge_m3`.
The stored model revision for that runtime is `xenova-4de13258303883538bd53b696b452bf8099f0858-model_quantized.onnx`.
No OpenAI key is required. Weights are cached under `search_service/.cache/huggingface`.
Delete `search_service/.cache/huggingface/torch_dll_blocked` to try PyTorch again after the policy changes.

```powershell
.\.venv\Scripts\python.exe -m app.index_sqlite --mode local-bge-m3 --dry-run
.\.venv\Scripts\python.exe -m app.index_sqlite --mode local-bge-m3 --execute-local
```

`--dry-run` does not load the model and does not write to Qdrant.
When PyTorch loads, the device is CUDA if a GPU is available, otherwise CPU.
Mock collection `crop_process_mock` and the reserved OpenAI collection `crop_process` are not modified.

Do not run real OpenAI indexing until it is explicitly approved:

```powershell
.\.venv\Scripts\python.exe -m app.index_sqlite --mode real --execute-real
```

That command is the only path that calls OpenAI. It refuses to start without `OPENAI_API_KEY` and writes only `crop_process`.
Point ids are UUIDv5 under the namespace URN `urn:s1-g14:crop-process:v1`.
Stale Qdrant points are printed in the report and are not deleted.

## Local search API

The API serves the existing `crop_process_bge_m3` collection. It embeds the query with the cached ONNX BGE-M3 model, applies structured filters in Qdrant, and reads production quantities from SQLite. It does not re-index points and it does not call OpenAI.

Start it on localhost after Qdrant is already running:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

`GET /health` reports liveness without loading a new model. `GET /ready` checks Qdrant, the 1024-dimensional cosine collection, SQLite read-only access, and the cached ONNX weights. Startup fails readiness when `search_service/.cache/huggingface` does not already contain the Xenova `model_quantized.onnx` snapshot. The model is loaded once per process. Query inference is serialized so CPU execution stays bounded.

`POST /search` accepts:

```json
{
  "query": "ผลผลิตมันสำปะหลังภาคเหนือปี 2566",
  "top_k": 5,
  "filters": {
    "crop_id": null,
    "year_ce": null,
    "region_code": null,
    "season": null,
    "spatial_level": null,
    "source_id": null
  }
}
```

`GET /search?query=maize%20production%20in%20central%20Thailand%202022&top_k=5` accepts the same fields as query parameters. `query` is required, at most 500 characters. `top_k` is from 1 to 105. Unknown JSON fields and unknown query parameters are rejected. Explicit filter values must already exist in SQLite: crop `CAS`, `MAI`, `RIC`, or `SUG`; region `CEN`, `EAS`, `NEA`, `NOR`, `SOU`, or `WES`; season `all`, `dry`, or `wet`; spatial level `country` or `region`; `year_ce` from 1900 through 2100. An explicit filter overrides a value inferred from the query text.

The parser recognizes the same Thai and English crop, region, and season aliases used by the document index. Buddhist Era years from 2500 through 2599 are converted by subtracting 543. Ambiguous crops, regions, seasons, years, or sources are left unfiltered and described in `warnings`. Fertilizer, energy input, water consumption, and carbon footprint requests add `unavailable_measures` because those inputs are not in the validated database. Matching production records can still be returned, and their quantities come from SQLite output exchanges.

A response contains `parsed_filters`, `count`, `results`, `warnings`, `search_engine`, and `embedding_model`. Each result includes the process, similarity score, crop, year, region, season, spatial level, production quantity and unit, source agency and title, and available indicators. An empty `results` array means no indexed process matched. Qdrant, SQLite, or model failures return HTTP 503. Invalid input returns HTTP 422. Clients do not receive stack traces or filesystem paths.

```powershell
.\.venv\Scripts\python.exe -m pytest -q -m "not integration"
.\.venv\Scripts\python.exe -m pytest -q
```

The integration tests load the cached ONNX model and query the local Qdrant collection. Current limitations: PyTorch remains blocked by Application Control, so this API pins the quantized ONNX runtime; GPU inference is not used; the service does not answer with generated prose; and it does not calculate environmental inputs that are absent from SQLite.

## Side-by-side search

Dictionary search and local BGE-M3 search stay separate. The comparison command loads the course file `Hee_M4\ch6 semantic search\src\semantic_search.py` and calls its `search` function. It does not edit that file or its SQL. The Neo4j character-ngram demo is a third system and is not called. Existing `/health`, `/ready`, and `/search` responses are unchanged.

```powershell
.\.venv\Scripts\python.exe -m app.compare_search --mode dictionary --query "มันสำปะหลังภาคเหนือปี 2566"
.\.venv\Scripts\python.exe -m app.compare_search --mode semantic --query "มันสำปะหลังภาคเหนือปี 2566"
.\.venv\Scripts\python.exe -m app.compare_search --mode compare --query "มันสำปะหลังภาคเหนือปี 2566"
.\.venv\Scripts\python.exe -m app.compare_search --mode semantic-fallback --query "มันสำปะหลังภาคเหนือปี 2566"
```

`--top-k` defaults to 5 and accepts 1 through 105. Optional `--crop-id`, `--year-ce`, `--region-code`, `--season`, `--spatial-level`, and `--source-id` are sent to BGE-M3. Dictionary mode reports those filters as not applied and still uses the original query parser.

`dictionary` returns the original payload in `original` and a normalized copy in `results`. Normalized dictionary rows have `similarity_score` null and a `match_reason` taken from the original intent. `semantic` reuses the Phase 4 service. Its rows have `match_reason` null and a cosine `similarity_score`. `compare` returns both objects and sets `score_comparison` to null. One backend can fail while the other still returns its own results.

`semantic-fallback` is opt-in. It uses BGE-M3 when that service is available, including when the result set is empty. It calls dictionary search only after an infrastructure failure, then sets `degraded` and `fallback_applied`. An invalid filter does not switch backends. The plain `semantic` mode never switches.

Availability is `supported` for a production query, `partially_supported` when an unavailable measure is combined with a crop, place, season, or year, and `unsupported` when dictionary search refuses the question or the semantic query asks only for an unavailable measure. Fertilizer, energy input, water input, and carbon footprint are unavailable. Production quantities in that last case are returned as `context_results` and marked `answers_requested_measure: false`.

```powershell
.\.venv\Scripts\python.exe -m pytest -q -m "not integration"
.\.venv\Scripts\python.exe -m pytest -q
```

The dictionary adapter depends on the read-only course script above and on the canonical SQLite file. Semantic comparison also requires the local Qdrant collection and the cached ONNX weights. The comparison does not rank the two methods against each other.

## Comparison API

`POST /compare` reuses the same adapters. `GET /health`, `GET /ready`, `POST /search`, and `GET /search` keep their existing response fields.

```json
{
  "query": "มันสำปะหลังภาคเหนือปี 2566",
  "top_k": 5,
  "filters": {},
  "mode": "compare"
}
```

`mode` is `dictionary`, `semantic`, `compare`, or `semantic-fallback`. The response keeps each backend's ranking in its own section. `score_comparison` is null. Dictionary rows still have a null similarity score. Semantic rows still have a null match reason.

Separate filters are applied only by semantic search. The response then sets `filter_comparability.directly_comparable` to false and explains that the eligible record sets differ. Dictionary SQL is unchanged.

A question that asks only for fertilizer, energy, water, or carbon footprint has availability `unsupported`. Related production rows, when returned, stay in `context_results` and have `answers_requested_measure` false. A scoped question for one of those measures is `partially_supported`: the production rows are visible and explicitly do not answer the requested measure.

## Search evaluation

The labeled queries are `evaluation/queries.json`. Process ids are read from SQLite when the report is built. Ambiguous queries and numeric thresholds that neither parser executes are excluded from single-answer relevance. Empty relevant sets are scored by empty-result correctness and are left out of precision, recall, hit rate, MRR, and nDCG.

```powershell
.\.venv\Scripts\python.exe -m app.evaluate_search --top-k 5 --backends both --repetitions 5 --warmup 2 --output-dir evaluation\reports
```

`--dataset`, `--top-k`, `--output-dir`, `--backends`, `--repetitions`, and `--warmup` are configurable. The output directory must stay inside this folder. The command writes `evaluation.json` and `evaluation.md`. Model initialization is timed separately from warm queries. `--backends all` also runs hybrid search. Historical precision still divides by the number of answer rows returned.

## Hybrid search

`POST /hybrid-search` is a separate mode. It does not change `/search` or `/compare`, and it does not add dictionary scores to cosine similarity.

The pipeline is intent analysis, structured SQLite eligibility, local BGE-M3 ranking of only those process ids, then SQLite hydration. An empty eligible set skips embedding. A question that names more than one crop with `and`, `และ`, `กับ`, or `compare` keeps each crop when `top_k` allows it. Numeric comparisons use SQLite quantities and reject incompatible units instead of converting them.

```powershell
.\.venv\Scripts\python.exe -m app.hybrid_search --query "มันสำปะหลังและข้าวโพด" --top-k 5
```

## Frontend

The local interface lives in `frontend`. It speaks Thai by default and calls only this FastAPI service. The browser does not open Qdrant or SQLite. Vite proxies `/api` to `http://127.0.0.1:8000`.

Start Qdrant, then the API, then the interface. Use three PowerShell windows and keep every bind address on localhost.

```powershell
Set-Location "D:\Final Project\final\search_service"
docker compose up -d
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

```powershell
Set-Location "D:\Final Project\final\search_service\frontend"
npm install
npm run dev
```

If PowerShell blocks `npm.ps1`, use `npm.cmd run dev`. The same `npm.cmd` prefix applies to `test`, `run build`, and `run preview`.

Open `http://127.0.0.1:5173`. Search modes are Hybrid, Semantic (`POST /search`), Dictionary (`POST /compare` with `mode=dictionary`), and Compare. Hybrid can send a numeric constraint with its metric, operator, threshold, and SQLite unit. `GET /catalog` lists filter values from SQLite. `GET /evaluation-report` reads the saved file `evaluation/reports/evaluation.json` and does not rerun the evaluation.

```powershell
Set-Location "D:\Final Project\final\search_service\frontend"
npm test
npm run build
npm run preview
```

`npm test` uses mocked API responses. `npm run build` writes `frontend/dist`. `npm run preview` serves that build on `http://127.0.0.1:4173` and still expects the API proxy only during `npm run dev`. For the preview server, set the API base if you are not using the dev proxy:

```powershell
$env:VITE_API_BASE = "http://127.0.0.1:8000"
npm run build
```

The dev proxy is the supported local setup. Do not publish port 8000 or 5173 beyond this machine.

Known limits: explicit filters are not applied by dictionary SQL; generic yield and kilogram thresholds are left unapplied; cosine similarity is not a production quantity; the evaluation page shows the saved benchmark, not a live measurement; fertilizer, water, energy, and carbon footprint stay unavailable.
