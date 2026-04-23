"""Service lifecycle management with dependency-aware start/stop and config hooks."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Dict, List, Optional, Protocol


logger = logging.getLogger(__name__)


class Service(Protocol):
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def on_config_changed(self, diff: dict) -> None: ...


@dataclass
class _Node:
    name: str
    service: Service
    deps: List[str]


class LifecycleManager:
    """Registers services and starts/stops them honoring dependencies.

    - On start: topological order so that dependencies start first
    - On stop: reverse order
    - On config change: broadcast in start order
    """

    def __init__(self) -> None:
        self._nodes: Dict[str, _Node] = {}
        self._start_order: List[str] = []
        self._started: bool = False

    def register(self, name: str, svc: Service, deps: Optional[List[str]] = None) -> None:
        if name in self._nodes:
            raise ValueError(f"Service '{name}' already registered")
        self._nodes[name] = _Node(name=name, service=svc, deps=list(deps or []))

    async def start_all(self) -> None:
        order = self._toposort()
        for name in order:
            node = self._nodes[name]
            logger.info("Starting service: %s", name)
            await node.service.start()
        self._start_order = order
        self._started = True

    async def stop_all(self) -> None:
        if not self._started:
            return
        for name in reversed(self._start_order):
            node = self._nodes[name]
            try:
                logger.info("Stopping service: %s", name)
                await node.service.stop()
            except Exception as exc:  # noqa: BLE001
                logger.exception("Stop service %s failed: %s", name, exc)
        self._started = False
        self._start_order = []

    async def broadcast_config_changed(self, diff: dict) -> None:
        for name in self._start_order:
            try:
                await self._nodes[name].service.on_config_changed(diff)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Config change hook failed for %s: %s", name, exc)

    def _toposort(self) -> List[str]:
        indeg: Dict[str, int] = defaultdict(int)
        adj: Dict[str, List[str]] = defaultdict(list)

        # ensure all nodes appear in maps
        for name, node in self._nodes.items():
            indeg.setdefault(name, 0)
            for d in node.deps:
                if d not in self._nodes:
                    raise ValueError(f"Service '{name}' depends on unknown service '{d}'")
                adj[d].append(name)
                indeg[name] += 1

        q: deque[str] = deque([n for n, deg in indeg.items() if deg == 0])
        order: List[str] = []
        while q:
            u = q.popleft()
            order.append(u)
            for v in adj.get(u, []):
                indeg[v] -= 1
                if indeg[v] == 0:
                    q.append(v)

        if len(order) != len(self._nodes):
            raise ValueError("Cyclic dependency detected among services")
        return order


__all__ = ["LifecycleManager", "Service"]


