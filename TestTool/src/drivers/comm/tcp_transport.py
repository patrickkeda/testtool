"""
TCP transport built on sockets with timeouts/retries/logging.
"""

from __future__ import annotations

import logging
import socket
import time

from .interfaces import ICommTransport, TimeoutError, RetryableError


class TcpTransport(ICommTransport):
    def __init__(self, *, host: str, port: int, timeout_ms: int = 2000, retries: int = 3, backoff_ms: int = 200) -> None:
        self._logger = logging.getLogger(__name__)
        self._host = host
        self._port = port
        self._timeout_ms = timeout_ms
        self._retries = retries
        self._backoff_ms = backoff_ms
        self._sock: socket.socket | None = None

    def open(self) -> None:
        attempt = 0
        while True:
            attempt += 1
            try:
                self._logger.info("正在连接TCP服务器: %s:%s", self._host, self._port)
                self._sock = socket.create_connection((self._host, self._port), timeout=self._timeout_ms / 1000)
                self._logger.info("TCP连接成功: %s:%s", self._host, self._port)
                return
            except Exception as e:  # noqa: BLE001
                if attempt > self._retries:
                    self._logger.error("TCP连接失败，重试 %d 次后放弃: %s", attempt, e)
                    raise RetryableError(f"tcp connect failed after {attempt} attempts: {e}")
                self._logger.warning("TCP连接重试 %d/%d: %s", attempt, self._retries, e)
                time.sleep(self._backoff_ms / 1000)

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._logger.info("正在关闭TCP连接: %s:%s", self._host, self._port)
                self._sock.close()
                self._logger.info("TCP连接已关闭: %s:%s", self._host, self._port)
            finally:
                self._sock = None 

    def is_open(self) -> bool:
        return self._sock is not None

    def send(self, data: bytes, timeout_ms: int) -> int:
        self._ensure()
        self._sock.settimeout(timeout_ms / 1000)
        try:
            n = self._sock.send(data)
            self._logger.info("TCP发送 %d 字节: %s", n, data.hex() if len(data) <= 20 else data.hex()[:40] + "...")
            return n
        except socket.timeout as e:
            self._logger.error("TCP发送超时: %s", e)
            raise TimeoutError(str(e))
        except Exception as e:  # noqa: BLE001
            self._logger.error("TCP发送失败: %s", e)
            raise RetryableError(str(e))

    def recv(self, timeout_ms: int) -> bytes:
        self._ensure()
        self._sock.settimeout(timeout_ms / 1000)
        try:
            data = self._sock.recv(4096)
            self._logger.info("TCP接收 %d 字节: %s", len(data), data.hex() if len(data) <= 20 else data.hex()[:40] + "...")
            return data
        except socket.timeout as e:
            self._logger.error("TCP接收超时: %s", e)
            raise TimeoutError(str(e))
        except Exception as e:  # noqa: BLE001
            self._logger.error("TCP接收失败: %s", e)
            raise RetryableError(str(e))

    def _ensure(self) -> None:
        if not self.is_open():
            raise RetryableError("tcp not open")


