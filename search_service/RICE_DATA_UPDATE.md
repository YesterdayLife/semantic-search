# Rice regional coverage update — 16 November 2026

The configured local SQLite catalog now includes OAE wet-season and dry-season
rice in all six project regions for 2019–2024 (B.E. 2562–2567). Southern Thailand
has 12 rice records, one for each season/year. Cassava and feed maize still have
no southern records in their source series; absence is not converted to zero.
Sugarcane remains national-only. This is complete seasonal-rice coverage within
the project's existing period, not a claim of complete coverage of every crop.

## Active database and results

- SQLite: `D:\Final Project\Hee_M3\output\S1-G14_M3.sqlite`
- Local API: `http://127.0.0.1:8000`
- Semantic index: Qdrant `crop_process_bge_m3`, 180 points.
- Data backend remains SQLite/Qdrant. No cloud or PostgreSQL copy was changed.

| Table | Before | After |
|---|---:|---:|
| process | 105 | 180 |
| exchange | 105 | 180 |
| crop_indicator | 324 | 624 |
| regional_aggregate | 60 | 132 |
| regional_contribution | 2,875 | 7,320 |
| source_file | 8 | 12 |

There are 72 new regional rice records and 3 missing national records were
filled: wet rice 2019 and 2024, dry rice 2019. The existing SRC-04 national rice
records are refreshed from the same archived source series. Other sources and
crops are preserved. Original crop-year labels (e.g. `2566/67`) are retained.

## Official sources and calculation

- [OAE wet rice series](https://catalog.oae.go.th/dataset/wet_rice_product):
  national and province CSV resources.
- [OAE dry rice series](https://catalog.oae.go.th/dataset/dry_rice_product):
  national and province XLSX resources.

The unmodified downloads, resource URLs, SHA-256 checksums and download times
are in `data/oae_rice_2026-11-16/manifest.json`. Each database `source_file` key
is the original resource URL; the manifest identifies its archived local file.
Province contributions retain the original CSV line / XLSX worksheet row.

The existing 77-province, six-region mapping is reused; OAE's four-region totals
are not mixed with the project's six-region definition. Production and areas
are summed by province. Regional yields are calculated as total tonnes × 1,000
divided by the relevant total area in rai, not averaged from provincial yields.
All 36 season/year/measure sums reconcile exactly to the national source:
12 season-years × production, planted area, harvested area.

Examples verified through semantic, hybrid and dictionary search:

- `ข้าวนาปีภาคใต้ปี 2566`: 274,135 tonnes.
- `ข้าวนาปรังภาคใต้ปี 2567`: 44,427 tonnes.
- `ข้าวนาปีภาคใต้ปี 2562`: 326,595 tonnes.
- `มันสำปะหลังภาคใต้ปี 2566`: no results, with no substitute or fabricated zero.

## Reproduce and validate

From `search_service`, review a dry run first:

```powershell
python scripts/update_rice_regions.py --database "D:\Final Project\Hee_M3\output\S1-G14_M3.sqlite"
```

Add `--apply --report artifacts/rice_update/applied_report.json` to apply.
The importer checks checksums, units, duplicate keys, province mapping,
season/year/region coverage and national reconciliation before writing.
It creates a SQLite backup, then applies all relational changes in one
transaction, checking integrity and foreign keys before commit. Rerunning the
same source import does not add duplicates.

After any catalog update, refresh the local semantic index using
`python -m app.index_sqlite --mode local-bge-m3 --execute-local`, then restart
the API. The original Hee_M3 build script creates the earlier catalog; if it
is rerun, apply this importer and refresh the index afterward.

Runtime catalog validation accepts nonempty catalogs of changing size, while
readiness still rejects a vector count that differs from the relational count.
The API's independent maximum `top_k=105` request limit is unchanged.

## Backups and evidence

- Database backup: `artifacts/database_backups/S1-G14_M3-20261116T064933192946Z.sqlite`
- Original 105 semantic vectors: `artifacts/rice_update/qdrant_before.json`
- Applied counts/reconciliation: `artifacts/rice_update/applied_report.json`
- Integrity and preservation checks: `artifacts/rice_update/data_validation.json`
- Index report: `artifacts/rice_update/index_report.json` (75 new, 4 changed,
  101 unchanged; no stale IDs).
- Actual API responses: `artifacts/rice_update/live_verification.json`.
- Test logs: `artifacts/rice_update/pytest_current.txt` and `pytest_full.txt`.

Final full regression run: **214 passed**, including real local-model/API
checks, idempotent imports, exact reconciliation, transaction rollback and
rejection of a stale vector count. SQLite integrity is `ok`, with zero foreign
key violations. Non-target process, exchange and indicator rows are unchanged.
Existing national rice production totals were unchanged; the update adds the
missing coverage and refreshes its source references and crop-year labels.

The displayed evaluation report is regenerated for 180 records, with the old
JSON/Markdown retained as `artifacts/rice_update/evaluation_before.*`. At fixed
top-5, Phase 6 subset recall changes from 0.6486 to 0.5446 because rice queries
now have more relevant records; subset precision remains 1.0. Historical report
numbers must not be presented as measurements of the expanded catalog.

Historical deployment reports and cloud migration approval hashes describe the
old 105-record snapshot. They are not new migration approvals. Historical
migration tests use frozen fixtures under `tests/fixtures`; production migration
guards have not been relaxed. The mock vector collection remains the original
105-record test collection and is not the live semantic search index.
