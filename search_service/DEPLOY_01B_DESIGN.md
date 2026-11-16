# DEPLOY-01B — Local PostgreSQL and pgvector design

This phase adds draft SQL, provider code, and tests inside `search_service`. It does not create a Neon project, connect to a remote database, upload rows or vectors, or change the running local search path.

Three layers are separate:

| Layer | State |
| --- | --- |
| Application code and unit tests | Written. Local SQLite and Qdrant behavior stays the default. |
| `migrations/postgres/*.sql` | Draft text. Nothing in the application executes these files. |
| A real PostgreSQL or Neon database | Not connected. `psycopg` is not installed. Cloud integration is not verified. |

## 1. Provider abstraction

`DATA_BACKEND` and `VECTOR_BACKEND` select one supported pair:

| Mode | Relational data | Vectors | When it is used |
| --- | --- | --- | --- |
| LOCAL | SQLite through `connect_readonly` | `QdrantStore` | Default. Both variables absent, or set to `sqlite` and `qdrant`. |
| CLOUD | `PostgresDataProvider` | `PgvectorStore` | Both variables set to `postgres` and `pgvector`, and `DATABASE_URL` is set. |

`build_service` keeps the existing ONNX embedder for both modes. It constructs `PostgresDataProvider` and `PgvectorStore` only for the cloud pair. Any other pair raises `ValueError` before a service object exists.

`SearchService` accepts an optional `relational` provider. When that argument is absent, catalog loading, hydration, and hybrid eligibility call the existing SQLite functions with `?` placeholders. When it is present, those calls use the provider and a missing database raises `postgres_unavailable`. Hybrid search still computes eligibility first and then ranks only those process ids.

The public catalog route and the evaluation runner still read SQLite. Moving those two readers is later work, after a staging database exists.

## 2. PostgreSQL schema

`migrations/postgres/001_schema.sql` is a non-executing draft translated from the canonical SQLite DDL. Column names for all 11 tables match `PRAGMA table_info`.

Tables, in load order: `crop`, `region`, `data_source`, `source_file`, `flow`, `province_region_map`, `process`, `exchange`, `crop_indicator`, `regional_aggregate`, `regional_contribution`.

Type mapping:

- SQLite `TEXT` becomes `text`.
- SQLite `INTEGER` identifiers and counts become `integer`.
- SQLite `REAL` quantities and indicator values become `double precision`, so the three fractional tonne values keep their binary values.
- `national_reconciled` and `used_in_formula` become `smallint` with `CHECK (... IN (0, 1))`.
- `process.region_code` stays nullable. The country-level check still requires `region_code IS NULL` when `spatial_level = 'country'` and `area = 'Thailand'`.

Primary keys, unique keys, and the foreign keys declared in SQLite are present in the draft. A read-only orphan audit of the canonical file reported zero broken references. Apply those foreign keys to loaded staging data only after `app.migration_audit` is run again on that staging database.

## 3. pgvector query strategy

`migrations/postgres/002_pgvector.sql` proposes `CREATE EXTENSION IF NOT EXISTS vector` and one `process_embeddings` table.

The table stores `process_id`, UUIDv5 `point_id`, `embedding vector(1024)`, model name, provider, revision, dimension, text hash, document schema version, and the payload fields used by the current filters: `crop_id`, `year_ce`, `season`, `spatial_level`, nullable `region_code`, and `source_id`. `process_id` references `process`. `vector_dimension` must be 1024.

No HNSW or IVFFlat index is created. At 105 vectors the adapter uses exact cosine distance:

```sql
ORDER BY embedding <=> %s::vector, process_id
LIMIT %s
```

Eligible hybrid ids are a bound array:

```sql
WHERE process_id = ANY(%s)
```

The API similarity field is `1 - cosine_distance`. The adapter calculates that subtraction in Python from the distance column. This score is the same definition pgvector documents for cosine similarity. It is not a claim that the number will match a Qdrant score bit for bit. Stored vectors are not normalized again during a future import.

`PgvectorStore.search_points` accepts the same arguments as `QdrantStore.search_points`. Filter fields are limited to the payload columns above. Values and id lists are driver parameters. A query vector must be 1024 finite numbers before any SQL is sent. A returned row whose revision, model, provider, or dimension differs from the quantized Xenova ONNX revision is rejected.

## 4. SQLite-to-PostgreSQL compatibility notes

- Placeholder `?` stays in `app/eligibility.py` and `app/records.py`. The PostgreSQL provider uses `%s`.
- Equality of source quantities is exact binary equality. The three non-integer Output quantities are `32882932.48`, `33851579.48`, and `33551336.65` tonnes, and they compare equal under Python `float` to the SQLite `REAL` values.
- Vector-score comparison is a different check. No score tolerance is accepted as a migration pass in this phase.
- Forty-five country processes keep `region_code` NULL. That is a valid state in the process check constraint.
- SQLite foreign-key enforcement was off in the inspected connection. The draft declares the keys. Staging must re-run the orphan audit before treating those constraints as enforced on loaded data.
- `audit_sqlite` binds its quantity lookup with `?`. `audit_embeddings` is written in PostgreSQL syntax, including `l2_norm`, and has not been executed on a server.

## 5. Dictionary adapter strategy

