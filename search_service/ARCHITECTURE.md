# Architecture

Local agricultural search for dataset S1-G14. Production quantities and process identity come from SQLite. Similarity is a separate local BGE-M3 rank over the process ids SQLite has already allowed.

## Boundaries

```text
Browser (React, Thai UI)
    |  HTTP only to FastAPI
    v
FastAPI  127.0.0.1:8000
    |                     \
    |                      \  read-only SQL
    v                       v
Qdrant 127.0.0.1:6333      SQLite  S1-G14_M3.sqlite
crop_process_bge_m3        105 process rows
105 x 1024 cosine
```

The browser never opens Qdrant or SQLite. The course dictionary script, the Neo4j import, and the CN230 MySQL container are outside this service. Dictionary search calls the course script in memory and does not edit it.

## SQLite source of truth

File: `D:\Final Project\Hee_M3\output\S1-G14_M3.sqlite`.

The service opens it read-only. Process id, crop, year, region, season, spatial level, source, and the output-exchange quantity are factual fields. Indicator values such as harvested area and yield per rai are also read from SQLite. A missing fertilizer, water, energy, or carbon measurement is absent. It is not stored or displayed as zero.

There are 105 process rows. Crops in the catalog are cassava `CAS`, maize `MAI`, rice `RIC`, and sugarcane `SUG`.

## Document indexing pipeline

Indexing already happened before this handover and is not part of startup.

`python -m app.index_sqlite --mode local-bge-m3` can dry-run or write the local collection. The dry-run does not load the model and does not write to Qdrant. The execute path embeds process documents with the local ONNX model and upserts `crop_process_bge_m3`. Point ids are UUIDv5. Stale points are reported and are not deleted by that command.

This handover does not run either mode. Do not re-index during a demonstration.

`crop_process_mock` is the earlier mock collection: 105 points, 1536 dimensions, cosine. The live API does not query it. `crop_process` is reserved for an approved OpenAI index and is not created. The real OpenAI command is `python -m app.index_sqlite --mode real --execute-real`. It refuses to start without `OPENAI_API_KEY`. It is not part of this release.

## Local BGE-M3 embedding

Query and document vectors use the cached Xenova quantized ONNX build of `BAAI/bge-m3` on CPU. The vector width is 1024. The model loads once per API process. Query inference is serialized. Startup readiness fails when the cached snapshot is missing; the service does not download weights.

Model initialization in the saved evaluation was 1930.796 ms and is timed separately from warm queries.

## Qdrant collection

Compose project `s1g14-search`, image `qdrant/qdrant:v1.20.0`, container `s1g14-qdrant`, volume `s1g14_qdrant_storage`, HTTP `127.0.0.1:6333`. gRPC port 6334 is not published. The Compose file does not mount SQLite and does not join the CN230 network.

Serving collection: `crop_process_bge_m3`, 105 points, size 1024, distance cosine.

Before a search, the service checks that this collection exists and has that shape. The check is cached in the process for 30 seconds, cleared on error, incompatibility, or restart, and forced by `GET /ready`. A cache hit contributes 0 ms to `timing_ms.collection_validation`. The cache does not change which ids are eligible and does not change scores. Hybrid times `search_points` separately from that check.

## FastAPI service

Package `app`. Uvicorn binds `127.0.0.1:8000`.

- `GET /health` reports liveness and does not load the model.
- `GET /ready` checks Qdrant, the collection shape, read-only SQLite, and the cached weights.
- `GET /catalog` lists crop, year, region, season, spatial level, and source values from SQLite.
- `POST /search` and `GET /search` run Semantic search.
- `POST /compare` runs Dictionary, Semantic, Compare, or Semantic-Fallback.
- `POST /hybrid-search` runs eligibility-first Hybrid search.
- `GET /evaluation-report` returns the saved JSON report and does not recompute it.

Unknown JSON fields are rejected. Invalid input returns HTTP 422. Qdrant, SQLite, or model failures return HTTP 503 without a stack trace or a filesystem path.

## React frontend

`frontend` is a Vite application. In development, `/api` is proxied to `http://127.0.0.1:8000`. The preview server needs `VITE_API_BASE` at build time because it does not use that proxy.

