"""
通过 Paramiko SFTP 递归下载远端目录到本机，可选 SSH 执行删除远端目录并重建空目录。

用于 PVT 等流程：Hub 老化倒计时结束后，员工接回数据线，将板上 ``/ota/pvt_stress_test`` 等目录
同步到本地，目录名由 SN 与「倒计时开始时」写入上下文的时间戳拼接。

参数
----
host, username, port
    SSH 连接信息（与 ``utility.ssh_exec`` 一致）。
private_key_file
    私钥路径；未填时使用上下文 ``ssh_private_key_path``。
remote_dir
    远端目录绝对路径（如 ``/ota/pvt_stress_test``）。
local_parent_dir
    本机保存父目录；空则使用配置 ``ssh.burnin_data_save_dir``（上下文 ``ssh_burnin_data_save_dir``），
    仍为空则使用 ``Path.home() / "Downloads"``。
local_dir_name
    在 ``local_parent_dir`` 下创建的子目录名；支持 ``${sn}``、``${pvt_hub_countdown_started_at}`` 等
    （由 worker 在步骤前展开）。缺失的 PVT 常用键会用时间戳 / ``unknown`` / ``UNKNOWN_SN`` 等回退；
    其它未解析占位符会替换为 ``unknown_<键名>`` 并写警告日志，避免因单步调试或变量未设而失败。
delete_remote_after
    默认 ``true``：下载成功后经 SSH 执行 ``rm -rf <remote_dir>`` 再 ``mkdir -p <remote_dir>``，
    便于后续 MCAP 仍写入同一路径。
strict_host_key
    默认 ``false``（``AutoAddPolicy``）。
show_pull_progress
    默认 ``true``：在 TestTool GUI 下显示导出进度条，并在文案中标出本机保存目录（通常为
    ``用户/Downloads/<local_dir_name>``）。无 Qt 环境或 ``false`` 时跳过弹窗。
pull_progress_title
    进度条窗口标题（可选）。
retry_until_success
    默认 ``false``。为 ``true`` 时导出失败弹出「重试拉取 / 放弃」；选重试则反复拉取直至成功。
retry_delay_sec
    每次重试前等待秒数，默认 ``3``。
min_files_downloaded
    至少下载文件数；不足则视为失败（默认 ``0``；STRESS 建议 ``1``）。
retry_confirm_title / retry_confirm_message
    补拉确认框标题与正文（可选）。
"""

from __future__ import annotations

import os
import re
import shlex
import stat
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ...base import BaseStep, StepResult
from ...context import Context
from ...utils import resolve_template_string
from ..cases.ssh_exec import _load_pkey_from_file

_PLACEHOLDER = re.compile(r"\$\{([^}]+)\}")


def _safe_dir_name(raw: str) -> str:
    s = (raw or "").strip()
    if not s:
        return "pvt_ota_pull"
    for ch in '<>:"/\\|?\n\r\t':
        s = s.replace(ch, "_")
    s = s.rstrip(" .")
    return s[:200] if len(s) > 200 else s


def _resolve_local_dir_name(raw: str, ctx: Context) -> Tuple[str, Optional[str]]:
    """展开 local_dir_name 占位符；缺失时尽量用上下文回退，仍无法解析则返回错误说明。"""
    template = (raw or "").strip()
    if not template:
        template = "${sn}_${pvt_hub_countdown_started_at}_${pvt_hub_burnin_outcome}"

    name = resolve_template_string(template, ctx).strip()

    if "${sn}" in name:
        sn = (ctx.get_data("sn") or ctx.get_sn() or "").strip()
        if sn and sn.upper() != "NULL":
            name = name.replace("${sn}", sn)
        else:
            fb = "UNKNOWN_SN"
            ctx.log_warning(
                "上下文无有效 SN（未扫码或仍为 NULL），local_dir_name 中 ${sn} 将替换为 "
                f"{fb}；建议在 step_1 正常扫码后再拉取。"
            )
            name = name.replace("${sn}", fb)

    if "${pvt_hub_countdown_started_at}" in name:
        ts = ctx.get_data("pvt_hub_countdown_started_at")
        if ts:
            name = name.replace("${pvt_hub_countdown_started_at}", str(ts))
        else:
            fb = datetime.now().strftime("%Y%m%d_%H%M%S")
            ctx.log_warning(
                "上下文无 pvt_hub_countdown_started_at（未跑 Hub 倒计时或单步调试跳过），"
                f"目录名使用当前时间 {fb}"
            )
            name = name.replace("${pvt_hub_countdown_started_at}", fb)

    if "${pvt_hub_burnin_outcome}" in name:
        oc = ctx.get_data("pvt_hub_burnin_outcome")
        if oc:
            name = name.replace("${pvt_hub_burnin_outcome}", str(oc))
        else:
            ctx.log_warning(
                "上下文无 pvt_hub_burnin_outcome（倒计时未点「无异常/异常」或未跑倒计时步），"
                "目录名使用 unknown"
            )
            name = name.replace("${pvt_hub_burnin_outcome}", "unknown")

    # 其余任意 ${xxx}：用 unknown_ 片段替代，避免变量名拼写错误或单步调试导致本步失败
    if "${" in name:

        def _unknown_placeholder(m: re.Match) -> str:
            key = (m.group(1) or "").strip()
            tail = _safe_dir_name(key.replace(".", "_")) or "var"
            ctx.log_warning(
                f"local_dir_name 仍含未解析占位符 ${{{key}}}，已替换为 unknown_{tail}"
            )
            return f"unknown_{tail}"

        name = _PLACEHOLDER.sub(_unknown_placeholder, name)

    safe = _safe_dir_name(name)
    if not safe:
        return "", "展开后目录名为空"
    return safe, None


