# DEPLOY-01C.2D — Independent Neon data and search validation

Validation was read-only. The migration command was not run. `S1G14_STAGING_WRITE_APPROVED` was not set. No `CREATE`, `ALTER`, `INSERT`, `UPDATE`, `DELETE`, `DROP`, `TRUNCATE`, `GRANT`, or `CREATE EXTENSION` was sent. The staging URL stayed in the private `.env` and was not printed.

Every Neon session used a direct TLS connection, `default_transaction_read_only=on`, and `transaction_read_only=on`. The session reported zero writes.

## 1. Verified staging identity

PASS.

- Project `ancient-frog-45954579`
- Branch `br-flat-bird-b34at9i8`
- Endpoint `ep-orange-voice-b3m1fhia`
- Database `s1g14_staging`
- Role `neondb_owner`
- Client TLS in use
- Direct endpoint, channel binding required, pooling off

Production was not connected.

## 2. PostgreSQL and pgvector versions

PASS. PostgreSQL `18.7 (a21afb5)`. Installed pgvector `0.8.7`. The embedding column type is `vector(1024)`.

## 3. Schema audit results

PASS for names, types, keys, and stored nulls. One catalog-flag difference is recorded below.

Column names match SQLite on all 11 relational tables, in the same order. PostgreSQL types match the approved translation: `text`, `integer`, `double precision`, and `smallint` for the two flag columns. There were no type mismatches.

Constraints: 12 primary keys, 16 foreign keys, 6 unique constraints, 12 checks. No unexpected public tables. The only added table is `process_embeddings`.

SQLite's table pragma reports 10 primary-key columns as nullable, while PostgreSQL primary keys are not nullable. The columns are `crop.crop_id`, `region.region_code`, `data_source.source_id`, `source_file.file_path`, `flow.flow_id`, `province_region_map.province`, `process.process_id`, `exchange.exchange_id`, `crop_indicator.indicator_id`, and `regional_aggregate.process_id`. The row comparison found no nulls in those columns. This is the catalog difference between SQLite's pragma and a PostgreSQL primary key.

KNOWN BASELINE DIFFERENCE for those 10 catalog flags. Stored NULL handling is PASS.

## 4. All relational row comparisons

PASS. Every relational row matched SQLite on its stable key. Mismatched tables: none. Maximum numeric absolute difference: `0.0`.

| Table | Rows |
| --- | ---: |
| crop | 4 |
| region | 6 |
| data_source | 5 |
| source_file | 8 |
| flow | 4 |
| province_region_map | 77 |
| process | 105 |
| exchange | 105 |
| crop_indicator | 324 |
| regional_aggregate | 60 |
| regional_contribution | 2875 |

Total: 3,573. The three fractional output quantities matched exactly. Country processes with a null region: 45.

## 5. All vector comparisons

PASS. 105 stored embeddings, 105 source points, 0 missing, 0 association mismatches, 0 bad dimensions. Maximum component absolute difference against Qdrant: `0.0`. Processes without an embedding: 0. Embeddings without a process: 0.

## 6. Dictionary parity results

PASS, with the known order tie.

The course parser and the course `ORDER BY p.year_ce, p.area, p.source_id` were used unchanged. SQLite used the course `search` function. PostgreSQL used the same parser and the same statement shape.

65 queries ran: all 61 saved queries plus 4 focus queries that were not in that file. 62 matched exactly, including parsed constraints, process-id order, counts, and quantities. 3 differed only by order.

## 7. Semantic parity results

PASS. 61 of 61 saved queries, plus the 4 extra focus queries, matched Qdrant and pgvector on top-5 process ids, rank, metadata, quantities, and empty results. Every similarity gap was inside `1e-5`. The largest gap retained for the focus queries was `2.885e-7`.

Eligibility filters were included. An explicit dry-season rice 2022 filter returned the same one process on both sides, with a score gap of `1.72e-7`.

## 8. Hybrid parity results

PASS. The same 65 queries matched on eligible behavior, ranked ids, quantities, metadata, and empty results. Score gaps were inside `1e-5`. No fusion or weight change was introduced.

Focus results:

- Cassava, Northern region, 2023: both sides returned 1 process.
- Dry-season rice 2022, as an explicit semantic filter: both sides returned 1 process.
- Central maize 2022: both sides returned 1 process.
- Southern cassava 2023: dictionary, semantic, and hybrid all returned 0 on both sides.
- Production above 1,000,000 t: both hybrid sides returned the same 5 processes. The score gap was `1.99e-7`.
- Carbon-footprint rice: both dictionaries returned the unsupported empty result. Both semantic and hybrid sides returned the same 5 rows.

The dictionary query `ผลผลิตมากกว่า 1000000 ตัน` returns no rows on both sides because the course parser has no crop. Semantic and hybrid still return ranked rows. That split is the same on SQLite and Neon.

## 9. Compare Mode results

PASS, except the same dictionary tie.

Compare mode ran for all 65 queries through the existing dispatch and comparison view. Semantic sides matched on all 65. Response keys matched, and `score_comparison` stayed null on both sides. The 3 dictionary order ties are the only compare differences.

## 10. 61-query evaluation matrix

All 61 saved queries were executed in dictionary, semantic, hybrid, and compare mode.

| Mode | Saved queries | PASS | KNOWN BASELINE DIFFERENCE | FAIL | NOT VERIFIED |
| --- | ---: | ---: | ---: | ---: | ---: |
| Dictionary | 61 | 58 | 3 | 0 | 0 |
| Semantic | 61 | 61 | 0 | 0 | 0 |
| Hybrid | 61 | 61 | 0 | 0 | 0 |
| Compare | 61 | 58 | 3 | 0 | 0 |

