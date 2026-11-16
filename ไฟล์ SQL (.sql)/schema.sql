PRAGMA foreign_keys = ON;
CREATE TABLE data_source (
  source_id TEXT PRIMARY KEY, title TEXT NOT NULL, agency TEXT NOT NULL,
  url TEXT NOT NULL, publication_year INTEGER
);
CREATE TABLE source_file (
  file_path TEXT PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES data_source(source_id),
  title TEXT NOT NULL
);
CREATE TABLE crop (
  crop_id TEXT PRIMARY KEY, crop_name TEXT NOT NULL UNIQUE
);
CREATE TABLE region (
  region_code TEXT PRIMARY KEY, region_name TEXT NOT NULL UNIQUE,
  mapping_version TEXT NOT NULL, mapping_url TEXT NOT NULL
);
CREATE TABLE province_region_map (
  province TEXT PRIMARY KEY, region_code TEXT NOT NULL REFERENCES region(region_code)
);
CREATE TABLE process (
  process_id TEXT PRIMARY KEY, crop_id TEXT NOT NULL REFERENCES crop(crop_id),
  source_id TEXT NOT NULL REFERENCES data_source(source_id),
  area TEXT NOT NULL,
  year_ce INTEGER NOT NULL, year_original TEXT NOT NULL,
  calendar TEXT NOT NULL, boundary TEXT NOT NULL,
  season TEXT NOT NULL, product_name TEXT NOT NULL,
  source_file TEXT NOT NULL REFERENCES source_file(file_path),
  spatial_level TEXT NOT NULL CHECK(spatial_level IN ('country','region')),
  region_code TEXT REFERENCES region(region_code),
  CHECK((spatial_level='country' AND area='Thailand' AND region_code IS NULL)
     OR (spatial_level='region' AND region_code IS NOT NULL)),
  UNIQUE(crop_id, source_id, year_ce, season, spatial_level, area)
);
CREATE TABLE flow (
  flow_id TEXT PRIMARY KEY, flow_name TEXT NOT NULL,
  flow_type TEXT NOT NULL CHECK(flow_type IN ('Product','Material','Energy','Water')),
  default_unit TEXT NOT NULL
);
CREATE TABLE exchange (
  exchange_id TEXT PRIMARY KEY, process_id TEXT NOT NULL REFERENCES process(process_id),
  flow_id TEXT NOT NULL REFERENCES flow(flow_id),
  source_id TEXT NOT NULL REFERENCES data_source(source_id),
  direction TEXT NOT NULL CHECK(direction IN ('Input','Output')),
  quantity REAL NOT NULL CHECK(quantity > 0), unit TEXT NOT NULL,
  source_row INTEGER, review_status TEXT NOT NULL CHECK(review_status = 'validated'),
  UNIQUE(process_id, flow_id, direction)
);
CREATE TABLE crop_indicator (
  indicator_id TEXT PRIMARY KEY, process_id TEXT NOT NULL REFERENCES process(process_id),
  source_id TEXT NOT NULL REFERENCES data_source(source_id),
  metric_code TEXT NOT NULL, value REAL NOT NULL CHECK(value > 0),
  unit TEXT NOT NULL, source_row INTEGER, moisture_basis TEXT,
  UNIQUE(process_id, metric_code)
);
CREATE TABLE regional_aggregate (
  process_id TEXT PRIMARY KEY REFERENCES process(process_id),
  reporting_provinces INTEGER NOT NULL CHECK(reporting_provinces>0),
  provinces_in_region INTEGER NOT NULL CHECK(provinces_in_region>0),
  national_reconciled INTEGER NOT NULL CHECK(national_reconciled IN (0,1)),
  method TEXT NOT NULL
);
CREATE TABLE regional_contribution (
  process_id TEXT NOT NULL REFERENCES regional_aggregate(process_id),
  metric_code TEXT NOT NULL, province TEXT NOT NULL REFERENCES province_region_map(province),
  source_file TEXT NOT NULL REFERENCES source_file(file_path),
  source_row INTEGER NOT NULL, raw_value REAL NOT NULL, raw_unit TEXT NOT NULL,
  used_in_formula INTEGER NOT NULL CHECK(used_in_formula IN (0,1)),
  PRIMARY KEY(process_id,metric_code,province)
);
CREATE INDEX ix_process_crop_year ON process(crop_id, year_ce);
CREATE INDEX ix_exchange_source ON exchange(source_id);
CREATE INDEX ix_indicator_metric ON crop_indicator(metric_code);
