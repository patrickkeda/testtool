"""
Transport factory and basic health check.
"""

from __future__ import annotations

from typing import Dict, Any

from .interfaces import ICommTransport
from .serial_transport import SerialTransport
from .tcp_transport import TcpTransport


def TransportFactory(kind: str, **kwargs: Dict[str, Any]) -> ICommTransport:  # noqa: N802 - factory name
    kind = kind.lower()
    if kind == "serial":
        return SerialTransport(**kwargs)
    if kind == "tcp":
        return TcpTransport(**kwargs)
    raise ValueError(f"unknown transport kind: {kind}")


def health_check(transport: ICommTransport, timeout_ms: int = 500) -> bool:
    try:
        transport.open()
        # For generic transports we cannot probe; just consider open success as healthy.
        return True
    except Exception:
        return False
    finally:
        try:
            transport.close()
        except Exception:
            pass


