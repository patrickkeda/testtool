"""
检查 S100 煲机告警：
1. /userdata/diagnostic-*.jsonl 必须存在。
2. diagnostic 无 fault_event → 通过。
3. diagnostic 有 fault_event → 必须成功查询 /log/usr/archive grep 结果才能继续判定。
4. diagnostic 含 Slam 类 fault_event → 不拦截（archive 含 IMU_DATA_ANOMALY 也放行）。
5. 非 Slam 类 fault_event → 按 diagnostic fault_event 拦截（舵机）。
6. 读取成功后可将 diagnostic 保存到本机 Result/diagnostic/{SN}_{远端文件名}。
"""

from __future__ import annotations

import json
import re
import shlex
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ...base import BaseStep, StepResult
from ...context import Context
from .ssh_exec import _load_pkey_from_file, resolve_private_key_file_path

_DEFAULT_DIR = "/userdata"
_DEFAULT_GLOB = "diagnostic-*.jsonl"
_DEFAULT_ARCHIVE_DIR = "/log/usr/archive"
_DEFAULT_SERVO_FAIL_MSG = "煲机时出现舵机异常请联系工程师处理"
_DEFAULT_LOCAL_OUTPUT_DIR = "Result/diagnostic"

_UNSAFE_FILENAME_CHARS = re.compile(r'[<>:"/\\|?\n\r\t]')

_ARCHIVE_FAULT_LINE_RE = re.compile(
    r"^\s*(\d+)\s+(\d{2}-\d{2})\s+([A-Z0-9_]+)(?:\s+(.*))?$"
)

_ARCHIVE_GREP_PIPELINE = (
    "grep -ahr \"fault_reporter.hpp:137\" ./ 2>/dev/null | "
    "sed -n '\n"
    "s/^\\([0-9][0-9]-[0-9][0-9]\\).* \\[FAULT\\] \\([A-Z_]*\\).*Timeout inputs: \\(.*?\\)$/\\1 \\2 \\3/p\n"
    "s/^\\([0-9][0-9]-[0-9][0-9]\\).* \\[FAULT\\] \\([A-Z_]*\\).*/\\1 \\2/p\n"
    "' | sort | uniq -c | sort -nr"
)


def _ssh_connect(
    *,
    host: str,
    port: int,
    username: str,
    key_path: str,
    password: str,
    connect_timeout: int,
    strict_host_key: bool,
):
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
    return client


def _ssh_exec_on_client(client, command: str, exec_timeout: int) -> Tuple[int, str, str]:
    _stdin, stdout, stderr = client.exec_command(command, timeout=exec_timeout)
    out_t = (stdout.read() or b"").decode("utf-8", errors="replace")
    err_t = (stderr.read() or b"").decode("utf-8", errors="replace")
    rc = stdout.channel.recv_exit_status()
    return rc, out_t, err_t


def _parse_fault_events(content: str) -> List[Dict[str, Any]]:
    faults: List[Dict[str, Any]] = []
    for line in content.splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            record = json.loads(text)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        if record.get("record_type") != "fault_event":
            continue
        faults.append(record)
    return faults


def _is_slam_fault(fault: Dict[str, Any]) -> bool:
    message = str(fault.get("message") or "").strip()
    return "slam" in message.lower()


def _has_slam_faults(faults: List[Dict[str, Any]]) -> bool:
    return any(_is_slam_fault(fault) for fault in faults)


