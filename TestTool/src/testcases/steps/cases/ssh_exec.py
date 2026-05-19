"""
通过 SSH 在远端执行一条 shell 命令（如跳板机上执行 bms 下电）。

认证方式三选一：password、private_key_file、private_key_env（环境变量中的私钥 PEM 文本）。
不要将私钥明文写入提交到仓库的 YAML；优先使用私钥文件路径或环境变量。
未在步骤中填写 private_key_file 时，可使用「配置 → 测试站 → 私钥配置」中的默认私钥路径（写入 Context）。

可选：allow_agent、look_for_keys（默认 false）。若命令行 ssh 依赖 ssh-agent（已 ssh-add），
可将二者设为 true，并确保未强制传入错误的 private_key_file（否则会先尝试该密钥）。

若设置 local_script_file（运行 TestTool 的机器上的路径），则通过 SSH 在远端执行
``bash -s`` 并从 stdin 传入脚本内容，无需在 S100 上预先拷贝脚本文件（执行环境仍在远端 Linux）。

若设置 invoke_remote_script=true 并提供 remote_script_path（远端要执行的脚本路径，如 ``/app/pvt_stress_test_v3.sh``），
则构造与手动操作等效的 ``bash -lc`` 命令：可选 ``mount -o remount,rw /app``、``cd``、``chmod +x``、``exec ./脚本``，
并将 script_args 原样追加在脚本名之后。与 command 互斥；此模式下若仍填写 local_script_file 会被忽略（便于同一 YAML 切换本机 stdin 脚本 / 远端脚本）。
remote_workdir 缺省为脚本所在目录（无法解析时为 ``/app``）；remote_remount_app_rw 默认 true。

若同时设置 upload_local_file（本机可读文件路径），则在同一 SSH 连接内先用 SFTP 覆盖写入远端
``remote_upload_path``（未设则用 ``remote_script_path``），默认先 ``mount -o remount,rw /app`` 再上传。
若上传前已 remount 且 ``remote_remount_app_rw`` 也为 true，构造执行命令时会省略重复的 ``mount``。
upload_local_file 仅支持与 invoke_remote_script=true 组合；与 command、stdin 模式互斥。

invoke_remote_script 模式下可设 ``invoke_remote_background=true``：远端用 ``nohup ./脚本 … >>日志`` 启动压测，
SSH 会话侧 ``tail -f`` 同一日志以继续流式匹配 ``pass_on_stdout_regex``；断开 SSH（如拔掉 Hub）后，
``nohup`` 子进程仍在板上运行。可选 ``invoke_remote_background_log`` 指定日志路径（默认
``/tmp/<脚本名>.testtool_nohup.log``）。仅与 ``invoke_remote_script=true`` 组合。

长耗时脚本在远端 sleep 时 SSH 信道可能长时间无数据，易被 NAT/防火墙断开；可设 keepalive_sec（默认 10）
启用 Paramiko 传输层保活，降低「远程主机强迫关闭连接」(Win 10054) 与退出码 -1 的概率。

若设 pass_on_stdout_regex（Python 正则），则在 exec_timeout 内流式读 stdout（可选含 stderr）。
默认在匹配到「checkpoint」后仍保持 SSH，继续等到远端 bash 退出（避免一通过就关连接导致压测脚本被杀死、机器不跑）。
仅当 pass_regex_disconnect_early=true 时才会在匹配后立即返回并断开 SSH（一般不推荐）。

pass_regex_ignore_script_exit（默认 true）：已出现 checkpoint 后不再因远端最终退出码非 0 / -1 判失败
（压测脚本中途报错退出仍视为本步骤通过）；若需严格判退出码，设为 false 并保持 expect_zero_exit。
"""

from __future__ import annotations

import io
import os
import posixpath
import re
import shlex
import socket
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ...base import BaseStep, StepResult
from ...context import Context


