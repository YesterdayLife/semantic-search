-- DEPLOY-01B schema draft. Do not execute this file in this phase.
-- It is not applied to Neon, to SQLite, or to any local database by the application.
--
-- Translated from the canonical SQLite DDL inspected on 2026-11-15.
-- A read-only orphan audit of that file found zero broken references.
-- Re-run app.migration_audit against the staging database before applying
-- these foreign keys to loaded data.
--
-- REAL columns become double precision so the three fractional tonne
-- quantities keep their binary values. Flag columns that are only 0 or 1
-- become smallint. region_code stays nullable for the 45 country processes.

CREATE TABLE crop (
  crop_id text PRIMARY KEY,
  crop_name text NOT NULL UNIQUE
);

CREATE TABLE region (
  region_code text PRIMARY KEY,
  region_name text NOT NULL UNIQUE,
  mapping_version text NOT NULL,
  mapping_url text NOT NULL
);

CREATE TABLE data_source (
  source_id text PRIMARY KEY,
  title text NOT NULL,
  agency text NOT NULL,
  url text NOT NULL,
  publication_year integer
);

CREATE TABLE source_file (
  file_path text PRIMARY KEY,
  source_id text NOT NULL REFERENCES data_source (source_id),
  title text NOT NULL
);

CREATE TABLE flow (
  flow_id text PRIMARY KEY,
  flow_name text NOT NULL,
  flow_type text NOT NULL CHECK (flow_type IN ('Product', 'Material', 'Energy', 'Water')),
  default_unit text NOT NULL
);

CREATE TABLE province_region_map (
  province text PRIMARY KEY,
  region_code text NOT NULL REFERENCES region (region_code)
);

CREATE TABLE process (
  process_id text PRIMARY KEY,
  crop_id text NOT NULL REFERENCES crop (crop_id),
  source_id text NOT NULL REFERENCES data_source (source_id),
  area text NOT NULL,
  year_ce integer NOT NULL,
  year_original text NOT NULL,
  calendar text NOT NULL,
  boundary text NOT NULL,
  season text NOT NULL,
  product_name text NOT NULL,
  source_file text NOT NULL REFERENCES source_file (file_path),
  spatial_level text NOT NULL CHECK (spatial_level IN ('country', 'region')),
  region_code text REFERENCES region (region_code),
  CHECK (
    (spatial_level = 'country' AND area = 'Thailand' AND region_code IS NULL)
    OR (spatial_level = 'region' AND region_code IS NOT NULL)
  ),
  UNIQUE (crop_id, source_id, year_ce, season, spatial_level, area)
);

CREATE TABLE exchange (
  exchange_id text PRIMARY KEY,
  process_id text NOT NULL REFERENCES process (process_id),
  flow_id text NOT NULL REFERENCES flow (flow_id),
  source_id text NOT NULL REFERENCES data_source (source_id),
  direction text NOT NULL CHECK (direction IN ('Input', 'Output')),
  quantity double precision NOT NULL CHECK (quantity > 0),
  unit text NOT NULL,
  source_row integer,
  review_status text NOT NULL CHECK (review_status = 'validated'),
  UNIQUE (process_id, flow_id, direction)
);

CREATE TABLE crop_indicator (
  indicator_id text PRIMARY KEY,
  process_id text NOT NULL REFERENCES process (process_id),
  source_id text NOT NULL REFERENCES data_source (source_id),
  metric_code text NOT NULL,
  value double precision NOT NULL CHECK (value > 0),
  unit text NOT NULL,
  source_row integer,
  moisture_basis text,
  UNIQUE (process_id, metric_code)
);

CREATE TABLE regional_aggregate (
  process_id text PRIMARY KEY REFERENCES process (process_id),
  reporting_provinces integer NOT NULL CHECK (reporting_provinces > 0),
  provinces_in_region integer NOT NULL CHECK (provinces_in_region > 0),
  national_reconciled smallint NOT NULL CHECK (national_reconciled IN (0, 1)),
  method text NOT NULL
);

CREATE TABLE regional_contribution (
  process_id text NOT NULL REFERENCES regional_aggregate (process_id),
  metric_code text NOT NULL,
  province text NOT NULL REFERENCES province_region_map (province),
  source_file text NOT NULL REFERENCES source_file (file_path),
  source_row integer NOT NULL,
  raw_value double precision NOT NULL,
  raw_unit text NOT NULL,
  used_in_formula smallint NOT NULL CHECK (used_in_formula IN (0, 1)),
  PRIMARY KEY (process_id, metric_code, province)
);

CREATE INDEX ix_exchange_source ON exchange (source_id);
CREATE INDEX ix_indicator_metric ON crop_indicator (metric_code);
CREATE INDEX ix_process_crop_year ON process (crop_id, year_ce);
