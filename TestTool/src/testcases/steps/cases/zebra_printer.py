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
import tempfile
import zipfile
import shutil
import subprocess
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

        channel = self._render_template(str(effective.get("channel", "tcp") or "tcp"), ctx, effective).strip().lower()
        host = self._render_template(str(effective.get("host", "") or ""), ctx, effective).strip()
        printer_name = self._render_template(str(effective.get("printer_name", "") or ""), ctx, effective).strip()
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
                resolved = self._resolve_local_printer_name(printer_name)
                if resolved:
                    ctx.log_warning(
                        f"本地打印机 '{printer_name}' 不可用，自动切换为可用队列: '{resolved}'"
                    )
                    printer_name = resolved
                else:
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
        hardlock_enabled = self.get_param_bool(effective, "hardlock_enabled", False)
        if hardlock_enabled:
            hardlock_tpl = str(effective.get("hardlock_zpl", "") or "")
            hardlock_rendered = self._render_template(hardlock_tpl, ctx, effective).strip()
            if hardlock_rendered:
                hardlock_payload = hardlock_rendered.encode(encoding, errors="replace")
                payload = hardlock_payload + payload
                ctx.log_info(f"已启用打印硬锁，附加字节: {len(hardlock_payload)}")
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
        # 该方法使用“位图渲染 + 内部加载 zip/rar 字体”，避免 ZPL 内置字体导致的基线/宽高差异。
        zpl = self._build_fixed_fields_image_zpl(imei=imei, scramble=scramble)
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

    def _build_fixed_fields_image_zpl(
        self, imei: str, scramble: str, params: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        固定模板：只渲染 IMEI/扰码两行到位图，再转成 ^GFA。

        这样可以保证：使用你提供的字体（IMEI 用 zip，扰码用 rar），并且位置基于像素一致，
        避免 ZPL 内置字体造成的漂移。
        """
        try:
            from PIL import Image, ImageDraw, ImageFont
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"Pillow is required for image rendering: {e}") from e

        # 固定模板参数（600dpi, 104x31mm）
        dpi = 600
        label_w_mm, label_h_mm = 104.0, 31.0
        # 可通过 Config/config.yaml -> printer.* 正式配置项覆盖
        cfg = params or {}
        imei_x_px = int(cfg.get("image_imei_x_px", 439))
        imei_y_px = int(cfg.get("image_imei_y_px", 611))
        scramble_x_px = int(cfg.get("image_scramble_x_px", 1616))
        scramble_y_px = int(cfg.get("image_scramble_y_px", 557))
        imei_font_px = int(cfg.get("image_imei_font_px", 43))
        scramble_font_px = int(cfg.get("image_scramble_font_px", 67))
        imei_prefix, scramble_prefix = "", " "
        threshold = int(cfg.get("image_threshold", 175))

        def mm_to_px(mm: float) -> int:
            return int(round(mm * float(dpi) / 25.4))

        W, H = mm_to_px(label_w_mm), mm_to_px(label_h_mm)
        imei_font_source = str(
            cfg.get("imei_font_source", r"C:/Users/VitaDynamics/Downloads/Vbot Sans 1.0(1)(1).zip")
        )
        text_font_source = str(
            cfg.get("scramble_font_source", r"C:/Users/VitaDynamics/Downloads/许可标志样式矢量图及字体库(1).rar")
        )

        def pick_valid_fonts(root: Path) -> List[Path]:
            out: List[Path] = []
            for p in root.rglob("*.ttf"):
                sp = str(p).replace("\\", "/")
                if "__MACOSX" in sp:
                    continue
                if p.name.startswith("._"):
                    continue
                out.append(p)
            for p in root.rglob("*.otf"):
                sp = str(p).replace("\\", "/")
                if "__MACOSX" in sp:
                    continue
                if p.name.startswith("._"):
                    continue
                out.append(p)
            return out

        def pick_preferred_imei_font(fonts: List[Path]) -> Optional[Path]:
            # 尽量取细/常规（Light 优先）
            prefer_keywords = ["Light", "Regular", "Medium", "Bold"]
            for kw in prefer_keywords:
                for p in fonts:
                    if kw.lower() in p.name.lower():
                        return p
            return sorted(fonts)[0] if fonts else None

        with tempfile.TemporaryDirectory(prefix="zebra_fixed_fonts_") as tmpdir:
            tmp = Path(tmpdir)
            imei_dir = tmp / "imei"
            text_dir = tmp / "text"
            imei_dir.mkdir(parents=True, exist_ok=True)
            text_dir.mkdir(parents=True, exist_ok=True)

            def resolve_font_candidates(source: str, target_dir: Path) -> List[Path]:
                src = Path(source)
                candidates: List[Path] = []
                if src.is_absolute():
                    candidates.append(src)
                else:
                    # 开发态通常以项目根目录为 cwd；打包态常以 dist/TestTool 为 cwd，
                    # 实际资源位于 dist/TestTool/_internal 下。
                    candidates.extend(
                        [
                            Path.cwd() / src,
                            Path.cwd() / "_internal" / src,
                            Path(__file__).resolve().parents[5] / src,
                            Path(__file__).resolve().parents[5] / "_internal" / src,
                        ]
                    )
                # 去重并保留顺序
                uniq_candidates: List[Path] = []
                seen = set()
                for c in candidates:
                    key = str(c).lower()
                    if key in seen:
                        continue
                    seen.add(key)
                    uniq_candidates.append(c)

                for cand in uniq_candidates:
                    if cand.exists() and cand.is_file() and cand.suffix.lower() in {".ttf", ".otf"}:
                        return [cand]
                    if cand.exists() and cand.is_dir():
                        return pick_valid_fonts(cand)
                    if cand.exists() and cand.is_file() and cand.suffix.lower() == ".zip":
                        with zipfile.ZipFile(cand, "r") as zf:
                            zf.extractall(target_dir)
                        return pick_valid_fonts(target_dir)
                    if cand.exists() and cand.is_file() and cand.suffix.lower() == ".rar":
                        seven_zip = shutil.which("7z")
                        if seven_zip:
                            cmd = [seven_zip, "x", str(cand), f"-o+{str(target_dir)}", "-y"]
                        else:
                            unrar = self._find_unrar_executable()
                            if not unrar:
                                raise RuntimeError("解压 rar 需要 7z 或 WinRAR/UnRAR。")
                            cmd = [unrar, "x", "-o+", str(cand), str(target_dir)]
                        subprocess.run(cmd, capture_output=True, text=True, check=False)
                        return pick_valid_fonts(target_dir)
                raise FileNotFoundError(
                    f"字体源不存在或格式不支持: {source}；尝试路径: "
                    + ", ".join(str(p) for p in uniq_candidates)
                )

            imei_fonts = resolve_font_candidates(imei_font_source, imei_dir)
            imei_font_path = pick_preferred_imei_font(imei_fonts)
            if imei_font_path is None:
                raise FileNotFoundError(f"IMEI 字体未找到可用 ttf/otf: {imei_font_source}")

            text_fonts = resolve_font_candidates(text_font_source, text_dir)
            scramble_font_path = text_fonts[0] if text_fonts else None
            if scramble_font_path is None:
                raise FileNotFoundError(f"扰码字体未找到可用 ttf/otf: {text_font_source}")

            imei_font = ImageFont.truetype(str(imei_font_path), size=imei_font_px)
            scramble_font_size = int(scramble_font_px)
            scramble_font = ImageFont.truetype(str(scramble_font_path), size=scramble_font_size)

            img = Image.new("L", (W, H), 255)
            draw = ImageDraw.Draw(img)
            draw.text((imei_x_px, imei_y_px), f"{imei_prefix}{imei}", fill=0, font=imei_font)

            scramble_text = f"{scramble_prefix}{scramble}"
            # 扰码防截断：超宽时自动缩小字体，并在必要时向左平移
            margin_right = 24
            margin_left = 16
            while True:
                bbox = draw.textbbox((0, 0), scramble_text, font=scramble_font)
                text_width = max(0, int(bbox[2] - bbox[0]))
                overflow = (scramble_x_px + text_width) - (W - margin_right)
                if overflow <= 0 or scramble_font_size <= 24:
                    break
                scramble_font_size -= 2
                scramble_font = ImageFont.truetype(str(scramble_font_path), size=scramble_font_size)

            bbox = draw.textbbox((0, 0), scramble_text, font=scramble_font)
            text_width = max(0, int(bbox[2] - bbox[0]))
            scramble_draw_x = min(scramble_x_px, max(margin_left, W - margin_right - text_width))
            draw.text((scramble_draw_x, scramble_y_px), scramble_text, fill=0, font=scramble_font)

            return self._image_to_zpl(img, threshold=threshold)

    @staticmethod
    def _find_unrar_executable() -> Optional[str]:
        """
        查找本机用于解压 .rar 的命令行工具。

        兼容：
        - 7z（7-Zip）
        - UnRAR / WinRAR（如果机器上没有 7z）
        """
        for name in ("unrar", "UnRAR", "WinRAR"):
            path = shutil.which(name)
            if path:
                return path
        candidates = [
            Path("C:/Program Files/WinRAR/UnRAR.exe"),
            Path("C:/Program Files/WinRAR/WinRAR.exe"),
            Path("C:/Program Files (x86)/WinRAR/UnRAR.exe"),
            Path("C:/Program Files (x86)/WinRAR/WinRAR.exe"),
        ]
        for p in candidates:
            if p.exists():
                return str(p)
        return None

    @staticmethod
    def _image_to_zpl(img: Any, threshold: int = 175) -> str:
        """
        把 PIL 灰度/二值图转成 ZPL ^GFA 位图发送内容。
        约定：黑色像素 -> 位 0；白色像素 -> 位 1（与 ^GFA 常见写法一致）。
        """
        mono = img.convert("L").point(lambda x: 0 if x < threshold else 255, mode="1")
        width, height = mono.size
        bytes_per_row = (width + 7) // 8
        total_bytes = bytes_per_row * height

        raw = bytearray()
        px = mono.load()
        for y in range(height):
            bit = 0
            count = 0
            for x in range(width):
                bit = (bit << 1) | (0 if px[x, y] else 1)
                count += 1
                if count == 8:
                    raw.append(bit & 0xFF)
                    bit = 0
                    count = 0
            if count:
                bit <<= (8 - count)
                raw.append(bit & 0xFF)

        hex_data = raw.hex().upper()
        return "^XA\n^FO0,0\n^GFA,{tb},{tb},{bpr},{data}\n^XZ".format(
            tb=total_bytes, bpr=bytes_per_row, data=hex_data
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
    def _resolve_local_printer_name(requested_name: str) -> str:
        """尝试从系统打印机列表中自动匹配一个可用本地队列。"""
        if os.name != "nt":
            return ""
        try:
            completed = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "Get-Printer | Select-Object -ExpandProperty Name",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if completed.returncode != 0:
                return ""
            names = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
            if not names:
                return ""

            def norm(s: str) -> str:
                return "".join(str(s).strip().lower().split())

            req = norm(requested_name)
            # 1) 完全匹配（忽略空白/大小写）
            for n in names:
                if norm(n) == req:
                    return n
            # 2) 包含关系匹配
            for n in names:
                nn = norm(n)
                if req and (req in nn or nn in req):
                    return n
            # 3) Zebra/ZDesigner 兜底
            for n in names:
                lower = n.lower()
                if "zdesigner" in lower or "zebra" in lower:
                    return n
            return ""
        except Exception:
            return ""

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
        # 支持模板中使用 ${var:15} 固定宽度格式：
        # - 超过长度则截断
        # - 不足长度则右侧补空格
        width = None
        if ":" in key:
            base, maybe_width = key.split(":", 1)
            base = base.strip()
            maybe_width = maybe_width.strip()
            if maybe_width.isdigit():
                key = base
                width = int(maybe_width)
        if key == "sn":
            val = str(ctx.get_sn() or "")
            if width is not None and width > 0:
                return val[:width].ljust(width)
            return val
        if key in params:
            val = str(params.get(key, "") or "")
            if width is not None and width > 0:
                return val[:width].ljust(width)
            return val
        val = str(ctx.get_data(key, "") or "")
        if width is not None and width > 0:
            return val[:width].ljust(width)
        return val

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


class ZebraImagePrintStep(ZebraPrintStep):
    """斑马打印机图片渲染打印步骤（固定模板 IMEI/扰码）。"""

    def run_once(self, ctx: Context, params: Dict[str, Any]) -> StepResult:
        effective = self._merge_params_with_config(params)
        if effective is None:
            return self.create_failure_result(
                "打印机未启用（请在 Config/config.yaml 中设置 printer.enabled=true）",
                error="PRINTER_DISABLED",
            )

        imei_tpl = str(effective.get("imei", "${sn}") or "${sn}")
        scramble_tpl = str(effective.get("scramble", "") or "")
        # 避免 imei/scramble 参数自引用（例如 imei: "${imei}"）
        # 导致变量替换时优先命中 params 并原样返回占位符。
        render_scope = dict(effective)
        render_scope.pop("imei", None)
        render_scope.pop("scramble", None)
        imei = self._render_template(imei_tpl, ctx, render_scope).strip()
        scramble = self._render_template(scramble_tpl, ctx, render_scope).strip()
        if not imei:
            return self.create_failure_result("缺少参数: imei", error="PARAM_IMEI_REQUIRED")
        if not scramble:
            return self.create_failure_result("缺少参数: scramble", error="PARAM_SCRAMBLE_REQUIRED")

        channel = self._render_template(str(effective.get("channel", "local") or "local"), ctx, effective).strip().lower()
        printer_name = self._render_template(str(effective.get("printer_name", "") or ""), ctx, effective).strip()
        host = self._render_template(str(effective.get("host", "") or ""), ctx, effective).strip()
        port = int(effective.get("port", 9100))
        copies = max(1, int(effective.get("copies", 1)))

        try:
            zpl = self._build_fixed_fields_image_zpl(imei=imei, scramble=scramble, params=effective)
        except Exception as e:  # noqa: BLE001
            return self.create_failure_result("图片渲染生成ZPL失败", error=str(e))

        forward_params = {
            **effective,
            "zpl": zpl,
            "channel": channel,
            "printer_name": printer_name,
            "host": host,
            "port": port,
            "copies": copies,
        }
        return ZebraPrintStep.run_once(self, ctx, forward_params)

