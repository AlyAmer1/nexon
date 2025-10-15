#!/usr/bin/env python3
"""
Generate deterministic test tensors for gRPC CLI testing.

Emits JSON with keys:
  - dims : list[int]
  - dtype: str ("float32", "int64", ...)
  - b64  : base64 of LITTLE-ENDIAN, row-major bytes

Usage examples:
  python3 gen_b64_inputs.py --case sigmoid
  python3 gen_b64_inputs.py --case medium_1x1 --out ../results/functional/grpc/inputs/medium_1x1.json
  python3 gen_b64_inputs.py --case gpt2_1x1 --indent 2
"""

from __future__ import annotations
import argparse, base64, json, sys
from typing import Dict, Any
import numpy as np

DTYPE_MAP = {
    "float32": np.float32,
    "float64": np.float64,
    "int32":   np.int32,
    "int64":   np.int64,
}

def to_le_bytes(arr: np.ndarray) -> bytes:
    """Return row-major LITTLE-ENDIAN bytes for the provided NumPy array."""
    # make contiguous, enforce little-endian for academic rigor
    le = arr.dtype.newbyteorder("<")
    return np.ascontiguousarray(arr.astype(le, copy=False)).tobytes(order="C")

def b64_bytes(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")

def build_case(name: str) -> Dict[str, Any]:
    if name == "sigmoid":
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
        arr = np.array(data, dtype=np.float32)
        dtype = "float32"
    elif name == "medium_1x1":
        arr = np.full((1, 1), 50022, dtype=np.float32)
        dtype = "float32"
    elif name == "gpt2_1x1":
        arr = np.array([[50256]], dtype=np.int64)
        dtype = "int64"
    else:
        raise ValueError(f"Unknown case: {name}")

    raw = to_le_bytes(arr)
    expected = int(arr.size) * int(arr.dtype.itemsize)
    if len(raw) != expected:
        raise RuntimeError(f"Byte-size mismatch: got {len(raw)} vs expected {expected}")

    return {"dims": list(arr.shape), "dtype": dtype, "b64": b64_bytes(raw)}

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Emit deterministic test tensors as JSON.")
    p.add_argument("--case", required=True, choices=["sigmoid", "medium_1x1", "gpt2_1x1"])
    p.add_argument("--out", help="Write JSON to this path (default: stdout)")
    p.add_argument("--indent", type=int, default=None, help="Pretty-print JSON with given indent")
    return p.parse_args()

def main() -> None:
    a = parse_args()
    obj = build_case(a.case)
    txt = json.dumps(obj, indent=a.indent, ensure_ascii=False)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(txt + "\n")
    else:
        sys.stdout.write(txt + "\n")

if __name__ == "__main__":
    main()