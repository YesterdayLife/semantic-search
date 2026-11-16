# Local demonstration guide

Demonstrate the service only on this machine. Start Qdrant, then the API, then the React app. Keep each process in its own PowerShell window.

The proposed release label is `v1.0.0-local`. These steps do not create a tag, a commit, or a public deployment.

## Prerequisites

- Docker Desktop is running.
- The virtual environment exists at `D:\Final Project\final\search_service\.venv`.
- Frontend dependencies are already installed in `frontend\node_modules`. Do not reinstall packages for a demonstration.
- Canonical database: `D:\Final Project\Hee_M3\output\S1-G14_M3.sqlite`.
- Cached quantized ONNX BGE-M3 weights already present under `search_service\.cache\huggingface`.
- No `OPENAI_API_KEY` is required.

Qdrant may already be listening on `127.0.0.1:6333`. Check before starting another copy.

## Start Qdrant

```powershell
Set-Location "D:\Final Project\final\search_service"
docker compose ps
docker compose up -d
```

`docker compose up -d` starts only the `s1g14-search` project and the container `s1g14-qdrant`. Run it from this folder so Compose does not touch the CN230 project or the MySQL container `cn230-db-1`.

Check:

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:6333/readyz"
```

The HTTP port must be bound to `127.0.0.1:6333`.

## Start FastAPI

```powershell
Set-Location "D:\Final Project\final\search_service"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Leave this window open. The first `/ready` call loads the ONNX model once for the process.

Health and readiness:

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/health"
Invoke-RestMethod -Uri "http://127.0.0.1:8000/ready"
```

`/health` returns `status: ok`. `/ready` is ready when the collection is `crop_process_bge_m3`, the vector size is 1024, the distance is cosine, the point count is 180, SQLite is ok, and the process count is 180.

## Start the React app

Development server, with the Vite proxy to `http://127.0.0.1:8000`:

```powershell
Set-Location "D:\Final Project\final\search_service\frontend"
npm.cmd run dev
```

Open `http://127.0.0.1:5173`.

`npm run dev` is the same script. On this machine PowerShell can block `npm.ps1`; `npm.cmd` avoids that policy.

### Preview option

The preview server does not use the development proxy. Build with the API base, then preview:

```powershell
Set-Location "D:\Final Project\final\search_service\frontend"
$env:VITE_API_BASE = "http://127.0.0.1:8000"
npm.cmd run build
npm.cmd run preview -- --host 127.0.0.1 --port 4173 --strictPort
```

Open `http://127.0.0.1:4173`. The API window must still be running. This build writes `frontend\dist` and does not change the API.

## What the pages do

- **ค้นหา** — Hybrid is selected by default and calls `POST /hybrid-search`. Semantic calls `POST /search`. Dictionary and Compare call `POST /compare` with `mode` set to `dictionary` or `compare`.
- **เปรียบเทียบ** — Dictionary and Semantic results for one query, kept in separate columns.
- **การประเมิน** — saved charts and tables from `evaluation/reports/evaluation.json`. Loading this page does not embed a query and does not rewrite the report.

The search button stays disabled until the query box has text. Example chips fill that box.

## Eight example queries

Use Hybrid unless a step says otherwise. Quantities below are SQLite output exchanges in tonnes. Ranking order is the order recorded in `qa_logs/live_check.json` for these exact strings. An English year warning from the API is expected; the page shows the Thai translation.

1. `ผลผลิตมันสำปะหลังภาคเหนือปี 2566`  
   Supported. Eligible count 1. Answer `P-REG-SRC-06-CAS-NOR-2023`, northern cassava, 2023, **7,707,851 t**. The API warning says year 2566 was converted to 2023 CE.

2. `maize production in central Thailand 2022`  
   Supported. Eligible count 1. Answer `P-REG-SRC-05-MAI-CEN-2022`, central maize, 2022, **431,024 t**.

3. `ข้าวนาปรังปี 2565`  
   Supported. Eligible count 1. Rice, dry season, 2022. Answer `P-SRC-04-RIC-dry-2022`, **6,171,197 t**.

4. `มันสำปะหลังและข้าวโพด`  
   Supported. Eligible count 84, both cassava and maize. Top 5 includes both crops. The first recorded row is `P-REG-SRC-06-CAS-EAS-2019`, **3,415,285 t**, and the fifth is maize `P-SRC-01-MAI-all-2024`, **4,558,192 t**.

5. `ผลผลิตมากกว่า 1,000,000 ตัน`  
   Supported. No crop filter. The numeric condition is production greater than 1,000,000 t, and it is applied. Eligible count 81. The first recorded row is `P-SRC-01-SUG-all-2020`, **74,968,070 t**.

