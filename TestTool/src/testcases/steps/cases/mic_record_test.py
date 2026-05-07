"""
经跳板机 SSH 在目标设备上执行录音命令（如 X5 arecord），并按输出判定是否打开声卡成功。

认证与 utility.ssh_exec 一致：password、private_key_file、private_key_env 三选一。
不要将私钥明文写入提交到仓库的 YAML。
未在步骤中填写 private_key_file 时，使用应用配置「SSH」页签中的默认私钥路径。
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

from ...base import BaseStep, StepResult
from ...context import Context
from .ssh_exec import (
    _load_pkey_from_file,
    _load_pkey_from_string,
    resolve_private_key_file_path,
)


def _step_timeout_seconds(step_timeout: Any) -> int:
    """Seq 步骤 timeout 多为毫秒；大于 1000 时按毫秒换算为秒。"""
    if step_timeout is None:
        return 30
    try:
        t = int(step_timeout)
    except (TypeError, ValueError):
        return 30
    if t > 1000:
        return max(1, t // 1000)
    return max(1, t)


def _parse_failure_substrings(params: Dict[str, Any]) -> List[str]:
    raw = params.get("failure_substrings")
    if raw is None:
        return ["audio open error", "No such file or directory"]
    if isinstance(raw, str):
        return [raw.strip()] if raw.strip() else []
    if isinstance(raw, (list, tuple)):
        return [str(x).strip() for x in raw if str(x).strip()]
    return []


class MicRecordSshStep(BaseStep):
    """跳板 SSH → 目标机执行录音命令并解析输出。"""

    def run_once(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        try:
            import paramiko
        except ImportError:
            return StepResult(
                passed=False,
                message="未安装 paramiko",
                error="请执行: pip install paramiko",
                error_code="MIC_RECORD_NO_PARAMIKO",
            )

        jump_host = self.get_param_str(params, "jump_host", "").strip()
        target_host = self.get_param_str(params, "target_host", "").strip()
        username = self.get_param_str(params, "username", "").strip()
        command = self.get_param_str(
            params,
            "command",
            "arecord -D remap8ch -c 8 -r 16000 -f S16_LE -d 5 /tmp/test.wav",
        ).strip()

        jump_port = self.get_param_int(params, "jump_port", 22)
        target_port = self.get_param_int(params, "target_port", 22)
        success_needle = self.get_param_str(params, "success_substring", "Recording WAVE")
        failure_needles = _parse_failure_substrings(params)
        failure_ignore_case = self.get_param_bool(
            params, "failure_substrings_ignore_case", False
        )

        password = params.get("password")
        password_str = str(password).strip() if password not in (None, "") else ""
        key_file = resolve_private_key_file_path(params, ctx)
        key_env = self.get_param_str(params, "private_key_env", "").strip()
        strict_host = self.get_param_bool(params, "strict_host_key", False)

        eff_sec = _step_timeout_seconds(self.timeout)
        connect_timeout = self.get_param_int(
            params, "connect_timeout", min(max(eff_sec, 5), 120)
        )
        exec_timeout = self.get_param_int(
            params, "exec_timeout", max(eff_sec, 30)
        )

        if not jump_host or not target_host or not username or not command:
            return StepResult(
                passed=False,
                message="参数不完整",
                error="需要提供 jump_host、target_host、username、command",
                error_code="MIC_RECORD_BAD_PARAMS",
            )

        auth_modes = sum(bool(x) for x in (password_str, key_file, key_env))
        if auth_modes == 0:
            return StepResult(
                passed=False,
                message="未配置认证方式",
                error="请设置 password、private_key_file 或 private_key_env 之一",
                error_code="MIC_RECORD_NO_AUTH",
            )

        pkey = None
        if key_file:
            try:
                pkey = _load_pkey_from_file(key_file)
            except Exception as e:  # noqa: BLE001
                return StepResult(
                    passed=False,
                    message="加载私钥文件失败",
                    error=str(e),
                    error_code="MIC_RECORD_KEY_FILE",
                )
        elif key_env:
            raw = os.environ.get(key_env, "")
            if not raw.strip():
                return StepResult(
                    passed=False,
                    message="环境变量中无私钥",
                    error=f"环境变量 {key_env} 为空或未设置",
                    error_code="MIC_RECORD_KEY_ENV",
                )
            try:
                pkey = _load_pkey_from_string(raw)
            except Exception as e:  # noqa: BLE001
                return StepResult(
                    passed=False,
                    message="解析环境变量私钥失败",
                    error=str(e),
                    error_code="MIC_RECORD_KEY_PARSE",
                )

        policy = (
            paramiko.RejectPolicy() if strict_host else paramiko.AutoAddPolicy()
        )

        jump_client = paramiko.SSHClient()
        target_client = paramiko.SSHClient()
        jump_client.set_missing_host_key_policy(policy)
        target_client.set_missing_host_key_policy(policy)

        try:
            connect_kw: Dict[str, Any] = {
                "hostname": jump_host,
                "port": jump_port,
                "username": username,
                "timeout": connect_timeout,
                "allow_agent": False,
                "look_for_keys": False,
            }
            if pkey is not None:
                connect_kw["pkey"] = pkey
            if password_str:
                connect_kw["password"] = password_str

            ctx.log_info(f"SSH 跳板连接 {username}@{jump_host}:{jump_port} …")
            jump_client.connect(**connect_kw)

            jump_transport = jump_client.get_transport()
            if jump_transport is None:
                return StepResult(
                    passed=False,
                    message="跳板 Transport 不可用",
                    error_code="MIC_RECORD_NO_TRANSPORT",
                )

            channel = jump_transport.open_channel(
                "direct-tcpip",
                dest_addr=(target_host, target_port),
                src_addr=("127.0.0.1", 0),
            )

            ctx.log_info(
                f"经跳板连接目标 {username}@{target_host}:{target_port} 并执行录音命令 …"
            )
            target_connect: Dict[str, Any] = {
                "hostname": target_host,
                "port": target_port,
                "username": username,
                "timeout": connect_timeout,
                "sock": channel,
                "allow_agent": False,
                "look_for_keys": False,
            }
            if pkey is not None:
                target_connect["pkey"] = pkey
            if password_str:
                target_connect["password"] = password_str
            target_client.connect(**target_connect)

            stdin, stdout, stderr = target_client.exec_command(
                command, timeout=exec_timeout
            )
            _ = stdin
            out_b = stdout.read()
            err_b = stderr.read()
            exit_code = stdout.channel.recv_exit_status()

            out_t = out_b.decode(errors="replace")
            err_t = err_b.decode(errors="replace")
            combined = out_t + err_t
            full_output = combined.strip()

            ctx.log_info(f"录音命令退出码: {exit_code}")
            if full_output:
                preview = full_output[:2000] + ("…" if len(full_output) > 2000 else "")
                ctx.log_info(f"合并输出: {preview}")

            data: Dict[str, Any] = {
                "exit_code": exit_code,
                "stdout": out_t.strip(),
                "stderr": err_t.strip(),
                "combined": full_output,
            }

            # 与独立脚本一致：先判成功，再判典型声卡/设备错误，其余为未知失败（驱动 Seq Pass/Fail）
            if success_needle and success_needle in combined:
                ctx.log_info("✅ [状态: 正常] X5 录音命令执行成功")
                return StepResult(
                    passed=True,
                    message="X5 录音命令执行成功（正常）",
                    data=data,
                )

            hay = combined.lower() if failure_ignore_case else combined
            for needle in failure_needles:
                if not needle:
                    continue
                n = needle.lower() if failure_ignore_case else needle
                if n in hay:
                    ctx.log_error(
                        "❌ [状态: 异常] X5 找不到声卡或打开音频设备失败"
                    )
                    return StepResult(
                        passed=False,
                        message="X5 找不到声卡或打开音频设备失败（异常）",
                        error=full_output or needle,
                        error_code="MIC_RECORD_DEVICE_ERROR",
                        data=data,
                    )

            ctx.log_warning("⚠️ [状态: 未知] 出现未预期的输出")
            return StepResult(
                passed=False,
                message="出现未预期的输出（未知）",
                error=full_output or "无输出",
                error_code="MIC_RECORD_UNEXPECTED",
                data=data,
            )

        except paramiko.AuthenticationException as e:
            return StepResult(
                passed=False,
                message="SSH 认证失败",
                error=str(e),
                error_code="MIC_RECORD_AUTH",
            )
        except Exception as e:  # noqa: BLE001
            return StepResult(
                passed=False,
                message="录音 SSH 执行异常",
                error=str(e),
                error_code="MIC_RECORD_EXCEPTION",
            )
        finally:
            target_client.close()
            jump_client.close()
