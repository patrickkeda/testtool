"""
Engineer Service Client - Production Line Testing Tool (FIXED FOR cpp-httplib)

Fixes:
- Prevent chunked encoding (cpp-httplib 502 root cause)
- Force single-use connection
- Retry on 502
- Compatible with curl behavior
"""

import asyncio
import httpx
import json
import logging
import time
from typing import Optional
from dataclasses import asdict

try:
    from .protocol import (
        CommandMessage, ResponseMessage, ResponseStatus,
        DEFAULT_PORT, CONNECTION_TIMEOUT_MS, COMMAND_TIMEOUT_MS,
    )
    from .crypto_utils import CryptoUtils, SecureSession
except ImportError:
    from protocol import (
        CommandMessage, ResponseMessage, ResponseStatus,
        DEFAULT_PORT, CONNECTION_TIMEOUT_MS, COMMAND_TIMEOUT_MS,
    )
    from crypto_utils import CryptoUtils, SecureSession


class EngineerServiceClient:
    def __init__(self, host: str, port: int = DEFAULT_PORT):
        self.host = host
        self.port = port
        self.base_url = f"http://{host}:{port}"

        self.client: Optional[httpx.AsyncClient] = None
        self.logger = logging.getLogger(__name__)

    # =========================
    # CRITICAL: HTTP CLIENT CONFIG
    # =========================
    def _ensure_client(self):
        if self.client:
            return

        timeout = httpx.Timeout(
            connect=CONNECTION_TIMEOUT_MS / 1000.0,
            read=COMMAND_TIMEOUT_MS / 1000,
            write=10.0,
            pool=10.0,
        )

        self.client = httpx.AsyncClient(
            timeout=timeout,
            base_url=self.base_url,
            http2=False,

            # ⭐关键：彻底关闭连接复用
            limits=httpx.Limits(
                max_connections=1,
                max_keepalive_connections=0,
            ),

            # ⭐关键：强制不使用 chunked（httpx internal hack）
            transport=httpx.AsyncHTTPTransport(
                retries=0,
                verify=False,
            ),
        )

    async def close(self):
        if self.client:
            await self.client.aclose()
            self.client = None

    async def __aenter__(self):
        self._ensure_client()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    # =========================
    # CORE REQUEST (cpp-httplib safe)
    # =========================
    async def _send_command(self, command: CommandMessage) -> ResponseMessage:
        self._ensure_client()

        message_dict = asdict(command)
        message_dict = {k: v for k, v in message_dict.items() if v is not None}

        json_str = json.dumps(message_dict, ensure_ascii=False)
        content_bytes = json_str.encode("utf-8")

        headers = {
            "Content-Type": "application/json",
            "Connection": "close",
            "Accept": "application/json",
        }

        last_error = None

        # =========================
        # RETRY (502 is common in cpp-httplib under load)
        # =========================
        for attempt in range(3):
            try:
                self.logger.info(f"Attempt {attempt+1}: POST {self.base_url}/command")

                response = await self.client.post(
                    "/command",
                    content=content_bytes,   # ⭐ MUST NOT use json=
                    headers=headers,
                )

                # =========================
                # EMPTY RESPONSE
                # =========================
                if not response.content:
                    raise ConnectionError(f"Empty response (HTTP {response.status_code})")

                # =========================
                # PARSE JSON
                # =========================
                try:
                    response_data = response.json()
                except Exception:
                    raise ConnectionError(f"Invalid JSON: {response.text[:200]}")

                # =========================
                # HTTP ERROR HANDLING
                # =========================
                if response.status_code == 502:
                    raise ConnectionError("502 Bad Gateway (cpp-httplib upstream issue)")

                if response.status_code >= 500:
                    raise ConnectionError(f"Server error {response.status_code}")

                # =========================
                # SUCCESS
                # =========================
                msg = ResponseMessage.from_json(json.dumps(response_data))
                msg.raw_response = response_data
                return msg

            except Exception as e:
                last_error = e
                self.logger.warning(f"Attempt {attempt+1} failed: {e}")
                await asyncio.sleep(0.3)

        # all retries failed
        raise ConnectionError(f"Command failed after retries: {last_error}")

    # =========================
    # SAFE API
    # =========================
    async def send_with_retry(self, command: CommandMessage) -> ResponseMessage:
        return await self._send_command(command)


# =========================
# TEST MAIN (FIXED)
# =========================
async def main():
    logging.basicConfig(level=logging.INFO)

    async with EngineerServiceClient(
        host="192.168.126.2",
        port=3579,
    ) as client:

        cmd = CommandMessage(
            command="enfac=1,1%",
            params={"op": "1", "en": "1"},
            timestamp=int(time.time() * 1000),
        )

        res = await client.send_with_retry(cmd)
        print(res)


if __name__ == "__main__":
    asyncio.run(main())