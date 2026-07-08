"""
探测 S100 是否已完成 provisioning（lifecycle 退出码 4 = 已加密）。

始终返回步骤通过，并写入上下文 ``s100_need_provision``（``true`` / ``false``），
供序列 YAML ``condition: '${s100_need_provision}'`` 控制是否执行 copy_efuse / provision_step。
"""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any, Dict, Tuple

from ...base import BaseStep, StepResult
from ...context import Context
from .ssh_exec import _load_pkey_from_file, resolve_private_key_file_path

_LIFECYCLE_CMD = (
    "bash -lc "
    + shlex.quote(
        "chmod 777 /usr/hobot/bin/provision_tool 2>/dev/null; "
        "/usr/hobot/bin/provision_tool --get-lifecycle; "
        "echo __LIFECYCLE_RC__=$?"
    )
)

_ENCRYPTED_RC = 4


def _ssh_lifecycle_rc(
    *,
    host: str,
    port: int,
    username: str,
    key_path: str,
    password: str,
    connect_timeout: int,
    exec_timeout: int,
    strict_host_key: bool,
) -> Tuple[int, str, str]:
    import paramiko

    client = paramiko.SSHClient()
    if strict_host_key:
        client.load_system_host_keys()
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
    else:
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    connect_kw: Dict[str, Any] = {
        "hostname": host,
        "port": port,
        "username": username,
        "timeout": connect_timeout,
        "allow_agent": False,
        "look_for_keys": False,
    }
    if key_path:
        connect_kw["pkey"] = _load_pkey_from_file(key_path)
    elif password:
        connect_kw["password"] = password
    else:
        raise ValueError("缺少 SSH 认证：请配置测试站私钥或 password")

    client.connect(**connect_kw)
    try:
        _stdin, stdout, stderr = client.exec_command(
            _LIFECYCLE_CMD, timeout=exec_timeout
        )
        out_t = (stdout.read() or b"").decode("utf-8", errors="replace").strip()
        err_t = (stderr.read() or b"").decode("utf-8", errors="replace").strip()
        tool_rc = stdout.channel.recv_exit_status()
        lifecycle_rc = tool_rc
        for line in (out_t + "\n" + err_t).splitlines():
            if "__LIFECYCLE_RC__=" in line:
                try:
                    lifecycle_rc = int(line.rsplit("=", 1)[-1].strip())
                except ValueError:
                    pass
                break
        return lifecycle_rc, out_t, err_t
    finally:
        client.close()


class ProbeS100ProvisionStep(BaseStep):
    """SSH 查询 provision_tool lifecycle，设置 s100_need_provision 供后续步骤 condition 使用。"""

    def run_once(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        host = (
            self.get_param_str(params, "host", "").strip()
            or self.get_param_str(params, "robot_ip", "").strip()
            or str(ctx.get_data("robot_ip") or "").strip()
        )
        if not host:
            return self.create_failure_result(
                "缺少 S100 地址",
                error="缺少 host / robot_ip 或上下文 robot_ip",
            )

        username = self.get_param_str(params, "username", "root").strip() or "root"
        port = max(1, self.get_param_int(params, "port", 22))
        password = self.get_param_str(params, "password", "").strip()
        key_file = resolve_private_key_file_path(params, ctx)
        key_path = str(Path(key_file).expanduser()) if key_file else ""
        strict_host = self.get_param_bool(params, "strict_host_key", False)
        connect_timeout = max(5, self.get_param_int(params, "connect_timeout", 25))
        exec_timeout = max(10, self.get_param_int(params, "exec_timeout", 30))

        try:
            lifecycle_rc, out_t, err_t = _ssh_lifecycle_rc(
                host=host,
                port=port,
                username=username,
                key_path=key_path,
                password=password,
                connect_timeout=connect_timeout,
                exec_timeout=exec_timeout,
                strict_host_key=strict_host,
            )
        except Exception as exc:  # noqa: BLE001
            return self.create_failure_result(
                f"S100 lifecycle 探测失败: {exc}",
                error=str(exc),
            )

        encrypted = lifecycle_rc == _ENCRYPTED_RC
        need = not encrypted
        ctx.set_data("s100_need_provision", "true" if need else "false")
        ctx.set_data("s100_encrypted", encrypted)
        ctx.set_data("s100_encrypted_str", "true" if encrypted else "false")
        ctx.set_data("s100_lifecycle_rc", lifecycle_rc)

        if encrypted:
            msg = "S100 已加密 (lifecycle=4)，跳过 provisioning"
        else:
            msg = f"S100 未加密 (lifecycle rc={lifecycle_rc})，将执行 provisioning"

        return self.create_success_result(
            message=msg,
            data={
                "encrypted": encrypted,
                "s100_need_provision": need,
                "lifecycle_rc": lifecycle_rc,
                "stdout": out_t,
                "stderr": err_t,
            },
        )
