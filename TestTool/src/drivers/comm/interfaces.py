"""
Transport interfaces and errors.
"""

from __future__ import annotations

from typing import Protocol


class TransportError(Exception):
    """Base transport error."""


class TimeoutError(TransportError):
    """Operation timed out."""


class RetryableError(TransportError):
    """Operation may be retried."""


class ICommTransport(Protocol):
    """Unified byte-stream transport interface."""

    def open(self) -> None:
        ...

    def close(self) -> None:
        ...

    def send(self, data: bytes, timeout_ms: int) -> int:
        ...

    def recv(self, timeout_ms: int) -> bytes:
        ...

    def is_open(self) -> bool:
        ...


