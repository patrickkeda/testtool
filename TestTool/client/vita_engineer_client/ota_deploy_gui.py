#!/usr/bin/env python3
"""VITA OTA 图形界面（业务逻辑在 ota_deploy，本文件仅含 Tk UI）。"""

import os
import sys
import threading
import time
import traceback
import fnmatch
from datetime import datetime
from typing import Callable, Optional

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

try:
    import paramiko  # noqa: F401 — 启动前检查 SSH 依赖
except ImportError:
    print("错误: 缺少依赖库 paramiko。请执行: pip3 install paramiko")
    sys.exit(1)

from ota_deploy import (
    CONFIG_FILE,
    DEFAULT_CONFIG,
    PKG_RULES,
    PKG_RULES_ENCRYPTED,
    PKG_RULES_PLAIN,
    DeployExecutor,
    load_config,
    OTA_DEFAULT_VERIFY_TIMEOUT_SEC,
    run_ota_deploy,
    save_config,
    discover_ota_manifests,
    ota_package_set_configured,
    load_ota_manifest,
    manifest_is_encrypted,
    merge_cfg_with_defaults,
    ota_pkg_storage_key,
    package_path_matches_encryption,
    resolve_packages_from_manifest,
    scan_package_dir,
    validate_ota_packages_match_manifest,
    validate_ota_packages_md5_match_manifest,
    validate_sn_packages,
    resolve_manifest_check_encryption,
    get_configured_ota_manifest,
    prepare_pc_network_for_device_swap,
    recover_hung_s100_device,
)

_FAIL_MARKERS = ("❌", "失败", "错误", "[FAIL]", "Traceback", "Exception", "超时", "未与", "校验", "⚠️")


def _format_failure_summary(log_lines: list[str], log_area_text: str = "", exc_msg: str = "") -> str:
    def _pick(source: list[str], *, limit: int = 8) -> list[str]:
        hits = [ln for ln in source if any(m in ln for m in _FAIL_MARKERS)]
        if hits:
            return hits[-limit:]
        nonempty = [ln for ln in source if ln.strip()]
        return nonempty[-limit:]

    parts: list[str] = []
    if exc_msg.strip():
        parts.append(f"程序异常:\n{exc_msg.strip()}")

    summary = _pick(log_lines)
    if summary:
        parts.append("错误摘要:\n" + "\n".join(summary))
    else:
        widget_lines: list[str] = []
        for ln in log_area_text.splitlines():
            ln = ln.strip()
            if not ln:
                continue
            if ln.startswith("[") and "] " in ln:
                widget_lines.append(ln.split("] ", 1)[1])
            else:
                widget_lines.append(ln)
        widget_summary = _pick(widget_lines)
        if widget_summary:
            parts.append("错误摘要:\n" + "\n".join(widget_summary))

    if not parts:
        return "未知错误（任务未产生日志输出）"
    return "\n\n".join(parts)


# ── 弹窗类：SN 输入与校验 ──────────────────────────────────────────────────────────
class SNDialog(tk.Toplevel):
    def __init__(self, parent, initial_sn=""):
        super().__init__(parent)
        self.title("SN 与版本包校验")
        self.result = None
        self.sn_value = ""

        self.transient(parent)
        self.grab_set()

        # 居中显示
        window_width, window_height = 400, 150
        position_right = int(parent.winfo_rootx() + parent.winfo_width()/2 - window_width/2)
        position_down = int(parent.winfo_rooty() + parent.winfo_height()/2 - window_height/2)
        self.geometry(f"{window_width}x{window_height}+{position_right}+{position_down}")

        tk.Label(self, text="请输入 19 位 SN 码，用于校验选中的 APP 版本包：").pack(padx=20, pady=(15, 5))
        self.entry = tk.Entry(self, width=35, font=("Arial", 11))
        self.entry.pack(padx=20, pady=5)
        self.entry.insert(0, initial_sn)
        self.entry.focus_set()

        self.entry.bind("<Return>", lambda e: self.on_confirm())

        btn_frame = tk.Frame(self)
        btn_frame.pack(pady=10)

        tk.Button(btn_frame, text="✅ 确定并校验", command=self.on_confirm, bg="#007aff", fg="black").pack(side=tk.LEFT, padx=10)
        tk.Button(btn_frame, text="⏭️ 跳过校验", command=self.on_skip).pack(side=tk.LEFT, padx=10)
        tk.Button(btn_frame, text="✖ 取消", command=self.on_cancel).pack(side=tk.LEFT, padx=10)

        self.protocol("WM_DELETE_WINDOW", self.on_cancel)
        self.wait_window(self)

    def on_confirm(self):
        self.sn_value = self.entry.get().strip()
        self.result = "confirm"
        self.destroy()

    def on_skip(self):
        self.result = "skip"
        self.destroy()

    def on_cancel(self):
        self.result = "cancel"
        self.destroy()


class OtaPkgKindDialog(tk.Toplevel):
    """双板 OTA：确认使用加密或未加密升级包。"""

    def __init__(self, parent, *, encrypted_available: bool, plain_available: bool):
        super().__init__(parent)
        self.title("确认升级包类型")
        self.result: Optional[bool] = None
        self.transient(parent)
        self.grab_set()

        w, h = 460, 220
        x = int(parent.winfo_rootx() + parent.winfo_width() / 2 - w / 2)
        y = int(parent.winfo_rooty() + parent.winfo_height() / 2 - h / 2)
        self.geometry(f"{w}x{h}+{x}+{y}")

        tk.Label(
            self,
            text="双板 OTA：请确认本次使用的升级包类型",
            font=("Arial", 11, "bold"),
        ).pack(padx=20, pady=(16, 8))

        if not encrypted_available and not plain_available:
            tk.Label(self, text="未配置任何升级包，请先填写至少一套。", fg="red").pack(padx=20)
            tk.Button(self, text="关闭", command=self.on_cancel).pack(pady=12)
            self.protocol("WM_DELETE_WINDOW", self.on_cancel)
            self.wait_window(self)
            return

        default = "encrypted" if encrypted_available and not plain_available else "plain"
        if plain_available and not encrypted_available:
            default = "plain"
        elif encrypted_available and plain_available:
            default = "plain"

        self._choice = tk.StringVar(value=default)

        plain_state = tk.NORMAL if plain_available else tk.DISABLED
        enc_state = tk.NORMAL if encrypted_available else tk.DISABLED

        tk.Radiobutton(
            self,
            text="未加密升级包（lifecycle 0-3）",
            variable=self._choice,
            value="plain",
            state=plain_state,
        ).pack(anchor="w", padx=28, pady=4)
        tk.Radiobutton(
            self,
            text="加密升级包（lifecycle ≥ 4）",
            variable=self._choice,
            value="encrypted",
            state=enc_state,
        ).pack(anchor="w", padx=28, pady=4)

        if not plain_available:
            tk.Label(self, text="（未配置未加密包，不可选）", fg="gray").pack(anchor="w", padx=44)
        if not encrypted_available:
            tk.Label(self, text="（未配置加密包，不可选）", fg="gray").pack(anchor="w", padx=44)

        btn_row = tk.Frame(self)
        btn_row.pack(pady=16)
        tk.Button(btn_row, text="确认并开始", command=self.on_ok, width=12).pack(side=tk.LEFT, padx=8)
        tk.Button(btn_row, text="取消", command=self.on_cancel, width=8).pack(side=tk.LEFT, padx=8)

        self.protocol("WM_DELETE_WINDOW", self.on_cancel)
        self.wait_window(self)

    def on_ok(self):
        self.result = self._choice.get() == "encrypted"
        self.destroy()

    def on_cancel(self):
        self.result = None
        self.destroy()