The 3 known rows are Q03 `ข้าว`, Q21 `rice in Thailand`, and Q47 `ผลผลิตข้าวกับอ้อย`. SQLite ordered `P-SRC-04-RIC-wet-2020` before `P-SRC-04-RIC-dry-2020`. PostgreSQL ordered the dry row first. The result set, quantities, and parsed constraints were the same. The course sort does not include season, so those two 2020 rice rows are tied.

Four additional focus queries were also executed in every mode and passed.

## 11. API contract verification

PASS for the checked contract. The FastAPI app ran in-process through its test client. It was not bound to a public interface. The providers were PostgreSQL and pgvector, using the local ONNX model. OpenAI was not called.

| Request | Result |
| --- | --- |
| `GET /health` | 200 |
| `GET /ready` | 200 |
| `GET /catalog` | 200 |
| `GET /evaluation-report` | 200 |
| `POST /search` | 200 |
| `POST /compare` | 200 |
| `POST /hybrid-search` | 200 |
| `POST /search` with a blank query | 422 |
| `POST /hybrid-search` for the large-production query | 200 |

No response contained the database URL, a password, or a connection string. The 61-query matrix was executed through the same service functions the routes call. It was not repeated as 61 separate HTTP requests.

The ready payload still uses the existing field names `sqlite` and `qdrant` when the selected backend is PostgreSQL. That label is existing response text, and the endpoint returned ready.

## 12. Known baseline differences

- The 2020 wet/dry rice dictionary order, on Q03, Q21, and Q47, and in compare mode for those queries.
- SQLite pragma nullability on the 10 primary-key columns listed above. Stored values still match.
- Dictionary search does not apply the numeric production phrase unless a crop is parsed. Semantic and hybrid do. Both databases behave the same way.
- Ready response field names remain `sqlite` and `qdrant`.

## 13. New regressions

None. No search comparison returned FAIL.

## 14. Security and role readiness

The draft `migrations/postgres/003_roles.draft.sql` was reviewed and not executed.

`s1g14_staging_app` and `s1g14_staging_migrator` do not exist. The only login used here was `neondb_owner`, and that role can insert, update, and delete. It must not remain the runtime role.

The draft is sufficient for a later, separately approved role phase:

- `CONNECT` on `s1g14_staging`
- `USAGE` on schema `public`
- `SELECT` on all current application tables
- `REVOKE` of `INSERT`, `UPDATE`, `DELETE`, `TRUNCATE`, `REFERENCES`, `TRIGGER`, and schema `CREATE`
- `default_transaction_read_only=on` and a statement timeout on the role
- No membership in the migration role

`SELECT` is enough for the current backend. Catalog, dictionary, eligibility, hydration, and pgvector ranking are all `SELECT` statements. The cosine operator `<=>` is executable by `PUBLIC`, so a select-only role can rank vectors. The backend does not need `CREATE`, `INSERT`, `UPDATE`, `DELETE`, `DROP`, or `ALTER` for these read routes.

Credentials should stay outside the repository and outside the frontend. The runtime process should receive a select-only URL, while `STAGING_DATABASE_URL` for `neondb_owner` is removed from the application configuration after that role exists. This phase did not create the role or change `.env`.

The missing select-only role is a deployment blocker. It is the next approved setup step, not a data defect.

## 15. Python test results

PASS. 208 passed.

## 16. Frontend test results

PASS. 29 passed. `tsc -b` and the production build passed. Bundle names are unchanged: `index-VZ4YOCg0.js`, `index-BvubhxAm.css`, `ProductionChart-Czm7FBFm.js`, `EvaluationPage-BTWqH6K8.js`, and `BarChart-BqrT--3E.js`.

## 17. Source integrity checks

PASS.

- SQLite checksum matches `9a80da4111beb44a00c5128c3ffdc10f1e6810825f10a838492981d8e3727808`
- Qdrant fingerprint matches `75aecb4737a45afa01a135af63eff05ff73953a9b4065f2d481ab1716f6f79ef`, count 105
- Both approved schema hashes match
- ONNX weight hash matches
- Course dictionary hash matches
- Local defaults remain SQLite and Qdrant
- The course dictionary file was not edited
- Neon production was not opened

## 18. Files created or modified

Created: `search_service/DEPLOY_01C2D_REPORT.md`.

No application, schema, dictionary, environment, or test file was modified. Temporary validation scripts were kept outside the repository and removed.

## 19. Remaining blockers

- There is still no select-only application role. Runtime use of `neondb_owner` can write.
- The backend has not been deployed, and the local default is still SQLite plus Qdrant.
- The ready response labels were not renamed. They are existing contract text.

There is no data, vector, or search-parity blocker.

## 20. Readiness for least-privilege application role setup and backend deployment

The staging copy matches the canonical SQLite and Qdrant data. Dictionary, semantic, hybrid, and compare behavior match, with the known rice order tie preserved. The API contract checks passed on a private in-process client.

The next step is a separate owner approval to create `s1g14_staging_app` from the reviewed draft, grant it select-only rights, and point a future backend at that role. Deployment and production cutover are not authorized by this validation.

A. NEON STAGING VALIDATED — READY FOR APPLICATION ROLE PREPARATION

STATUS: DEPLOY-01C.2D COMPLETE — AWAITING OWNER REVIEW
