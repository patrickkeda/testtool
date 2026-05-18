"""
在本机执行 set_zenoh_mode_client.py：通过系统 SSH 将 Zenoh 会话切为 client 模式。

与 OTA 部署工具中逻辑对齐：``enforce_commit_hash_check=true`` 时不传 ``--skip-hash-check``；
否则传入 ``--skip-hash-check``。可选 ``ssh_key_file``；未设置时可使用上下文 ``ssh_private_key_path``。

可选 ``params``：``script_attempt_max``（默认 1）、``retry_interval_sec``（默认 5）、
``retry_if_output_contains``（`|` 分隔子串）。

脚本成功后的「是否可跳过上下电」探测（二选一，**SSH 优先**）：

- 若配置了 ``post_success_ssh_command``（如 ``systemctl is-active vita01.target``），则经 **Paramiko SSH**
  登录 X5（与 MobaXterm 会话等价）执行该命令；**退出码 0** 时写入 ``zenoh_need_repower`` = ``"false"``。
  可选 ``post_success_ssh_host``（默认 ``x5_host``）、``post_success_ssh_user``（默认 ``root``）、
  ``post_success_ssh_port``、``post_success_ssh_connect_timeout_sec``、``post_success_ssh_exec_timeout_sec``；
  私钥与 ``set_zenoh`` 一致：``ssh_key_file`` 或上下文 ``ssh_private_key_path``。
- 否则若配置了 ``post_success_ping_host``（如 ``${x5_ip}``），则对本机 ping；ping 成功则 ``"false"``。
- 均未配置时默认 ``"true"``，保持原上下电流程。

配合 YAML ``condition: '${zenoh_need_repower}'``：仅在需要上下电时执行 PLC 与长等待步骤。
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

from ...base import BaseStep, StepResult
from ...context import Context
from ...utils import resolve_placeholders_in_params
from ..cases.ssh_exec import _load_pkey_from_file


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


def _run_zenoh_subprocess(cmd: List[str], timeout_sec: int) -> subprocess.CompletedProcess:
    run_kw: Dict[str, Any] = dict(
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_sec,
    )
    if sys.platform == "win32" and hasattr(subprocess, "CREATE_NO_WINDOW"):
        run_kw["creationflags"] = subprocess.CREATE_NO_WINDOW
    return subprocess.run(cmd, **run_kw)


def _icmp_ping_returncode(host: str, count: int, timeout_sec: int) -> int:
    """返回 ping 进程退出码（0 表示至少收到应答）。"""
    if sys.platform == "win32":
        wait_ms = max(1000, timeout_sec * 1000)
        cmd: List[str] = ["ping", "-n", str(count), "-w", str(wait_ms), host]
    elif sys.platform == "darwin":
        cmd = ["ping", "-c", str(count), host]
    else:
        cmd = ["ping", "-c", str(count), "-W", str(timeout_sec), host]
    run_kw: Dict[str, Any] = dict(
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_sec + 10,
    )
    if sys.platform == "win32" and hasattr(subprocess, "CREATE_NO_WINDOW"):
        run_kw["creationflags"] = subprocess.CREATE_NO_WINDOW
    proc = subprocess.run(cmd, **run_kw)
    return int(proc.returncode)


def _zenoh_ssh_exec_exit_code(
    *,
    host: str,
    port: int,
    username: str,
    command: str,
    key_path: str,
    connect_timeout: int,
    exec_timeout: int,
    strict_host_key: bool,
) -> tuple[int, str, str]:
    """SSH 登录后执行一条命令，返回 (exit_status, stdout_tail, stderr_tail)。"""
    import paramiko

    if not key_path or not os.path.isfile(Path(key_path).expanduser()):
        return -1, "", "无有效私钥文件，跳过 SSH 探测"

    pkey = _load_pkey_from_file(key_path)
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(
        paramiko.RejectPolicy() if strict_host_key else paramiko.AutoAddPolicy()
    )
    try:
        client.connect(
            hostname=host,
            port=port,
            username=username,
            pkey=pkey,
            timeout=connect_timeout,
            allow_agent=False,
            look_for_keys=False,
        )
        stdin, stdout, stderr = client.exec_command(command, timeout=exec_timeout)
        try:
            stdin.close()
        except Exception:
            pass
        out_b = stdout.read() or b""
        err_b = stderr.read() or b""
        code = int(stdout.channel.recv_exit_status())
        out = out_b.decode("utf-8", errors="replace").strip()
        err = err_b.decode("utf-8", errors="replace").strip()
        tail_o = out[-1500:] if out else ""
        tail_e = err[-1500:] if err else ""
        return code, tail_o, tail_e
    finally:
        try:
            client.close()
        except Exception:
            pass


class SetZenohClientModeStep(BaseStep):
    """本机子进程执行 set_zenoh_mode_client.py。"""

    def _post_zenoh_success_probe(self, ctx: Context, params: Dict[str, Any]) -> None:
        """脚本成功后：可选 SSH 或 ping 探测，写入 ``zenoh_need_repower`` 供 YAML ``condition`` 使用。"""
        ssh_cmd_raw = self.get_param_str(params, "post_success_ssh_command", "").strip()
        if ssh_cmd_raw:
            try:
                import paramiko  # noqa: F401  # 与 case.ssh_exec 一致，需单独安装
            except ImportError:
                ctx.set_data("zenoh_need_repower", "true")
                ctx.log_warning(
                    "SetZenohClient: 已配置 post_success_ssh_command 但未安装 paramiko，默认需要上下电"
                )
                return
            cmd_resolved = str(
                resolve_placeholders_in_params({"c": ssh_cmd_raw}, ctx).get("c", ssh_cmd_raw)
            ).strip()
            if not cmd_resolved:
                ctx.set_data("zenoh_need_repower", "true")
                ctx.log_warning(
                    "SetZenohClient: post_success_ssh_command 展开为空，默认需要上下电"
                )
                return
            x5_default = self.get_param_str(params, "x5_host", "").strip() or "192.168.127.10"
            host_raw = self.get_param_str(params, "post_success_ssh_host", "").strip() or x5_default
            host = str(
                resolve_placeholders_in_params({"h": host_raw}, ctx).get("h", host_raw)
            ).strip()
            if not host:
                ctx.set_data("zenoh_need_repower", "true")
                ctx.log_warning("SetZenohClient: SSH 目标主机展开为空，默认需要上下电")
                return
            user = self.get_param_str(params, "post_success_ssh_user", "root").strip() or "root"
            port = max(1, self.get_param_int(params, "post_success_ssh_port", 22))
            cto = max(5, self.get_param_int(params, "post_success_ssh_connect_timeout_sec", 20))
            eto = max(5, self.get_param_int(params, "post_success_ssh_exec_timeout_sec", 45))
            strict_hk = self.get_param_bool(params, "post_success_ssh_strict_host_key", False)
            key_file = self.get_param_str(params, "ssh_key_file", "").strip()
            if not key_file:
                fb = ctx.get_data("ssh_private_key_path")
                key_file = str(fb).strip() if fb not in (None, "") else ""
            key_path = str(Path(key_file).expanduser()) if key_file else ""
            ctx.log_info(
                f"SetZenohClient: 脚本成功，SSH {user}@{host}:{port} 执行探测命令 …"
            )
            try:
                exit_st, out_t, err_t = _zenoh_ssh_exec_exit_code(
                    host=host,
                    port=port,
                    username=user,
                    command=cmd_resolved,
                    key_path=key_path,
                    connect_timeout=cto,
                    exec_timeout=eto,
                    strict_host_key=strict_hk,
                )
            except Exception as exc:  # noqa: BLE001
                ctx.set_data("zenoh_need_repower", "true")
                ctx.log_warning(
                    f"SetZenohClient: SSH 探测异常，默认需要上下电: {exc}"
                )
                return
            if exit_st == 0:
                ctx.set_data("zenoh_need_repower", "false")
                ctx.log_info(
                    "SetZenohClient: SSH 探测成功（exit 0），后续可跳过 PLC 上下电与长等待"
                )
            else:
                ctx.set_data("zenoh_need_repower", "true")
                detail = err_t or out_t or f"exit {exit_st}"
                ctx.log_warning(
                    f"SetZenohClient: SSH 探测未通过（exit {exit_st}），将执行上下电与等待；"
                    f"输出摘要: {detail[:500]}"
                )
            return

        raw = self.get_param_str(params, "post_success_ping_host", "").strip()
        if not raw:
            ctx.set_data("zenoh_need_repower", "true")
            ctx.log_info("SetZenohClient: 未配置 post_success_ssh_command 与 post_success_ping_host，默认需要上下电")
            return
        host = str(resolve_placeholders_in_params({"h": raw}, ctx).get("h", "")).strip()
        if not host:
            ctx.set_data("zenoh_need_repower", "true")
            ctx.log_warning("SetZenohClient: post_success_ping_host 展开为空，默认需要上下电")
            return
        ping_to = max(1, self.get_param_int(params, "post_success_ping_timeout_sec", 3))
        count = max(1, self.get_param_int(params, "post_success_ping_count", 1))
        ctx.log_info(f"SetZenohClient: 脚本成功，探测 {host} ping …")
        try:
            rc = _icmp_ping_returncode(host, count, ping_to)
        except Exception as ex:  # noqa: BLE001
            ctx.set_data("zenoh_need_repower", "true")
            ctx.log_warning(f"SetZenohClient: ping {host} 异常，默认需要上下电: {ex}")
            return
        if rc == 0:
            ctx.set_data("zenoh_need_repower", "false")
            ctx.log_info(f"SetZenohClient: ping {host} 成功，后续可跳过 PLC 上下电与长等待")
        else:
            ctx.set_data("zenoh_need_repower", "true")
            ctx.log_warning(
                f"SetZenohClient: ping {host} 失败 (exit {rc})，将执行 PLC 上下电与等待"
            )

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
        # 脚本进程最多尝试次数（例如 4 次）；成功即返回。
        attempt_max = max(1, self.get_param_int(params, "script_attempt_max", 1))
        retry_interval = max(0, self.get_param_int(params, "retry_interval_sec", 5))
        # 失败时仅当合并输出（不区分大小写）包含任一子串才继续重试；`|` 分隔多个
        retry_raw = self.get_param_str(params, "retry_if_output_contains", "").strip().lower()
        retry_needles = [p.strip() for p in retry_raw.split("|") if p.strip()]

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

        for att in range(1, attempt_max + 1):
            ctx.log_info(f"SetZenohClient 第 {att}/{attempt_max} 次执行 …")
            try:
                proc = _run_zenoh_subprocess(cmd, timeout_sec)
            except subprocess.TimeoutExpired:
                return self.create_failure_result(
                    f"Zenoh 脚本超时（>{timeout_sec}s）",
                    error="TimeoutExpired",
                    data={"cmd": cmd, "attempt": att},
                )
            except OSError as e:
                return self.create_failure_result(
                    "无法启动子进程（检查 Python / 权限）",
                    error=str(e),
                    data={"cmd": cmd, "attempt": att},
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
                "attempt": att,
                "attempt_max": attempt_max,
            }

            if proc.returncode == 0:
                self._post_zenoh_success_probe(ctx, params)
                data["zenoh_need_repower"] = ctx.get_data("zenoh_need_repower", "")
                return self.create_success_result(data, "set_zenoh_mode_client 执行成功")

            combined = f"{out}\n{err}".lower()
            can_retry = (
                att < attempt_max
                and bool(retry_needles)
                and any(n in combined for n in retry_needles)
            )
            if can_retry:
                ctx.log_warning(
                    f"SetZenohClient 第 {att} 次失败（输出含子串 {retry_needles!r}），"
                    f"{retry_interval} 秒后重试 …"
                )
                time.sleep(retry_interval)
                continue

            return self.create_failure_result(
                f"Zenoh 脚本失败（退出码 {proc.returncode}，第 {att}/{attempt_max} 次）",
                error=err or out or f"exit {proc.returncode}",
                data=data,
            )
