"""
SCPI-based power supply driver implementing IPowerSupply using an instrument session.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from .psu import IPowerSupply
from .session import IInstrumentSession


class ScpiPowerSupply(IPowerSupply):
    """Generic SCPI PSU driver.

    Parameters
    ----------
    session: IInstrumentSession
        Underlying instrument session implementation.
    """

    def __init__(self, session: IInstrumentSession) -> None:
        self._session = session
        self._logger = logging.getLogger(__name__)
        self._connected = False

    def connect(self, resource: str, timeout_ms: int) -> None:
        self._session.open(resource, timeout_ms)
        self._connected = True
        try:
            idn = self._session.query("*IDN?").strip()
            self._logger.info("PSU connected: %s", idn)
        except Exception as e:  # noqa: BLE001
            self._logger.warning("PSU *IDN? failed: %s", e)

    def disconnect(self) -> None:
        try:
            self._session.close()
        finally:
            self._connected = False

    def set_voltage(self, channel: int, volts: float) -> None:
        self._ensure()
        self._session.write(f"INST:NSEL {channel}")
        self._session.write(f"VOLT {volts}")

    def set_current(self, channel: int, amps: float) -> None:
        self._ensure()
        self._session.write(f"INST:NSEL {channel}")
        self._session.write(f"CURR {amps}")

    def output(self, on: bool) -> None:
        self._ensure()
        self._session.write(f"OUTP {'ON' if on else 'OFF'}")

    def measure_voltage(self, channel: int) -> float:
        self._ensure()
        self._session.write(f"INST:NSEL {channel}")
        resp = self._session.query("MEAS:VOLT?")
        return float(resp.strip())

    def measure_current(self, channel: int) -> float:
        self._ensure()
        self._session.write(f"INST:NSEL {channel}")
        resp = self._session.query("MEAS:CURR?")
        return float(resp.strip())

    # ---- helpers ---------------------------------------------------------
    def _ensure(self) -> None:
        if not self._connected:
            raise RuntimeError("PSU not connected")




