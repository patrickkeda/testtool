"""
Zebra printer step.

Send ZPL commands to Zebra printer over TCP (default port 9100).
"""

from __future__ import annotations

import re
import socket
import ctypes
import ctypes.wintypes as wintypes
import os
from pathlib import Path
from typing import Any, Dict, Optional, List, Tuple

try:
    import winreg
except Exception:  # noqa: BLE001
    winreg = None

from ...base import BaseStep, StepResult
from ...context import Context


_TPL_PATTERN = re.compile(r"\$\{([^}]+)\}")


class ZebraPrintStep(BaseStep):
    """斑马打印机打印步骤（ZPL over TCP）。"""

    def run_once(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        effective = self._merge_params_with_config(params)
        if effective is None:
            return self.create_failure_result(
                "打印机未启用（请在 Config/config.yaml 中设置 printer.enabled=true）",
                error="PRINTER_DISABLED",
            )

        channel = str(effective.get("channel", "tcp") or "tcp").strip().lower()
        host = str(effective.get("host", "")).strip()
        printer_name = str(effective.get("printer_name", "")).strip()
        if channel not in {"tcp", "local"}:
            return self.create_failure_result("打印通道不支持", error=f"UNSUPPORTED_CHANNEL:{channel}")

        if channel == "tcp":
            if not host:
                return self.create_failure_result(
                    "缺少打印机地址（请在 config 的 printer.host 或步骤 params.host 中配置）",
                    error="PARAM_HOST_REQUIRED",
                )
            try:
                port = int(effective.get("port", 9100))
            except Exception:
                return self.create_failure_result("打印机端口无效", error="PARAM_PORT_INVALID")
        else:
            if not printer_name:
                return self.create_failure_result(
                    "本地打印通道缺少打印机名称（printer_name）",
                    error="PARAM_PRINTER_NAME_REQUIRED",
                )
            port = int(effective.get("port", 9100))

            detect_software = self.get_param_bool(effective, "detect_software", True)
            if detect_software:
                keywords = effective.get("required_software_keywords", ["Zebra Setup Utilities", "ZDesigner"])
                if not isinstance(keywords, list):
                    keywords = ["Zebra Setup Utilities", "ZDesigner"]
                ok, detail = self._detect_zebra_software([str(k) for k in keywords if str(k).strip()])
                if not ok:
                    installer_hint = self._build_installer_hint(effective)
                    self._handle_installer_prompt(ctx, effective, f"未检测到斑马打印软件/驱动: {detail}")
                    return self.create_failure_result(
                        f"未检测到斑马打印软件/驱动: {detail}。{installer_hint}",
                        error="ZEBRA_SOFTWARE_MISSING",
                    )

            exists, detail = self._printer_exists(printer_name)
            if not exists:
                return self.create_failure_result(
                    f"本地打印机不存在或不可用: {printer_name} ({detail})",
                    error="LOCAL_PRINTER_NOT_FOUND",
                )

        timeout_ms = int(effective.get("timeout_ms", 3000))
        copies = max(1, int(effective.get("copies", 1)))
        encoding = str(effective.get("encoding", "utf-8") or "utf-8")
        enable_preview = self.get_param_bool(effective, "preview", False)
        preview_only = self.get_param_bool(effective, "preview_only", False)
        save_preview = self.get_param_bool(effective, "save_preview", True)

        try:
            zpl_text = self._load_zpl_text(effective)
        except Exception as e:  # noqa: BLE001
            return self.create_failure_result("读取ZPL模板失败", error=str(e))

        if not zpl_text.strip():
            return self.create_failure_result("ZPL内容为空", error="PARAM_ZPL_EMPTY")

        rendered = self._render_template(zpl_text, ctx, effective)
        payload = rendered.encode(encoding, errors="replace")
        timeout_s = max(0.1, timeout_ms / 1000.0)
        preview_file = ""

        if save_preview:
            try:
                preview_file = self._save_preview_file(rendered, ctx, effective)
                ctx.log_info(f"打印预览文件已保存: {preview_file}")
            except Exception as e:  # noqa: BLE001
                ctx.log_warning(f"保存打印预览文件失败: {e}")

        if enable_preview:
            accepted = self._show_preview_dialog(ctx, rendered)
            if not accepted:
                return self.create_failure_result(
                    "用户取消打印预览确认",
                    error="PREVIEW_CANCELLED",
                    data={"preview_file": preview_file},
                )

        if preview_only:
            return self.create_success_result(
                {
                    "preview_only": True,
                    "preview_file": preview_file,
                    "channel": channel,
                    "host": host,
                    "port": port,
                    "printer_name": printer_name,
                    "copies": copies,
                    "bytes": len(payload),
                },
                "打印预览完成（未实际打印）",
            )

        ctx.log_info(
            f"准备发送斑马打印指令: channel={channel}, host={host}:{port}, "
            f"printer_name={printer_name}, copies={copies}, bytes={len(payload)}"
        )
        try:
            if channel == "tcp":
                self._send_via_tcp(host, port, timeout_s, copies, payload)
            else:
                self._send_via_local_printer(printer_name, copies, payload)
            return self.create_success_result(
                {
                    "channel": channel,
                    "host": host,
                    "port": port,
                    "printer_name": printer_name,
                    "copies": copies,
                    "bytes": len(payload),
                    "preview_file": preview_file,
                },
                "斑马打印机调用成功",
            )
        except Exception as e:  # noqa: BLE001
            ctx.log_error(f"斑马打印机调用失败: {e}")
            return self.create_failure_result("斑马打印机调用失败", error=str(e))

    @staticmethod
    def _send_via_tcp(host: str, port: int, timeout_s: float, copies: int, payload: bytes) -> None:
        with socket.create_connection((host, port), timeout=timeout_s) as conn:
            conn.settimeout(timeout_s)
            for _ in range(copies):
                conn.sendall(payload)

    @staticmethod
    def _send_via_local_printer(printer_name: str, copies: int, payload: bytes) -> None:
        # 使用 winspool 原生 API 以 RAW 方式发送 ZPL 到本地打印队列（无需 pywin32）
        winspool = ctypes.WinDLL("winspool.drv")

        class DOC_INFO_1W(ctypes.Structure):
            _fields_ = [
                ("pDocName", wintypes.LPWSTR),
                ("pOutputFile", wintypes.LPWSTR),
                ("pDatatype", wintypes.LPWSTR),
            ]

        open_printer = winspool.OpenPrinterW
        open_printer.argtypes = [wintypes.LPWSTR, ctypes.POINTER(wintypes.HANDLE), wintypes.LPVOID]
        open_printer.restype = wintypes.BOOL

        close_printer = winspool.ClosePrinter
        close_printer.argtypes = [wintypes.HANDLE]
        close_printer.restype = wintypes.BOOL

        start_doc = winspool.StartDocPrinterW
        start_doc.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPBYTE]
        start_doc.restype = wintypes.DWORD

        end_doc = winspool.EndDocPrinter
        end_doc.argtypes = [wintypes.HANDLE]
        end_doc.restype = wintypes.BOOL

        start_page = winspool.StartPagePrinter
        start_page.argtypes = [wintypes.HANDLE]
        start_page.restype = wintypes.BOOL

        end_page = winspool.EndPagePrinter
        end_page.argtypes = [wintypes.HANDLE]
        end_page.restype = wintypes.BOOL

        write_printer = winspool.WritePrinter
        write_printer.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
        write_printer.restype = wintypes.BOOL

        h_printer = wintypes.HANDLE()
        if not open_printer(printer_name, ctypes.byref(h_printer), None):
            raise OSError(f"OpenPrinterW failed for '{printer_name}'")
        try:
            for _ in range(copies):
                doc = DOC_INFO_1W("Zebra RAW ZPL", None, "RAW")
                if start_doc(h_printer, 1, ctypes.cast(ctypes.byref(doc), wintypes.LPBYTE)) == 0:
                    raise OSError("StartDocPrinterW failed")
                try:
                    if not start_page(h_printer):
                        raise OSError("StartPagePrinter failed")
                    try:
                        written = wintypes.DWORD(0)
                        buf = ctypes.create_string_buffer(payload)
                        if not write_printer(h_printer, buf, len(payload), ctypes.byref(written)):
                            raise OSError("WritePrinter failed")
                        if int(written.value) != len(payload):
                            raise OSError(f"WritePrinter short write: {written.value}/{len(payload)}")
                    finally:
                        end_page(h_printer)
                finally:
                    end_doc(h_printer)
        finally:
            close_printer(h_printer)

    def print_imei_and_scramble(
        self,
        ctx: Context,
        imei: str,
        scramble: str,
        *,
        channel: str = "local",
        printer_name: str = "ZDesigner 110Xi4 600 dpi (副本 1)",
        host: str = "",
        port: int = 9100,
        copies: int = 1,
    ) -> StepResult:
        """
        固定模板快速打印入口：只需传 IMEI 和扰码。

        该方法会使用当前已调好的固定模板参数生成 ZPL 并直接打印。
        """
        zpl = self._build_fixed_fields_zpl(imei=imei, scramble=scramble)
        params: Dict[str, Any] = {
            "channel": channel,
            "printer_name": printer_name,
            "host": host,
            "port": int(port),
            "copies": max(1, int(copies)),
            "zpl": zpl,
            "save_preview": True,
            "preview": False,
        }
        return self.run_once(ctx, params)

    @staticmethod
    def _build_fixed_fields_zpl(imei: str, scramble: str) -> str:
        # 当前定版模板参数（600dpi, 104x31mm）
        dpi = 600
        label_w_mm, label_h_mm = 104.0, 31.0
        imei_x_mm, imei_y_mm = 11.2, 27.66
        scramble_x_mm, scramble_y_mm = 59.6, 25.0
        imei_h_mm, imei_w_mm = 1.8, 1.1
        scramble_h_mm, scramble_w_mm = 3.0, 2.2
        imei_prefix, scramble_prefix = "", " "

        def mm_to_px(mm: float) -> int:
            return int(round(mm * float(dpi) / 25.4))

        return (
            "^XA\n"
            f"^PW{mm_to_px(label_w_mm)}\n"
            f"^LL{mm_to_px(label_h_mm)}\n"
            "^CI28\n"
            f"^FO{mm_to_px(imei_x_mm)},{mm_to_px(imei_y_mm)}"
            f"^A0N,{mm_to_px(imei_h_mm)},{mm_to_px(imei_w_mm)}"
            f"^FD{imei_prefix}{imei}^FS\n"
            f"^FO{mm_to_px(scramble_x_mm)},{mm_to_px(scramble_y_mm)}"
            f"^A0N,{mm_to_px(scramble_h_mm)},{mm_to_px(scramble_w_mm)}"
            f"^FD{scramble_prefix}{scramble}^FS\n"
            "^XZ"
        )

    @staticmethod
    def _build_installer_hint(params: Dict[str, Any]) -> str:
        installer_path = str(params.get("installer_path", "") or "").strip()
        installer_url = str(params.get("installer_url", "") or "").strip()
        hints = []
        if installer_path:
            hints.append(f"安装包路径: {installer_path}")
        if installer_url:
            hints.append(f"下载地址: {installer_url}")
        if not hints:
            return "请联系工程师安装 Zebra Setup Utilities/ZDesigner 驱动。"
        return "请先安装后再重试。 " + "；".join(hints)

    @staticmethod
    def _printer_exists(printer_name: str) -> Tuple[bool, str]:
        winspool = ctypes.WinDLL("winspool.drv")
        open_printer = winspool.OpenPrinterW
        open_printer.argtypes = [wintypes.LPWSTR, ctypes.POINTER(wintypes.HANDLE), wintypes.LPVOID]
        open_printer.restype = wintypes.BOOL

        close_printer = winspool.ClosePrinter
        close_printer.argtypes = [wintypes.HANDLE]
        close_printer.restype = wintypes.BOOL

        handle = wintypes.HANDLE()
        if not open_printer(printer_name, ctypes.byref(handle), None):
            return False, "OpenPrinterW failed"
        try:
            return True, "ok"
        finally:
            close_printer(handle)

    @staticmethod
    def _detect_zebra_software(keywords: List[str]) -> Tuple[bool, str]:
        if os.name != "nt" or winreg is None:
            return True, "non-windows"

        # 常见安装路径优先快速检查
        common_paths = [
            Path("C:/Program Files/Zebra Technologies/Zebra Setup Utilities"),
            Path("C:/Program Files (x86)/Zebra Technologies/Zebra Setup Utilities"),
            Path("C:/Program Files/Zebra Technologies"),
            Path("C:/Program Files (x86)/Zebra Technologies"),
        ]
        for p in common_paths:
            if p.exists():
                return True, f"path:{p}"

        # 退化到注册表卸载项检查
        uninstall_roots = [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        ]
        lowered = [k.lower() for k in keywords if k]

        for root, path in uninstall_roots:
            try:
                with winreg.OpenKey(root, path) as key:
                    count = winreg.QueryInfoKey(key)[0]
                    for i in range(count):
                        sub_name = winreg.EnumKey(key, i)
                        try:
                            with winreg.OpenKey(key, sub_name) as sub:
                                display_name, _ = winreg.QueryValueEx(sub, "DisplayName")
                                name_lower = str(display_name).lower()
                                if any(k in name_lower for k in lowered):
                                    return True, f"registry:{display_name}"
                        except OSError:
                            continue
            except OSError:
                continue

        return False, f"keywords={keywords}"

    def _handle_installer_prompt(self, ctx: Context, params: Dict[str, Any], reason: str) -> None:
        installer_path = str(params.get("installer_path", "") or "").strip()
        installer_url = str(params.get("installer_url", "") or "").strip()
        prompt_install = self.get_param_bool(params, "prompt_install_on_missing", True)
        auto_open = self.get_param_bool(params, "auto_open_installer_on_missing", False)

        if auto_open:
            self._open_installer_target(ctx, installer_path, installer_url)
            return

        if not prompt_install:
            return

        message = reason
        if installer_path:
            message += f"\n\n安装包: {installer_path}"
        if installer_url:
            message += f"\n下载地址: {installer_url}"
        message += "\n\n是否立即打开安装程序/下载页？"

        try:
            from src.app.ui_invoker import invoke_in_gui_confirmation

            accepted = invoke_in_gui_confirmation(
                title="斑马打印机未安装",
                message=message,
                confirm_text="立即安装",
                cancel_text="稍后",
                port=ctx.port,
                allow_cancel=True,
            )
            if accepted:
                self._open_installer_target(ctx, installer_path, installer_url)
        except Exception as e:  # noqa: BLE001
            ctx.log_warning(f"安装提示弹窗失败: {e}")

    @staticmethod
    def _open_installer_target(ctx: Context, installer_path: str, installer_url: str) -> None:
        try:
            if installer_path:
                p = Path(installer_path)
                if p.exists() and os.name == "nt":
                    os.startfile(str(p))  # type: ignore[attr-defined]
                    ctx.log_info(f"已打开安装程序: {p}")
                    return
            if installer_url and os.name == "nt":
                os.startfile(installer_url)  # type: ignore[attr-defined]
                ctx.log_info(f"已打开下载地址: {installer_url}")
        except Exception as e:  # noqa: BLE001
            ctx.log_warning(f"打开安装程序/下载地址失败: {e}")

    def _merge_params_with_config(self, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """合并 Config/config.yaml 中的 printer 段与步骤 params，后者优先。"""
        candidates = [
            Path("Config/config.yaml"),
            Path(__file__).resolve().parents[4] / "Config" / "config.yaml",
        ]
        cfg_path = next((p for p in candidates if p.exists()), None)
        if cfg_path is None:
            return dict(params)

        try:
            from ....config.service import ConfigService

            root = ConfigService(str(cfg_path)).load()
            printer = getattr(root, "printer", None)
            if printer is None:
                return dict(params)
            if hasattr(printer, "model_dump"):
                defaults = printer.model_dump()
            else:
                defaults = printer.dict()
            if not defaults.get("enabled", True):
                return None
            defaults.pop("enabled", None)
            return {**defaults, **params}
        except Exception:  # noqa: BLE001
            return dict(params)

    @staticmethod
    def _load_zpl_text(params: Dict[str, Any]) -> str:
        inline = str(params.get("zpl", "") or "")
        if inline.strip():
            return inline

        zpl_file = str(params.get("zpl_file", "") or "").strip()
        if not zpl_file:
            raise ValueError("缺少参数: zpl 或 zpl_file（也可在 config.printer.zpl_file 中配置默认模板）")

        file_path = Path(zpl_file)
        if not file_path.is_absolute():
            file_path = Path.cwd() / file_path
        if not file_path.exists():
            raise FileNotFoundError(f"ZPL模板不存在: {file_path}")
        return file_path.read_text(encoding="utf-8")

    @staticmethod
    def _resolve_var(name: str, ctx: Context, params: Dict[str, Any]) -> str:
        key = name.strip()
        if not key:
            return ""
        if key == "sn":
            return str(ctx.get_sn() or "")
        if key in params:
            return str(params.get(key, "") or "")
        return str(ctx.get_data(key, "") or "")

    def _render_template(self, text: str, ctx: Context, params: Dict[str, Any]) -> str:
        def _repl(match: re.Match[str]) -> str:
            return self._resolve_var(match.group(1), ctx, params)

        return _TPL_PATTERN.sub(_repl, text)

    def _show_preview_dialog(self, ctx: Context, rendered_zpl: str) -> bool:
        preview_text = rendered_zpl.strip()
        if len(preview_text) > 1200:
            preview_text = f"{preview_text[:1200]}\n... (已截断)"
        message = (
            "请确认打印预览内容:\n\n"
            f"{preview_text}\n\n"
            "点击“确认打印”继续，点击“取消”终止。"
        )
        try:
            from src.app.ui_invoker import invoke_in_gui_confirmation

            return invoke_in_gui_confirmation(
                title="打印预览",
                message=message,
                confirm_text="确认打印",
                cancel_text="取消",
                port=ctx.port,
                allow_cancel=True,
            )
        except Exception as e:  # noqa: BLE001
            # 无GUI环境时退化为自动通过，避免阻塞生产流程
            ctx.log_warning(f"打印预览弹窗失败，自动继续: {e}")
            return True

    def _save_preview_file(self, rendered_zpl: str, ctx: Context, params: Dict[str, Any]) -> str:
        output_dir = str(params.get("preview_dir", "Result/print_preview") or "Result/print_preview").strip()
        sn = str(ctx.get_sn() or "").strip()
        if not sn or sn == "NULL":
            sn = "unknown_sn"
        step_id = str(getattr(self, "step_id", "") or "zebra_print")
        file_name_tpl = str(params.get("preview_file_name", f"{sn}_{step_id}.zpl") or f"{sn}_{step_id}.zpl").strip()
        file_name = self._render_template(file_name_tpl, ctx, params)

        path = Path(output_dir)
        if not path.is_absolute():
            path = Path.cwd() / path
        path.mkdir(parents=True, exist_ok=True)
        full_path = path / file_name
        full_path.write_text(rendered_zpl, encoding="utf-8")
        return str(full_path)

