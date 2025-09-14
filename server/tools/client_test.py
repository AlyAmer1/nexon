"""
NEXON gRPC test client with optional REST parity checks.

Examples (run from ./server):
  python -m tools.client_test --model-name sigmoid.onnx --preset sigmoid
  python -m tools.client_test --model-name sigmoid.onnx --preset sigmoid --compare-rest
  python -m tools.client_test --model-name gpt2_dynamic.onnx --preset gpt2 --compare-rest
  python -m tools.client_test --model-name <NAME> --json ./input.json --dtype float32 --compare-rest
"""
from __future__ import annotations
import argparse, asyncio, json, os, time
from typing import List, Tuple, cast
import numpy as np
import grpc
import requests

import inference_pb2 as pb
import inference_pb2_grpc as pb_grpc

PB_TO_NP = {
    pb.DT_FLOAT32: np.float32,
    pb.DT_FLOAT64: np.float64,
    pb.DT_INT32:   np.int32,
    pb.DT_INT64:   np.int64,
    pb.DT_BOOL:    np.bool_,
}
NP_TO_PB = {v: k for k, v in PB_TO_NP.items()}

def as_le_bytes(arr: np.ndarray) -> bytes:
    if arr.dtype == np.bool_:
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

def preset_gpt2() -> np.ndarray:
    return np.array([[50256]], dtype=np.int64)

def post_rest_infer(base_url: str, model_name: str, x: np.ndarray) -> Tuple[List, float, int]:
    url = base_url.rstrip("/") + f"/{model_name}"
    payload = {"input": x.tolist()}
    data = json.dumps(payload).encode("utf-8")
    t0 = time.perf_counter()
    r = requests.post(url, headers={"Content-Type": "application/json"}, data=data, timeout=60)
    elapsed = time.perf_counter() - t0
    r.raise_for_status()
    body = r.content
    obj = r.json()
    return obj["results"], elapsed, len(body)

async def predict_grpc(addr: str, model_name: str, x: np.ndarray, deadline_sec: float = 60.0, wait_for_ready: bool = True):
    req = pb.PredictRequest(model_name=model_name, input=numpy_to_request_tensor(x))
    req_bytes = req.SerializeToString()
    # Single-port Envoy on 8080, plaintext gRPC over HTTP/2 (no TLS)
    async with grpc.aio.insecure_channel(addr) as channel:
        stub = pb_grpc.InferenceServiceStub(channel)
        t0 = time.perf_counter()
        reply = await stub.Predict(req, timeout=deadline_sec, wait_for_ready=wait_for_ready)
        elapsed = time.perf_counter() - t0
    rep_bytes = reply.SerializeToString()
    outs = [response_tensor_to_numpy(t) for t in reply.outputs]
    return outs, elapsed, len(req_bytes), len(rep_bytes)

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

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="NEXON gRPC client (single-port Envoy on 8080, with optional REST parity).")
    # Defaults now point at Envoy (single port)
    p.add_argument("--grpc-addr", default=os.environ.get("NEXON_GRPC_ADDR", "127.0.0.1:8080"),
                   help="Target address for gRPC (Envoy single-port)")
    p.add_argument("--rest-base", default=os.environ.get("NEXON_REST_BASE", "http://127.0.0.1:8080/inference/infer"),
                   help="Envoy REST base URL for inference")
    p.add_argument("--model-name", required=True, help="Deployed model name (e.g., sigmoid.onnx)")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--preset", choices=["sigmoid", "gpt2"], help="Use a built-in test input")
    g.add_argument("--json", dest="json_path", help="Path to JSON file containing nested lists")
    p.add_argument("--dtype", choices=["float32", "float64", "int32", "int64", "bool"],
                   help="Required if --json is used")
    p.add_argument("--compare-rest", action="store_true",
                   help="Also send to REST and compare outputs")
    p.add_argument("--rtol", type=float, default=1e-5)
    p.add_argument("--atol", type=float, default=1e-6)
    return p.parse_args()

def load_input_from_json(path: str, dtype_str: str) -> np.ndarray:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    dmap = {"float32": np.float32, "float64": np.float64, "int32": np.int32, "int64": np.int64, "bool": np.bool_}
    if dtype_str not in dmap:
        raise SystemExit("--json requires a valid --dtype")
    return np.asarray(data, dtype=dmap[dtype_str])

def main() -> None:
    args = parse_args()
    if args.preset == "sigmoid":
        x = preset_sigmoid()
    elif args.preset == "gpt2":
        x = preset_gpt2()
    else:
        if not args.json_path or not args.dtype:
            raise SystemExit("--json requires --dtype")
        x = load_input_from_json(args.json_path, args.dtype)

    outs_grpc, t_grpc, grpc_req_sz, grpc_rep_sz = asyncio.run(
        predict_grpc(args.grpc_addr, args.model_name, x)
    )
    print("Inference OK (gRPC via Envoy:8080). Decoded outputs:")
    for i, arr in enumerate(outs_grpc):
        print(" ", summarize_array(f"[grpc output[{i}]]", arr))
    print(f"  gRPC time: {t_grpc*1000:.2f} ms | sizes: req={grpc_req_sz}B rep={grpc_rep_sz}B")

    if not args.compare_rest:
        return

    results_json, t_rest, rest_rep_sz = post_rest_infer(args.rest_base, args.model_name, x)
    outs_rest = [np.asarray(results_json[0], dtype=outs_grpc[0].dtype)] if results_json else []
    print("\nInference OK (REST via Envoy:8080). Decoded outputs:")
    for i, arr in enumerate(outs_rest):
        print(" ", summarize_array(f"[rest output[{i}]]", arr))
    rest_req_sz = len(json.dumps({"input": x.tolist()}).encode("utf-8"))
    print(f"  REST time: {t_rest*1000:.2f} ms | sizes: req={rest_req_sz}B rep={rest_rep_sz}B")

    if outs_grpc and outs_rest:
        ok, max_abs, max_rel = compare_arrays(outs_grpc[0], outs_rest[0], rtol=args.rtol, atol=args.atol)
        status = "PASS ✅" if ok else "FAIL ❌"
        print(f"\nPARITY [{status}] rtol={args.rtol} atol={args.atol}")
        print(f"  max_abs_err={max_abs:.3e} | max_rel_err={max_rel:.3e}")

if __name__ == "__main__":
    main()