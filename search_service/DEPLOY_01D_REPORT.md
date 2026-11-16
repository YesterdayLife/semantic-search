# DEPLOY-01D — Linux ONNX container validation

Local validation only. The image was not pushed, no cloud service was created, and the Neon migration was not started.

Recommendation: **B. READY WITH NON-BLOCKING ISSUES.**

The Linux container loads the approved quantized ONNX model, matches the Windows vectors on the measured queries, and stays inside a 2 GB limit. The image does not contain the model snapshot. Container dictionary search and `GET /catalog` cannot see the Windows file paths those code paths still use.

## 1. Preflight

| Item | Result |
| --- | --- |
| Docker client and engine | PASS. Docker 29.8.2, Docker Desktop 4.94.0, `linux/amd64`. |
| Engine memory | PASS for this test. The engine reports 7,958,327,296 bytes and 16 CPUs. A 2 GB container limit is inside that budget. |
| Host available RAM at preflight | About 406 MB. The benchmark ran in the Docker VM, one model load at a time. |
| Windows Python | 3.14.7. |
| Container Python | 3.12.16, glibc 2.36, bookworm. |
| ONNX file | PASS. `model_quantized.onnx` is 569,694,530 bytes at revision `4de13258303883538bd53b696b452bf8099f0858`. The Xenova snapshot directory is 586,787,341 bytes and contains real files, not symlinks. |
| Qdrant | PASS. `127.0.0.1:6333`, collection `crop_process_bge_m3`. Compose was not changed. |
| Packaging | The snapshot is inside `search_service/.cache`, which `.dockerignore` excludes. The image mounts it read-only and copies it into a private container directory because the hub client may create lock files. The source cache is not modified and is not baked into the image. A registry copy was not made. |

## 2. Files created

- `Dockerfile`
- `.dockerignore`
- `requirements-linux.txt`
- `requirements-linux.lock.txt`
- `scripts/onnx_stage.py`
- `scripts/onnx_probe.py`
- `scripts/onnx_entrypoint.py`
- `scripts/container_bench.py`
- `scripts/container_api_bench.py`
- `tests/test_onnx_image.py`
- `DEPLOY_01D_REPORT.md`

No search ranking code, frontend code, Compose file, SQLite file, dictionary script, or model weight was edited. Local evidence JSON is under `artifacts/deploy01d/`, which is gitignored.

## 3. Dockerfile design

`s1g14-search-onnx:local` is a Linux CPU image. It installs the lockfile packages, copies the application and the saved evaluation report, and runs as uid 10001. One Uvicorn worker listens on `0.0.0.0:8000` inside the container. The published mapping used for the benchmark was `127.0.0.1:8011:8000`. The health check calls `http://127.0.0.1:8000/health` from inside the container. No credential is set in the image. `HF_HUB_OFFLINE=1`. If the approved snapshot is absent, the process exits 1 with `approved ONNX snapshot is not mounted`. That failure was executed.

## 4. Linux dependency compatibility

PASS. The image has `onnxruntime==1.32.0`, `numpy==2.2.6`, `tokenizers==0.23.3`, `huggingface_hub==1.33.0`, `fastapi==0.136.3`, and `uvicorn==0.35.0`. Torch, CUDA, sentence-transformers, pytest, and the OpenAI client are not installed. `pip check` passed during the build. The session provider is `CPUExecutionProvider`. The wheel also lists `AzureExecutionProvider`; the session does not select it. No CUDA provider is present.

Windows remains on Python 3.14.7 with its existing environment. The Linux file does not change that environment.

## 5. Container build

PASS. Build completed and the local tag is `s1g14-search-onnx:local`. Image size 474,184,606 bytes. Id `sha256:c5a013d820f43ab814e02bf9afb0bc01a26d62bf07075f34ca5ab5e73fcab3e3`. The image was not pushed. The model is not a layer in the image.

## 6. ONNX model loading

PASS.

| Check | Measured |
| --- | --- |
| Revision | `xenova-4de13258303883538bd53b696b452bf8099f0858-model_quantized.onnx` |
| Provider | `CPUExecutionProvider` |
| Dimension | 1024 |
| Finite values | yes |
| Output norm | 1.0 for the Thai query, and `0.9999999999999999` for `cassava production` |
| Pooling | CLS, `hidden[:, 0, :]`, then the existing L2 normalization |
| First Linux load, including the first embed | 4,457 ms |
| Snapshot staging copy | 11,844 ms |
| Prepare before the session load | 84 ms |

