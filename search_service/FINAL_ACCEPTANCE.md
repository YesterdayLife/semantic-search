# Final acceptance — local demonstration

Proposed identifier: `v1.0.0-local`.

The tag has not been created. This record accepts the service for a local demonstration. It does not accept a public deployment.

Acceptance date: 2026-11-14.

## Recommendation

**A. READY FOR FINAL ACCEPTANCE — LOCAL DEMONSTRATION ONLY**

## Verification record

| Check | Result | Evidence |
| --- | --- | --- |
| Python tests | 122/122 PASS | `pytest -q --tb=line` in `search_service`, 122 passed in 48.41s on 2026-11-14 |
| Frontend tests | 29/29 PASS | `vitest run`, 29 passed in 8.47s on 2026-11-14 |
| Production build | PASS | `tsc -b && vite build`, built in 718 ms, no chunk-size warning |
| Browser search and comparison | PASS | Owner decision approving handover after manual use of Search and Compare |
| SQLite integrity | PASS | SHA-256 `9A80DA4111BEB44A00C5128C3FFDC10F1E6810825F10A838492981D8E3727808`, 921600 bytes |
| Qdrant integrity | PASS | `crop_process_bge_m3` 105 / 1024 / Cosine; `crop_process_mock` 105 / 1536 / Cosine; `crop_process` absent |
| Evaluation report unchanged | PASS | `evaluation/reports/evaluation.json` SHA-256 `BF72A8BA7AE98365D4B1658D5BDBBD05B7D48F3C4D6DB4F6771524B19720800E` |
| Manual keyboard verification | 7/7 PASS | Owner-reported. See the next section. |
| OpenAI | Not used | No API key is required. Collection `crop_process` is not present. |

Reconfirmed while writing this handover, without re-indexing and without an embedding call: the SQLite checksum, the Qdrant collection metadata, and the evaluation-report checksum match the values above.

## Keyboard checks

These seven checks are **owner-reported manual verification**. They are not Agent-operated keyboard tests. An earlier agent session could not keep the application window in the foreground and therefore left live keyboard traversal as NOT VERIFIED. The owner then verified the checks by hand and approved this handover.

| # | Check | Result |
| --- | --- | --- |
| 1 | Tab focus order | PASS |
| 2 | Shift+Tab reverse navigation | PASS |
| 3 | Search mode keyboard selection | PASS |
| 4 | Enter-to-search | PASS |
| 5 | Keyboard filter interaction | PASS |
| 6 | Compare and Evaluation keyboard navigation | PASS |
| 7 | No keyboard trap and visible focus | PASS |

## Hybrid result retained from verification

`ผลผลิตมันสำปะหลังภาคเหนือปี 2566` returns `P-REG-SRC-06-CAS-NOR-2023` with SQLite production quantity 7,707,851 t. Semantic and Hybrid recorded the same process and the same cosine score 0.5816793 in `qa_logs/fix01b/bench.json`.

## What this acceptance does not include

- A git commit, an annotated tag, or a push.
- Public hosting, authentication, or a port published on `0.0.0.0`.
- A new evaluation run or a new vector index.
- A claim that Hybrid is statistically superior outside the 61 labeled queries.
