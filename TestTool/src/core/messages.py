"""Typed message contracts shared across modules."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Dict, List, Literal, TypedDict


class AlertLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class ConfigChanged(TypedDict):
    version: str
    diff: Dict[str, object]
    at: datetime


class StepMetric(TypedDict, total=False):
    value: float | str
    unit: str
    min: float
    max: float
    result: Literal["PASS", "FAIL", "SKIP"]
    duration_ms: int
    retries: int


class StepUpdate(TypedDict):
    port: str
    step_id: str
    metrics: StepMetric
    ts: float


class HeartbeatStatus(TypedDict):
    name: str
    ok: bool
    latency_ms: int
    details: Dict[str, object]
    ts: float


class AlertMessage(TypedDict):
    level: AlertLevel
    message: str
    context: Dict[str, object]
    ts: float


__all__ = [
    "AlertLevel",
    "ConfigChanged",
    "StepMetric",
    "StepUpdate",
    "HeartbeatStatus",
    "AlertMessage",
]