# ── GUI 界面 ──────────────────────────────────────────────────────────
class OTADeployGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("VITA 部署工具")
        self.root.geometry("1100x900")
        self.root.minsize(900, 700)
        self.bg = "#f5f5f5"
        self.root.configure(bg=self.bg)
        
        self.cfg = load_config()
        self.sync_rows = []
        self.last_sn = ""  # 缓存上次输入的 SN
        self._package_dir = ""  # 「扫描填充包」目录，双板 OTA 时用于 lifecycle 选包
        
        self._build_ui()
        self._load_fields()

    def _build_ui(self):
        paned = tk.PanedWindow(
            self.root, orient=tk.VERTICAL, sashwidth=5, sashrelief=tk.RAISED, bg="#cccccc"
        )
        paned.pack(fill=tk.BOTH, expand=True)

        container = tk.Frame(paned, bg=self.bg, padx=15, pady=5)
        log_shell = tk.LabelFrame(
            paned,
            text=" ▼ 执行日志（点「执行 OTA 升级」后看这里） ",
            bg=self.bg,
            padx=8,
            pady=6,
            fg="#333",
            font=("Arial", 10, "bold"),
        )

        f_ssh = tk.LabelFrame(container, text=" 1. 基础连接凭据 ", bg=self.bg, padx=10, pady=5)
        f_ssh.pack(fill=tk.X, pady=2)
        r1 = tk.Frame(f_ssh, bg=self.bg); r1.pack(fill=tk.X)
        self.s100_ip = self._labeled_entry(r1, "S100 IP:", 15)
        self.x5_ip = self._labeled_entry(r1, "X5 IP:", 15, padx=30)
        r2 = tk.Frame(f_ssh, bg=self.bg, pady=5); r2.pack(fill=tk.X)
        self.use_key = tk.BooleanVar()
        tk.Checkbutton(r2, text="私钥模式", variable=self.use_key, bg=self.bg, command=self._on_key_toggle).pack(side=tk.LEFT)
        self.key_path = tk.Entry(r2, width=45, bg="white"); self.key_path.pack(side=tk.LEFT, padx=5)
        tk.Button(r2, text="选择私钥", command=self._browse_key).pack(side=tk.LEFT)
        r2b = tk.Frame(f_ssh, bg=self.bg, pady=2)
        r2b.pack(fill=tk.X)
        tk.Button(
            r2b,
            text="🔁 换台清网络",
            command=self._manual_swap_network_prep,
        ).pack(side=tk.LEFT)
        tk.Button(
            r2b,
            text="🔧 恢复 Hang",
            command=self._manual_hang_recovery,
        ).pack(side=tk.LEFT, padx=(6, 0))
        tk.Label(
            r2b,
            text="换台清 ARP；Hang=远程 reboot（ping/SSH 均不通时需人工关电）",
            bg=self.bg,
            fg="#666",
            anchor="w",
        ).pack(side=tk.LEFT, padx=(8, 0))

        ota_bg = "#e8f4f8"
        _ota_label_col = 220
        f_ota = tk.LabelFrame(container, text=" 2. OTA 升级功能 ", bg=ota_bg, padx=10, pady=5)
        f_ota.pack(fill=tk.X, pady=5)
        f_ota.columnconfigure(0, minsize=_ota_label_col)
        f_ota.columnconfigure(1, weight=1)

        r_o_t = tk.Frame(f_ota, bg=ota_bg)
        r_o_t.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 6))
        self.ota_s100_v, self.ota_x5_v, self.use_tmux = (
            tk.BooleanVar(),
            tk.BooleanVar(),
            tk.BooleanVar(),
        )
        tk.Checkbutton(r_o_t, text="升级 S100", variable=self.ota_s100_v, bg=ota_bg).pack(
            side=tk.LEFT
        )
        tk.Checkbutton(r_o_t, text="升级 X5", variable=self.ota_x5_v, bg=ota_bg, padx=15).pack(
            side=tk.LEFT
        )
        tk.Checkbutton(r_o_t, text="Tmux 后台", variable=self.use_tmux, bg=ota_bg, padx=15).pack(
            side=tk.LEFT
        )

        self.ota_paths_encrypted: dict = {}
        self.ota_paths_plain: dict = {}
        grid_row = 1

        def _build_pkg_set(
            parent: tk.Widget,
            title: str,
            entries: dict,
            row: int,
            *,
            encrypted: bool,
        ) -> tk.Entry:
            pkg_rules = PKG_RULES_ENCRYPTED if encrypted else PKG_RULES_PLAIN
            box = tk.LabelFrame(parent, text=f" {title} ", bg=ota_bg, padx=8, pady=6)
            box.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(4, 2))
            box.columnconfigure(0, minsize=_ota_label_col)
            box.columnconfigure(1, weight=1)
            r = 0
            scan_row = tk.Frame(box, bg=ota_bg)
            scan_row.grid(row=r, column=0, columnspan=3, sticky="e", pady=(0, 4))
            tk.Button(
                scan_row,
                text="🔍 核对 MD5",
                command=lambda enc=encrypted: self._verify_packages_md5(encrypted=enc),
            ).pack(side=tk.RIGHT, padx=(6, 0))
            tk.Button(
                scan_row,
                text="📂 扫描填充本组包",
                command=lambda enc=encrypted: self._scan_fill_packages(encrypted=enc),
            ).pack(side=tk.RIGHT)
            r += 1
            manifest_entry = tk.Entry(box, bg="white")
            tk.Label(box, text="manifest:", anchor="e", bg=ota_bg).grid(
                row=r, column=0, sticky="e", padx=(0, 8), pady=3
            )
            manifest_entry.grid(row=r, column=1, sticky="ew", padx=(0, 5), pady=3)
            tk.Button(
                box,
                text="选择",
                width=8,
                command=lambda me=manifest_entry, es=entries, enc=encrypted: self._browse_manifest(
                    me, es, expect_encrypted=enc
                ),
            ).grid(row=r, column=2, sticky="e", pady=3)
            r += 1
            _label_to_cfg_key = {
                "S100 APP": "s100_app_path",
                "S100 SYS": "s100_sys_path",
                "X5 APP": "x5_app_path",
                "X5 SYS": "x5_sys_path",
            }
            for label, pattern in pkg_rules.items():
                tk.Label(box, text=f"{label}:", anchor="e", bg=ota_bg).grid(
                    row=r, column=0, sticky="e", padx=(0, 8), pady=2
                )
                ent = tk.Entry(box, bg="white")
                ent.grid(row=r, column=1, sticky="ew", padx=(0, 5), pady=2)
                tk.Button(
                    box,
                    text="选择",
                    width=8,
                    command=lambda e=ent, pat=pattern, enc=encrypted, ck=_label_to_cfg_key[
                        label
                    ]: self._browse_ota(e, pat, encrypted=enc, cfg_key=ck),
                ).grid(row=r, column=2, sticky="e", pady=2)
                entries[label] = ent
                r += 1
            return manifest_entry

        self.manifest_encrypted = _build_pkg_set(
            f_ota,
            "加密升级包 (lifecycle≥4)",
            self.ota_paths_encrypted,
            grid_row,
            encrypted=True,
        )
        grid_row += 1
        self.manifest_plain = _build_pkg_set(
            f_ota,
            "未加密升级包 (lifecycle 0-3)",
            self.ota_paths_plain,
            grid_row,
            encrypted=False,
        )
        grid_row += 1

        tk.Label(
            f_ota,
            text="双板 OTA：两套包可分别点「扫描填充本组包」；开始时弹窗确认用哪套。单板只填对应一套即可。",
            bg=ota_bg,
            fg="#444",
            anchor="w",
        ).grid(row=grid_row, column=0, columnspan=3, sticky="w", pady=(2, 0))
        grid_row += 1

        btn_row = grid_row
        self.ota_btn = tk.Button(
            f_ota,
            text="🚀 执行 OTA 升级",
            bg="#007aff",
            font=("Arial", 10, "bold"),
            command=self._pre_start_ota,
        )
        self.ota_btn.grid(row=btn_row, column=0, columnspan=3, pady=(8, 2))

        self.status_var = tk.StringVar(value="就绪。执行 OTA 或文件同步后，日志在窗口下方黑框。")
        tk.Label(
            f_ota,
            textvariable=self.status_var,
            bg="#fff8e1",
            fg="#333",
            anchor="w",
            wraplength=980,
            padx=8,
            pady=6,
            relief=tk.GROOVE,
        ).grid(row=btn_row + 1, column=0, columnspan=3, sticky="ew", pady=(4, 0))

        f_sync = tk.LabelFrame(container, text=" 3. 快速文件同步 ", bg="#eef9f0", padx=10, pady=5)
        f_sync.pack(fill=tk.X, pady=5)
        cv_f = tk.Frame(f_sync, bg="white")
        cv_f.pack(fill=tk.X)
        # 增大canvas宽度，防止内容被裁剪
        canvas_width = 1200
        self.canvas = tk.Canvas(cv_f, bg="white", height=100, highlightthickness=0, width=canvas_width)
        self.scrollbar = ttk.Scrollbar(cv_f, orient="vertical", command=self.canvas.yview)
        self.scroll_f = tk.Frame(self.canvas, bg="white")
        self.scroll_f.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0, 0), window=self.scroll_f, anchor="nw", width=canvas_width)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        rsb = tk.Frame(f_sync, bg="#eef9f0", pady=5); rsb.pack(fill=tk.X)
        tk.Button(rsb, text="➕ 增加同步项", command=self.add_sync_row, fg="green").pack(side=tk.LEFT)
        self.sync_btn = tk.Button(rsb, text="📁 执行文件同步", bg="#34c759", font=("Arial", 10, "bold"), command=lambda: self._start("sync"))
        self.sync_btn.pack(side=tk.RIGHT)

        f_config_ctrl = tk.Frame(container, bg="#eeeeee", padx=10, pady=8)
        f_config_ctrl.pack(fill=tk.X, pady=(10, 0))
        
        tk.Button(f_config_ctrl, text="💾 保存当前配置", command=self._save_all, width=15).pack(side=tk.LEFT)
        tk.Button(f_config_ctrl, text="🗑️ 重置所有配置", command=self._clear_cfg, fg="red", width=15).pack(side=tk.LEFT, padx=15)
        tk.Button(f_config_ctrl, text="清理日志框", command=self._clear_log, width=12).pack(side=tk.RIGHT)
        tk.Label(f_config_ctrl, text="配置自动保存在 ~/.ota_deploy_config.json", bg="#eeeeee", fg="gray").pack(side=tk.RIGHT, padx=10)

        self.log_area = scrolledtext.ScrolledText(
            log_shell, height=10, bg="#1e1e1e", fg="#00ff00", font=("Consolas", 10)
        )
        self.log_area.pack(fill=tk.BOTH, expand=True)
        self.log_area.insert(
            tk.END, "日志输出区。点击「执行 OTA 升级」或「执行文件同步」后在此显示进度。\n"
        )

        paned.add(container, stretch="always")
        paned.add(log_shell, minsize=220, stretch="always")
        paned.paneconfig(log_shell, minsize=220)

    def add_sync_row(self, src="", dst="", s100=True, x5=False, executable=False):
        f = tk.Frame(self.scroll_f, bg="white", pady=1)
        f.pack(fill=tk.X)
        sv, dv = tk.StringVar(value=src), tk.StringVar(value=dst)
        s100v, x5v = tk.BooleanVar(value=s100), tk.BooleanVar(value=x5)
        execv = tk.BooleanVar(value=executable)
        tk.Entry(f, textvariable=sv, width=40).pack(side=tk.LEFT, padx=1)
        tk.Button(f, text="..", width=2, command=lambda: self._browse_sync_file(sv)).pack(side=tk.LEFT, padx=1)
        tk.Label(f, text="➔", bg="white").pack(side=tk.LEFT, padx=2)
        tk.Entry(f, textvariable=dv, width=40).pack(side=tk.LEFT, padx=1)
        tk.Checkbutton(f, text="S100", variable=s100v, bg="white").pack(side=tk.LEFT, padx=1)
        tk.Checkbutton(f, text="X5", variable=x5v, bg="white").pack(side=tk.LEFT, padx=1)
        # 直接放置可执行Checkbutton，设置合适宽度，减少padding，避免被裁剪
        tk.Checkbutton(f, text="可执行", variable=execv, bg="white", anchor="w", width=7).pack(side=tk.LEFT, padx=1)
        obj = {"frame": f, "src": sv, "dst": dv, "s100": s100v, "x5": x5v, "executable": execv}
        tk.Button(f, text="✖", fg="red", command=lambda: [f.destroy(), self.sync_rows.remove(obj)]).pack(side=tk.RIGHT, padx=3)
        self.sync_rows.append(obj)

    def _ping_tick_callback(self, s100_ip: str):
        def _on_tick(elapsed: float, total: float) -> None:
            self.status_var.set(
                f"等待 S100 ping {s100_ip}… {elapsed:.0f}/{total:.0f}s"
            )
            try:
                self.root.update_idletasks()
            except tk.TclError:
                pass
        return _on_tick

    def _run_hang_recovery_worker(
        self,
        cfg: dict,
        *,
        on_done: Optional[Callable[[bool, str], None]] = None,
    ) -> None:
        """后台线程执行 Hang 恢复。"""
        s100_ip = str(cfg.get("s100_ip") or "").strip()
        x5_ip = str(cfg.get("x5_ip") or "").strip()
        post_wait = float(cfg.get("ota_hang_post_reboot_wait_sec", 180))
        ssh_probe = float(cfg.get("ota_hang_ssh_probe_sec", 15))
        ping_interval = float(cfg.get("ota_swap_ping_interval_sec", 3))

        def _worker():
            try:
                ok, msg = recover_hung_s100_device(
                    cfg,
                    x5_ip,
                    post_reboot_wait_sec=post_wait,
                    ping_interval_sec=ping_interval,
                    ssh_connect_timeout=ssh_probe,
                    log=self._log_immediate,
                    on_ping_tick=self._ping_tick_callback(s100_ip),
                )
            except Exception as exc:
                ok, msg = False, str(exc)
            self.root.after(0, lambda o=ok, m=msg, cb=on_done: self._on_hang_recovery_done(o, m, cb))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_hang_recovery_done(
        self,
        ok: bool,
        msg: str,
        on_done: Optional[Callable[[bool, str], None]] = None,
    ) -> None:
        if on_done:
            on_done(ok, msg)
            return
        if ok:
            self._log(msg)
            self.status_var.set(msg.splitlines()[0])
            messagebox.showinfo("Hang 恢复", msg)
        else:
            self._log(f"❌ {msg}")
            self.status_var.set("Hang 恢复未成功")
            messagebox.showerror("Hang 恢复", msg)

    def _manual_hang_recovery(self) -> None:
        """手动：清 ARP + SSH reboot + 等 ping 恢复。"""
        cfg = self._get_ui_cfg()
        if not str(cfg.get("s100_ip") or "").strip():
            messagebox.showwarning("提示", "请先填写 S100 IP")
            return
        if not messagebox.askyesno(
            "恢复 Hang",
            f"将对 S100 ({cfg.get('s100_ip')}) 尝试：\n"
            "1. 清除本机 ARP\n"
            "2. SSH 下发 reboot\n"
            "3. 等待设备重启后 ping 通\n\n"
            "若 SSH 不可达，请改用手动关电 10 秒后上电。\n\n是否继续？",
        ):
            return
        self.status_var.set("Hang 恢复进行中…")
        self._log_immediate("开始 Hang 恢复（远程 reboot）…")
        self._run_hang_recovery_worker(cfg)

    def _offer_hang_recovery_after_ping_fail(
        self, cfg: dict, summary: str
    ) -> Optional[bool]:
        """ping 失败后询问 Hang 恢复。返回 True=恢复后可用，False=未恢复，None=用户取消。"""
        if not cfg.get("ota_hang_recovery_on_ping_fail", True):
            return False
        choice = messagebox.askyesnocancel(
            "设备未响应 ping",
            f"{summary}\n\n"
            "可能原因：换台 ARP、设备 hang、未上电或仍在 reboot。\n\n"
            "•【是】尝试 Hang 恢复（SSH 远程 reboot 并等待 ping）\n"
            "•【否】跳过，按原流程继续\n"
            "•【取消】中止本次操作",
        )
        if choice is None:
            return None
        if not choice:
            return False
        result: dict = {"ok": False, "done": False}

        def _done(ok: bool, _msg: str) -> None:
            result["ok"] = ok
            result["done"] = True

        self.status_var.set("Hang 恢复进行中…")
        self._log_immediate("开始 Hang 恢复（远程 reboot）…")
        self._run_hang_recovery_worker(cfg, on_done=_done)
        while not result["done"]:
            try:
                self.root.update()
            except tk.TclError:
                break
            time.sleep(0.05)
        if result["ok"]:
            self._log("Hang 恢复完成，继续检查网络 …")
        else:
            self._log("Hang 恢复未成功")
        return bool(result["ok"])

    def _swap_network_prep_common(
        self,
        *,
        wait_ping: bool,
        allow_continue_on_fail: bool,
    ) -> bool:
        """清 ARP 并可选等待 S100 ping。返回是否继续后续流程。"""
        s100_ip = self.s100_ip.get().strip()
        x5_ip = self.x5_ip.get().strip()
        if not s100_ip:
            messagebox.showwarning("提示", "请先填写 S100 IP")
            return False

        ping_wait = float(self.cfg.get("ota_swap_ping_wait_sec", 90))
        ping_interval = float(self.cfg.get("ota_swap_ping_interval_sec", 3))

        ok, summary = prepare_pc_network_for_device_swap(
            s100_ip,
            x5_ip,
            wait_ping_s100=wait_ping,
            ping_wait_sec=ping_wait,
            ping_interval_sec=ping_interval,
            log=self._log_immediate,
            on_ping_tick=self._ping_tick_callback(s100_ip) if wait_ping else None,
        )
        if ok:
            self.status_var.set(summary)
            return True

        self._log(f"❌ {summary}")
        self.status_var.set(summary)

        cfg = self._get_ui_cfg()
        hang_result = self._offer_hang_recovery_after_ping_fail(cfg, summary)
        if hang_result is None:
            return False
        if hang_result:
            self._log("Hang 恢复后重新等待 S100 ping …")
            ok2, summary2 = prepare_pc_network_for_device_swap(
                s100_ip,
                x5_ip,
                wait_ping_s100=True,
                ping_wait_sec=ping_wait,
                ping_interval_sec=ping_interval,
                log=self._log_immediate,
                on_ping_tick=self._ping_tick_callback(s100_ip),
            )
            if ok2:
                self.status_var.set(summary2)
                return True
            summary = summary2
            self._log(f"❌ {summary}")

        if allow_continue_on_fail:
            return messagebox.askyesno(
                "设备未响应 ping",
                f"{summary}\n\n"
                "请确认：\n"
                "• 上一台已断电/拔线，Hub 上只有当前设备\n"
                "• 新设备已上电并等待 1～2 分钟\n"
                "• PC 产线网口连接正确\n\n"
                "仍要继续 OTA 吗？",
            )
        messagebox.showerror(
            "设备未响应 ping",
            f"{summary}\n\n请检查接线、上电与 IP 后再试。",
        )
        return False

    def _manual_swap_network_prep(self) -> None:
        """员工手动换台后点按钮：清 ARP + 等待 ping。"""
        self._swap_network_prep_common(wait_ping=True, allow_continue_on_fail=False)

    def _auto_swap_network_prep(self, cfg: dict) -> bool:
        """执行 OTA 前自动换台准备（可配置关闭）。"""
        if not cfg.get("ota_swap_clear_arp_on_start", True):
            return True
        return self._swap_network_prep_common(
            wait_ping=True,
            allow_continue_on_fail=True,
        )

    def _pre_start_ota(self):
        """OTA执行前的校验逻辑"""
        cfg = self._get_ui_cfg()
        if not (cfg["ota_target_s100"] or cfg["ota_target_x5"]):
            return messagebox.showwarning("提示", "未选择任何 OTA 升级目标。")

        both = cfg["ota_target_s100"] and cfg["ota_target_x5"]
        ota_encrypted: Optional[bool] = None

        if both:
            enc_ok = ota_package_set_configured(cfg, True)
            plain_ok = ota_package_set_configured(cfg, False)
            if not enc_ok and not plain_ok:
                return messagebox.showwarning(
                    "提示",
                    "双板 OTA 请至少配置【加密】或【未加密】其中一套升级包\n"
                    "（manifest 或四个 zip）。",
                )
            kind_dlg = OtaPkgKindDialog(
                self.root,
                encrypted_available=enc_ok,
                plain_available=plain_ok,
            )
            if kind_dlg.result is None:
                return
            ota_encrypted = kind_dlg.result
            kind_name = "加密" if ota_encrypted else "未加密"
            paths_map = (
                self.ota_paths_encrypted if ota_encrypted else self.ota_paths_plain
            )
            _label_to_cfg_key = {
                "S100 APP": "s100_app_path",
                "S100 SYS": "s100_sys_path",
                "X5 APP": "x5_app_path",
                "X5 SYS": "x5_sys_path",
            }
            bad = [
                label
                for label, ent in paths_map.items()
                if ent.get().strip()
                and not package_path_matches_encryption(
                    ent.get().strip(),
                    ota_encrypted,
                    cfg_key=_label_to_cfg_key[label],
                )
            ]
            if bad:
                return messagebox.showwarning(
                    "包类型不符",
                    f"【{kind_name}】配置区中以下路径看起来像另一套包：\n"
                    + "\n".join(bad)
                    + "\n\n请检查未加密/加密两套是否填反，或重新「扫描填充包」。",
                )
            ok_manifest, err_manifest = validate_ota_packages_match_manifest(
                cfg, encrypted=ota_encrypted
            )
            if not ok_manifest:
                return messagebox.showerror("manifest 与升级包不一致", err_manifest)
            self.status_var.set(f"正在核对【{kind_name}】烧录包 MD5...")
            self.root.update_idletasks()
            ok_md5, err_md5 = validate_ota_packages_md5_match_manifest(
                cfg, encrypted=ota_encrypted
            )
            if not ok_md5:
                return messagebox.showerror("MD5 校验失败", err_md5)
            if not messagebox.askyesno(
                "确认升级",
                f"本次双板 OTA 将使用【{kind_name}】升级包。\n"
                f"已核对：四个 zip 与 manifest 中 filename、MD5 一致。\n\n是否继续？",
            ):
                return
        else:
            if cfg["ota_target_s100"] and not cfg.get("s100_app_path"):
                return messagebox.showwarning("提示", "已勾选 S100，但未选择 S100 APP 升级包。")
            if cfg["ota_target_x5"] and not cfg.get("x5_app_path"):
                return messagebox.showwarning("提示", "已勾选 X5，但未选择 X5 APP 升级包。")
            enc_flag = resolve_manifest_check_encryption(cfg)
            if enc_flag is not None:
                ok_manifest, err_manifest = validate_ota_packages_match_manifest(
                    cfg, encrypted=enc_flag
                )
                if not ok_manifest:
                    return messagebox.showerror("manifest 与升级包不一致", err_manifest)
                self.status_var.set("正在核对烧录包 MD5...")
                self.root.update_idletasks()
                ok_md5, err_md5 = validate_ota_packages_md5_match_manifest(
                    cfg, encrypted=enc_flag
                )
                if not ok_md5:
                    return messagebox.showerror("MD5 校验失败", err_md5)

        if not self._auto_swap_network_prep(cfg):
            return

        # 弹出 SN 输入窗口
        dialog = SNDialog(self.root, initial_sn=self.last_sn)
        
        if dialog.result == "cancel" or dialog.result is None:
            return  # 用户取消操作
            
        if dialog.result == "skip":
            self._start("ota", ota_encrypted=ota_encrypted)
            return
            
        if dialog.result == "confirm":
            sn = dialog.sn_value
            self.last_sn = sn
            ok, err = validate_sn_packages(sn, cfg)
            if not ok:
                messagebox.showerror("校验失败", err)
                return
            self._start("ota", ota_encrypted=ota_encrypted)

    def _start(self, mode, ota_encrypted: Optional[bool] = None):
        cfg = self._get_ui_cfg()
        if ota_encrypted is not None:
            cfg["ota_pkg_encrypted"] = ota_encrypted
            cfg["auto_pkg_by_lifecycle"] = False
        if mode == "sync":
            valid = [i for i in cfg["sync_items"] if i["src"].strip() and (i["s100"] or i["x5"])]
            if not valid: return messagebox.showwarning("提示", "同步列表为空或未选目标。")
        
        save_config(cfg)
        self.log_area.delete(1.0, tk.END)
        self.ota_btn.config(state=tk.DISABLED); self.sync_btn.config(state=tk.DISABLED)
        task_name = "OTA 升级" if mode == "ota" else "文件同步"
        self.status_var.set(f"⏳ {task_name}进行中…")
        self._log_immediate(f"⏳ {task_name}已开始，正在连接设备…（日志见本框）")
        last_log: list[str] = [f"⏳ {task_name}已开始，正在连接设备…"]

        def _status_cb(text: str) -> None:
            self.root.after(0, lambda t=text: self.status_var.set(t))

        def _capture_log(msg: str) -> None:
            last_log.append(msg)
            self._log(msg)
            if "OTA 判定通过" in msg or "版本校验通过" in msg:
                self.root.after(0, lambda: self.status_var.set("✅ OTA 升级完成"))
            elif "版本校验中" in msg or "轮询设备版本" in msg or "开始版本校验" in msg:
                self.root.after(0, lambda: self.status_var.set("🔍 版本校验中…"))
            elif "请人工上下电" in msg or "人工上下电" in msg:
                self.root.after(0, lambda: self.status_var.set("⏸ 请人工上下电…"))
            elif "tmux OTA 进行中" in msg or "轮询 tmux" in msg:
                self.root.after(
                    0,
                    lambda m=msg: self.status_var.set(
                        m.split("…")[0].replace("…", "")[:80]
                        if "…" in m
                        else "⏳ tmux OTA 进行中…"
                    ),
                )

        def _finish(ok: bool, logs: list[str], exc_msg: str = "", task_mode: str = mode) -> None:
            self.ota_btn.config(state=tk.NORMAL)
            self.sync_btn.config(state=tk.NORMAL)
            if ok:
                if task_mode == "ota":
                    self.status_var.set("✅ OTA 完成，设备版本与本次升级包一致。")
                    messagebox.showinfo(
                        "任务成功",
                        "OTA 升级完成。\n\n设备版本已与本次选中的升级包一致。\n"
                        "详细日志见下方黑框。",
                    )
                else:
                    self.status_var.set("✅ 文件同步完成。")
                    messagebox.showinfo("任务成功", "文件同步已完成。详细日志见下方黑框。")
                return
            try:
                self.root.update_idletasks()
                self.root.update()
            except tk.TclError:
                pass
            area_text = self.log_area.get("1.0", tk.END)
            hint = _format_failure_summary(logs, area_text, exc_msg)
            self.status_var.set("❌ OTA 升级失败" if task_mode == "ota" else "❌ 文件同步失败")
            messagebox.showerror(
                "任务失败",
                f"任务执行失败。\n\n{hint}\n\n完整日志请见下方日志框。",
            )

        def _manual_power_cycle_cb() -> bool:
            done = threading.Event()
            result = {"ok": False}

            def _show() -> None:
                result["ok"] = messagebox.askokcancel(
                    "请人工上下电",
                    "设备刷写完成后会提示本窗口。\n\n"
                    "操作顺序：\n"
                    "  1. 先点击「确定」\n"
                    "  2. 立即对机器关电\n"
                    "  3. 等待约 10 秒\n"
                    "  4. 重新上电\n\n"
                    "工具将自动检测 ping 断开→恢复，然后才读版本。\n"
                    "未关电不会进入读版本（避免空等）。\n\n"
                    "点击「取消」中止本次 OTA。",
                )
                done.set()

            self.root.after(0, _show)
            done.wait()
            return bool(result["ok"])

        def _worker() -> None:
            ok = False
            exc_msg = ""
            try:
                cfg["_status_callback"] = _status_cb
                if (
                    cfg.get("ota_target_s100")
                    and not cfg.get("ota_s100_auto_reboot", False)
                ):
                    cfg["_manual_power_cycle_callback"] = _manual_power_cycle_cb
                if mode == "sync":
                    ok = DeployExecutor(cfg, _capture_log).run_sync()
                else:
                    ok = run_ota_deploy(
                        cfg,
                        _capture_log,
                        wait_tmux=cfg.get("use_tmux", True),
                        wait_timeout_sec=int(
                            cfg.get(
                                "ota_wait_timeout_sec",
                                OTA_DEFAULT_VERIFY_TIMEOUT_SEC,
                            )
                        ),
                    )
            except Exception as exc:
                exc_msg = traceback.format_exc()
                _capture_log(f"❌ 程序异常: {exc}")
            finally:
                snapshot = list(last_log)
                self.root.after(0, lambda o=ok, lg=snapshot, ex=exc_msg, m=mode: _finish(o, lg, ex, m))

        threading.Thread(target=_worker, daemon=True).start()

    def _get_ui_cfg(self):
        sync_items = [{
            "src": r["src"].get(),
            "dst": r["dst"].get(),
            "s100": r["s100"].get(),
            "x5": r["x5"].get(),
            "executable": r["executable"].get()
        } for r in self.sync_rows]
        cfg = {
            "s100_ip": self.s100_ip.get(),
            "x5_ip": self.x5_ip.get(),
            "username": "root",
            "password": "root",
            "ota_dir": self.cfg["ota_dir"],
            "connect_timeout": 5,
            "use_identity_file": self.use_key.get(),
            "identity_file": self.key_path.get(),
            "ota_target_s100": self.ota_s100_v.get(),
            "ota_target_x5": self.ota_x5_v.get(),
            "use_tmux": self.use_tmux.get(),
            "sync_items": sync_items,
            "package_dir": getattr(self, "_package_dir", ""),
            "auto_pkg_by_lifecycle": True,
            "ota_manifest_encrypted": self.manifest_encrypted.get().strip(),
            "ota_manifest_plain": self.manifest_plain.get().strip(),
        }
        cfg = merge_cfg_with_defaults(cfg)
        for label, base_key in (
            ("S100 APP", "s100_app_path"),
            ("S100 SYS", "s100_sys_path"),
            ("X5 APP", "x5_app_path"),
            ("X5 SYS", "x5_sys_path"),
        ):
            enc_p = self.ota_paths_encrypted[label].get().strip()
            plain_p = self.ota_paths_plain[label].get().strip()
            cfg[ota_pkg_storage_key(base_key, True)] = enc_p
            cfg[ota_pkg_storage_key(base_key, False)] = plain_p
        if not (cfg["ota_target_s100"] and cfg["ota_target_x5"]):
            for label, base_key in (
                ("S100 APP", "s100_app_path"),
                ("S100 SYS", "s100_sys_path"),
                ("X5 APP", "x5_app_path"),
                ("X5 SYS", "x5_sys_path"),
            ):
                cfg[base_key] = (
                    self.ota_paths_plain[label].get().strip()
                    or self.ota_paths_encrypted[label].get().strip()
                )
        return cfg

    def _labeled_entry(self, p, t, w, padx=0):
        tk.Label(p, text=t, bg=self.bg).pack(side=tk.LEFT, padx=(padx,0))
        e = tk.Entry(p, width=w, bg="white"); e.pack(side=tk.LEFT, padx=5); return e
    def _clear_log(self) -> None:
        self.log_area.delete(1.0, tk.END)
        self.status_var.set("日志已清空。")

    def _log_immediate(self, msg: str) -> None:
        """主线程立即写入日志（任务开始时给用户即时反馈）。"""
        self.log_area.insert(tk.END, f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")
        self.log_area.see(tk.END)
        self.status_var.set(msg)
        try:
            self.log_area.update_idletasks()
        except tk.TclError:
            pass

    def _log(self, msg):
        def _append():
            self.log_area.insert(tk.END, f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")
            self.log_area.see(tk.END)
            self.status_var.set(msg)
        self.root.after(0, _append)
    def _save_all(self): save_config(self._get_ui_cfg()); messagebox.showinfo("OK", "配置已成功保存")
    def _clear_cfg(self):
        if messagebox.askyesno("?", "确定要重置所有配置吗？"):
            if os.path.exists(CONFIG_FILE): os.remove(CONFIG_FILE)
            self.cfg = dict(DEFAULT_CONFIG); self._load_fields()
    def _browse_ota(self, e, p, *, encrypted: bool, cfg_key: str):
        f = filedialog.askopenfilename()
        # 兼容 askopenfilename 返回 tuple 的情况
        if isinstance(f, (list, tuple)):
            f = f[0] if f else ""
        if not f:
            return
        if not fnmatch.fnmatch(os.path.basename(f).lower(), p.lower()):
            messagebox.showerror("错误", "文件名不匹配当前规则")
            return
        if not package_path_matches_encryption(f, encrypted, cfg_key=cfg_key):
            kind = "加密" if encrypted else "未加密"
            if cfg_key == "s100_sys_path":
                hint = "S100 SYS 加密包文件名须含 signed（如 all_in_one_signed-v5...）"
            else:
                hint = "请检查是否选错配置区"
            messagebox.showerror(
                "包类型错误",
                f"不能填入【{kind}】配置区。\n{hint}\n文件: {os.path.basename(f)}",
            )
            return
        e.delete(0, tk.END)
        e.insert(0, f)

    def _browse_manifest(self, entry: tk.Entry, path_entries: dict, *, expect_encrypted: bool) -> None:
        f = filedialog.askopenfilename(
            title="选择 manifest.yaml",
            filetypes=[("YAML", "*.yaml *.yml"), ("All", "*.*")],
        )
        if not f:
            return
        entry.delete(0, tk.END)
        entry.insert(0, f)
        manifest_dir = os.path.dirname(f)
        if manifest_dir:
            self._package_dir = manifest_dir
        try:
            doc = load_ota_manifest(f)
            enc = manifest_is_encrypted(doc)
            if enc != expect_encrypted:
                expect = "加密" if expect_encrypted else "未加密"
                actual = "加密" if enc else "未加密"
                messagebox.showerror(
                    "manifest 类型不符",
                    f"该 manifest 属于【{actual}】包，不能填入【{expect}】配置区。\n"
                    f"请换 manifest.yaml，或使用上方【{actual}】区域。",
                )
                return
            scanned = resolve_packages_from_manifest(f, self._package_dir)
            label_to_key = {
                "S100 APP": "s100_app_path",
                "S100 SYS": "s100_sys_path",
                "X5 APP": "x5_app_path",
                "X5 SYS": "x5_sys_path",
            }
            for label, ent in path_entries.items():
                path = scanned.get(label_to_key.get(label, ""), "")
                if path:
                    ent.delete(0, tk.END)
                    ent.insert(0, path)
            self._log(
                f"已从 manifest 填充本组四个 zip（{'加密' if enc else '未加密'}）: "
                f"{os.path.basename(f)}"
            )
        except Exception as exc:
            self._log(f"manifest 解析: {exc}")
    def _fill_paths_from_scanned(
        self, scanned: dict, path_entries: dict, *, encrypted: bool
    ) -> None:
        label_to_key = {
            "S100 APP": "s100_app_path",
            "S100 SYS": "s100_sys_path",
            "X5 APP": "x5_app_path",
            "X5 SYS": "x5_sys_path",
        }
        for label, ent in path_entries.items():
            path = scanned.get(label_to_key.get(label, ""), "")
            if not path:
                continue
            cfg_key = label_to_key.get(label, "")
            if not package_path_matches_encryption(path, encrypted, cfg_key=cfg_key):
                self._log(
                    f"[选包] 跳过 {label}（S100 SYS 须{'含' if encrypted else '不含'} signed）: "
                    f"{os.path.basename(path)}"
                )
                continue
            ent.delete(0, tk.END)
            ent.insert(0, path)

    def _verify_packages_md5(self, *, encrypted: bool) -> None:
        """后台核对本组烧录包与 manifest 的 MD5。"""
        kind = "加密" if encrypted else "未加密"
        cfg = self._get_ui_cfg()
        manifest = get_configured_ota_manifest(cfg, encrypted)
        if not manifest:
            return messagebox.showwarning("提示", f"【{kind}】请先选择 manifest.yaml")
        self.status_var.set(f"正在核对【{kind}】烧录包 MD5，请稍候...")
        self._log_immediate(
            f"开始核对【{kind}】烧录包 MD5（manifest: {os.path.basename(manifest)}）"
        )

        def _worker():
            try:
                ok, msg = validate_ota_packages_md5_match_manifest(
                    cfg,
                    encrypted=encrypted,
                    check_all_packages=True,
                )
            except Exception as exc:
                ok, msg = False, str(exc)
            self.root.after(0, lambda o=ok, m=msg, k=kind: self._on_md5_verify_done(o, m, k))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_md5_verify_done(self, ok: bool, msg: str, kind: str) -> None:
        if ok:
            self._log(msg)
            self.status_var.set(msg.splitlines()[0])
            messagebox.showinfo("MD5 核对通过", msg)
        else:
            self._log(f"❌ {msg}")
            self.status_var.set(f"【{kind}】MD5 核对失败")
            messagebox.showerror("MD5 核对失败", msg)

    def _scan_fill_packages(self, *, encrypted: bool) -> None:
        """仅扫描并填充加密或未加密其中一套（manifest 优先，否则按文件名规则）。"""
        kind = "加密" if encrypted else "未加密"
        d = filedialog.askdirectory(title=f"选择【{kind}】OTA 包目录")
        if not d:
            return
        self._package_dir = d
        path_entries = self.ota_paths_encrypted if encrypted else self.ota_paths_plain
        manifest_ent = self.manifest_encrypted if encrypted else self.manifest_plain

        manifests = discover_ota_manifests(d)
        matching: list[str] = []
        skipped_kind: list[str] = []
        for mp in manifests:
            try:
                if manifest_is_encrypted(load_ota_manifest(mp)) == encrypted:
                    matching.append(mp)
                else:
                    skipped_kind.append(os.path.basename(mp))
            except Exception as exc:
                self._log(f"[{kind}] 跳过 manifest {os.path.basename(mp)}: {exc}")

        if matching:
            mp = max(matching, key=os.path.getmtime)
            if len(matching) > 1:
                self._log(
                    f"[{kind}] 目录内有多份【{kind}】manifest，使用最新: {os.path.basename(mp)}"
                )
            try:
                scanned = resolve_packages_from_manifest(mp, d)
            except Exception as exc:
                messagebox.showerror("扫描失败", f"[{kind}] manifest 解析失败:\n{exc}")
                return
            manifest_ent.delete(0, tk.END)
            manifest_ent.insert(0, mp)
            self._fill_paths_from_scanned(scanned, path_entries, encrypted=encrypted)
            missing = [lb for lb, ent in path_entries.items() if not ent.get().strip()]
            if missing:
                self._log(f"[{kind}] ⚠️ manifest 已加载，仍缺少 zip: {', '.join(missing)}")
            else:
                self._log(f"[{kind}] ✅ 已从 manifest 填充 4 个包: {os.path.basename(mp)}")
            if skipped_kind:
                self._log(f"[{kind}] 已忽略另一套 manifest: {', '.join(skipped_kind)}")
            return

        if manifests and skipped_kind:
            messagebox.showwarning(
                "未找到匹配的 manifest",
                f"目录里有 manifest，但没有【{kind}】类型。\n"
                f"已忽略: {', '.join(skipped_kind)}\n\n"
                f"请换目录，或把【{kind}】的 manifest.yaml 放进该目录。",
            )
            return

        if encrypted:
            scanned = scan_package_dir(d, rules=PKG_RULES_ENCRYPTED, encrypted=True)
        else:
            scanned = scan_package_dir(d, rules=PKG_RULES_PLAIN, encrypted=False)
        manifest_ent.delete(0, tk.END)
        self._fill_paths_from_scanned(scanned, path_entries, encrypted=encrypted)
        filled = sum(1 for ent in path_entries.values() if ent.get().strip())
        if filled:
            self._log(
                f"[{kind}] 已按文件名规则填充 {filled}/4 个 zip"
                f"（目录内无【{kind}】manifest）"
            )
        else:
            messagebox.showwarning(
                "扫描结果",
                f"未在目录中找到【{kind}】升级包。\n"
                f"请确认 zip：仅 S100 SYS 用 signed 区分（加密须 all_in_one_signed-...）。",
            )
    def _on_key_toggle(self): self.key_path.config(state=tk.NORMAL if self.use_key.get() else tk.DISABLED)
    def _browse_key(self):
        f = filedialog.askopenfilename()
        if f: self.key_path.delete(0, tk.END); self.key_path.insert(0, f)
    def _browse_sync_file(self, v):
        f = filedialog.askopenfilename()
        if f: v.set(f)

    def _load_fields(self):
        for e in [self.s100_ip, self.x5_ip, self.key_path]: e.delete(0, tk.END)
        self.s100_ip.insert(0, self.cfg.get("s100_ip", "")); self.x5_ip.insert(0, self.cfg.get("x5_ip", ""))
        self.use_key.set(self.cfg.get("use_identity_file", False)); self.key_path.insert(0, self.cfg.get("identity_file", ""))
        self.ota_s100_v.set(self.cfg.get("ota_target_s100", True)); self.ota_x5_v.set(self.cfg.get("ota_target_x5", True))
        legacy_map = {
            "S100 APP": "s100_app_path",
            "S100 SYS": "s100_sys_path",
            "X5 APP": "x5_app_path",
            "X5 SYS": "x5_sys_path",
        }
        for label, base in legacy_map.items():
            legacy = str(self.cfg.get(base, "") or "").strip()
            enc_stored = str(self.cfg.get(ota_pkg_storage_key(base, True), "") or "").strip()
            plain_stored = str(
                self.cfg.get(ota_pkg_storage_key(base, False), "") or ""
            ).strip()
            enc_val = enc_stored
            if not enc_val and legacy and package_path_matches_encryption(
                legacy, True, cfg_key=base
            ):
                enc_val = legacy
            plain_val = plain_stored
            if not plain_val and legacy and package_path_matches_encryption(
                legacy, False, cfg_key=base
            ):
                plain_val = legacy
            self.ota_paths_encrypted[label].delete(0, tk.END)
            self.ota_paths_encrypted[label].insert(0, enc_val)
            self.ota_paths_plain[label].delete(0, tk.END)
            self.ota_paths_plain[label].insert(0, plain_val)
        self.use_tmux.set(self.cfg.get("use_tmux", True))
        for ent, key, expect_enc in (
            (self.manifest_encrypted, "ota_manifest_encrypted", True),
            (self.manifest_plain, "ota_manifest_plain", False),
        ):
            ent.delete(0, tk.END)
            mp = str(self.cfg.get(key, "") or "").strip()
            if mp and os.path.isfile(mp):
                try:
                    if manifest_is_encrypted(load_ota_manifest(mp)) != expect_enc:
                        mp = ""
                except Exception:
                    pass
            ent.insert(0, mp)
        for r in self.sync_rows: r["frame"].destroy()
        self.sync_rows = []
        for item in self.cfg.get("sync_items", []):
            self.add_sync_row(
                item.get("src", ""),
                item.get("dst", ""),
                item.get("s100", True),
                item.get("x5", False),
                item.get("executable", False)
            )
        if not self.sync_rows:
            self.add_sync_row()
        self._on_key_toggle()

def launch_gui() -> None:
    root = tk.Tk()
    if sys.platform == "darwin":
        root.tk.call("tk", "scaling", 2.0)
    OTADeployGUI(root)
    root.mainloop()


if __name__ == "__main__":
    launch_gui()