def _resolve_private_key(params: Dict[str, Any], ctx: Context) -> str:
    raw = str(params.get("private_key_file") or "").strip()
    if raw:
        return raw
    fb = ctx.get_data("ssh_private_key_path")
    return str(fb).strip() if fb not in (None, "") else ""


def _sftp_collect_files(
    sftp: Any, remote_dir: str, local_dir: Path, ctx: Context
) -> Tuple[List[Tuple[str, Path]], int, int]:
    """列出待下载的 (远端路径, 本机路径)，并统计文件数与近似总字节。"""
    files: List[Tuple[str, Path]] = []
    n_files = 0
    total_b = 0
    local_dir.mkdir(parents=True, exist_ok=True)
    for entry in sftp.listdir_attr(remote_dir):
        name = entry.filename
        if name in (".", ".."):
            continue
        rpath = f"{remote_dir.rstrip('/')}/{name}"
        lpath = local_dir / name
        mode = int(getattr(entry, "st_mode", 0) or 0)
        is_dir = stat.S_ISDIR(mode)
        if not is_dir and mode == 0:
            try:
                st2 = sftp.stat(rpath)
                is_dir = stat.S_ISDIR(int(st2.st_mode))
            except OSError:
                is_dir = False
        if is_dir:
            sub_list, sub_n, sub_b = _sftp_collect_files(sftp, rpath, lpath, ctx)
            files.extend(sub_list)
            n_files += sub_n
            total_b += sub_b
        else:
            files.append((rpath, lpath))
            n_files += 1
            try:
                total_b += int(entry.st_size or 0)
            except (TypeError, ValueError):
                pass
    return files, n_files, total_b