def _resolve_local_path_for_ssh(raw: str) -> str:
    """解析本机脚本/待上传文件路径（与 engineer transfer 逻辑一致）。

    相对路径时依次尝试：原路径、cwd、打包 exe 目录与 ``_internal``、TestTool 根目录
    （本文件位于 ``src/testcases/steps/cases``，向上四级到项目根）。
    """
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
    candidates: List[Path] = [Path.cwd() / s]
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent
        candidates.append(base / s)
        candidates.append(base / "_internal" / s)
    try:
        here = Path(__file__).resolve().parent
        tt_root = here.parent.parent.parent.parent
        candidates.append(tt_root / s)
        candidates.append(here / s)
    except OSError:
        pass
    for c in candidates:
        try:
            if c.is_file():
                return str(c.resolve())
        except OSError:
            continue
    return s


def resolve_private_key_file_path(params: Dict[str, Any], ctx: Context) -> str:
    """步骤参数 private_key_file 优先；否则使用应用配置注入的 ssh_private_key_path。"""
    raw = params.get("private_key_file")
    s = str(raw).strip() if raw not in (None, "") else ""
    if s:
        return s
    fb = ctx.get_data("ssh_private_key_path")
    return str(fb).strip() if fb not in (None, "") else ""


def _load_pkey_from_file(path: str):
    import paramiko

    expanded = str(Path(path).expanduser())
    errs: List[str] = []
    for cls in (paramiko.Ed25519Key, paramiko.RSAKey, paramiko.ECDSAKey):
        try:
            return cls.from_private_key_file(expanded)
        except Exception as e:  # noqa: BLE001
            errs.append(f"{cls.__name__}: {e}")
    raise ValueError("无法解析私钥文件: " + "; ".join(errs))


def _pkey_md5_fingerprint(pkey) -> str:
    """与 ssh-keygen -lf -E md5 类似的 MD5 指纹格式。"""
    fp = pkey.get_fingerprint()
    return ":".join(f"{b:02x}" for b in fp)


def _load_pkey_from_string(key_text: str):
    import paramiko

    buf = io.StringIO(key_text.strip())
    errs: List[str] = []
    for cls in (paramiko.Ed25519Key, paramiko.RSAKey, paramiko.ECDSAKey):
        try:
            buf.seek(0)
            return cls.from_private_key(buf)
        except Exception as e:  # noqa: BLE001
            errs.append(f"{cls.__name__}: {e}")
    raise ValueError("无法解析私钥字符串: " + "; ".join(errs))


def _build_remote_script_invoke_command(
    *,
    remote_script_path: str,
    remote_workdir: str,
    remount_app_rw: bool,
    script_args: str,
    invoke_remote_background: bool = False,
    invoke_remote_background_log: str = "",
) -> str:
    """构造在远端执行板上已有脚本的 bash -lc 单行命令（参数经 shlex 转义）。"""
    p = Path(remote_script_path.replace("\\", "/"))
    name = p.name
    if not name:
        raise ValueError("remote_script_path 无效（无文件名）")
    wd = remote_workdir.strip()
    if not wd:
        par = str(p.parent)
        wd = par if par and par not in (".", "") else "/app"
    arg_tokens: List[str] = []
    if script_args.strip():
        arg_tokens = shlex.split(script_args.strip(), posix=True)
    segs: List[str] = []
    if remount_app_rw:
        segs.append("mount -o remount,rw /app")
    segs.append(f"cd {shlex.quote(wd)}")
    segs.append(f"chmod +x {shlex.quote(name)}")
    arg_part = ""
    if arg_tokens:
        arg_part = " " + " ".join(shlex.quote(t) for t in arg_tokens)
    run_target = f"{shlex.quote('./' + name)}{arg_part}"
    if invoke_remote_background:
        raw_log = (invoke_remote_background_log or "").strip()
        log_abs = (
            raw_log if raw_log else posixpath.join("/tmp", f"{name}.testtool_nohup.log")
        )
        log_q = shlex.quote(log_abs)
        # 使用 POSIX 的 tail -f（避免部分 BusyBox/旧 coreutils 对 tail -n +1 报错导致会话立刻以 1 退出）；
        # sleep 让 nohup 子进程先打开日志，减少首行丢失；exec 使 SSH 退出码仅反映 tail。
        segs.append(
            f": > {log_q} && "
            f"nohup {run_target} >>{log_q} 2>&1 < /dev/null & "
            f"echo PVT_TESTTOOL_REMOTE_BG_PID=$! && "
            f"sleep 0.4 && "
            f"exec tail -f {log_q}"
        )
    else:
        segs.append(f"exec {run_target}")
    inner = " && ".join(segs)
    return "bash -lc " + shlex.quote(inner)