def _non_slam_faults(faults: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    has_slam = _has_slam_faults(faults)
    result: List[Dict[str, Any]] = []
    for fault in faults:
        message = str(fault.get("message") or "").strip()
        if _is_slam_fault(fault):
            continue
        if has_slam and not message:
            continue
        result.append(fault)
    return result


def _parse_archive_fault_summary(content: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for line in content.splitlines():
        text = line.strip()
        if not text:
            continue
        match = _ARCHIVE_FAULT_LINE_RE.match(text)
        if not match:
            continue
        count = int(match.group(1))
        if count <= 0:
            continue
        fault_type = match.group(3).strip().upper()
        rows.append(
            {
                "count": count,
                "date": match.group(2),
                "fault_type": fault_type,
                "detail": (match.group(4) or "").strip(),
                "raw": text,
            }
        )
    return rows


def _find_archive_imu_hits(
    rows: List[Dict[str, Any]],
    *,
    imu_fault_type: str,
) -> List[Dict[str, Any]]:
    imu_key = imu_fault_type.strip().upper()
    return [
        row
        for row in rows
        if str(row.get("fault_type") or "").upper() == imu_key
    ]


def _build_archive_grep_cmd(archive_dir: str) -> str:
    inner = f"cd {archive_dir} && {_ARCHIVE_GREP_PIPELINE}"
    return "bash -lc " + shlex.quote(inner)


def _sanitize_filename_part(raw: str, *, fallback: str = "UNKNOWN") -> str:
    s = _UNSAFE_FILENAME_CHARS.sub("_", (raw or "").strip())
    s = s.rstrip(" .")
    return s[:120] if s else fallback


def _resolve_local_output_dir(raw: str) -> Path:
    text = (raw or _DEFAULT_LOCAL_OUTPUT_DIR).strip() or _DEFAULT_LOCAL_OUTPUT_DIR
    path = Path(text).expanduser()
    if path.is_absolute():
        path.mkdir(parents=True, exist_ok=True)
        return path

    candidates: List[Path] = [Path.cwd() / path]
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent
        candidates.extend([base / path, base / "_internal" / path])
    candidates.append(Path(__file__).resolve().parents[4] / path)

    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate.resolve()
        except OSError:
            continue

    fallback = Path.cwd() / path
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback.resolve()


def _build_local_diagnostic_path(
    *,
    sn: str,
    remote_file: str,
    output_dir: Path,
) -> Path:
    remote_name = Path(remote_file.replace("\\", "/")).name.strip() or "diagnostic.jsonl"
    if not remote_name.lower().startswith("diagnostic"):
        remote_name = f"diagnostic-{remote_name}"
    safe_sn = _sanitize_filename_part(sn, fallback="UNKNOWN_SN")
    local_name = f"{safe_sn}_{remote_name}"
    return output_dir / local_name


def _save_diagnostic_local(
    *,
    content: str,
    sn: str,
    remote_file: str,
    output_dir_raw: str,
) -> Tuple[Optional[Path], Optional[str]]:
    try:
        output_dir = _resolve_local_output_dir(output_dir_raw)
        local_path = _build_local_diagnostic_path(
            sn=sn,
            remote_file=remote_file,
            output_dir=output_dir,
        )
        local_path.write_text(content, encoding="utf-8")
        return local_path, None
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)


class CheckDiagnosticFaultStep(BaseStep):
    """SSH 检查 S100 diagnostic jsonl 与 /log/usr/archive fault_reporter 告警。"""

    def run_once(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        host = (
            self.get_param_str(params, "host", "").strip()
            or self.get_param_str(params, "robot_ip", "").strip()
            or str(ctx.get_data("robot_ip") or "").strip()
        )
        if not host:
            return self.create_failure_result(
                "缺少 S100 地址",
                error="HOST_MISSING",
            )

        username = self.get_param_str(params, "username", "root").strip() or "root"
        port = max(1, self.get_param_int(params, "port", 22))
        password = self.get_param_str(params, "password", "").strip()
        key_file = resolve_private_key_file_path(params, ctx)
        key_path = str(Path(key_file).expanduser()) if key_file else ""
        strict_host = self.get_param_bool(params, "strict_host_key", False)
        connect_timeout = max(5, self.get_param_int(params, "connect_timeout", 25))
        exec_timeout = max(10, self.get_param_int(params, "exec_timeout", 60))
        archive_exec_timeout = max(
            exec_timeout,
            self.get_param_int(params, "archive_exec_timeout", 120),
        )
        remote_dir = self.get_param_str(params, "remote_dir", _DEFAULT_DIR).strip() or _DEFAULT_DIR
        file_glob = self.get_param_str(params, "file_glob", _DEFAULT_GLOB).strip() or _DEFAULT_GLOB
        archive_dir = (
            self.get_param_str(params, "archive_dir", _DEFAULT_ARCHIVE_DIR).strip()
            or _DEFAULT_ARCHIVE_DIR
        )
        imu_fault_type = (
            self.get_param_str(params, "imu_fault_type", "IMU_DATA_ANOMALY").strip()
            or "IMU_DATA_ANOMALY"
        )
        servo_fail_message = (
            self.get_param_str(params, "fail_message", _DEFAULT_SERVO_FAIL_MSG).strip()
            or self.get_param_str(params, "servo_fail_message", _DEFAULT_SERVO_FAIL_MSG).strip()
            or _DEFAULT_SERVO_FAIL_MSG
        )
        check_archive = self.get_param_bool(params, "check_archive", True)
        save_local = self.get_param_bool(params, "save_local", True)
        local_output_dir = (
            self.get_param_str(params, "local_output_dir", _DEFAULT_LOCAL_OUTPUT_DIR).strip()
            or _DEFAULT_LOCAL_OUTPUT_DIR
        )
        fail_on_save_error = self.get_param_bool(params, "fail_on_save_error", False)

        list_cmd = (
            "bash -lc "
            + shlex.quote(
                f"ls -1t {remote_dir}/{file_glob} 2>/dev/null | head -1 || true"
            )
        )
        archive_cmd = _build_archive_grep_cmd(archive_dir)
        local_diagnostic_path: Optional[Path] = None
        local_save_error: Optional[str] = None

        try:
            client = _ssh_connect(
                host=host,
                port=port,
                username=username,
                key_path=key_path,
                password=password,
                connect_timeout=connect_timeout,
                strict_host_key=strict_host,
            )
        except Exception as exc:  # noqa: BLE001
            return self.create_failure_result(
                f"SSH 连接 S100 失败: {exc}",
                error=str(exc),
            )

        try:
            _rc, out_t, _err_t = _ssh_exec_on_client(client, list_cmd, exec_timeout)
            remote_file = out_t.strip().splitlines()[0].strip() if out_t.strip() else ""
            if not remote_file:
                msg = f"未找到 {remote_dir}/{file_glob}，请确认已完成煲机并生成 diagnostic 记录"
                ctx.log_error(msg)
                return self.create_failure_result(
                    msg,
                    error="DIAGNOSTIC_FILE_MISSING",
                )

            cat_cmd = "bash -lc " + shlex.quote(f"cat {remote_file}")
            cat_rc, cat_out, cat_err = _ssh_exec_on_client(client, cat_cmd, exec_timeout)
            if cat_rc != 0:
                return self.create_failure_result(
                    f"读取 {remote_file} 失败 (exit={cat_rc}): {cat_err.strip() or cat_out.strip()}",
                    error="DIAGNOSTIC_READ_FAILED",
                )

            sn = (
                self.get_param_str(params, "sn", "").strip()
                or str(ctx.get_data("sn") or "").strip()
                or str(ctx.get_sn() or "").strip()
                or "UNKNOWN_SN"
            )
            if save_local:
                local_diagnostic_path, local_save_error = _save_diagnostic_local(
                    content=cat_out,
                    sn=sn,
                    remote_file=remote_file,
                    output_dir_raw=local_output_dir,
                )
                if local_diagnostic_path is not None:
                    ctx.log_info(f"diagnostic 已保存到本机: {local_diagnostic_path}")
                    ctx.set_data("diagnostic_local_path", str(local_diagnostic_path))
                elif local_save_error:
                    msg = f"diagnostic 保存到本机失败: {local_save_error}"
                    if fail_on_save_error:
                        ctx.log_error(msg)
                        return self.create_failure_result(
                            msg,
                            error="DIAGNOSTIC_SAVE_FAILED",
                        )
                    ctx.log_warning(msg)

            faults = _parse_fault_events(cat_out)
            has_slam = _has_slam_faults(faults)
            other_faults = _non_slam_faults(faults)
            need_archive = check_archive and bool(faults)

            archive_out = ""
            archive_err = ""
            archive_rc = 0
            if need_archive:
                archive_rc, archive_out, archive_err = _ssh_exec_on_client(
                    client,
                    archive_cmd,
                    archive_exec_timeout,
                )
                if archive_rc != 0:
                    detail = archive_err.strip() or archive_out.strip()
                    msg = f"archive 告警日志查询失败 (exit={archive_rc})"
                    if detail:
                        msg = f"{msg}: {detail}"
                    ctx.log_error(msg)
                    return self.create_failure_result(
                        msg,
                        error="ARCHIVE_QUERY_FAILED",
                    )
        except Exception as exc:  # noqa: BLE001
            return self.create_failure_result(
                f"读取 S100 告警数据失败: {exc}",
                error=str(exc),
            )
        finally:
            client.close()

        archive_rows = _parse_archive_fault_summary(archive_out)
        imu_hits = _find_archive_imu_hits(
            archive_rows,
            imu_fault_type=imu_fault_type,
        )

        result_data: Dict[str, Any] = {
            "remote_file": remote_file,
            "local_diagnostic_path": str(local_diagnostic_path) if local_diagnostic_path else None,
            "local_save_error": local_save_error,
            "fault_count": len(faults),
            "faults": faults[:10],
            "has_slam_fault": has_slam,
            "non_slam_fault_count": len(other_faults),
            "archive_checked": need_archive,
            "archive_dir": archive_dir,
            "archive_rc": archive_rc,
            "archive_fault_rows": archive_rows[:20],
            "archive_imu_hits": imu_hits,
        }
        if archive_err.strip():
            result_data["archive_stderr"] = archive_err.strip()

        if not faults:
            msg = f"告警检查通过: {remote_file} 无 fault_event"
            ctx.log_info(msg)
            return self.create_success_result(message=msg, data=result_data)

        if other_faults:
            detail = self._format_fault_summary(other_faults[0])
            message = servo_fail_message
            if detail:
                message = f"{servo_fail_message}（{detail}）"
            ctx.log_error(message)
            return self.create_failure_result(
                message,
                error="DIAGNOSTIC_FAULT_EVENT",
                data=result_data,
            )

        if imu_hits:
            ctx.log_info(
                f"archive 含 {imu_fault_type}（{imu_hits[0].get('raw', '')}），按规则不拦截"
            )

        msg = f"告警检查通过: {remote_file} 含 Slam 告警，archive 查询成功，不拦截"
        ctx.log_info(msg)
        return self.create_success_result(message=msg, data=result_data)

    @staticmethod
    def _format_fault_summary(fault: Dict[str, Any]) -> str:
        fault_id = str(fault.get("fault_id") or "").strip()
        event = str(fault.get("event") or "").strip()
        message = str(fault.get("message") or "").strip()
        parts = [p for p in (fault_id, event, message) if p]
        return " ".join(parts)
