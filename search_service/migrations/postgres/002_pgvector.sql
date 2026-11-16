-- DEPLOY-01B pgvector draft. Do not execute this file in this phase.
-- No HNSW or IVFFlat index is created. One hundred five vectors are ranked
-- by exact cosine distance. Do not normalize stored vectors again on import.
--
-- Similarity returned to the API is 1 - (embedding <=> query).
-- That value is not promised to be bit-identical to a Qdrant score.
-- Tie break is process_id ascending after the distance.
--
-- Application code sends the query vector and the limit as parameters.
-- The statements below show the shape; they are not a runnable copy-paste
-- of a literal vector.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE process_embeddings (
  process_id text PRIMARY KEY REFERENCES process (process_id),
  point_id uuid UNIQUE NOT NULL,
  embedding vector(1024) NOT NULL,
  embedding_model text NOT NULL,
  embedding_provider text NOT NULL,
  model_revision text NOT NULL,
  vector_dimension integer NOT NULL CHECK (vector_dimension = 1024),
  text_hash text NOT NULL,
  document_schema_version text NOT NULL,
  crop_id text NOT NULL,
  year_ce integer NOT NULL,
  season text NOT NULL,
  spatial_level text NOT NULL,
  region_code text,
  source_id text NOT NULL
);

-- Exact ranking of an eligible id list. %s placeholders are bound by the
-- driver. The first parameter is the query vector text, the second is the
-- eligible process_id array, and the third is the limit.
--
-- SELECT
--   process_id,
--   point_id::text,
--   (embedding <=> %s::vector) AS cosine_distance
-- FROM process_embeddings
-- WHERE process_id = ANY(%s)
-- ORDER BY embedding <=> %s::vector, process_id
-- LIMIT %s;