class SshExecStep(BaseStep):
    """SSH 远程执行命令。"""

    def run_once(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        try:
            import paramiko
        except ImportError:
            return StepResult(
                passed=False,
                message="未安装 paramiko",
                error="请执行: pip install paramiko",
                error_code="SSH_EXEC_NO_PARAMIKO",
            )

        host = self.get_param_str(params, "host", "").strip()
        username = self.get_param_str(params, "username", "").strip()
        command = self.get_param_str(params, "command", "").strip()
        local_script_file = self.get_param_str(params, "local_script_file", "").strip()
        script_args = self.get_param_str(params, "script_args", "").strip()
        port = self.get_param_int(params, "port", 22)
        upload_local_file = self.get_param_str(params, "upload_local_file", "").strip()

        invoke_remote = self.get_param_bool(params, "invoke_remote_script", False)
        invoke_remote_background = self.get_param_bool(
            params, "invoke_remote_background", False
        )
        invoke_remote_background_log = self.get_param_str(
            params, "invoke_remote_background_log", ""
        ).strip()
        if invoke_remote_background and not invoke_remote:
            return StepResult(
                passed=False,
                message="参数冲突",
                error="invoke_remote_background 仅支持与 invoke_remote_script=true 组合",
                error_code="SSH_EXEC_BAD_PARAMS",
            )

        upload_local_abs: Optional[str] = None
        if upload_local_file:
            if not invoke_remote:
                return StepResult(
                    passed=False,
                    message="参数冲突",
                    error="upload_local_file 已设置时需 invoke_remote_script=true（SFTP 上传到远端后再 chmod+执行）",
                    error_code="SSH_EXEC_BAD_PARAMS",
                )
            ul_resolved = _resolve_local_path_for_ssh(upload_local_file)
            ul_p = Path(ul_resolved).expanduser()
            if ul_resolved != upload_local_file.strip():
                ctx.log_info(f"本机待上传路径解析: {upload_local_file!r} -> {ul_p}")
            if not ul_p.is_file():
                return StepResult(
                    passed=False,
                    message="待上传的本机文件不存在",
                    error=str(ul_p),
                    error_code="SSH_EXEC_UPLOAD_LOCAL_MISSING",
                )
            upload_local_abs = str(ul_p.resolve())

        if invoke_remote:
            if command:
                return StepResult(
                    passed=False,
                    message="参数冲突",
                    error="invoke_remote_script=true 时不应再设置 command",
                    error_code="SSH_EXEC_BAD_PARAMS",
                )
            rpath = self.get_param_str(params, "remote_script_path", "").strip()
            if not rpath:
                return StepResult(
                    passed=False,
                    message="参数不完整",
                    error="invoke_remote_script=true 时需要 remote_script_path（远端执行路径；可先由 upload_local_file 上传覆盖）",
                    error_code="SSH_EXEC_BAD_PARAMS",
                )
            rwd = self.get_param_str(params, "remote_workdir", "").strip()
            remount_rw = self.get_param_bool(params, "remote_remount_app_rw", True)
            remount_bu = self.get_param_bool(
                params, "remote_remount_app_rw_before_upload", True
            )
            if upload_local_abs and remount_bu and remount_rw:
                remount_rw = False
            try:
                command = _build_remote_script_invoke_command(
                    remote_script_path=rpath,
                    remote_workdir=rwd,
                    remount_app_rw=remount_rw,
                    script_args=script_args,
                    invoke_remote_background=invoke_remote_background,
                    invoke_remote_background_log=invoke_remote_background_log,
                )
            except ValueError as e:
                return StepResult(
                    passed=False,
                    message="构造远端脚本命令失败",
                    error=str(e),
                    error_code="SSH_EXEC_BAD_PARAMS",
                )
            local_script_file = ""

        password = params.get("password")
        password_str = str(password).strip() if password not in (None, "") else ""

        raw_pk_param = params.get("private_key_file")
        pk_explicit = bool(
            str(raw_pk_param).strip() if raw_pk_param not in (None, "") else False
        )
        key_file = resolve_private_key_file_path(params, ctx)
        key_env = self.get_param_str(params, "private_key_env", "").strip()

        strict_host = self.get_param_bool(params, "strict_host_key", False)
        expect_zero = self.get_param_bool(params, "expect_zero_exit", True)
        allow_agent = self.get_param_bool(params, "allow_agent", False)
        look_for_keys = self.get_param_bool(params, "look_for_keys", False)

        connect_timeout = self.get_param_int(
            params, "connect_timeout", min(max(self.timeout, 5), 60)
        )
        exec_timeout = self.get_param_int(params, "exec_timeout", max(self.timeout, 10))

        if not host or not username:
            return StepResult(
                passed=False,
                message="参数不完整",
                error="需要提供 host、username",
                error_code="SSH_EXEC_BAD_PARAMS",
            )
        if not local_script_file and not command:
            return StepResult(
                passed=False,
                message="参数不完整",
                error="需要提供 command，或提供 local_script_file（本机脚本经 SSH 在远端执行）",
                error_code="SSH_EXEC_BAD_PARAMS",
            )

        has_pkey_material = bool(key_file or key_env)
        if (
            not password_str
            and not has_pkey_material
            and not allow_agent
            and not look_for_keys
        ):
            return StepResult(
                passed=False,
                message="未配置认证方式",
                error="请设置 password、private_key_file、private_key_env 之一，"
                "或将 allow_agent / look_for_keys 设为 true",
                error_code="SSH_EXEC_NO_AUTH",
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
                    error_code="SSH_EXEC_KEY_FILE",
                )
        elif key_env:
            raw = os.environ.get(key_env, "")
            if not raw.strip():
                return StepResult(
                    passed=False,
                    message="环境变量中无私钥",
                    error=f"环境变量 {key_env} 为空或未设置",
                    error_code="SSH_EXEC_KEY_ENV",
                )
            try:
                pkey = _load_pkey_from_string(raw)
            except Exception as e:  # noqa: BLE001
                return StepResult(
                    passed=False,
                    message="解析环境变量私钥失败",
                    error=str(e),
                    error_code="SSH_EXEC_KEY_PARSE",
                )

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(
            paramiko.RejectPolicy() if strict_host else paramiko.AutoAddPolicy()
        )

        try:
            connect_kw: Dict[str, Any] = {
                "hostname": host,
                "port": port,
                "username": username,
                "timeout": connect_timeout,
                "allow_agent": allow_agent,
                "look_for_keys": look_for_keys,
            }
            if pkey is not None:
                connect_kw["pkey"] = pkey
            if password_str:
                connect_kw["password"] = password_str

            if key_file:
                src = "步骤 private_key_file" if pk_explicit else "配置默认私钥 (ssh_private_key_path)"
                ctx.log_info(f"SSH 使用私钥文件 ({src}): {Path(key_file).expanduser()}")
                if pkey is not None:
                    ctx.log_info(f"SSH 私钥 MD5 指纹: {_pkey_md5_fingerprint(pkey)}")
            elif key_env:
                ctx.log_info(f"SSH 使用环境变量私钥: {key_env}")
                if pkey is not None:
                    ctx.log_info(f"SSH 私钥 MD5 指纹: {_pkey_md5_fingerprint(pkey)}")
            if password_str:
                ctx.log_info("SSH 同时提供密码参数（Paramiko 与密钥一并协商）")
            if allow_agent:
                ctx.log_info("SSH allow_agent=True（将尝试本机 ssh-agent）")
            if look_for_keys:
                ctx.log_info("SSH look_for_keys=True（将尝试 ~/.ssh 等默认路径）")

            ctx.log_info(f"SSH 连接 {username}@{host}:{port} …")
            client.connect(**connect_kw)

            keepalive_sec = self.get_param_int(params, "keepalive_sec", 10)
            t = client.get_transport()
            if t is not None and keepalive_sec > 0:
                t.set_keepalive(keepalive_sec)
                ctx.log_info(
                    f"SSH 传输层 keepalive 已开启（每 {keepalive_sec}s），减轻长连接被中间设备空闲断开"
                )

            if upload_local_abs:
                r_dest = self.get_param_str(params, "remote_upload_path", "").strip()
                if not r_dest:
                    r_dest = self.get_param_str(params, "remote_script_path", "").strip()
                if not r_dest:
                    return StepResult(
                        passed=False,
                        message="SFTP 目标路径未设置",
                        error="upload_local_file 需要 remote_script_path 或 remote_upload_path",
                        error_code="SSH_EXEC_BAD_PARAMS",
                    )
                remount_bu = self.get_param_bool(
                    params, "remote_remount_app_rw_before_upload", True
                )
                if remount_bu:
                    ctx.log_info("SFTP 上传前: mount -o remount,rw /app")
                    _si, _so, _se = client.exec_command(
                        "bash -lc " + shlex.quote("mount -o remount,rw /app"),
                        timeout=min(120, max(30, exec_timeout)),
                    )
                    try:
                        _si.close()
                    except Exception:
                        pass
                    st = _so.channel.recv_exit_status()
                    out_d = _so.read().decode("utf-8", errors="replace").strip()
                    err_d = _se.read().decode("utf-8", errors="replace").strip()
                    if st != 0:
                        return StepResult(
                            passed=False,
                            message="上传前 remount /app 失败",
                            error=err_d or out_d or f"exit {st}",
                            error_code="SSH_EXEC_UPLOAD_REMOUNT",
                        )
                r_dest_norm = str(r_dest).strip().replace("\\", "/")
                parent = posixpath.dirname(r_dest_norm)
                if parent:
                    ctx.log_info(f"SFTP 确保远端父目录存在: {parent}")
                    _mkdir_inner = "mkdir -p " + shlex.quote(parent)
                    _si_m, _so_m, _se_m = client.exec_command(
                        "bash -lc " + shlex.quote(_mkdir_inner),
                        timeout=min(60, max(20, exec_timeout)),
                    )
                    try:
                        _si_m.close()
                    except Exception:
                        pass
                    st_m = _so_m.channel.recv_exit_status()
                    err_m = _se_m.read().decode("utf-8", errors="replace").strip()
                    out_m = _so_m.read().decode("utf-8", errors="replace").strip()
                    if st_m != 0:
                        return StepResult(
                            passed=False,
                            message="SFTP 上传前创建远端目录失败",
                            error=err_m or out_m or f"exit {st_m}",
                            error_code="SSH_EXEC_UPLOAD_MKDIR",
                        )
                try:
                    local_sz = Path(upload_local_abs).stat().st_size
                except OSError as e:
                    return StepResult(
                        passed=False,
                        message="无法读取本机待上传文件大小",
                        error=str(e),
                        error_code="SSH_EXEC_UPLOAD_LOCAL_STAT",
                    )
                try:
                    sftp = client.open_sftp()
                    try:
                        ctx.log_info(
                            f"SFTP 上传 {upload_local_abs} ({local_sz} 字节) → "
                            f"{username}@{host}:{r_dest_norm}"
                        )
                        sftp.put(upload_local_abs, r_dest_norm)
                        try:
                            rst = sftp.stat(r_dest_norm)
                            rsz = int(getattr(rst, "st_size", -1))
                        except OSError as se:
                            return StepResult(
                                passed=False,
                                message="SFTP 上传后无法 stat 远端文件",
                                error=str(se),
                                error_code="SSH_EXEC_SFTP_STAT",
                            )
                        if rsz != local_sz:
                            return StepResult(
                                passed=False,
                                message="SFTP 上传后远端大小与本地不一致",
                                error=f"本地 {local_sz} 字节, 远端 {rsz} 字节",
                                error_code="SSH_EXEC_SFTP_SIZE_MISMATCH",
                            )
                        ctx.log_info(
                            f"SFTP 校验通过: 远端 {r_dest_norm} 大小 {rsz} 字节"
                        )
                    finally:
                        sftp.close()
                except Exception as e:  # noqa: BLE001
                    return StepResult(
                        passed=False,
                        message="SFTP 上传失败",
                        error=str(e),
                        error_code="SSH_EXEC_SFTP_PUT",
                    )

            elif invoke_remote:
                ctx.log_info(
                    "已启用 invoke_remote_script，但未设置 upload_local_file："
                    "不会覆盖远端文件，将直接执行 remote_script_path 指向的板上脚本。"
                )

            if local_script_file:
                script_resolved = _resolve_local_path_for_ssh(local_script_file)
                script_path = Path(script_resolved).expanduser()
                if script_resolved != local_script_file.strip():
                    ctx.log_info(f"本机脚本路径解析: {local_script_file!r} -> {script_path}")
                if not script_path.is_file():
                    return StepResult(
                        passed=False,
                        message="本机脚本路径无效",
                        error=str(script_path),
                        error_code="SSH_EXEC_LOCAL_SCRIPT",
                    )
                try:
                    script_text = script_path.read_text(encoding="utf-8", errors="replace")
                except OSError as e:
                    return StepResult(
                        passed=False,
                        message="读取本机脚本失败",
                        error=str(e),
                        error_code="SSH_EXEC_LOCAL_SCRIPT_READ",
                    )
                script_body = script_text.replace("\r\n", "\n").encode("utf-8")
                arg_tokens = shlex.split(script_args, posix=True) if script_args else []
                remote_cmd = (
                    "bash -s -- " + " ".join(shlex.quote(t) for t in arg_tokens)
                    if arg_tokens
                    else "bash -s"
                )
                ctx.log_info(
                    f"SSH 从本机传入脚本执行（远端不落盘）: {script_path} → {remote_cmd}"
                )
                stdin, stdout, stderr = client.exec_command(
                    remote_cmd, timeout=exec_timeout
                )
                bs = 65536
                for off in range(0, len(script_body), bs):
                    stdin.write(script_body[off : off + bs])
                stdin.channel.shutdown_write()
            else:
                if invoke_remote_background:
                    ctx.log_info(
                        "invoke_remote_background: 远端以 nohup 执行 ./ 脚本并 tail -f 日志；"
                        "断开 SSH 后压测仍在板上运行"
                    )
                ctx.log_info(f"SSH 执行: {command}")
                stdin, stdout, stderr = client.exec_command(command, timeout=exec_timeout)
                _ = stdin

            pass_regex_str = self.get_param_str(params, "pass_on_stdout_regex", "").strip()
            include_err_in_regex = self.get_param_bool(
                params, "pass_regex_include_stderr", True
            )

            if pass_regex_str:
                try:
                    cre = re.compile(pass_regex_str)
                except re.error as e:
                    return StepResult(
                        passed=False,
                        message="pass_on_stdout_regex 不是合法正则",
                        error=str(e),
                        error_code="SSH_EXEC_BAD_REGEX",
                    )

                disconnect_early = self.get_param_bool(
                    params, "pass_regex_disconnect_early", False
                )

                stdout.channel.settimeout(0.5)
                if include_err_in_regex:
                    stderr.channel.settimeout(0.5)

                buf_out = b""
                buf_err = b""
                deadline = time.monotonic() + float(exec_timeout)
                matched = False
                checkpoint_logged = False

                while time.monotonic() < deadline:
                    try:
                        chunk = stdout.channel.recv(4096)
                    except socket.timeout:
                        chunk = b""
                    except Exception:
                        chunk = b""
                    if chunk:
                        buf_out += chunk

                    if include_err_in_regex:
                        try:
                            ech = stderr.channel.recv(4096)
                        except socket.timeout:
                            ech = b""
                        except Exception:
                            ech = b""
                        if ech:
                            buf_err += ech

                    haystack = (buf_out + buf_err).decode("utf-8", errors="replace")
                    if cre.search(haystack):
                        matched = True
                        if not checkpoint_logged:
                            checkpoint_logged = True
                            ctx.log_info(
                                "SSH 输出已匹配 pass_on_stdout_regex（checkpoint）；"
                                + (
                                    "立即断开会话（pass_regex_disconnect_early）"
                                    if disconnect_early
                                    else "保持连接直至远端脚本结束"
                                )
                            )
                        if disconnect_early:
                            break

                    if stdout.channel.exit_status_ready():
                        break
                    if stdout.channel.closed:
                        break

                if matched and disconnect_early:
                    out_t = buf_out.decode(errors="replace").strip()
                    err_t = buf_err.decode(errors="replace").strip()
                    if out_t:
                        ctx.log_info(
                            f"stdout: {out_t[:2000]}{'…' if len(out_t) > 2000 else ''}"
                        )
                    if err_t:
                        ctx.log_warning(
                            f"stderr: {err_t[:2000]}{'…' if len(err_t) > 2000 else ''}"
                        )
                    data_early: Dict[str, Any] = {
                        "exit_code": None,
                        "stdout": out_t,
                        "stderr": err_t,
                        "matched_regex": pass_regex_str,
                        "disconnect_early": True,
                        "invoke_remote_background": invoke_remote_background,
                    }
                    early_msg = (
                        "SSH 已匹配输出条件（已提前断开）；远端压测由 nohup 在后台运行，拔 Hub/断线后仍继续"
                        if invoke_remote_background
                        else "SSH 已匹配输出条件（已提前断开，远端进程可能被终止）"
                    )
                    return StepResult(
                        passed=True,
                        message=early_msg,
                        data=data_early,
                    )

                try:
                    while True:
                        chunk = stdout.channel.recv(65536)
                        if not chunk:
                            break
                        buf_out += chunk
                except Exception:
                    pass
                try:
                    while True:
                        chunk = stderr.channel.recv(65536)
                        if not chunk:
                            break
                        buf_err += chunk
                except Exception:
                    pass

                out_t = buf_out.decode(errors="replace").strip()
                err_t = buf_err.decode(errors="replace").strip()
                if out_t:
                    ctx.log_info(
                        f"stdout: {out_t[:2000]}{'…' if len(out_t) > 2000 else ''}"
                    )
                if err_t:
                    ctx.log_warning(
                        f"stderr: {err_t[:2000]}{'…' if len(err_t) > 2000 else ''}"
                    )

                exit_code = -1
                if stdout.channel.exit_status_ready():
                    try:
                        exit_code = stdout.channel.recv_exit_status()
                    except Exception:
                        pass
                elif matched and time.monotonic() >= deadline:
                    data_to: Dict[str, Any] = {
                        "exit_code": exit_code,
                        "stdout": out_t,
                        "stderr": err_t,
                        "matched_regex": pass_regex_str,
                    }
                    return StepResult(
                        passed=False,
                        message=(
                            f"已匹配 checkpoint 但在 {exec_timeout}s 内仍未收到远端退出状态"
                            "（压测仍在进行或网络断开，请调大 exec_timeout）"
                        ),
                        error=err_t or out_t or "no_exit_status",
                        error_code="SSH_EXEC_PASS_REGEX_SCRIPT_TIMEOUT",
                        data=data_to,
                    )
                elif matched:
                    try:
                        stdout.channel.settimeout(min(30.0, max(1.0, deadline - time.monotonic())))
                        exit_code = stdout.channel.recv_exit_status()
                    except Exception:
                        exit_code = -1

                ctx.log_info(f"SSH 退出码: {exit_code}")

                data_rx: Dict[str, Any] = {
                    "exit_code": exit_code,
                    "stdout": out_t,
                    "stderr": err_t,
                    "matched_regex": pass_regex_str if matched else None,
                }

                if not matched:
                    hint = ""
                    if invoke_remote_background and exit_code not in (0, -1):
                        hint = (
                            "（invoke_remote_background：若会话很快结束，多为 tail 失败或压测脚本立即退出；"
                            "请查看 stderr 与板上 nohup 日志）"
                        )
                    return StepResult(
                        passed=False,
                        message=(
                            f"在 {exec_timeout}s 内未匹配 pass_on_stdout_regex: "
                            f"{pass_regex_str!r}{hint}"
                        ),
                        error=err_t or out_t or f"exit {exit_code}",
                        error_code="SSH_EXEC_PASS_REGEX_TIMEOUT",
                        data=data_rx,
                    )

                ignore_script_exit = self.get_param_bool(
                    params, "pass_regex_ignore_script_exit", True
                )
                if expect_zero and exit_code != 0 and not ignore_script_exit:
                    if exit_code == -1:
                        msg = (
                            "已匹配 checkpoint，但 SSH 会话异常结束（退出码 -1）；"
                            "远端脚本可能仍受网络断开影响"
                        )
                    else:
                        msg = (
                            f"已匹配 checkpoint，但远端脚本非零退出: {exit_code}"
                        )
                    return StepResult(
                        passed=False,
                        message=msg,
                        error=err_t or out_t or f"exit {exit_code}",
                        error_code="SSH_EXEC_NONZERO",
                        data=data_rx,
                    )

                if exit_code != 0 and ignore_script_exit:
                    ctx.log_warning(
                        f"已匹配 checkpoint，按 pass_regex_ignore_script_exit 忽略远端退出码: {exit_code}"
                    )

                return StepResult(
                    passed=True,
                    message="SSH 已匹配输出条件且远端脚本已结束",
                    data=data_rx,
                )

            out_b = stdout.read()
            err_b = stderr.read()
            exit_code = stdout.channel.recv_exit_status()

            out_t = out_b.decode(errors="replace").strip()
            err_t = err_b.decode(errors="replace").strip()
            ctx.log_info(f"SSH 退出码: {exit_code}")
            if out_t:
                ctx.log_info(f"stdout: {out_t[:2000]}{'…' if len(out_t) > 2000 else ''}")
            if err_t:
                ctx.log_warning(f"stderr: {err_t[:2000]}{'…' if len(err_t) > 2000 else ''}")

            data: Dict[str, Any] = {
                "exit_code": exit_code,
                "stdout": out_t,
                "stderr": err_t,
            }

            if expect_zero and exit_code != 0:
                if exit_code == -1:
                    msg = (
                        "SSH 会话异常结束（退出码 -1）：连接可能在脚本运行中被对端或网络复位"
                        "（如 Win 10054）；远端进程可能仍在执行，请查看远端日志。"
                    )
                else:
                    msg = f"命令非零退出: {exit_code}"
                return StepResult(
                    passed=False,
                    message=msg,
                    error=err_t or out_t or f"exit {exit_code}",
                    error_code="SSH_EXEC_NONZERO",
                    data=data,
                )

            return StepResult(
                passed=True,
                message="SSH 命令执行完成",
                data=data,
            )

        except paramiko.AuthenticationException as e:
            ctx.log_error(f"SSH 认证失败: {e}")
            hint_parts: List[str] = []
            if key_file and pkey is not None:
                exp = str(Path(key_file).expanduser())
                hint_parts.append(
                    f"确认用户 {username} 在主机上的 ~/.ssh/authorized_keys 是否包含"
                    f"与该私钥对应的公钥；本机核对指纹: ssh-keygen -lf \"{exp}\""
                )
            elif key_env:
                hint_parts.append(
                    f"确认用户 {username} 的 authorized_keys 是否包含环境变量 {key_env} 中私钥对应的公钥"
                )
            if allow_agent or look_for_keys:
                hint_parts.append(
                    "若命令行 ssh 正常，请对比 ssh -v 实际使用的密钥，并在步骤中指定对应 private_key_file"
                )
            for h in hint_parts:
                ctx.log_error(h)
            err = str(e)
            if hint_parts:
                err = f"{err} — " + " ".join(hint_parts)
            return StepResult(
                passed=False,
                message="SSH 认证失败",
                error=err,
                error_code="SSH_EXEC_AUTH",
            )
        except Exception as e:  # noqa: BLE001
            ctx.log_error(f"SSH 执行异常 ({type(e).__name__}): {e}")
            return StepResult(
                passed=False,
                message=f"SSH 执行异常: {type(e).__name__}",
                error=str(e),
                error_code="SSH_EXEC_EXCEPTION",
            )
        finally:
            try:
                client.close()
            except Exception:
                pass
