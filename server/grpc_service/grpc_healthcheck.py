"""Async health probe for the NEXON gRPC inference server."""

from __future__ import annotations

import asyncio
import sys

import grpc
from grpc_health.v1 import health_pb2, health_pb2_grpc


async def check(target: str, service: str = "") -> int:
    """Run a single gRPC health check against the given endpoint.

    Args:
        target: Host:port pair to contact.
        service: Fully qualified service name or empty string for aggregate status.

    Returns:
        Zero when the service reports SERVING, otherwise one. Any exception while
        performing the probe is treated as a failure to keep existing tooling parity.
    """
    async with grpc.aio.insecure_channel(target) as channel:
        stub = health_pb2_grpc.HealthStub(channel)
        try:
            resp = await stub.Check(health_pb2.HealthCheckRequest(service=service), timeout=5)
            return 0 if resp.status == health_pb2.HealthCheckResponse.SERVING else 1
        except Exception:
            # Broad catch preserves previous behavior where all errors mapped to failure.
            return 1

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1:50051"
    service = sys.argv[2] if len(sys.argv) > 2 else ""
    raise SystemExit(asyncio.run(check(target, service)))
