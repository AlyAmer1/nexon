from __future__ import annotations
import asyncio, sys, grpc
from grpc_health.v1 import health_pb2, health_pb2_grpc

async def check(target: str, service: str = "") -> int:
    async with grpc.aio.insecure_channel(target) as ch:
        stub = health_pb2_grpc.HealthStub(ch)
        try:
            resp = await stub.Check(health_pb2.HealthCheckRequest(service=service), timeout=5)
            return 0 if resp.status == health_pb2.HealthCheckResponse.SERVING else 1
        except Exception:
            return 1

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1:50051"
    service = sys.argv[2] if len(sys.argv) > 2 else ""
    raise SystemExit(asyncio.run(check(target, service)))