## 7. Windows versus Linux embeddings

PASS for the two measured queries. The comparison tolerance was exact component equality after JSON round-trip, which preserves distinct IEEE values. Both queries met it.

| Query | Tokens equal | Max absolute difference | Cosine | Norm difference |
| --- | --- | --- | --- | --- |
| ผลผลิตมันสำปะหลังภาคเหนือปี 2566 | yes, 13 tokens | 0 | 1 | 0 |
| cassava production | yes, 6 tokens | 0 | 1 | 0 |

This is bit-identical for these two queries. It is not a claim about every possible string. Windows Python is 3.14.7 and Linux Python is 3.12.16. Windows first load was 3,144 ms. Warm embed was 22 ms and 20 ms on Windows, and 87 ms and 75 ms in the 2-CPU container.

## 8. Memory

PASS. Limit `--memory=2g --memory-swap=2g`. No OOM kill and no restart.

| Point | Container memory |
| --- | --- |
| Process just started | 12.2 MiB |
| Python import of FastAPI and ONNX Runtime, model not loaded | 72.8 MiB RSS |
| During load | 596 MiB, then 1,001 MiB, with CPU near 100–202% |
| After load and after queries | 1.173 GiB |
| After about 15 s idle | 1.173 GiB |
| Process RSS reported by Linux after the probe | 1,245,003,776 bytes |

Seventeen samples were taken about every 2 seconds. The observed peak is 1.173 GiB of the 2 GiB limit. A 512 MB limit is not enough. A 2 GB limit is sufficient for this process, with roughly 0.8 GiB unused at the observed peak.

## 9. Latency

| Measurement | Samples | Result |
| --- | --- | --- |
| Cold start until `GET /health` | 1 | 17,879 ms, including the snapshot copy and ONNX load |
| Warm `POST /search` for the northern cassava query | 20 | p50 89.6 ms, p95 95.4 ms, min 63.9 ms, max 103.7 ms, mean 86.1 ms |
| Four concurrent clients, eight `POST /search` calls | 8 | p50 203 ms, p95 391 ms, wall time 580 ms |

The cold-start number includes copying 587 MB from the read-only mount. An image that already contained the snapshot would not pay that copy. That layout was not built.

## 10. Container API

Published only on `127.0.0.1:8011`. SQLite was mounted read-only at `/data/S1-G14_M3.sqlite`. Qdrant was reached at `http://host.docker.internal:6333` without changing its `127.0.0.1` binding.

| Route | Result |
| --- | --- |
| `GET /health` | PASS, 200 |
| `GET /ready` | PASS, 200, 105 processes, quantized revision, Qdrant reachable |
| `GET /catalog` | FAIL in the container, 503 `sqlite_unavailable`. The catalog helper still opens the Windows absolute path and does not read `SQLITE_PATH`. The same route on Windows returned 200 and 105 processes. |
| `GET /evaluation-report` | PASS, 200. Keys include `backends`, `benchmark`, `comparison`, and `report_note`. The report was not regenerated. |
| `POST /search` | PASS |
| `POST /hybrid-search` | PASS |
| `POST /compare` semantic half | PASS |
| `POST /compare` dictionary half | FAIL in the container. Backend `dictionary-sqlite` returned `dictionary_unavailable` because the course script path is a Windows path outside the image. |

## 11. Search parity

PASS for semantic and hybrid against the Windows process. Dictionary parity inside the container is FAIL for the path reason above. Ranking code was not changed.

