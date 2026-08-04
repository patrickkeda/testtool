"""
比对本机时间与机器人 RTC（工程命令 ``rtc=0%``）。

默认允许误差 ``max_diff_sec=300``（5 分钟）。
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from types import MethodType
from typing import Any, Dict, List, Optional, Tuple

from ...base import BaseStep, StepResult
from ...context import Context


_DT_PATTERNS = (
    # 2025-11-03 20:10:40 / 2025-11-03T20:10:40
    re.compile(
        r"(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})[ T](?P<H>\d{2}):(?P<M>\d{2}):(?P<S>\d{2})"
    ),
    # ok 2025-11-03,20:10:40  （文档返回示例：ok time,time;）
    re.compile(
        r"(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2}),(?P<H>\d{2}):(?P<M>\d{2}):(?P<S>\d{2})"
    ),
)


def _parse_datetime(text: str) -> Optional[datetime]:
    s = (text or "").strip()
    if not s:
        return None
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
    ):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    for pat in _DT_PATTERNS:
        m = pat.search(s)
        if not m:
            continue
        try:
            return datetime(
                int(m.group("y")),
                int(m.group("m")),
                int(m.group("d")),
                int(m.group("H")),
                int(m.group("M")),
                int(m.group("S")),
            )
        except ValueError:
            continue
    return None


def _collect_text_blobs(obj: Any, out: List[str], *, depth: int = 0) -> None:
    if depth > 6 or obj is None:
        return
    if isinstance(obj, str):
        if obj.strip():
            out.append(obj)
        return
    if isinstance(obj, (int, float, bool)):
        return
    if isinstance(obj, dict):
        for k in ("message", "data", "time", "rtc", "datetime", "value", "result"):
            if k in obj:
                _collect_text_blobs(obj[k], out, depth=depth + 1)
        for v in obj.values():
            _collect_text_blobs(v, out, depth=depth + 1)
        return
    if isinstance(obj, (list, tuple)):
        for v in obj:
            _collect_text_blobs(v, out, depth=depth + 1)


def parse_rtc_datetime(response_obj: Dict[str, Any], raw: str = "") -> Optional[datetime]:
    """从工程服务响应中解析 RTC 时间。"""
    blobs: List[str] = []
    if raw:
        blobs.append(raw)
    _collect_text_blobs(response_obj, blobs)
    for blob in blobs:
        dt = _parse_datetime(blob)
        if dt is not None:
            return dt
    return None


class CompareRtcStep(BaseStep):
    """读取 ``rtc=0%``，与本机时间比对，误差在阈值内通过。"""

    def run_once(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        robot_ip = self.get_param_str(params, "robot_ip", "192.168.125.2").strip()
        port = int(self.get_param_int(params, "port", 3579))
        timeout_sec = int(self.get_param_int(params, "timeout", 30))
        max_diff_sec = int(self.get_param_int(params, "max_diff_sec", 300))
        if max_diff_sec < 0:
            return self.create_failure_result(
                "max_diff_sec 不能为负",
                error="RTC_BAD_MAX_DIFF",
            )

        command = self.get_param_str(params, "command", "rtc=0%").strip() or "rtc=0%"
        command = self._replace_variables(command, ctx)

        ctx.log_info(
            f"RTC 时间比对: command={command} @ {robot_ip}:{port}, "
            f"允许误差 ≤{max_diff_sec}s"
        )

        try:
            ok, response_obj, raw, err = self._fetch_rtc(
                ctx, robot_ip=robot_ip, port=port, command=command, timeout_sec=timeout_sec
            )
        except Exception as e:  # noqa: BLE001
            return self.create_failure_result(
                f"读取 RTC 失败: {e}",
                error="RTC_FETCH_EXCEPTION",
            )

        if not ok:
            return self.create_failure_result(
                f"rtc 命令失败: {err or 'unknown'}",
                error="RTC_COMMAND_FAILED",
                data={"response": response_obj, "raw": (raw or "")[:1000]},
            )

        rtc_dt = parse_rtc_datetime(response_obj or {}, raw or "")
        if rtc_dt is None:
            return self.create_failure_result(
                "无法从 rtc 响应解析时间",
                error="RTC_PARSE_FAILED",
                data={"response": response_obj, "raw": (raw or "")[:1000]},
            )

        pc_dt = datetime.now()
        diff_sec = abs((pc_dt - rtc_dt).total_seconds())
        data = {
            "pc_time": pc_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "rtc_time": rtc_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "diff_sec": round(diff_sec, 3),
            "max_diff_sec": max_diff_sec,
            "response": response_obj,
        }
        ctx.log_info(
            f"本机={data['pc_time']} RTC={data['rtc_time']} "
            f"|diff|={data['diff_sec']}s (阈值 {max_diff_sec}s)"
        )

        if diff_sec <= float(max_diff_sec):
            return self.create_success_result(
                data=data,
                message=(
                    f"RTC 时间正常：差值 {diff_sec:.1f}s ≤ {max_diff_sec}s "
                    f"(本机 {data['pc_time']} / RTC {data['rtc_time']})"
                ),
            )
        return self.create_failure_result(
            (
                f"RTC 时间偏差过大：{diff_sec:.1f}s > {max_diff_sec}s "
                f"(本机 {data['pc_time']} / RTC {data['rtc_time']})"
            ),
            error="RTC_TIME_DIFF_EXCEEDED",
            data=data,
        )

    def _fetch_rtc(
        self,
        ctx: Context,
        *,
        robot_ip: str,
        port: int,
        command: str,
        timeout_sec: int,
    ) -> Tuple[bool, Optional[Dict[str, Any]], str, str]:
        client_path = self._resolve_engineer_client()
        if client_path is None:
            raise FileNotFoundError("找不到 test_engineer_client.py")

        pkg_dir = client_path.parent
        root_dir = pkg_dir.parent
        for path in (str(root_dir), str(pkg_dir)):
            if path not in sys.path:
                sys.path.insert(0, path)

        from vita_engineer_client.engineer_client import EngineerServiceClient
        from vita_engineer_client.test_engineer_client import command_handler, parser

        json_response: Optional[str] = None
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:

            async def _run() -> bool:
                nonlocal json_response
                async with EngineerServiceClient(host=robot_ip, port=port) as client:
                    test_params = parser.parse_test_case(command)
                    original_send = command_handler._send_command
                    outer_timeout = max(float(timeout_sec), 30.0)

                    async def wrapped_send(self, client, cmd, timeout=180.0, **kwargs):
                        inner = max(min(float(timeout), outer_timeout - 1.0), 5.0)
                        response_str = await original_send(client, cmd, timeout=inner)
                        nonlocal json_response
                        json_response = response_str
                        return response_str

                    command_handler._send_command = MethodType(wrapped_send, command_handler)
                    try:
                        return bool(
                            await command_handler.execute_command(client, test_params)
                        )
                    finally:
                        command_handler._send_command = original_send

            ok = loop.run_until_complete(
                asyncio.wait_for(_run(), timeout=max(float(timeout_sec), 30.0) + 5.0)
            )
        finally:
            loop.close()

        raw = json_response or ""
        response_obj: Optional[Dict[str, Any]] = None
        err = ""
        if raw:
            try:
                response_obj = json.loads(raw)
                ctx.log_info(
                    "RTC 响应: " + json.dumps(response_obj, ensure_ascii=False)[:800]
                )
                if not ok:
                    err = str(
                        response_obj.get("message")
                        or response_obj.get("error")
                        or response_obj.get("status")
                        or "failed"
                    )
            except Exception as e:  # noqa: BLE001
                err = f"JSON 解析失败: {e}"
                response_obj = {"raw": raw[:500]}
        elif not ok:
            err = "无响应"
        return ok, response_obj, raw, err

    @staticmethod
    def _resolve_engineer_client() -> Optional[Path]:
        here = Path(__file__).resolve()
        testtool_root = here.parents[4]
        candidates = [
            testtool_root / "client" / "vita_engineer_client" / "test_engineer_client.py",
        ]
        if getattr(sys, "frozen", False):
            exe_dir = Path(sys.executable).resolve().parent
            candidates.extend(
                [
                    exe_dir
                    / "_internal"
                    / "client"
                    / "vita_engineer_client"
                    / "test_engineer_client.py",
                    exe_dir / "client" / "vita_engineer_client" / "test_engineer_client.py",
                ]
            )
        for p in candidates:
            try:
                if p.is_file():
                    return p
            except OSError:
                continue
        return None

    def _replace_variables(self, text: str, ctx: Context) -> str:
        s = str(text)
        if "${" not in s:
            return s
        try:
            from ...utils import replace_variables  # type: ignore

            return replace_variables(s, ctx)
        except Exception:
            return s
