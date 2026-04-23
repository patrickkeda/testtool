"""
Serial transport built on pyserial with timeouts/retries/logging.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from .interfaces import ICommTransport, TimeoutError, RetryableError


class SerialTransport(ICommTransport):
    def __init__(
        self,
        *,
        port: str,
        baudrate: int = 115200,
        bytesize: int = 8,
        parity: str = "N",
        stopbits: float = 1.0,
        read_timeout_ms: int = 2000,
        write_timeout_ms: int = 2000,
        retries: int = 3,
        backoff_ms: int = 200,
    ) -> None:
        self._logger = logging.getLogger(__name__)
        self._port = port
        self._baudrate = baudrate
        self._bytesize = bytesize
        self._parity = parity
        self._stopbits = stopbits
        self._read_timeout_ms = read_timeout_ms
        self._write_timeout_ms = write_timeout_ms
        self._retries = retries
        self._backoff_ms = backoff_ms
        self._ser = None

    def open(self) -> None:
        try:
            import serial  # type: ignore
        except Exception as e:  # noqa: BLE001
            raise RetryableError("pyserial not available") from e
        self._logger.info("正在打开串口: %s, 波特率: %s", self._port, self._baudrate)
        self._ser = serial.Serial()
        self._ser.port = self._port
        self._ser.baudrate = self._baudrate
        self._ser.timeout = max(0, self._read_timeout_ms / 1000)
        self._ser.write_timeout = max(0, self._write_timeout_ms / 1000)
        # bytesize/parity/stopbits mapping
        self._ser.bytesize = getattr(serial, f"EIGHTBITS" if self._bytesize == 8 else f"SEVENBITS", serial.EIGHTBITS)
        self._ser.parity = getattr(serial, f"PARITY_{self._parity}", serial.PARITY_NONE)
        self._ser.stopbits = getattr(serial, f"STOPBITS_{str(self._stopbits).replace('.', '_')}", serial.STOPBITS_ONE)
        self._ser.open()
        self._ser.reset_input_buffer()
        self._ser.reset_output_buffer()
        self._logger.info("串口连接成功: %s", self._port)

    def close(self) -> None:
        if self._ser is not None:
            try:
                self._logger.info("正在关闭串口: %s", self._port)
                self._ser.close()
                self._logger.info("串口已关闭: %s", self._port)
            finally:
                self._ser = None

    def is_open(self) -> bool:
        return bool(self._ser and self._ser.is_open)

    def send(self, data: bytes, timeout_ms: int) -> int:
        self._ensure()
        attempt = 0
        while True:
            attempt += 1
            try:
                self._ser.write_timeout = max(0, timeout_ms / 1000)
                n = self._ser.write(data)
                self._logger.info("串口发送 %d 字节: %s", n, data.hex() if len(data) <= 20 else data.hex()[:40] + "...")
                return n
            except Exception as e:  # noqa: BLE001
                if attempt > self._retries:
                    self._logger.error("串口发送失败，重试 %d 次后放弃: %s", attempt, e)
                    raise RetryableError(f"serial write failed after {attempt} attempts: {e}")
                self._logger.warning("串口发送重试 %d/%d: %s", attempt, self._retries, e)
                time.sleep(self._backoff_ms / 1000)

    def recv(self, timeout_ms: int) -> bytes:
        self._ensure()
        try:
            self._ser.timeout = max(0, timeout_ms / 1000)
            data = self._ser.read_all()
            self._logger.info("串口接收 %d 字节: %s", len(data), data.hex() if len(data) <= 20 else data.hex()[:40] + "...")
            return data
        except Exception as e:  # noqa: BLE001
            self._logger.error("串口接收超时: %s", e)
            raise TimeoutError(str(e))

    def _ensure(self) -> None:
        if not self.is_open():
            raise RetryableError("serial not open")


