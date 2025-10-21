# 🧪 NEXON: Local Testing & Evaluation Guide

**Note: The official results in the thesis were generated in a Client VM to Server VM environment.** <br>
<br>
This document provides instructions for reproducing the tests on a local machine to verify the functionality and core metrics without needing to provision virtual machines.

---

## Table of Contents

1.  [Initial Setup](#1-initial-setup)
2.  [Functional Testing](#2-functional-testing)
3.  [Performance Benchmarking](#3-performance-benchmarking)
4.  [Resource Utilization](#4-resource-utilization)
5.  [Robustness Testing](#5-robustness-testing)
6.  [Reproducibility Notes](#reproducibility-notes)

## 1) Initial Setup

### Platform Support & Windows Usage

The functional test runners under `server/tests` are Bash (POSIX) scripts and require a **POSIX environment** plus the following tools:

- `node`, `npm`, `newman`, `newman-reporter-htmlextra`
- `grpcurl`
- `jq`
 - `k6` (v0.49+)


> Versions are captured automatically in the Environment Snapshot generated later

### macOS (Homebrew)
   ```bash
   brew install jq node grpcurl k6
   npm i -g newman newman-reporter-htmlextra
   ```
### Linux (Ubuntu/Debian)

   ```bash
# Base utilities
sudo apt update && sudo apt install -y curl jq ca-certificates

# Node.js 20 (via NodeSource) + Newman + HTML report plugin
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
npm i -g newman newman-reporter-htmlextra

# grpcurl (arch-aware download: x86_64 or arm64)
v=1.9.1
a="$(uname -m)"
case "$a" in
  x86_64|amd64) p=linux_x86_64 ;;
  aarch64|arm64) p=linux_arm64 ;;
  *) echo "Unsupported arch: $a — see https://github.com/fullstorydev/grpcurl/releases"; exit 1 ;;
esac
curl -fsSL "https://github.com/fullstorydev/grpcurl/releases/download/v${v}/grpcurl_${v}_${p}.tar.gz" \
  | tar xz
sudo install -m 0755 grpcurl /usr/local/bin/grpcurl
   ```
   For `k6`, install from the official repository or your distro package (any v0.49+ works).

### Windows (Recommended: WSL2)

1. Install Docker Desktop and WSL2 with an Ubuntu distro.
2. Open the Ubuntu (WSL) terminal and run the exact commands from the
   [Linux (Ubuntu/Debian) setup](#linux-ubuntudebian) section inside WSL.
3. Use your repo path under WSL (e.g., \\wsl$\Ubuntu\home\<you>\nexon) for all Bash commands in this guide.


---

### Environment Setup

1. Start the services (see root [README.md](../../README.md) → Installation — Docker recommended).

   ```bash
   docker compose up -d --build
   ```

2. Fetch the reference model assets used by tests (release: models-v1.0).

   From repo root:

   ```bash
   bash server/tests/assets/fetch_models.sh
   # Verifies checksums against manifest.sha256
   ```

   Validate files (Optional):

   ```bash
   ls -lh server/tests/assets/models
   shasum -a 256 -c server/tests/assets/models/manifest.sha256
   ```


---

## 2) Functional Testing

**Goal:** Verify success paths, input validation, existence/deployment checks, and health/readiness.

**What we verify**

| ID       | Case                             | REST (expected)             | gRPC (expected)             |
|----------|----------------------------------|-----------------------------|-----------------------------|
| FT-01/02 | Valid inference (deployed model) | 200 + `results[]`           | OK (code 0)                 |
| FT-03/04 | Invalid input (shape/type)       | 400/422                     | InvalidArgument (code 3)    |
| FT-05/06 | Non-deployed model               | 400/409                     | FailedPrecondition (code 9) |
| FT-07/08 | Non-existing model               | 404                         | NotFound (code 5)           |
| FT-09/10 | Health                           | 200 + `{"status":"ok"}`     | SERVING                     |
| FT-11/12 | Readiness                        | 200 + `{"status":"ready"}`  | SERVING                     |

### Pre-generated fixtures (no action needed)
- [`server/tests/functional/grpc/inputs/`](./functional/grpc/inputs)
  
  Note: Only `sigmoid.json` and `medium_1x1.json` are used for FT; `gpt2_1x1` is not needed here.

### Model state checklist (required for FT)
- `sigmoid.onnx` → uploaded & deployed (FT-01/02 valid)
- `medium_sized_model.onnx` → uploaded but NOT deployed (FT-05/06)
- `DOES_NOT_EXIST` → absent (FT-07/08)

### Model state setup commands (run from repo root: `nexon/`):

```bash
# Upload medium placeholder from release assets (do NOT deploy)
curl -f -X POST http://127.0.0.1:8080/upload/ \
  -F "file=@server/tests/assets/models/medium_sized_model.onnx"

# Upload + deploy the small model (reference preset)
curl -f -X POST http://127.0.0.1:8080/deployment/deploy-file/ \
  -F "file=@server/tools/presets/sigmoid.onnx"
```

**Optional (clear prior artifacts before a run):**

```bash
rm -f server/tests/results/functional/rest/* \
      server/tests/results/functional/grpc/* 2>/dev/null || true
```

---

### Run REST functional tests (5 iterations)

Note: `NEXON-LOCAL_REST.postman_environment.json` already sets `base_url = http://127.0.0.1:8080`.

```bash
# from repo root:
cd server/tests/functional/rest/postman
OUTDIR="$(git rev-parse --show-toplevel)/server/tests/results/functional/rest"; mkdir -p "$OUTDIR"; TS=$(date -u +%Y%m%d_%H%M%S)

newman run NEXON_Functional_REST.postman_collection.json \
  -e NEXON-LOCAL_REST.postman_environment.json \
  -n 5 -r cli,htmlextra,json \
  --reporter-htmlextra-export "$OUTDIR/POSTMAN_REST_${TS}.html" \
  --reporter-json-export     "$OUTDIR/POSTMAN_REST_${TS}.json"
```

**Outputs saved to: `server/tests/results/functional/rest/POSTMAN_REST_<UTC-TIMESTAMP>.{html,json}`**

---

### Run gRPC functional tests (5 iterations)

```bash
# from repo root: 
bash server/tests/functional/grpc/run_grpc_functional.sh --endpoint 127.0.0.1:8080 --iters 5
```

**Outputs saved to: `server/tests/results/functional/grpc/`**

---

### Acceptance & Evidence (from artifacts)

Generates an acceptance summary and an environment snapshot for evidence/provenance.

Run from repo root:

```bash
bash server/tests/functional/check_acceptance.sh
```

This reads the latest artifacts and writes:
- `server/tests/results/functional/ACCEPTANCE_FUNCTIONAL_LOCAL.txt`
- `server/tests/results/functional/ENV_SNAPSHOT_LOCAL.txt` ← toolchain & endpoint versions for provenance

---

## 3) Performance Benchmarking

Goal: measure latency, throughput, and resource behavior for REST and gRPC via Envoy across four targeted experiments.

- [**E1 – Latency & Throughput**](#e1--latency--throughput) (1 VU, 3 reps, all models)
- [**E2 – Network Bandwidth**](#e2--network-bandwidth) (1 VU, 3 reps, all models)
- [**E2 – Overhead Analysis**](#e3--overhead-analysis) (1 VU, 3 reps, sigmoid model)
- [**E4 – Scalability**](#e4--scalability) (1/20/100 VUs, 3 reps)

### General notes
- All runners:
  - Ensure the Docker stack is up and auto pre-warm the required models.
  - Export k6 JSON summaries with p50/p90/p95/p99 under the designated results folders.

- REST latency source: `metrics.http_req_duration`.
- gRPC latency source: `rpc_duration_ms`.
- Artifacts include UTC timestamps and never overwrite previous runs. Use `--clean` to delete existing summaries when you want a fresh baseline.

### E1 – Latency & Throughput

**What we run**

| Dimension  | Values                                                         |
|------------|----------------------------------------------------------------|
| Models     | `sigmoid.onnx`, `medium_sized_model.onnx`, `gpt2_dynamic.onnx` |
| Protocols  | REST, gRPC (via `127.0.0.1:8080` through Envoy)                |
| VUs        | 1                                                              |
| Replicates | 3                                                              |
| Stats      | min, avg, med, p(50), p(90), p(95), p(99), max                 |

**Runner**

From repo root:

```bash
# Optional: start fresh (deletes prior *.summary.json first)
bash server/tests/performance/utilities/scripts/run_e1_latency_throughput.sh --clean

# Prewarm models + Run full E1 (1 VU × 3 reps × 3 models × (REST+gRPC))
bash server/tests/performance/utilities/scripts/run_e1_latency_throughput.sh

# Optional (generate CSVs from summaries)
bash server/tests/performance/utilities/scripts/postprocess_uniform_summaries.sh
# CSVs → server/tests/results/performance/latency_throughput/latency_throughput_{rest,grpc}.csv
```

**Where results are saved**
- REST → `server/tests/results/performance/latency_throughput/rest/*.summary.json`
- gRPC → `server/tests/results/performance/latency_throughput/grpc/*.summary.json`



### E2 – Network Bandwidth

**Purpose**

Report network bandwidth for the same E1 runs (1 VU, 3 reps, all models) using k6's byte counters.

- MB/s = `metrics.data_{received,sent}.rate / 1,048,576`
- GB total = `metrics.data_{received,sent}.count / 1,073,741,824`
- Bandwidth is **observational** (no pass/fail). Pass criteria remain E1 checks-rate thresholds.

**Runner**

From repo root:

```bash
# Optional: clear bandwidth artifacts only
bash server/tests/performance/utilities/scripts/gen_e2_bandwidth.sh --clean

# Generate bandwidth per-run JSONs and aggregate CSVs
bash server/tests/performance/utilities/scripts/gen_e2_bandwidth.sh
```

**Where results are saved**
- REST per-run JSON → `server/tests/results/performance/bandwidth/rest/*.bandwidth.json`
- gRPC per-run JSON → `server/tests/results/performance/bandwidth/grpc/*.bandwidth.json`
- REST aggregate CSV → `server/tests/results/performance/bandwidth/E2_bandwidth_rest.csv`
- gRPC aggregate CSV → `server/tests/results/performance/bandwidth/E2_bandwidth_grpc.csv`

**Notes**
- The generator searches both `latency_throughput/{rest,grpc}` and legacy flat `{rest,grpc}` folders.
- If no files are produced, run E1 – Latency & Throughput first and re-run this generator.

### E3 – Overhead Analysis

**Purpose**

Isolate protocol/path overhead at low concurrency. Two knobs:
1. Connection strategy: reused HTTP/gRPC connection vs new connection per request
2. Path: Envoy (gateway) vs Direct (service backend)

**What we run**

| Factor     | Levels                   |
|------------|--------------------------|
| Model      | `sigmoid.onnx`           |
| Protocol   | REST, gRPC               |
| Path       | Envoy vs Direct          |
| Conn       | Reuse vs New per request |
| VU         | 1                        |
| Replicates | 3                        |

**Runner**

```bash
# Optional: clear only E2 artifacts
bash server/tests/performance/utilities/scripts/run_e3_overhead.sh --clean

# Prewarm models + Run all 2×2×2 (path × conn × proto) for sigmoid, 1 VU × 3 reps
bash server/tests/performance/utilities/scripts/run_e3_overhead.sh

# Optional (generate CSVs from summaries)
bash server/tests/performance/utilities/scripts/postprocess_uniform_summaries.sh
# CSVs → server/tests/results/performance/overhead/overhead_{rest,grpc}.csv
```

The script selects the appropriate endpoints for “Envoy” vs “Direct” internally; no manual port changes required.

**Where results are saved**
- REST → `server/tests/results/performance/overhead/rest/*.summary.json`
- gRPC → `server/tests/results/performance/overhead/grpc/*.summary.json`

### E4 – Scalability

**What we run**

| Dimension  | Values                                                                               |
|------------|--------------------------------------------------------------------------------------|
| Models     | `sigmoid.onnx`, `medium_sized_model.onnx`, `gpt2_dynamic.onnx`                       |
| Protocols  | REST, gRPC (both via `127.0.0.1:8080`)                                               |
| VU Tiers   | 1, 20, 100                                                                           |
| Replicates | 1, 2, 3 (odd reps: REST→gRPC; even: gRPC→REST)                                       |
| Tuning     | REST `REQ_TIMEOUT=900s`; gRPC `MAX_MSG_MB=256` (sets `maxReceiveSize`/`maxSendSize`) |
| Stats      | min, avg, med, p(50), p(90), p(95), p(99), max in JSON summaries                     |

**Runner**

From repo root:

```bash
# Optional: start fresh for E4 only (deletes old scalability summaries)
bash server/tests/performance/utilities/scripts/run_e4_scalability.sh --clean

# Prewarm models+ append a new full E4 run
bash server/tests/performance/utilities/scripts/run_e4_scalability.sh

# Optional (generate CSVs from summaries)
bash server/tests/performance/utilities/scripts/postprocess_uniform_summaries.sh
# CSVs → server/tests/results/performance/scalability/scalability_{rest,grpc}.csv
```

**Where results are saved**
- REST summaries → `server/tests/results/performance/rest/*.summary.json`  
  e.g., `rest_sigmoid_v20_rep2_20251018_221530.summary.json`
- gRPC summaries → `server/tests/results/performance/grpc/*.summary.json`  
  e.g., `grpc_gpt2_dynamic_v100_rep3_20251018_224210.summary.json`

### Notes

- **Pass criteria (local reproducibility)**
  - We accept ≥90% check pass-rate locally to account for inevitable noise on developer machines for the Scalability experiment (OS background tasks, shared CPU, Docker Desktop).

- **Pass criteria (VM / thesis)**
  - On the isolated Client-VM ↔ Server-VM setup, the pass-rate is ≥99% (typically 100%), i.e., effectively zero errors.

- The warning "cli level configuration overrode scenarios configuration entirely" is expected; scenarios are driven via CLI so specific metrics (e.g., p99) are exported consistently.
- Artifacts are written with UTC timestamps and never overwrite previous runs. Use `--clean` when you want a fresh baseline.
- **Evidence (optional but recommended)**
  Capture toolchain & Envoy admin state for provenance:

```bash
# Local (saved under server/tests/results/performance/ENV_SNAPSHOT_LOCAL.txt)
bash server/tests/performance/utilities/scripts/collect_env_snapshot.sh
```

---

## 4) Resource Utilization

**Goal:** capture CPU/RAM behavior under representative load and summarize per container (`nexon-envoy`, `nexon-grpc`, `nexon-rest`) across models and protocols.
The runner is self-contained: it **drives** the load and **collects** Docker stats at the same time.

### Workload & scope
- Dimensions: **1 VU × 3 reps × 3 models × (REST + gRPC)**
- Segment duration: **30s** per (model × proto) segment
- Models: `sigmoid.onnx`, `medium_sized_model.onnx`, `gpt2_dynamic.onnx`
- Pipeline: **RAW → STEADY (strict 3 rows/timestamp) → SUMMARY (CSV)**

### Runner (one-liners)

From repo root:

```bash
# Fresh RU run (cleans RAW/STEADY/SUMMARY, then capture + summarize)
bash server/tests/resource_utilization/run_ru_capture.sh --clean && \
bash server/tests/resource_utilization/build_ru_summaries.sh

# Append a new RU run (keeps prior artifacts, then capture + summarize)
bash server/tests/resource_utilization/run_ru_capture.sh && \
bash server/tests/resource_utilization/build_ru_summaries.sh

# Summaries only (when STEADY already exists)
bash server/tests/resource_utilization/build_ru_summaries.sh
```

### Where results are saved
- RAW (per-run, noisy) → `server/tests/results/resource_utilization/raw/{rest,grpc}/ru_<model>_<proto>_rep<r>_<UTC>.csv`
- STEADY (per-run, filtered) → `server/tests/results/resource_utilization/steady/{rest,grpc}/ru_<model>_<proto>_rep<r>_<UTC>.steady.csv`
- SUMMARY (CSVs) → `server/tests/results/resource_utilization/summary/`
  - `RU_peaks_all.csv` — per-run peak CPU%/MEM% by container
  - `RU_means_all.csv` — mean of peaks across replicates (model/proto/container)
  - `RU_means_rest.csv`, `RU_means_grpc.csv` — filtered views
  - `RU_build.log` — ignored local provenance (counts, duplicate check, files consumed)

### Interpreting the summaries
- Peaks (per run): maximum CPU% and MEM% observed per container → `RU_peaks_all.csv`
- Means (across reps): average of per-run peaks for each (model, proto, container) → `RU_means_*.csv`
- Expected pattern (sanity): 
  - REST runs → higher `nexon-rest` CPU
  - gRPC runs → higher `nexon-grpc` CPU

---

## 5) Robustness Testing 

Scenarios: DB down/recovery, service crash & restart, malformed requests, resource pressure, transient network faults.
Optional local experiments: `docker compose` stop/kill/pause selected services; archive short logs under `server/tests/results/robustness/`.

---

## Reproducibility Notes

- Directory layout & filenames are stable; artifacts are UTC-timestamped to avoid overwrites.
- Runners are idempotent: re-running creates a new timestamped set without touching prior results.
- Single-source oracles: REST assertions live in the Postman collection; gRPC expectations are encoded in the runner and the acceptance script for consistent grading.
