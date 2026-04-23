"""Health checks aggregation for services and external dependencies."""

from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable, Dict, Optional


ProbeFunc = Callable[[], Awaitable[Dict[str, object]]]


class HealthAggregator:
    def __init__(self) -> None:
        self._probes: Dict[str, ProbeFunc] = {}

    def register(self, name: str, probe: ProbeFunc) -> None:
        if name in self._probes:
            raise ValueError(f"Probe '{name}' already registered")
        self._probes[name] = probe

    def unregister(self, name: str) -> None:
        self._probes.pop(name, None)

    async def snapshot(self, timeout_ms: Optional[int] = 1000) -> Dict[str, Dict[str, object]]:
        results: Dict[str, Dict[str, object]] = {}
        tasks = {name: asyncio.create_task(self._wrap_probe(name, fn, timeout_ms)) for name, fn in self._probes.items()}
        for name, task in tasks.items():
            results[name] = await task
        return results

    async def _wrap_probe(self, name: str, fn: ProbeFunc, timeout_ms: Optional[int]) -> Dict[str, object]:
        started = time.time()
        try:
            if timeout_ms and timeout_ms > 0:
                data = await asyncio.wait_for(fn(), timeout=timeout_ms / 1000)
            else:
                data = await fn()
            latency_ms = int((time.time() - started) * 1000)
            return {"ok": True, "latency_ms": latency_ms, "details": data, "ts": time.time()}
        except Exception as exc:  # noqa: BLE001
            latency_ms = int((time.time() - started) * 1000)
            return {"ok": False, "latency_ms": latency_ms, "details": {"error": str(exc)}, "ts": time.time()}


__all__ = ["HealthAggregator"]


