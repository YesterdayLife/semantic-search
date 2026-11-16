# DEPLOY-01C.2A — Read-only connection verification

The connection string was not read from disk. No Neon session was opened. No cloud SQL was sent. `S1G14_STAGING_WRITE_APPROVED` is unset. `--write` was not used.

## 1. Environment configuration

FAIL. `search_service/.env` exists and was last written at 22:10:13 local time. Its size is 0 bytes. It contains no `STAGING_DATABASE_URL` and no other keys. The variable is also unset in the process, user, and machine environments.

The owner-supplied target remains unverified: project `s1g14-semantic-search`, branch `staging`, database `s1g14_staging`, AWS Singapore, pooling off, TLS required.

## 2. Git ignore verification

PASS for the ignore rule. `search_service/.gitignore` lists `.env` on its first line. This workspace has no `.git` directory, so `git check-ignore` cannot run and the file is not in a repository. The frontend ignore file does not need this secret; the secret belongs only in `search_service/.env`.

## 3. Secure environment loading method

PASS as a method. NOT VERIFIED against Neon because the file is empty.

`scripts/neon_staging_migrate.py` does not load `.env`. The API loader in `app/config.py` does, and only when the API process starts. It does not treat `STAGING_DATABASE_URL` as `DATABASE_URL`, and the local defaults stay SQLite and Qdrant.

The read-only probe is `scripts/neon_readonly_probe.py`. It reads `.env` inside the process, refuses localhost, a non-Neon host, a `-pooler` host, a missing TLS mode, and any database name other than `s1g14_staging`, then opens a read-only transaction. It prints catalog facts and withholds any error text that contains a URL. Windows psycopg is still blocked by Application Control, so the probe is intended to run in the existing Linux image `s1g14-search-onnx:local` (`sha256:1e1f9ce01a58ee1e9221e71b0b9302be86f8b1b924be307bab08cba1664577f9`) with the service directory mounted read-only. That container was not started.

## 4. Neon connection result

NOT VERIFIED. No connection was attempted. An empty URL is not a destination.

## 5. Database identity

NOT VERIFIED. `current_database()` was not queried.

## 6. PostgreSQL version

NOT VERIFIED. `server_version` was not queried.

## 7. TLS verification

NOT VERIFIED. No session existed, so `pg_stat_ssl` was not read. The URL's `sslmode` could not be checked.

## 8. Branch and project identity

NOT VERIFIED. The database name `s1g14_staging` would not by itself prove project `s1g14-semantic-search` or branch `staging`. No endpoint hostname, Neon project id, or branch id was available to compare. AWS Singapore was not confirmed from a hostname.

## 9. Application table inventory

NOT VERIFIED. No catalog query was run.

## 10. Database emptiness

NOT VERIFIED. No row counts were read. Nothing was deleted.

## 11. pgvector availability

NOT VERIFIED on the target. The published Neon catalog still lists `vector` 0.8.0 for PostgreSQL 16. The extension was not enabled and `pg_available_extensions` was not queried.

## 12. Role privileges

NOT VERIFIED. `current_user`, ownership, and schema privileges were not queried. `003_roles.draft.sql` remains unexecuted.

## 13. Migration runner safeguards

Source-only dry-run: PASS. Mode `dry-run`, writes 0, destination `NOT CONNECTED`, source ready, fingerprint match, 105 vectors.

| Safeguard | Result |
| --- | --- |
| Dry-run is the default | PASS |
| Remote write requires `--write` | PASS |
| Remote write requires `S1G14_STAGING_WRITE_APPROVED=1` | PASS |
| Known destination rows block a write | PASS |
| Schema hashes match the approved files | PASS |
| SQLite is opened read-only and Qdrant is scrolled | PASS |
| Credentials are redacted from runner errors | PASS |
| `DROP` statements in schema files are skipped | PASS |
| Project and branch are proven before a write | FAIL |
| Localhost and pooled endpoints are rejected | FAIL |
| Fingerprint and schema-hash mismatches stop the load | FAIL |

Schema hashes:

- `001_schema.sql` `e73c2f25342c3210e3ff793427dd763d234ba1d36f8d4e9d3054dece4f2fd17e`
- `002_pgvector.sql` `47afa1781c649e8e1e94026eb25e5401a0a759c2d55abc417bcfb26ed246861f`

## 14. Source integrity

PASS.

| Source | Result |
| --- | --- |
| SQLite SHA-256 | `9a80da4111beb44a00c5128c3ffdc10f1e6810825f10a838492981d8e3727808` |
| Vector fingerprint | `75aecb4737a45afa01a135af63eff05ff73953a9b4065f2d481ab1716f6f79ef` |
| Qdrant | green, 105 points, 1024 dimensions, cosine |
| Dictionary script | `8db66ee8ee675e43822e827375a2bba299eeed252063cc2a88f4a130e8e7cc60` |
| Evaluation report | `bf72a8ba7ae98365d4b1658d5bdbbd05b7d48f3c4d6db4f6771524b19720800e` |
| ONNX weights | `0826f8c1ab9edf1801db86c61919d4d108e8bfc0b809ec823ad366882ff0b77d` |
| Local backends | SQLite and Qdrant |

No source data was uploaded.

## 15. Remaining blockers

- Save `STAGING_DATABASE_URL` into `search_service/.env`. The verification process can read the file on disk; an unsaved editor buffer is invisible to it. Do not paste the string into chat.
- Repeat the Linux read-only probe after the file is non-empty.
- Prove the endpoint belongs to project `s1g14-semantic-search` and branch `staging`. The database name is not that proof.
- Close the runner gaps before any write: project and branch, direct endpoint, fingerprint, and schema hash.
- Keep the write approval flag unset until that proof is accepted.

## 16. Recommendation for DEPLOY-01C.2B

Do not start a write. The next session can repeat this read-only probe after `.env` contains the direct staging URL. 01C.2B stays a read-only identity check: database, user, server version, SSL, direct endpoint, project, branch, public tables, and available `vector` version.

## Classification

| Item | Result |
| --- | --- |
| `.env` exists | PASS |
| Git ignore rule | PASS |
| `STAGING_DATABASE_URL` configured | FAIL |
| URL targets `s1g14_staging` | NOT VERIFIED |
| TLS | NOT VERIFIED |
| No credential printed | PASS |
| Write approval unset | PASS |
| Secure loader prepared | PASS |
| Neon connection | NOT VERIFIED |
| Database identity | NOT VERIFIED |
| PostgreSQL version | NOT VERIFIED |
| Branch and project | NOT VERIFIED |
| Application tables | NOT VERIFIED |
| Emptiness | NOT VERIFIED |
| pgvector on the target | NOT VERIFIED |
| Role privileges | NOT VERIFIED |
| Source dry-run and integrity | PASS |
| Runner project and pre-write gates | FAIL |
| Cloud writes | PASS — none |

Final decision:

B. CONFIGURATION INCOMPLETE

STATUS: DEPLOY-01C.2A COMPLETE — AWAITING OWNER APPROVAL FOR NEON WRITE
