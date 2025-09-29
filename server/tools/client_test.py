"""
NEXON Test Client for gRPC and REST Inference

This script provides performance tests and functional validation for the
inference backends. It supports:
  • Built-in preset input (sigmoid)
  • Custom input from YAML (recommended) or JSON

Run from the project root's ./server directory.
See the README section “NEXON Test Clients & Benchmarks” for examples.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from typing import List, Tuple, Optional, cast

import grpc
import numpy as np
import requests
import yaml  # PyYAML

import inference_pb2 as pb
import inference_pb2_grpc as pb_grpc

# -------- proto dtype <-> numpy dtype maps --------
PB_TO_NP = {
    pb.DT_FLOAT32: np.float32,
    pb.DT_FLOAT64: np.float64,
    pb.DT_INT32:   np.int32,
    pb.DT_INT64:   np.int64,
    pb.DT_BOOL:    np.bool_,
}
NP_TO_PB = {v: k for k, v in PB_TO_NP.items()}

# ---------------------- helpers: bytes/arrays ----------------------
def as_le_bytes(arr: np.ndarray) -> bytes:
    if arr.dtype == np.bool_:
        # booleans transported as bytes
        return np.ascontiguousarray(arr.astype(np.uint8, copy=False)).tobytes(order="C")
    le = arr.dtype.newbyteorder("<")
    return np.ascontiguousarray(arr.astype(le, copy=False)).tobytes(order="C")

def numpy_to_request_tensor(x: np.ndarray, name: str = "") -> pb.RequestTensor:
    return pb.RequestTensor(name=name, dims=list(x.shape), tensor_content=as_le_bytes(x))

def response_tensor_to_numpy(t: pb.ResponseTensor) -> np.ndarray:
    np_dtype = PB_TO_NP.get(t.data_type)
    if np_dtype is None:
        raise ValueError(f"Unsupported response dtype enum: {t.data_type}")
    arr = np.frombuffer(t.tensor_content, dtype=np_dtype)
    return arr.reshape(tuple(t.dims), order="C")

# ---------------------- preset inputs ----------------------
def preset_sigmoid() -> np.ndarray:
    data = [
        [[0.90611831,0.55083885,0.60356778,0.4017955,0.93486481],
         [0.4901685,0.13770382,0.18119458,0.96234953,0.73380571],
         [0.45169349,0.43948672,0.42517826,0.66069703,0.03820433],
         [0.03415621,0.20126882,0.12834833,0.40389847,0.91753817]],
        [[0.35571745,0.00176035,0.50712222,0.8112738,0.87369624],
         [0.72933191,0.90544295,0.42246992,0.40272341,0.32540792],
         [0.81075661,0.63102424,0.2854389,0.70343316,0.40121651],
         [0.91779477,0.42282643,0.28781966,0.72246921,0.2001259]],
        [[0.48461046,0.17440038,0.65646471,0.45603641,0.35819514],
         [0.41587646,0.16148726,0.66821656,0.6465515,0.72218574],
         [0.98868071,0.5001877,0.98337036,0.06299395,0.53611984],
         [0.33656247,0.69934775,0.59331723,0.7628454,0.1131932]],
    ]
    return np.array(data, dtype=np.float32)

# ---------------------- REST (Session reuse) ----------------------
_SESSION: Optional[requests.Session] = None

def _get_session(fresh_conn: bool) -> requests.Session:
    global _SESSION
    if fresh_conn:
        return requests.Session()
    if _SESSION is None:
        _SESSION = requests.Session()
    return _SESSION

def post_rest_infer(base_url: str, model_name: str, x: np.ndarray, fresh_conn: bool) -> Tuple[List, float, int, int]:
    url = base_url.rstrip("/") + f"/{model_name}"
    payload = {"input": x.tolist()}
    data = json.dumps(payload).encode("utf-8")
    s = _get_session(fresh_conn)
    t0 = time.perf_counter()
    r = s.post(url, headers={"Content-Type": "application/json"}, data=data, timeout=60)
    elapsed = time.perf_counter() - t0
    r.raise_for_status()
    body = r.content
    obj = r.json()
    return obj["results"], elapsed, len(data), len(body)

# ---------------------- gRPC (Channel reuse) ----------------------
_GRPC_CHANNEL: Optional[grpc.aio.Channel] = None
_GRPC_STUB: Optional[pb_grpc.InferenceServiceStub] = None
_GRPC_ADDR: Optional[str] = None

async def _get_grpc_stub(addr: str, fresh_conn: bool) -> pb_grpc.InferenceServiceStub:
    global _GRPC_CHANNEL, _GRPC_STUB, _GRPC_ADDR
    if fresh_conn:
        ch = grpc.aio.insecure_channel(addr)
        return pb_grpc.InferenceServiceStub(ch)
    if _GRPC_STUB is None or _GRPC_ADDR != addr:
        _GRPC_ADDR = addr
        _GRPC_CHANNEL = grpc.aio.insecure_channel(addr)
        _GRPC_STUB = pb_grpc.InferenceServiceStub(_GRPC_CHANNEL)
    return _GRPC_STUB

async def predict_grpc(addr: str, model_name: str, x: np.ndarray,
                       deadline_sec: float, wait_for_ready: bool,
                       fresh_conn: bool) -> Tuple[List[np.ndarray], float, int, int]:
    req = pb.PredictRequest(model_name=model_name, input=numpy_to_request_tensor(x))
    req_bytes = req.SerializeToString()

    if fresh_conn:
        async with grpc.aio.insecure_channel(addr) as channel:
            stub = pb_grpc.InferenceServiceStub(channel)
            t0 = time.perf_counter()
            reply = await stub.Predict(req, timeout=deadline_sec, wait_for_ready=wait_for_ready)
            elapsed = time.perf_counter() - t0
    else:
        stub = await _get_grpc_stub(addr, fresh_conn=False)
        t0 = time.perf_counter()
        reply = await stub.Predict(req, timeout=deadline_sec, wait_for_ready=wait_for_ready)
        elapsed = time.perf_counter() - t0

    rep_bytes = reply.SerializeToString()
    outs = [response_tensor_to_numpy(t) for t in reply.outputs]
    return outs, elapsed, len(req_bytes), len(rep_bytes)

# ---------------------- compare + print ----------------------
def summarize_array(tag: str, arr: np.ndarray, n: int = 8) -> str:
    flat = arr.ravel()
    sample = flat[:n].tolist()
    return (f"{tag} shape={tuple(arr.shape)} dtype={arr.dtype} "
            f"min={float(flat.min(initial=0)):.6g} max={float(flat.max(initial=0)):.6g} "
            f"sample={sample}")

def compare_arrays(a: np.ndarray, b: np.ndarray, rtol: float, atol: float) -> Tuple[bool, float, float]:
    ok = bool(np.allclose(a, b, rtol=rtol, atol=atol))
    diff = np.abs(a - b)
    max_abs = float(np.max(diff)) if diff.size else 0.0
    with np.errstate(divide="ignore", invalid="ignore"):
        denom = np.maximum(np.abs(a), np.abs(b))
        rel = diff / denom
    if rel.size == 0 or np.isnan(rel).all():
        max_rel = 0.0
    else:
        max_rel_np = cast(np.floating, np.nanmax(rel))
        max_rel = float(max_rel_np)
    return ok, max_abs, max_rel

# ---------------------- input loaders ----------------------
def load_input_from_json(path: str, dtype_str: str) -> np.ndarray:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    dmap = {"float32": np.float32, "float64": np.float64, "int32": np.int32, "int64": np.int64, "bool": np.bool_}
    if dtype_str not in dmap:
        raise SystemExit("--json requires a valid --dtype (float32|float64|int32|int64|bool)")
    return np.asarray(data, dtype=dmap[dtype_str])

def load_input_from_yaml(path: str) -> np.ndarray:
    with open(path, "r", encoding="utf-8") as f:
        obj = yaml.safe_load(f)
    if not isinstance(obj, dict) or "data" not in obj or "dtype" not in obj:
        raise SystemExit("--input YAML must be a mapping with keys: data, dtype")
    dmap = {"float32": np.float32, "float64": np.float64, "int32": np.int32, "int64": np.int64, "bool": np.bool_}
    dtype_str = str(obj["dtype"]).lower()
    if dtype_str not in dmap:
        raise SystemExit("--input dtype must be one of: float32|float64|int32|int64|bool")
    return np.asarray(obj["data"], dtype=dmap[dtype_str])

# ---------------------- args ----------------------
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="NEXON client for gRPC (Envoy 8080 by default) with optional REST parity checks."
    )
    p.add_argument("--grpc-addr", default=os.environ.get("NEXON_GRPC_ADDR", "127.0.0.1:8080"),
                   help="Target address for gRPC (default: Envoy 127.0.0.1:8080)")
    p.add_argument("--rest-base", default=os.environ.get("NEXON_REST_BASE", "http://127.0.0.1:8080/inference/infer"),
                   help="Base URL for REST (default: Envoy)")
    p.add_argument("--model-name", required=True, help="Deployed model name (e.g., sigmoid.onnx)")

    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--preset", choices=["sigmoid"], help="Use a built-in test input")
    g.add_argument("--json", dest="json_path", help="Path to JSON file containing nested lists (use with --dtype)")
    g.add_argument("--input", dest="yaml_path", help="YAML file with {data: [...], dtype: <type>}")

    p.add_argument("--dtype", choices=["float32", "float64", "int32", "int64", "bool"],
                   help="Required if --json is used")

    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--compare-rest", action="store_true", help="Run gRPC then REST and compare outputs.")
    mode.add_argument("--rest-only", action="store_true", help="Run ONLY the REST test.")

    p.add_argument("--rtol", type=float, default=1e-5)
    p.add_argument("--atol", type=float, default=1e-6)
    p.add_argument("--iters", type=int, default=1, help="Repeat requests to show connection reuse effects")
    p.add_argument("--fresh-conn", action="store_true",
                   help="Do NOT reuse connections (new gRPC channel / new HTTP connection each request)")
    p.add_argument("--deadline", type=float, default=60.0, help="gRPC per-call deadline (seconds)")
    return p.parse_args()

# ---------------------- main ----------------------
async def main_async(args: argparse.Namespace) -> None:
    global _GRPC_CHANNEL, _SESSION

    # Choose input
    if args.preset == "sigmoid":
        x = preset_sigmoid()
    elif args.yaml_path:
        x = load_input_from_yaml(args.yaml_path)
    else:
        if not args.json_path or not args.dtype:
            raise SystemExit("--json requires --dtype")
        x = load_input_from_json(args.json_path, args.dtype)

    # --- gRPC Run ---
    outs_grpc_last: List[np.ndarray] = []
    if not args.rest_only:
        total_ms_grpc = 0.0
        req_sz_last = rep_sz_last = 0
        for i in range(args.iters):
            outs_grpc, t_grpc, grpc_req_sz, grpc_rep_sz = await predict_grpc(
                args.grpc_addr, args.model_name, x, args.deadline, True, args.fresh_conn
            )
            if i == args.iters - 1:
                outs_grpc_last = outs_grpc
                req_sz_last, rep_sz_last = grpc_req_sz, grpc_rep_sz
            total_ms_grpc += t_grpc * 1000.0

        avg_ms_grpc = total_ms_grpc / args.iters
        print(f"Inference OK (gRPC @ {args.grpc_addr}). iters={args.iters} fresh={args.fresh_conn}")
        for i, arr in enumerate(outs_grpc_last):
            print(" ", summarize_array(f"[grpc output[{i}]]", arr))
        print(f"  gRPC avg time: {avg_ms_grpc:.2f} ms | sizes (last): req={req_sz_last}B rep={rep_sz_last}B")

    # --- REST Run ---
    if args.compare_rest or args.rest_only:
        total_ms_rest = 0.0
        outs_rest_last: List[np.ndarray] = []
        rest_req_last = rest_rep_last = 0
        for i in range(args.iters):
            ref_dtype = outs_grpc_last[0].dtype if outs_grpc_last else np.float32
            results_json, t_rest, rest_req_sz, rest_rep_sz = post_rest_infer(
                args.rest_base, args.model_name, x, args.fresh_conn
            )
            outs_rest = [np.asarray(results_json[0], dtype=ref_dtype)] if results_json else []
            if i == args.iters - 1:
                outs_rest_last = outs_rest
                rest_req_last, rest_rep_last = rest_req_sz, rest_rep_sz
            total_ms_rest += t_rest * 1000.0

        avg_ms_rest = total_ms_rest / args.iters
        print(f"\nInference OK (REST @ {args.rest_base}). iters={args.iters} fresh={args.fresh_conn}")
        for i, arr in enumerate(outs_rest_last):
            print(" ", summarize_array(f"[rest output[{i}]]", arr))
        print(f"  REST avg time: {avg_ms_rest:.2f} ms | sizes (last): req={rest_req_last}B rep={rest_rep_last}B")

        # --- Parity Check ---
        if args.compare_rest and outs_grpc_last and outs_rest_last:
            ok, max_abs, max_rel = compare_arrays(outs_grpc_last[0], outs_rest_last[0], rtol=args.rtol, atol=args.atol)
            status = "PASS ✅" if ok else "FAIL ❌"
            print(f"\nPARITY [{status}] rtol={args.rtol} atol={args.atol}")
            print(f"  max_abs_err={max_abs:.3e} | max_rel_err={max_rel:.3e}")

    # --- Cleanup ---
    if _GRPC_CHANNEL:
        await _GRPC_CHANNEL.close()
    if _SESSION:
        _SESSION.close()

def main() -> None:
    args = parse_args()
    asyncio.run(main_async(args))

if __name__ == "__main__":
    main()