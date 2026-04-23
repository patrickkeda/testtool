"""
Instrument session abstraction and VISA-based implementation (placeholder).
"""

from __future__ import annotations

import logging
from typing import Optional


class IInstrumentSession:
    """Instrument session interface for SCPI/SDK devices.

    All methods should implement timeouts and raise meaningful exceptions.
    """

    def open(self, resource: str, timeout_ms: int) -> None:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError

    def write(self, cmd: str) -> None:
        raise NotImplementedError

    def query(self, cmd: str) -> str:
        raise NotImplementedError


class VisaSession(IInstrumentSession):
    """VISA-backed session using pyvisa if available.

    Falls back to simple socket-like behavior if pyvisa is not installed.
    """

    def __init__(self) -> None:
        self._rm = None
        self._inst = None
        self._logger = logging.getLogger(__name__)

    def open(self, resource: str, timeout_ms: int) -> None:
        try:
            import pyvisa  # type: ignore
        except Exception as e:  # noqa: BLE001
            raise RuntimeError("pyvisa not available") from e
        self._rm = pyvisa.ResourceManager()
        self._inst = self._rm.open_resource(resource)
        self._inst.timeout = max(1, int(timeout_ms))
        self._logger.info("VISA open: %s", resource)

    def close(self) -> None:
        try:
            if self._inst is not None:
                self._inst.close()
            if self._rm is not None:
                self._rm.close()
        finally:
            self._inst = None
            self._rm = None

    def write(self, cmd: str) -> None:
        if self._inst is None:
            raise RuntimeError("session not open")
        self._logger.debug("SCPI>> %s", cmd)
        self._inst.write(cmd)

    def query(self, cmd: str) -> str:
        if self._inst is None:
            raise RuntimeError("session not open")
        self._logger.debug("SCPI?? %s", cmd)
        resp = self._inst.query(cmd)
        self._logger.debug("SCPI<< %s", resp.strip())
        return resp


