"""
本机 ICMP ping：用于在跑后续步骤前确认与设备（如狗子/机器人）二层或路由可达。
在 Windows 上使用系统 ping；在类 Unix 上使用 ping -c 1，并以 subprocess 总超时兜底。
"""

from __future__ import annotations

import subprocess
import sys
from typing import Any, Dict, List

from ...base import BaseStep, StepResult
from ...context import Context


class PingHostStep(BaseStep):
    """对本机执行 ping，检查目标主机是否可达。"""

    def run_once(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        host = self.get_param_str(params, "host", "").strip()
        if not host:
            return self.create_failure_result(
                "参数不完整", error="需要提供 host（IP 或主机名）"
            )

        count = max(1, self.get_param_int(params, "count", 1))
        timeout_sec = max(1, self.get_param_int(params, "timeout_sec", 5))

        if sys.platform == "win32":
            # -n 次数；-w 单次等待毫秒
            wait_ms = max(1000, timeout_sec * 1000)
            cmd: List[str] = ["ping", "-n", str(count), "-w", str(wait_ms), host]
        elif sys.platform == "darwin":
            cmd = ["ping", "-c", str(count), host]
        else:
            # GNU ping：-W 为等待响应超时（秒）
            cmd = ["ping", "-c", str(count), "-W", str(timeout_sec), host]

        ctx.log_info(f"Ping {host}（本机执行）: {' '.join(cmd)}")

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_sec + 10,
            )
        except subprocess.TimeoutExpired:
            return self.create_failure_result(
                f"Ping {host} 超时",
                error=f"超过 {timeout_sec + 10}s",
                data={"host": host},
            )
        except OSError as e:
            return self.create_failure_result(
                "无法执行 ping", error=str(e), data={"host": host}
            )

        out = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()
        if out:
            ctx.log_info(out[:1500] + ("…" if len(out) > 1500 else ""))
        if err:
            ctx.log_warning(err[:1500] + ("…" if len(err) > 1500 else ""))

        data: Dict[str, Any] = {
            "host": host,
            "returncode": proc.returncode,
            "stdout": out,
            "stderr": err,
        }

        if proc.returncode == 0:
            return self.create_success_result(data, f"Ping {host} 成功")

        return self.create_failure_result(
            f"Ping {host} 失败（退出码 {proc.returncode}）",
            error=err or out or f"exit {proc.returncode}",
            data=data,
        )
