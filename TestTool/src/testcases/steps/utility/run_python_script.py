"""
在本机用当前 Python 解释器执行仓库内脚本（subprocess），以进程退出码判定通过/失败。

用于产线序列调用 ``Seq/scripts/mic_test.py`` 等独立脚本；参数中字符串仍由 Worker 做 ``${}`` 展开。

**超时**：步骤 YAML 里 ``timeout`` 大于 1000 时视为**毫秒**，换算为子进程超时秒数；否则使用
``params.timeout_sec``（默认 60 秒）。

**占位符**：未展开的 ``${...}`` 会报错；``${ssh_private_key_path}`` 等会经
``resolve_private_key_file_path`` 与 ``mic_record_ssh`` 对齐后补全。

**日志**：使用 ``Popen`` + 合并 stderr→stdout 单管道读取，子进程**逐行**写入 ``ctx.log_info``，
避免长时间无界面日志；子进程结束后仍将完整输出放入 ``StepResult.data``。

**控制台 / 弹窗**：Windows 下对 ``mic_test.py`` 使用 ``CREATE_NO_WINDOW | DETACHED_PROCESS``，并配合
``STARTUPINFO(SW_HIDE)``；子进程内脚本在 stdout 已重定向时也会 ``FreeConsole``。POSIX 下
``start_new_session=True``。仍可能出现的系统弹窗（杀毒、钥匙串）需在系统侧处理。
"""

from __future__ import annotations

import logging
import os
import shlex
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ...base import BaseStep, StepResult
from ...context import Context


def _format_cmd_for_log(cmd: List[str]) -> str:
    """日志中隐藏 ``--private-key-file`` 后的路径，避免私钥路径随日志扩散。"""
    parts = list(cmd)
    for i in range(len(parts) - 1):
        if parts[i] == "--private-key-file":
            parts[i + 1] = "<redacted>"
    return " ".join(parts)


def _flush_logging_handlers(logger: Optional[logging.Logger] = None) -> None:
    """刷新日志 Handler，使界面与日志文件尽快更新。"""
    seen: set[int] = set()

    def _flush_one(log: Optional[logging.Logger]) -> None:
        if log is None or id(log) in seen:
            return
        seen.add(id(log))
        for h in getattr(log, "handlers", None) or []:
            try:
                h.flush()
            except Exception:
                pass
        _flush_one(log.parent)

    _flush_one(logger)
    _flush_one(logging.getLogger())


def _testtool_package_root() -> Path:
    """``TestTool`` 包根目录（内含 ``Seq/``、``src/``）。"""
    return Path(__file__).resolve().parents[4]


def _resolve_script_path(raw: str) -> Path:
    s = (raw or "").strip()
    if not s:
        return Path()
    p = Path(s).expanduser()
    try:
        if p.is_file():
            return p.resolve()
    except OSError:
        pass
    candidates: List[Path] = [Path.cwd() / s]
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent
        candidates.append(base / s)
        candidates.append(base / "_internal" / s)
    candidates.append(_testtool_package_root() / s)
    for c in candidates:
        try:
            if c.is_file():
                return c.resolve()
        except OSError:
            continue
    return p


def _popen_kwargs_for_hidden_console(*, script_path: Path) -> Dict[str, Any]:
    """减少子进程弹出控制台窗口（Windows 为主）。``mic_test.py`` 额外加 DETACHED_PROCESS，降低闪控制台概率。"""
    kw: Dict[str, Any] = {}
    if sys.platform == "win32":
        cf = int(getattr(subprocess, "CREATE_NO_WINDOW", 0) or 0)
        # 0x00000008 DETACHED_PROCESS：不继承父控制台，常与 CREATE_NO_WINDOW 同用于无窗子进程
        if script_path.name.lower() == "mic_test.py":
            cf |= 0x00000008
        if cf:
            kw["creationflags"] = cf
        if hasattr(subprocess, "STARTUPINFO"):
            si = subprocess.STARTUPINFO()
            st_use = getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
            sw_hide = getattr(subprocess, "SW_HIDE", 0)
            if st_use and sw_hide:
                si.dwFlags |= st_use
                si.wShowWindow = sw_hide
            kw["startupinfo"] = si
    else:
        kw["start_new_session"] = True
    return kw