def _execute_sftp_pull(
    ctx: Context,
    *,
    host: str,
    username: str,
    port: int,
    remote_dir: str,
    dest_dir: Path,
    delete_after: bool,
    strict_hk: bool,
    connect_timeout: int,
    exec_timeout: int,
    show_pull_progress: bool,
    pull_prog_title: str,
    pkey: Any,
) -> StepResult:
    """单次 SFTP 拉取（含可选远端删除）。"""
    import paramiko

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(
        paramiko.RejectPolicy() if strict_hk else paramiko.AutoAddPolicy()
    )
    progress_opened = False
    n_files = 0
    approx_b = 0
    try:
        ctx.log_info(f"SFTP 连接 {username}@{host}:{port}，远端目录 {remote_dir}")
        client.connect(
            hostname=host,
            port=port,
            username=username,
            pkey=pkey,
            timeout=connect_timeout,
            allow_agent=False,
            look_for_keys=False,
        )
        sftp = client.open_sftp()
        try:
            try:
                st = sftp.stat(remote_dir)
            except OSError as e:
                return StepResult(
                    passed=False,
                    message="远端目录不存在或不可访问",
                    error=str(e),
                    data={"remote_dir": remote_dir},
                )
            if not stat.S_ISDIR(int(st.st_mode)):
                return StepResult(
                    passed=False,
                    message="remote_dir 不是目录",
                    error=remote_dir,
                )
            entries, n_files, approx_b = _sftp_collect_files(
                sftp, remote_dir, dest_dir, ctx
            )

            if show_pull_progress:
                try:
                    from src.app.ui_invoker import invoke_sftp_pull_progress_open

                    progress_opened = invoke_sftp_pull_progress_open(
                        pull_prog_title,
                        str(dest_dir),
                        len(entries),
                    )
                except Exception as exc:  # noqa: BLE001
                    ctx.log_warning(f"无法显示导出进度条: {exc}")
                    progress_opened = False

            for i, (rpath, lpath) in enumerate(entries, start=1):
                lpath.parent.mkdir(parents=True, exist_ok=True)
                ctx.log_info(f"SFTP get {rpath} -> {lpath}")
                if progress_opened:
                    try:
                        from src.app.ui_invoker import invoke_sftp_pull_progress_update

                        invoke_sftp_pull_progress_update(i, rpath)
                    except Exception:
                        pass
                sftp.get(rpath, str(lpath))

            if not entries and progress_opened:
                try:
                    from src.app.ui_invoker import invoke_sftp_pull_progress_update

                    invoke_sftp_pull_progress_update(1, "（远端目录下未发现文件）")
                except Exception:
                    pass
        finally:
            sftp.close()

        if delete_after:
            if progress_opened:
                try:
                    from src.app.ui_invoker import invoke_sftp_pull_progress_update

                    invoke_sftp_pull_progress_update(
                        max(n_files, 1),
                        "正在删除并重建远端目录…",
                    )
                except Exception:
                    pass
            inner = f"rm -rf {shlex.quote(remote_dir)} && mkdir -p {shlex.quote(remote_dir)}"
            cmd = "bash -lc " + shlex.quote(inner)
            ctx.log_info(f"SSH 删除并重建远端目录: {remote_dir}")
            _si, stdout, stderr = client.exec_command(cmd, timeout=exec_timeout)
            try:
                _si.close()
            except Exception:
                pass
            out = (stdout.read() or b"").decode("utf-8", errors="replace").strip()
            err = (stderr.read() or b"").decode("utf-8", errors="replace").strip()
            rc = int(stdout.channel.recv_exit_status())
            if rc != 0:
                return StepResult(
                    passed=False,
                    message="远端删除/重建目录失败",
                    error=err or out or f"exit {rc}",
                    data={"remote_dir": remote_dir, "exit_code": rc},
                )

        return StepResult(
            passed=True,
            message=f"已拉取 {n_files} 个文件到 {dest_dir}",
            data={
                "local_dir": str(dest_dir),
                "remote_dir": remote_dir,
                "files_downloaded": n_files,
                "approx_bytes": approx_b,
                "delete_remote_after": delete_after,
            },
        )
    except Exception as e:  # noqa: BLE001
        return StepResult(
            passed=False,
            message="SFTP/SSH 执行失败",
            error=str(e),
        )
    finally:
        if progress_opened:
            try:
                from src.app.ui_invoker import invoke_sftp_pull_progress_close

                invoke_sftp_pull_progress_close()
            except Exception:
                pass
        try:
            client.close()
        except Exception:
            pass


