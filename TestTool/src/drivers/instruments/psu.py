"""
Power Supply (PSU) abstraction.
"""

from __future__ import annotations

from typing import Protocol


class IPowerSupply(Protocol):
    """Power supply high-level API.

    All methods should implement timeouts, retries, and raise meaningful errors.
    """

    def connect(self, resource: str, timeout_ms: int) -> None:
        ...

    def disconnect(self) -> None:
        ...

    def set_voltage(self, channel: int, volts: float) -> None:
        ...

    def set_current(self, channel: int, amps: float) -> None:
        ...

    def output(self, on: bool) -> None:
        ...

    def measure_voltage(self, channel: int) -> float:
        ...

    def measure_current(self, channel: int) -> float:
        ...