class RunPythonScriptStep(BaseStep):
    """``sys.executable`` + 脚本路径 + ``args``；退出码 0 为通过。"""

    def run_once(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        script_raw = self.get_param_str(params, "script", "").strip()
        if not script_raw:
            return StepResult(
                passed=False,
                message="未配置 script",
                error="需要 params.script（如 Seq/scripts/mic_test.py）",
                error_code="RUN_PY_NO_SCRIPT",
            )

        script_path = _resolve_script_path(script_raw)
        if not script_path.is_file():
            return StepResult(
                passed=False,
                message="脚本文件不存在",
                error=str(script_path),
                error_code="RUN_PY_SCRIPT_NOT_FOUND",
            )

        args_raw = params.get("args")
        args_list: List[str]
        if args_raw is None:
            args_list = []
        elif isinstance(args_raw, str):
            args_list = shlex.split(
                args_raw.strip(), posix=(sys.platform != "win32")
            )
        elif isinstance(args_raw, (list, tuple)):
            args_list = [str(x) for x in args_raw]
        else:
            return StepResult(
                passed=False,
                message="params.args 须为字符串列表或单条 shell 字符串",
                error_code="RUN_PY_BAD_ARGS",
            )

        from ...steps.cases.ssh_exec import resolve_private_key_file_path

        key_path = ""
        try:
            key_path = (resolve_private_key_file_path(params, ctx) or "").strip()
        except Exception:
            key_path = ""

        _ssh_key_placeholders = frozenset(
            {
                "${ssh_private_key_path}",
                "${context.ssh_private_key_path}",
                "$ssh_private_key_path",
            }
        )

        def _fill_ssh_placeholder(raw: str) -> str:
            s = str(raw).strip()
            if s in _ssh_key_placeholders:
                return key_path if key_path else raw
            return str(raw)

        args_list = [_fill_ssh_placeholder(a) for a in args_list]

        for i, a in enumerate(args_list):
            if "${" in a or a.strip() == "$ssh_private_key_path":
                return StepResult(
                    passed=False,
                    message="参数仍含未展开的占位符",
                    error=(
                        f"args[{i}]={a!r}。请配置：「配置 → 测试站 → 私钥配置」默认私钥、"
                        "或本步骤 params.private_key_file 指向私钥文件。"
                    ),
                    error_code="RUN_PY_UNRESOLVED_PLACEHOLDER",
                )

        cwd_raw = self.get_param_str(params, "cwd", "").strip()
        cwd: str | None = None
        if cwd_raw:
            cpath = Path(cwd_raw).expanduser()
            if not cpath.is_dir():
                return StepResult(
                    passed=False,
                    message="cwd 不是有效目录",
                    error=str(cpath),
                    error_code="RUN_PY_BAD_CWD",
                )
            cwd = str(cpath.resolve())

        timeout_ms = int(self.timeout or 0)
        if timeout_ms > 1000:
            timeout_sec = max(1, timeout_ms // 1000)
        else:
            timeout_sec = max(1, int(self.get_param_int(params, "timeout_sec", 60)))

        expect_code = int(self.get_param_int(params, "expect_exit_code", 0))

        cmd: List[str] = [sys.executable, str(script_path)] + args_list
        ctx.log_info("run_python_script: " + _format_cmd_for_log(cmd))
        _flush_logging_handlers(getattr(ctx, "logger", None))

        child_env = os.environ.copy()
        child_env.setdefault("PYTHONUNBUFFERED", "1")

        pop_kw: Dict[str, Any] = {
            "args": cmd,
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "cwd": cwd,
            "env": child_env,
            **_popen_kwargs_for_hidden_console(script_path=script_path),
        }

        combined_chunks: List[str] = []
        combined_lock = threading.Lock()
        read_done = threading.Event()

        try:
            proc = subprocess.Popen(**pop_kw)
        except Exception as e:  # noqa: BLE001
            return StepResult(
                passed=False,
                message="启动子进程失败",
                error=str(e),
                error_code="RUN_PY_SUBPROCESS",
            )

        def _pump_stdout() -> None:
            try:
                if proc.stdout is None:
                    return
                for line in iter(proc.stdout.readline, ""):
                    if line == "":
                        break
                    with combined_lock:
                        combined_chunks.append(line)
                    s = line.rstrip("\r\n")
                    if s:
                        ctx.log_info("[子进程] " + s)
                        _flush_logging_handlers(getattr(ctx, "logger", None))
            finally:
                read_done.set()
                try:
                    if proc.stdout:
                        proc.stdout.close()
                except Exception:
                    pass

        pump = threading.Thread(target=_pump_stdout, name="run_python_script_pump", daemon=True)
        pump.start()

        deadline = time.monotonic() + float(timeout_sec)
        try:
            while True:
                rc = proc.poll()
                if rc is not None:
                    break
                if time.monotonic() > deadline:
                    proc.kill()
                    try:
                        proc.wait(timeout=5)
                    except Exception:
                        pass
                    pump.join(timeout=3.0)
                    _flush_logging_handlers(getattr(ctx, "logger", None))
                    return StepResult(
                        passed=False,
                        message="脚本执行超时",
                        error=f"超过 {timeout_sec}s",
                        error_code="RUN_PY_TIMEOUT",
                    )
                time.sleep(0.05)
            proc.wait(timeout=5)
        except Exception as e:  # noqa: BLE001
            try:
                proc.kill()
            except Exception:
                pass
            pump.join(timeout=3.0)
            _flush_logging_handlers(getattr(ctx, "logger", None))
            return StepResult(
                passed=False,
                message="等待子进程结束失败",
                error=str(e),
                error_code="RUN_PY_WAIT",
            )

        pump.join(timeout=5.0)
        if not read_done.is_set():
            read_done.wait(timeout=2.0)

        full_combined = "".join(combined_chunks)
        return_code = proc.returncode
        if return_code is None:
            return_code = -1

        _flush_logging_handlers(getattr(ctx, "logger", None))

        data: Dict[str, Any] = {
            "exit_code": return_code,
            "stdout": full_combined,
            "stderr": "",
        }

        if return_code == expect_code:
            return StepResult(
                passed=True,
                message=f"脚本退出码 {return_code}",
                data=data,
            )
        tail = full_combined.strip()[-2000:] if full_combined else ""
        return StepResult(
            passed=False,
            message=f"脚本退出码 {return_code}，期望 {expect_code}",
            error=tail,
            error_code="RUN_PY_BAD_EXIT",
            data=data,
        )