6. `มันสำปะหลังภาคใต้ปี 2566`  
   Supported as a production question, with an empty eligible set. Embedding is skipped. The page shows no substitute region. Southern cassava for 2023 is not in SQLite.

7. `carbon footprint of rice production`  
   Partially supported. Rice is recognized, and carbon footprint is not in the database. Eligible rice processes: 15. The listed tonnes are production context, with `answers_requested_measure` false. The first recorded context row is `P-SRC-04-RIC-wet-2021`, **26,806,578 t** of rice production, not a carbon value.

8. `ปริมาณปุ๋ยที่ใช้ปลูกมันสำปะหลัง`  
   Partially supported. Cassava is recognized, and fertilizer is not in the database. Eligible cassava processes: 42. The tonnes are production context, not fertilizer. The first recorded context row is `P-REG-SRC-06-CAS-EAS-2019`, **3,415,285 t**.

## Comparison demonstration

Open **เปรียบเทียบ**. The page starts with `ผลผลิตมันสำปะหลังภาคเหนือปี 2566`.

Submit it. Dictionary and Semantic each return `P-REG-SRC-06-CAS-NOR-2023` at **7,707,851 t**. Dictionary shows a match reason and a null similarity score. Semantic shows a cosine score and a null match reason. The two scores are not fused.

Then try `มันสำปะหลังและข้าวโพด`. The columns can differ: Dictionary keeps the course parser’s crop resolution, while Semantic does not treat that phrase as one structured crop filter. That difference is expected.

## Evaluation dashboard

Open **การประเมิน**.

Expect:

- The note that the page reads the saved report.
- Query count 61 and top-k 5.
- The sentence that Precision@5 uses the number of returned answer rows as its denominator.
- Cards for Dictionary, Semantic, and Hybrid, plus the Phase 6 subset of the original 45 queries.
- A bar chart of Precision@5 and Recall@5. Those bars are evaluation scores, not tonnes.
- A latency table whose caption says the numbers are the saved benchmark, not a live measurement.

Hybrid on the full set reads Precision@5 1.0, Recall@5 0.5849, Hit Rate@5 1.0, MRR 1.0, nDCG@5 1.0, multi-crop coverage 1.0, and numeric-condition correctness 1.0.

## Safe shutdown

Stop only the processes this demonstration started.

1. In the Vite window, press `Ctrl+C`.
2. In the API window, press `Ctrl+C`. Uvicorn should log `Shutting down` and `Application shutdown complete`.
3. If Qdrant should stop, and only this project’s container:

```powershell
Set-Location "D:\Final Project\final\search_service"
docker compose stop
```

`docker compose stop` keeps the volume `s1g14_qdrant_storage`. Start it later with `docker compose start`.

Do not run `docker compose down -v`. Do not stop containers by image or by a broad `docker stop`. Leave `cn230-db-1` and every unrelated container running.

`scripts/local_session.py` records and signals only the pids a verification script started. It is not required for this demonstration. Do not signal a pid that the script did not record.

## Tests

```powershell
Set-Location "D:\Final Project\final\search_service"
$env:PYTHONPATH = "D:\Final Project\final\search_service"
.\.venv\Scripts\python.exe -m pytest -q --tb=line
```

```powershell
Set-Location "D:\Final Project\final\search_service\frontend"
npm.cmd test
npm.cmd run build
```

The last accepted run was Python 122 passed and frontend 29 passed. `npm.cmd run build` passed, with the search bundle separate from `EvaluationPage` and `BarChart`.

## Troubleshooting

| What you see | What to check |
| --- | --- |
| Browser requests fail immediately | The API window is not running, or it was started after the page loaded. Reload after `/ready` succeeds. |
| `/ready` says the model is not ready | The cached ONNX snapshot is missing. Do not download a model as part of the demo. |
| `/ready` says Qdrant is unavailable | `docker compose ps` in this folder. Port 6333 must be `127.0.0.1`. |
| Vite prints `ECONNREFUSED 127.0.0.1:8000` | The UI started before the API was listening. Wait for `/ready`, then reload. |
| `npm.ps1` cannot be loaded | Use `npm.cmd` instead of `npm`. |
| Empty result for southern cassava 2566 | That combination is absent. An empty list is the correct result. |
| Fertilizer or carbon rows show tonnes | Those tonnes are production context. The page must not present them as the missing measurement. |
| Port 8000 or 5173 already in use | Stop the window that you started earlier with `Ctrl+C`. Do not kill unrelated listeners. |