| Query | Mode | Linux result | Windows result |
| --- | --- | --- | --- |
| ผลผลิตมันสำปะหลังภาคเหนือปี 2566 | search and hybrid | `P-REG-SRC-06-CAS-NOR-2023`, 7707851.0 t, score 0.5816793 | same id, quantity, unit, and score |
| มันสำปะหลังและข้าวโพด | hybrid | first `P-REG-SRC-06-CAS-EAS-2019`, 3415285.0 t, score 0.53229153, method `eligibility-first-bge-m3` | same |
| ผลผลิตมากกว่า 1000000 ตัน | hybrid, production greater than 1,000,000 t | first `P-SRC-01-SUG-all-2020`, 74968070.0 t, score 0.48755878 | same |
| มันสำปะหลังภาคใต้ปี 2566 | hybrid | count 0 | count 0 |
| carbon footprint of rice | search | count 5, first `P-SRC-04-RIC-wet-2020`, 26423822.0 t, score 0.5028599, `unavailable_measures: ["carbon_footprint"]` | same |
| compare, same cassava query | semantic | `P-REG-SRC-06-CAS-NOR-2023`, score 0.5816793 | same |
| compare, same cassava query | dictionary | unavailable in the container | Windows returned `P-REG-SRC-06-CAS-NOR-2023` |

## 12. Python tests

PASS. **148 passed in 38.00 s.** That is the previous 144 plus four static image checks. The checks do not build Docker.

## 13. Frontend tests and build

PASS. Vitest 29 passed. `tsc -b && vite build` passed in 2.56 s. Bundle names are unchanged, including `index-VZ4YOCg0.js`.

## 14. SQLite and Qdrant integrity

PASS after the container runs and the Python suite.

- SQLite SHA-256 `9a80da4111beb44a00c5128c3ffdc10f1e6810825f10a838492981d8e3727808`, 921,600 bytes.
- ONNX file size still 569,694,530 bytes. The container mount was read-only.
- Qdrant `crop_process_bge_m3` is green, 105 points, size 1024, distance Cosine.
- Course dictionary script, `build_serving_layer.py`, `import.cypher`, `docker-compose.yml`, and `evaluation/reports/evaluation.json` hashes match the prior baseline.
- No re-index and no OpenAI call.

## 15. Minimum backend resources

Use **2 GB RAM and 2 vCPU** for one Uvicorn worker and this ONNX model. The measured resident set is 1.173 GiB and stays there while idle. Do not plan a 512 MB or 1 GB instance. Disk needs about 0.5 GB for this image plus about 0.6 GB for the snapshot wherever it is mounted or later copied.

## 16. Hosting recommendation

Nothing was purchased or provisioned. Prices below are from the provider pages read on 15 Nov 2026.

| Option | Fit for this process | Notes |
| --- | --- | --- |
| Railway Free | No | Documented maximum is 0.5 GB RAM and a 4 GB image. |
| Railway Hobby | Possible after the snapshot is included | $5 per month includes $5 of usage. RAM is $10 per GB-month and CPU is $20 per vCPU-month, billed for use. A process that holds about 1.2 GB while idle exceeds the included $5 if it stays up all month. Documented serverless mode sleeps after 10 minutes without work. Cold start would add platform wake time to the measured model load. |
| Render Free | No | 512 MB. |
| Render 1 CPU / 2 GB | Possible after the snapshot is included | Plan `1c-2g` is $25 per month on the current pricing page. Persistent disk is $0.25 per GB-month. |
| A 2 GB VPS with Docker | Suitable for a supervised university demo | Same image, snapshot supplied by a volume or an authorized image copy, port bound to the host loopback unless the owner later chooses otherwise. Operational work is the operator's. |

The local image build does not by itself make Railway or Render compatible. Those hosts do not have this Windows cache mount.

## 17. Remaining blockers

- The approved snapshot is not in the image. A cloud host needs an authorized copy into the image or a volume. This phase did not make that copy.
- `GET /catalog` does not honor `SQLITE_PATH`.
- Dictionary search still opens the course script at its Windows path.
- The Linux image has no PostgreSQL driver. That belongs with a later database phase.
- Warm container latency is higher than the Windows process under the 2-CPU cap.

## 18. DEPLOY-01C staging prerequisites

01C was not started. It still needs a separate approval, a staging database, `psycopg` in an environment that is allowed to have it, a server-side URL with a `SELECT`-only role, application of the draft SQL, a fresh audit, and an authorized copy of the 105 vectors without re-embedding or a second normalization. The 2 GB measurement from this phase is the backend size to plan around. It is not a database migration.

**STATUS: DEPLOY-01D COMPLETE — AWAITING OWNER APPROVAL FOR NEXT PHASE**