`D:\Final Project\Hee_M4\ch6 semantic search\src\semantic_search.py` is unchanged and remains the LOCAL dictionary implementation. `DictionarySearchAdapter` still calls that file's `search` function.

`PostgresDictionaryAdapter` loads the same module and calls its `parse_query`. The adapter then runs a separate statement with `%s` placeholders, the same joins, the same `BETWEEN` year predicate, `ORDER BY p.year_ce, p.area, p.source_id`, and `LIMIT`. Unsupported input and a missing crop return the same Thai messages and no rows. Explicit API filters are still ignored, with the same warning.

Parity was checked by executing that statement on the canonical SQLite file after replacing `%s` with `?`, and comparing process ids, quantities, counts, and messages with `module.search` for representative queries. That check does not prove the statement on a PostgreSQL server.

## 6. Configuration variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `DATA_BACKEND` | `sqlite` | `sqlite` or `postgres` |
| `VECTOR_BACKEND` | `qdrant` | `qdrant` or `pgvector` |
| `DATABASE_URL` | empty | Server-side PostgreSQL URL. Required only for the cloud pair. |

Supported pairs are `(sqlite, qdrant)` and `(postgres, pgvector)`. A cloud pair with an empty `DATABASE_URL` raises `ValueError` and does not open SQLite. The error text does not include the URL.

`DATABASE_URL` is a server setting. It must not be copied into a `VITE_` variable. This phase creates no credential and no `.env` entry.

The intended cloud database role has `SELECT` on the 11 relational tables and on `process_embeddings`. That role is a deployment design. It has not been created.

## 7. Migration validation checklist

`app.migration_audit.audit_sqlite` runs against the canonical file in read-only mode. `audit_embeddings` is the staging-only embedding check and was not executed.

Checked on the canonical SQLite file:

- All 11 table counts match the expected inventory, including 105 processes, 105 exchanges, 324 indicators, and 2,875 regional contributions.
- Process ids are unique.
- Output exchanges: 105.
- Orphan checks for every declared foreign key: 0.
- Country processes with NULL `region_code`: 45.
- The three fractional quantities match exactly.
- Northern cassava `P-REG-SRC-06-CAS-NOR-2023` remains `7707851.0` t.

Still required on a future staging database, before any pass mark:

- The same count, uniqueness, orphan, NULL-region, and exact-quantity checks through the PostgreSQL connection.
- 105 embedding rows, 105 distinct process ids, dimension 1024, revision `xenova-4de13258303883538bd53b696b452bf8099f0858-model_quantized.onnx`, model `BAAI/bge-m3`, and nonzero finite vectors.
- A separate, documented tolerance if Qdrant and pgvector scores are compared. Exact source equality and score tolerance stay different decisions.

This phase writes no raw-record export.

## 8. Known unverified behavior

- No PostgreSQL server was started or contacted.
- `psycopg` is not installed. A cloud connection without the driver raises `PostgreSQL driver is not installed`.
- `audit_embeddings` and the `l2_norm` expression were not executed.
- pgvector scores were not compared with Qdrant scores.
- Neon, Vercel, and a remote API host were not created.
- The public catalog route and `evaluate_search.py` still read SQLite.
- Live HTTP search during this phase ran only inside the existing pytest integration modules, through the in-process TestClient. Those modules use the cached ONNX model and the existing Qdrant collection. They do not exercise `PgvectorStore` on a server.

## 9. DEPLOY-01C staging prerequisites

Do not start DEPLOY-01C from this work. It needs a separate owner approval and then:

1. A staging Neon project and database, created only after that approval.
2. `psycopg` installed in `search_service\.venv`, not as a system-wide package.
3. A server-side `DATABASE_URL` with a `SELECT`-only role. The URL stays out of the frontend and out of logs.
4. Apply `001_schema.sql` and `002_pgvector.sql` to that empty staging database.
5. Re-run the orphan audit on the staged relational data before relying on the foreign keys.
6. Copy the 105 vectors only under a separate authorization. Preserve the stored floats, the UUIDv5 point ids, and the Xenova revision. Do not normalize them again and do not re-embed documents.
7. Run `audit_sqlite` expectations against staging, then `audit_embeddings`.
8. Compare dictionary, eligibility, hydration, and exact cosine ranking on staging. A Qdrant score difference needs its own recorded tolerance.

Until those steps pass, the cloud migration remains not verified.

## 10. Rollback

Local rollback is configuration only. Leave `DATA_BACKEND` and `VECTOR_BACKEND` unset, or set them to `sqlite` and `qdrant`. The API then uses the canonical SQLite file and the existing Qdrant collection. No schema was applied, so there is no cloud schema to undo in this phase.

If a later staging apply must be reversed, drop that staging database or its application schema. Do not delete the SQLite file, the Qdrant volume, or the ONNX cache to roll back a cloud experiment.

## DEPLOY-01D Linux container prerequisites

These are prerequisites for a later image, not work done here:

- Build a Linux image that serves FastAPI with one uvicorn worker.
- Bake the existing quantized Xenova ONNX cache into the image. Do not download a model on boot.
- Use `CPUExecutionProvider`. Omit the CUDA torch wheel from that image.
- Measure resident memory on the image before choosing a host size. Plan for 2 GB until that measurement exists. A 512 MB instance is too small for the 543 MB ONNX file plus the process.
- Keep Qdrant and SQLite available locally until the staging pgvector checks pass.
