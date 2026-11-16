# Release notes — `v1.0.0-local`

Proposed identifier: `v1.0.0-local`.

This identifier is a local demonstration label. The annotated tag has not been created. Nothing in this release is deployed beyond `127.0.0.1`.

Date of this note: 2026-11-14.

## Scope

The search service in `D:\Final Project\final\search_service` answers agricultural production questions from the canonical SQLite database and the existing local BGE-M3 index. The browser talks only to the FastAPI service. It does not open Qdrant or SQLite itself.

No OpenAI API key is required. The reserved collection `crop_process` is absent.

## Implemented features

- Read-only SQLite access to `D:\Final Project\Hee_M3\output\S1-G14_M3.sqlite` (105 process records).
- Local BGE-M3 query embeddings through the cached quantized ONNX model on CPU.
- Qdrant 1.20.0 collection `crop_process_bge_m3`: 105 points, 1024 dimensions, cosine distance.
- FastAPI on `127.0.0.1:8000` with `/health`, `/ready`, `/catalog`, `/search`, `/compare`, `/hybrid-search`, and `/evaluation-report`.
- React, TypeScript, and Vite interface on `127.0.0.1:5173`, Thai by default.
- Saved evaluation dashboard. Opening it reads `evaluation/reports/evaluation.json` and does not rerun the benchmark.
- Separate collection-validation timing. A process-local cache records a compatible collection for 30 seconds. `GET /ready` forces a fresh check. The cache is not used for ranking or scores.
- Frontend code splitting: the evaluation page and the production chart load apart from the search page.
- Visible `:focus-visible` outlines and native radios, buttons, selects, and checkboxes.

## Search modes

| Mode | Where it runs | What it does |
| --- | --- | --- |
| Dictionary | Search page, Compare page, `POST /compare` with `mode=dictionary`, CLI | Course parser and SQL. Rows carry a match reason. Similarity is null. |
| Semantic | Search page, `POST /search` and `GET /search` | BGE-M3 cosine over `crop_process_bge_m3`, with structured filters applied in Qdrant. Quantities come from SQLite. |
| Hybrid | Search page default, `POST /hybrid-search`, CLI | SQLite eligibility first, then BGE-M3 ranking of only those process ids. Ranking method: `eligibility-first-bge-m3`. |
| Compare | Compare page, `POST /compare` with `mode=compare` | Dictionary and Semantic side by side. `score_comparison` stays null. |
| Semantic-Fallback | CLI and `POST /compare` with `mode=semantic-fallback` | BGE-M3 first, including an empty result. Dictionary is called only after an infrastructure failure. |

Hybrid does not use Reciprocal Rank Fusion and does not add dictionary match reasons to cosine similarity.

## Performance and evaluation

Official figures are the saved report `evaluation/reports/evaluation.json` (SHA-256 `BF72A8BA7AE98365D4B1658D5BDBBD05B7D48F3C4D6DB4F6771524B19720800E`). The labeled set has 61 queries and top-k 5. Precision uses the number of returned answer rows, at most k, as its denominator.

Aggregate results on the 39 ranked queries:

| Mode | Precision@5 | Recall@5 | Hit Rate@5 | MRR | nDCG@5 | Multi-crop coverage | Numeric-condition correctness |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Dictionary | 0.8923 | 0.5251 | 1.0 | 0.9402 | 0.8976 | 0.6 | 0.0 |
| Semantic | 0.8641 | 0.5166 | 0.9744 | 0.909 | 0.8746 | 0.6 | 0.0 |
| Hybrid | 1.0 | 0.5849 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 |

Saved warm latency (5 repetitions, 2 warm-up queries, 15 warm samples), separate from model initialization of 1930.796 ms:

| Segment | Mean | Median | p95 |
| --- | ---: | ---: | ---: |
| Dictionary | 0.545 ms | 0.676 ms | 1.026 ms |
| Semantic | 188.975 ms | 184.015 ms | 216.253 ms |
| Hybrid | 115.719 ms | 177.434 ms | 185.573 ms |
| Compare | 189.983 ms | 180.817 ms | 225.686 ms |

The Hybrid warm minimum in that report is 2.09 ms because an empty eligible set skips embedding. The median therefore mixes skipped and embedded queries. These figures describe the labeled set on this machine. They are not a claim that Hybrid is faster for every question, and they are not a statistical ranking of the systems.

A later localhost HTTP sample is stored in `qa_logs/fix01b/bench.json`. It is not a replacement for the evaluation report. On that sample, warm end-to-end medians were Dictionary 7.001 ms, Semantic 60.344 ms, Hybrid 62.563 ms, and Compare 45.530 ms.

The recorded Hybrid answer for `ผลผลิตมันสำปะหลังภาคเหนือปี 2566` is process `P-REG-SRC-06-CAS-NOR-2023`, production quantity 7,707,851 t. That quantity is the SQLite output exchange for that process.

## Compatibility

- Windows PowerShell, this machine.
- Python 3.14.7 virtual environment at `search_service\.venv`.
- Node.js with npm. If `npm.ps1` is blocked, use `npm.cmd`.
- Docker, for the existing Qdrant container only.
- Qdrant image `qdrant/qdrant:v1.20.0`, already populated. This release does not re-index.
- Cached Xenova quantized ONNX weights under `search_service/.cache/huggingface`. `GET /ready` fails when that snapshot is missing. The service does not download a model.
- Canonical SQLite file outside this folder, opened read-only.

## Known limitations

- The dataset contains 105 process records.
- Fertilizer, water, energy, and carbon footprint are not in the validated database. Related production rows are context. Those measurements are not reported as zero.
- Dictionary SQL does not apply the explicit filters that Semantic and Hybrid can apply.
- Generic yield and kilogram thresholds can remain unapplied when the unit is not an executable SQLite unit.
- Cosine similarity is not a production quantity.
- The service binds to localhost only and has no authentication.
- Inference uses the quantized ONNX model on CPU. PyTorch GPU inference is not the serving path.
- Production quantities are the values published by each source. Two sources can describe different geographies for the same crop and year.
- Evaluation numbers apply to the 61 labeled queries and the stated methodology.
- The seven keyboard checks were confirmed manually by the owner. They were not operated by the agent.

## Local-only deployment

Supported addresses:

- Qdrant: `http://127.0.0.1:6333`
- API: `http://127.0.0.1:8000`
- Development UI: `http://127.0.0.1:5173`
- Optional preview UI: `http://127.0.0.1:4173`

Do not publish ports 6333, 8000, 5173, or 4173 beyond this machine. Do not run `docker compose down -v`. That flag deletes `s1g14_qdrant_storage`.