The search page holds the mode, the query, top-k, the example chips, and the structured filters. The evaluation route and the production chart are separate bundles. Loading and error text use `role="status"` and `role="alert"`. Focus uses the browser’s native tab order and a visible `:focus-visible` outline.

The evaluation page charts Precision@5 and Recall@5 from the saved report. Those chart values are scores, not production quantities.

## Query parsing

Dictionary and Semantic share the course parser’s crop, region, season, and year aliases. Buddhist Era years from 2500 through 2599 become Common Era by subtracting 543. An explicit filter overrides a value inferred from the text when that mode applies filters.

Hybrid planning keeps that parse and adds:

- more than one crop joined by `and`, `และ`, `กับ`, or `compare`, retained together when the question coordinates them
- a year range when the text states one
- a numeric comparison when the metric, operator, threshold, and SQLite unit are recognized

An explicit non-null filter replaces the inferred value and records a warning. Ambiguous crops, regions, seasons, years, or sources stay unfiltered and are described in `warnings`.

## Structured eligibility

Hybrid asks SQLite for every process id that matches the planned crops, year bounds, region, season, spatial level, source, and applied numeric condition. The SQL is parameterized. Production comparisons read `exchange` rows with direction `Output` and the requested unit. Other applied metrics read `crop_indicator`. Incompatible units are rejected instead of converted.

An empty eligible set returns no rows and does not call the embedding model.

## Semantic ranking

Semantic search embeds the query, applies its structured filters inside Qdrant, and takes the cosine nearest neighbors up to `top_k`.

Hybrid embeds the same query only after eligibility returns at least one id. `search_eligible_ids` then searches with a process-id filter limited to that set. The response field `ranking_method` is `eligibility-first-bge-m3`. Dictionary match reasons are not added to the cosine score. Reciprocal Rank Fusion is not implemented. It remains a later experiment and cannot decide availability or numeric eligibility.

## SQLite hydration

After ranking, each returned process id is loaded again from SQLite. The displayed production quantity, unit, crop, year, region, season, source, and indicators come from that read. A conflicting output exchange leaves the quantity empty rather than inventing a number. Cosine similarity is displayed as similarity, not as tonnes.

## Data availability

| Status | Meaning |
| --- | --- |
| `supported` | The question asks for a measure the database holds, normally production, and any structured scope can be applied. |
| `partially_supported` | The question names an unavailable measure and also a crop, place, season, or year. Matching production rows are returned as context with `answers_requested_measure` false. |
| `unsupported` | The question asks only for an unavailable measure, or Dictionary refuses the wording. The answer list is empty. |

Unavailable measures named by the service are fertilizer, energy input, water consumption, and carbon footprint. Context tonnes are the production output of the matching processes.

## How the four modes differ

- **Dictionary** executes the original course SQL. It is the exact audit path when its parser accepts the question. It does not apply the separate explicit filters used by the vector service, and it does not execute the Hybrid numeric comparison. Similarity is null.
- **Semantic** ranks the vector collection and can filter inside Qdrant. It does not first reduce the candidate set with the Hybrid eligibility query. A multi-crop phrase can therefore stay unfiltered.
- **Hybrid** reduces candidates in SQLite, then ranks only that set with BGE-M3. Both crops survive a coordinated question. A recognized tonne threshold is applied before embedding. Empty eligibility skips the model.
- **Compare** returns the Dictionary object and the Semantic object together. It does not merge their order and does not fill `score_comparison`.
- **Semantic-Fallback** is available on the CLI and on `POST /compare`. It is not a radio button on the search page. An empty Semantic result stays empty. Dictionary runs only when the Semantic infrastructure fails.

## Limitations

- 105 processes, four crops, and the years and regions present in this SQLite file.
- No authentication and no bind address other than localhost.
- CPU quantized ONNX only.
- Source-dependent quantities: a country total and a regional row can both be valid and must not be added together unless the question asks for that.
- Dictionary and Semantic can return different top-k sets for the same words. On the labeled comparison, 29 of 39 ranked nonempty queries differed. Mean Jaccard was 0.4679. Equal hit rates can still hide different process ids.
- The saved metrics describe this labeled set under the published denominator. They do not establish statistical superiority on other questions.
