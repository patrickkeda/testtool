"""Simple plugin registry with entry point loading and version guard."""

from __future__ import annotations

import importlib
from importlib import metadata
from typing import Any, Callable, Dict, Optional


class PluginRegistry:
    def __init__(self, api_version: str) -> None:
        self._api_version = api_version
        self._factories: Dict[str, Callable[[], Any]] = {}

    def register(self, name: str, factory: Callable[[], Any]) -> None:
        if name in self._factories:
            raise ValueError(f"Plugin '{name}' already registered")
        self._factories[name] = factory

    def get(self, name: str) -> Any:
        if name not in self._factories:
            raise KeyError(name)
        return self._factories[name]()

    def load_entry_points(self, group: str) -> int:
        count = 0
        for ep in metadata.entry_points(group=group):  # type: ignore[arg-type]
            meta = ep.metadata or {}
            plugin_api = meta.get("api_version") or meta.get("API-Version")
            if plugin_api and str(plugin_api) != self._api_version:
                continue
            factory = ep.load()
            if not callable(factory):
                continue
            name = ep.name
            if name not in self._factories:
                self._factories[name] = factory  # type: ignore[assignment]
                count += 1
        return count


__all__ = ["PluginRegistry"]