class SshSftpPullDirStep(BaseStep):
    """SFTP 递归拉取远端目录，可选删除远端并重建空目录。"""

    def run_once(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        try:
            import paramiko
        except ImportError:
            return self.create_failure_result(
                "未安装 paramiko",
                error="请执行: pip install paramiko",
            )

        host = self.get_param_str(params, "host", "").strip()
        username = self.get_param_str(params, "username", "").strip()
        if not host or not username:
            return self.create_failure_result(
                "缺少 host 或 username",
                error="请在 params 中设置 host、username",
            )
        port = max(1, self.get_param_int(params, "port", 22))
        remote_dir = self.get_param_str(params, "remote_dir", "").strip().rstrip("/")
        if not remote_dir.startswith("/"):
            return self.create_failure_result(
                "remote_dir 须为绝对路径",
                error=remote_dir,
            )
        parent_raw = self.get_param_str(params, "local_parent_dir", "").strip()
        if parent_raw and "${" not in parent_raw:
            local_parent = Path(parent_raw).expanduser()
        else:
            if "${" in parent_raw:
                ctx.log_warning(
                    "local_parent_dir 含未解析占位符，改用配置或本机用户 Downloads 目录"
                )
            cfg_dir = ctx.get_data("ssh_burnin_data_save_dir")
            cfg_dir_s = str(cfg_dir).strip() if cfg_dir not in (None, "") else ""
            if cfg_dir_s:
                local_parent = Path(cfg_dir_s).expanduser()
                ctx.log_info(f"使用配置 ssh.burnin_data_save_dir 作为本机保存父目录: {local_parent}")
            else:
                local_parent = Path.home() / "Downloads"
        local_name_raw = self.get_param_str(params, "local_dir_name", "").strip()
        local_name, name_err = _resolve_local_dir_name(local_name_raw, ctx)
        if name_err:
            ctx.log_warning(f"local_dir_name 解析: 模板={local_name_raw!r}")
            return self.create_failure_result(
                "local_dir_name 无效或未解析",
                error=name_err,
                data={
                    "local_dir_name_template": local_name_raw,
                    "sn": ctx.get_data("sn", ctx.get_sn()),
                    "pvt_hub_countdown_started_at": ctx.get_data(
                        "pvt_hub_countdown_started_at"
                    ),
                    "pvt_hub_burnin_outcome": ctx.get_data("pvt_hub_burnin_outcome"),
                },
            )
        delete_after = self.get_param_bool(params, "delete_remote_after", True)
        strict_hk = self.get_param_bool(params, "strict_host_key", False)
        connect_timeout = max(5, self.get_param_int(params, "connect_timeout", 30))
        exec_timeout = max(10, self.get_param_int(params, "exec_timeout", 120))
        show_pull_progress = self.get_param_bool(params, "show_pull_progress", True)
        pull_prog_title = self.get_param_str(params, "pull_progress_title", "正在导出数据")

        key_path = _resolve_private_key(params, ctx)
        expanded = str(Path(key_path).expanduser()) if key_path else ""
        if not expanded or not os.path.isfile(expanded):
            return self.create_failure_result(
                "缺少有效私钥文件",
                error=key_path or "(未配置 private_key_file / ssh_private_key_path)",
            )

        dest_dir = (local_parent.expanduser() / local_name).resolve()
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return self.create_failure_result(
                "无法创建本机目标目录",
                error=str(e),
                data={"dest_dir": str(dest_dir)},
            )

        try:
            pkey = _load_pkey_from_file(expanded)
        except Exception as e:  # noqa: BLE001
            return self.create_failure_result(
                "加载私钥失败",
                error=str(e),
            )

        retry_until = self.get_param_bool(params, "retry_until_success", False)
        retry_delay = max(0, self.get_param_int(params, "retry_delay_sec", 3))
        min_files = max(0, self.get_param_int(params, "min_files_downloaded", 0))
        retry_title = self.get_param_str(params, "retry_confirm_title", "数据导出失败")
        retry_msg_tpl = self.get_param_str(params, "retry_confirm_message", "").strip()

        attempt = 0
        last_result: Optional[StepResult] = None
        while True:
            attempt += 1
            if attempt > 1:
                ctx.log_info(f"数据导出第 {attempt} 次尝试")

            pull = _execute_sftp_pull(
                ctx,
                host=host,
                username=username,
                port=port,
                remote_dir=remote_dir,
                dest_dir=dest_dir,
                delete_after=delete_after,
                strict_hk=strict_hk,
                connect_timeout=connect_timeout,
                exec_timeout=exec_timeout,
                show_pull_progress=show_pull_progress,
                pull_prog_title=pull_prog_title,
                pkey=pkey,
            )

            if pull.passed:
                n_files = 0
                if isinstance(pull.data, dict):
                    n_files = int(pull.data.get("files_downloaded") or 0)
                if min_files > 0 and n_files < min_files:
                    last_result = self.create_failure_result(
                        f"远端数据文件不足（{n_files} < {min_files}）",
                        error="INSUFFICIENT_FILES",
                        data={
                            **(pull.data or {}),
                            "min_files_downloaded": min_files,
                            "pull_attempts": attempt,
                        },
                    )
                else:
                    data = dict(pull.data or {})
                    if attempt > 1:
                        data["pull_attempts"] = attempt
                    return self.create_success_result(
                        data,
                        pull.message or f"已拉取 {n_files} 个文件到 {dest_dir}",
                    )
            else:
                last_result = self.create_failure_result(
                    pull.message or "SFTP/SSH 执行失败",
                    error=pull.error,
                    data={**(pull.data or {}), "pull_attempts": attempt},
                )

            if not retry_until:
                return last_result

            err_detail = (pull.error or pull.message or "").strip()
            msg = retry_msg_tpl or (
                f"导出失败：{err_detail}\n\n"
                f"保存目标：{dest_dir}\n\n"
                "请检查 Hub 连接与网络后点击「重试拉取」（须本轮内成功方可过站）。"
                "点击「放弃」则 MES 上报 FAIL。"
            )
            try:
                from src.app.ui_invoker import invoke_in_gui_confirmation

                again = invoke_in_gui_confirmation(
                    title=retry_title,
                    message=msg,
                    confirm_text="重试拉取",
                    cancel_text="放弃",
                    port=str(getattr(ctx, "port", "") or "PortA"),
                    allow_cancel=True,
                )
            except Exception as exc:  # noqa: BLE001
                ctx.log_warning(f"补拉确认框失败: {exc}")
                return last_result

            if not again:
                ctx.log_warning("操作员放弃补拉，数据导出保持失败")
                return last_result

            if retry_delay > 0:
                ctx.log_info(f"等待 {retry_delay}s 后重试拉取…")
                time.sleep(retry_delay)
