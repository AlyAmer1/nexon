# 🧪 NEXON: Local Testing & Evaluation Guide

**Note: The official results in the thesis were generated in a Client VM to Server VM environment.** <br>
<br>
This document provides instructions for reproducing the tests on a local machine to verify the functionality and core metrics without needing to provision virtual machines.

---

## Table of Contents

1.  [Initial Setup](#1-initial-setup)
2.  [Functional Testing](#2-functional-testing)
3.  [Performance Benchmarking](#3-performance-benchmarking-local-path-prepared-thesis-results-come-from-vm)
4.  [Resource Utilization](#4-resource-utilization-reported-in-thesis-from-vm-local-optional)
5.  [Robustness Testing](#5-robustness-testing-reported-in-thesis-from-vm-local-optional)
6.  [Reproducibility Notes](#reproducibility-notes)

## 1) Initial Setup

### Platform Support & Windows Usage

The functional test runners under `server/tests` are Bash (POSIX) scripts and require a **POSIX environment** plus the following tools:

- `node`, `npm`, `newman`, `newman-reporter-htmlextra`
- `grpcurl`
- `jq`


> Versions are captured automatically in the Environment Snapshot generated later

### macOS (Homebrew)
   ```bash
   brew install jq node grpcurl
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

## 3) Performance Benchmarking (local path prepared; thesis results come from VM)

Scope: latency, throughput, and concurrency scaling (REST & gRPC via Envoy).

Where to look (scaffolding and results):
- Runners: `server/tests/performance/{rest,grpc}`
- Artifacts: `server/tests/results/performance/{rest,grpc}`

Local runner scripts follow the same pattern as Functional: single command, timestamped artifacts, JSON/HTML outputs suitable for acceptance/evidence flows.

---

## 4) Resource Utilization (reported in thesis from VM; local optional)

Focus: CPU/RAM during representative load; correlate with latency/throughput.
Optional local capture: `docker stats`, `top`/`htop`, store snapshots under `server/tests/results/performance/*`.

---

## 5) Robustness Testing (reported in thesis from VM; local optional)

Scenarios: DB down/recovery, service crash & restart, malformed requests, resource pressure, transient network faults.
Optional local experiments: `docker compose` stop/kill/pause selected services; archive short logs under `server/tests/results/robustness/`.

---

## Reproducibility Notes

- Directory layout & filenames are stable; artifacts are UTC-timestamped to avoid overwrites.
- Runners are idempotent: re-running creates a new timestamped set without touching prior results.
- Single-source oracles: REST assertions live in the Postman collection; gRPC expectations are encoded in the runner and the acceptance script for consistent grading.
