"""
在本机执行 set_zenoh_mode_client.py：通过系统 SSH 将 Zenoh 会话切为 client 模式。

与 OTA 部署工具中逻辑对齐：``enforce_commit_hash_check=true`` 时不传 ``--skip-hash-check``；
否则传入 ``--skip-hash-check``。可选 ``ssh_key_file``；未设置时可使用上下文 ``ssh_private_key_path``。
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

from ...base import BaseStep, StepResult
from ...context import Context


def _resolve_local_script(raw: str) -> str:
    s = (raw or "").strip()
    if not s:
        return s
    p = Path(s).expanduser()
    try:
        if p.is_file():
            return str(p.resolve())
    except OSError:
        pass
    if p.is_absolute():
        return s
    for c in (Path.cwd() / s, Path(__file__).resolve().parents[4] / s):
        try:
            if c.is_file():
                return str(c.resolve())
        except OSError:
            continue
    return str(p)


class SetZenohClientModeStep(BaseStep):
    """本机子进程执行 set_zenoh_mode_client.py。"""

    def run_once(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        script_raw = self.get_param_str(params, "script_path", "").strip()
        script = _resolve_local_script(script_raw)
        if not script or not os.path.isfile(script):
            return self.create_failure_result(
                "脚本路径无效",
                error=f"找不到文件: {script_raw or '(空)'}",
                data={"script_path": script_raw},
            )

        s100_host = self.get_param_str(params, "s100_host", "").strip()
        if not s100_host:
            s100_host = str(ctx.get_data("robot_ip", "") or "").strip()
        if not s100_host:
            return self.create_failure_result(
                "缺少 S100 地址",
                error="请在 params 中设置 s100_host，或在上下文中设置 robot_ip",
            )

        x5_host = self.get_param_str(params, "x5_host", "").strip() or "192.168.127.10"

        enforce = self.get_param_bool(params, "enforce_commit_hash_check", False)

        key_file = self.get_param_str(params, "ssh_key_file", "").strip()
        if not key_file:
            fb = ctx.get_data("ssh_private_key_path")
            key_file = str(fb).strip() if fb not in (None, "") else ""

        timeout_sec = max(60, self.get_param_int(params, "subprocess_timeout_sec", 900))

        cmd: List[str] = [
            sys.executable,
            script,
            "--s100-host",
            s100_host,
            "--x5-host",
            x5_host,
        ]
        if key_file and os.path.isfile(Path(key_file).expanduser()):
            cmd.extend(["--key", str(Path(key_file).expanduser().resolve())])
        if not enforce:
            cmd.append("--skip-hash-check")

        ctx.log_info("SetZenohClient: " + " ".join(shlex.quote(c) for c in cmd))

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_sec,
            )
        except subprocess.TimeoutExpired:
            return self.create_failure_result(
                f"Zenoh 脚本超时（>{timeout_sec}s）",
                error="TimeoutExpired",
                data={"cmd": cmd},
            )
        except OSError as e:
            return self.create_failure_result(
                "无法启动子进程（检查 Python / 权限）",
                error=str(e),
                data={"cmd": cmd},
            )

        out = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()
        if out:
            ctx.log_info(out[:4000] + ("…" if len(out) > 4000 else ""))
        if err:
            ctx.log_warning(err[:2000] + ("…" if len(err) > 2000 else ""))

        data: Dict[str, Any] = {
            "returncode": proc.returncode,
            "stdout_tail": out[-2000:],
            "stderr_tail": err[-2000:],
        }

        if proc.returncode == 0:
            return self.create_success_result(data, "set_zenoh_mode_client 执行成功")

        return self.create_failure_result(
            f"Zenoh 脚本失败（退出码 {proc.returncode}）",
            error=err or out or f"exit {proc.returncode}",
            data=data,
        )
