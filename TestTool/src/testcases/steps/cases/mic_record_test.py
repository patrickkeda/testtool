"""
经跳板机 SSH 在目标设备上执行录音命令（如 X5 arecord），并按输出判定是否打开声卡成功。

认证与 utility.ssh_exec 一致：password、private_key_file、private_key_env 三选一。
不要将私钥明文写入提交到仓库的 YAML。
未在步骤中填写 private_key_file 时，使用「配置 → 测试站 → 私钥配置」中的默认私钥路径。
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

from ...base import BaseStep, StepResult
from ...context import Context
from src.drivers.ssh.jump_ssh import JumpSSHSession, load_pkey_from_file, load_pkey_from_string
from .ssh_exec import resolve_private_key_file_path


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
            import paramiko  # noqa: F401
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
        require_zero_exit = self.get_param_bool(params, "require_zero_exit", True)

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
                pkey = load_pkey_from_file(key_file)
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
                pkey = load_pkey_from_string(raw)
            except Exception as e:  # noqa: BLE001
                return StepResult(
                    passed=False,
                    message="解析环境变量私钥失败",
                    error=str(e),
                    error_code="MIC_RECORD_KEY_PARSE",
                )

        try:
            ctx.log_info(f"SSH 跳板连接 {username}@{jump_host}:{jump_port} …")
            ctx.log_info(
                f"经跳板连接目标 {username}@{target_host}:{target_port} 并执行录音命令 …"
            )
            with JumpSSHSession.connect(
                jump_host=jump_host,
                target_host=target_host,
                username=username,
                pkey=pkey,
                password=password_str,
                jump_port=jump_port,
                target_port=target_port,
                connect_timeout=connect_timeout,
                strict_host_key=strict_host,
            ) as sess:
                exit_code, full_output = sess.exec(command, exec_timeout=exec_timeout)

            combined = full_output or ""
            ctx.log_info(f"录音命令退出码: {exit_code}")
            if full_output:
                preview = full_output[:2000] + ("…" if len(full_output) > 2000 else "")
                ctx.log_info(f"合并输出: {preview}")

            data: Dict[str, Any] = {
                "exit_code": exit_code,
                "stdout": full_output,
                "stderr": "",
                "combined": full_output,
            }

            has_success = bool(success_needle and success_needle in combined)
            if has_success and (not require_zero_exit or exit_code == 0):
                ctx.log_info("[OK] [状态: 正常] X5 录音命令执行成功")
                return StepResult(
                    passed=True,
                    message="X5 录音命令执行成功（正常）",
                    data=data,
                )

            if has_success and require_zero_exit and exit_code != 0:
                return StepResult(
                    passed=False,
                    message=f"出现成功关键字但退出码非 0 (exit={exit_code})",
                    error=full_output or f"exit {exit_code}",
                    error_code="MIC_RECORD_NONZERO",
                    data=data,
                )

            hay = combined.lower() if failure_ignore_case else combined
            for needle in failure_needles:
                if not needle:
                    continue
                n = needle.lower() if failure_ignore_case else needle
                if n in hay:
                    ctx.log_error(
                        "[FAIL] [状态: 异常] X5 找不到声卡或打开音频设备失败"
                    )
                    return StepResult(
                        passed=False,
                        message="X5 找不到声卡或打开音频设备失败（异常）",
                        error=full_output or needle,
                        error_code="MIC_RECORD_DEVICE_ERROR",
                        data=data,
                    )

            ctx.log_warning("[WARN] [状态: 未知] 出现未预期的输出")
            return StepResult(
                passed=False,
                message="出现未预期的输出（未知）",
                error=full_output or "无输出",
                error_code="MIC_RECORD_UNEXPECTED",
                data=data,
            )

        except Exception as e:  # noqa: BLE001
            import paramiko

            if isinstance(e, paramiko.AuthenticationException):
                return StepResult(
                    passed=False,
                    message="SSH 认证失败",
                    error=str(e),
                    error_code="MIC_RECORD_AUTH",
                )
            return StepResult(
                passed=False,
                message="录音 SSH 执行异常",
                error=str(e),
                error_code="MIC_RECORD_EXCEPTION",
            )
