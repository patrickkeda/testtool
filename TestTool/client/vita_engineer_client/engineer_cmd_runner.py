#!/usr/bin/env python3
"""
VITA Engineer Cmd Runner — 带UI的工程测试上位机

Usage (GUI):
    python3 engineer_cmd_runner.py [robot_ip]

Usage (CLI, 与 test_engineer_client.py 兼容):
    python3 engineer_cmd_runner.py vel_cmd=2% 192.168.126.2

Commands config is saved to engineer_commands.json in the same directory.
"""

import asyncio
import json
import os
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog
from datetime import datetime
from typing import Optional

# ── import client ──────────────────────────────────────────────────────────────
try:
    from .engineer_client import EngineerServiceClient
    from .test_engineer_client import (
        command_registry, command_handler, parser, test_single_case,
        register_all_handlers,
    )
except ImportError:
    from engineer_client import EngineerServiceClient
    from test_engineer_client import (
        command_registry, command_handler, parser, test_single_case,
        register_all_handlers,
    )

# ── constants ──────────────────────────────────────────────────────────────────
HERE = os.path.dirname(os.path.abspath(__file__))
COMMANDS_FILE = os.path.join(HERE, "engineer_commands.json")
CONFIG_FILE = os.path.join(HERE, "engineer_config.json")

DEFAULT_COMMANDS = [
    {"cmd": "enfac=1,1%",        "desc": "进入工程模式"},
    {"cmd": "motor_id=1%",       "desc": "查询电机ID连通情况"},
    {"cmd": "servo=0%",          "desc": "查询舵机连通情况"},
    {"cmd": "vel_cmd=2%",        "desc": "校验vel_cmd结果文件（位移/heading）"},
    {"cmd": "version=0%",        "desc": "查询版本信息"},
    {"cmd": "mic=1%",            "desc": "音频回环测试"},
    {"cmd": "sig4g=1%",          "desc": "4G网卡ping测试"},
    {"cmd": "lcd=3%",            "desc": "开启屏幕信息显示IP"},
    {"cmd": "action_mode=1,mpc%","desc": "切换MPC运动模式"},
    {"cmd": "action_mode=2%",    "desc": "停止运动模式"},
    {"cmd": "motor_ota=1,<firmware_path>%", "desc": "电机固件升级-全部（执行时会提示选择.bin）"},
    {"cmd": "motor_ota=2,<firmware_path>,1-2-3%", "desc": "电机固件升级-指定ID（如1-2-3）"},
]

# ── helpers ────────────────────────────────────────────────────────────────────
def load_commands():
    if os.path.exists(COMMANDS_FILE):
        try:
            with open(COMMANDS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
        except Exception:
            pass
    return list(DEFAULT_COMMANDS)


def save_commands(cmds):
    with open(COMMANDS_FILE, "w", encoding="utf-8") as f:
        json.dump(cmds, f, ensure_ascii=False, indent=2)


def get_default_ssh_key_path():
    """Get default SSH key path based on platform"""
    import platform
    home = os.path.expanduser("~")
    if platform.system().lower() == "windows":
        # Windows: C:\Users\username\.ssh\id_ed25519
        return os.path.join(home, ".ssh", "id_ed25519")
    else:
        # Unix-like: ~/.ssh/id_ed25519
        return "~/.ssh/id_ed25519"


def load_config():
    """Load application configuration"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "s100_ip": "192.168.126.2",
        "port": "3579",
        "x5_ip": "192.168.127.10",
        "use_ssh_key": False,
        "ssh_key_path": get_default_ssh_key_path()
    }


def save_config(config):
    """Save application configuration"""
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def check_ssh_available():
    """Check if SSH command is available on the system"""
    import subprocess
    import platform
    try:
        if platform.system().lower() == "windows":
            # On Windows, check for OpenSSH
            result = subprocess.run(["where", "ssh"], capture_output=True, timeout=5)
        else:
            # On Unix-like systems
            result = subprocess.run(["which", "ssh"], capture_output=True, timeout=5)
        return result.returncode == 0
    except Exception:
        return False


# ── async helper ───────────────────────────────────────────────────────────────
def run_async(coro, callback=None):
    """Run an async coroutine in a background thread and call callback(ok, output)."""
    def _thread():
        captured = []

        class _Capture:
            """Redirect print() inside the coroutine to our buffer."""
            def write(self, s):
                captured.append(s)
            def flush(self):
                pass

        import builtins
        _orig_print = builtins.print

        def _print(*args, **kwargs):
            _orig_print(*args, **kwargs)
            text = " ".join(str(a) for a in args)
            captured.append(text)

        builtins.print = _print
        ok = False
        try:
            ok = asyncio.run(coro)
        except Exception as e:
            captured.append(f"[异常] {e}")
        finally:
            builtins.print = _orig_print

        if callback:
            callback(ok, "\n".join(captured))

    t = threading.Thread(target=_thread, daemon=True)
    t.start()
    return t


# ══════════════════════════════════════════════════════════════════════════════
class EngineerCmdRunnerApp:
    """Main GUI application."""

    # ── build UI ───────────────────────────────────────────────────────────────
    def __init__(self, root: tk.Tk, default_ip: str = "192.168.126.2"):
        self.root = root
        self.root.title("VITA Engineer Cmd Runner")
        self.root.geometry("960x660")
        self.root.minsize(800, 560)

        self.commands = load_commands()
        self._running = False

        # Load configuration
        self.config = load_config()

        self._build_ui(default_ip)
        self._refresh_list()

        # Register save config on window close
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Show config load info
        if os.path.exists(CONFIG_FILE):
            self._log(f"✓ 已加载配置: {os.path.basename(CONFIG_FILE)}", "info")
        else:
            self._log(f"ℹ 使用默认配置 (将保存到: {os.path.basename(CONFIG_FILE)})", "dim")

    def _build_ui(self, default_ip: str):
        # ── top bar ────────────────────────────────────────────────────────────
        top = ttk.Frame(self.root, padding=6)
        top.pack(fill=tk.X)

        ttk.Label(top, text="S100 IP:").pack(side=tk.LEFT)
        # Use config value if available, otherwise use provided default_ip
        s100_ip = self.config.get("s100_ip", default_ip)
        self.ip_var = tk.StringVar(value=s100_ip)
        ttk.Entry(top, textvariable=self.ip_var, width=18).pack(side=tk.LEFT, padx=4)

        ttk.Label(top, text="端口:").pack(side=tk.LEFT)
        port = self.config.get("port", "3579")
        self.port_var = tk.StringVar(value=port)
        ttk.Entry(top, textvariable=self.port_var, width=7).pack(side=tk.LEFT, padx=4)

        ttk.Label(top, text="X5 IP:").pack(side=tk.LEFT, padx=(8, 0))
        x5_ip = self.config.get("x5_ip", "192.168.127.10")
        self.x5_ip_var = tk.StringVar(value=x5_ip)
        ttk.Entry(top, textvariable=self.x5_ip_var, width=18).pack(side=tk.LEFT, padx=4)

        # ── ping controls ──────────────────────────────────────────────────────
        ttk.Separator(top, orient=tk.VERTICAL).pack(side=tk.LEFT, padx=8, fill=tk.Y)
        ttk.Label(top, text="网络测试:").pack(side=tk.LEFT, padx=(0, 4))
        self.ping_s100_btn = ttk.Button(top, text="Ping S100", command=self._ping_s100, width=10)
        self.ping_s100_btn.pack(side=tk.LEFT, padx=2)
        self.ping_x5_btn = ttk.Button(top, text="Ping X5", command=self._ping_x5, width=10)
        self.ping_x5_btn.pack(side=tk.LEFT, padx=2)

        # ── SSH key configuration ──────────────────────────────────────────────
        # Create a second row for SSH key settings
        top2 = ttk.Frame(self.root, padding=(6, 0, 6, 6))
        top2.pack(fill=tk.X)

        use_ssh_key = self.config.get("use_ssh_key", False)
        self.use_ssh_key_var = tk.BooleanVar(value=use_ssh_key)
        self.use_ssh_key_check = ttk.Checkbutton(top2, text="使用SSH密钥", variable=self.use_ssh_key_var,
                                                  command=self._update_ssh_key_controls)
        self.use_ssh_key_check.pack(side=tk.LEFT)

        ttk.Label(top2, text="密钥路径:").pack(side=tk.LEFT, padx=(8, 0))
        ssh_key_path = self.config.get("ssh_key_path", "~/.ssh/id_ed25519")
        self.ssh_key_var = tk.StringVar(value=ssh_key_path)
        initial_state = tk.NORMAL if use_ssh_key else tk.DISABLED
        self.ssh_key_entry = ttk.Entry(top2, textvariable=self.ssh_key_var, width=30, state=initial_state)
        self.ssh_key_entry.pack(side=tk.LEFT, padx=4)

        self.ssh_key_browse_btn = ttk.Button(top2, text="浏览...", command=self._browse_ssh_key,
                                             width=8, state=initial_state)
        self.ssh_key_browse_btn.pack(side=tk.LEFT, padx=2)

        # Save config button
        ttk.Separator(top2, orient=tk.VERTICAL).pack(side=tk.LEFT, padx=8, fill=tk.Y)
        self.save_config_btn = ttk.Button(top2, text="💾 保存配置", command=self._save_config_manual)
        self.save_config_btn.pack(side=tk.LEFT, padx=2)

        # ── main paned layout ──────────────────────────────────────────────────
        paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 4))

        # ─── left: command list ────────────────────────────────────────────────
        left = ttk.Frame(paned, padding=4)
        paned.add(left, weight=1)

        # Use grid inside `left` so treeview expands vertically but buttons
        # always stay visible at the bottom without needing to resize the pane.
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)   # row 1 = treeview, expands

        ttk.Label(left, text="命令列表", font=("", 10, "bold")).grid(
            row=0, column=0, columnspan=2, sticky=tk.W, pady=(0, 2))

        # treeview + scrollbar in their own inner frame
        tree_frame = ttk.Frame(left)
        tree_frame.grid(row=1, column=0, columnspan=2, sticky=tk.NSEW)
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)

        cols = ("cmd", "desc")
        self.tree = ttk.Treeview(tree_frame, columns=cols, show="headings",
                                 selectmode="extended")
        self.tree.heading("cmd",  text="命令")
        self.tree.heading("desc", text="描述")
        self.tree.column("cmd",  width=160, stretch=True)
        self.tree.column("desc", width=180, stretch=True)
        sb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.grid(row=0, column=0, sticky=tk.NSEW)
        sb.grid(row=0, column=1, sticky=tk.NS)
        self.tree.bind("<Double-1>", lambda _: self._run_selected())

        # list buttons (edit/move)
        btn_frame = ttk.Frame(left, padding=(0, 4))
        btn_frame.grid(row=2, column=0, columnspan=2, sticky=tk.W)
        ttk.Button(btn_frame, text="+ 新增", command=self._add_command).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="编辑",   command=self._edit_command).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="删除",   command=self._delete_command).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text=" ^ ",   command=lambda: self._move(-1)).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text=" v ",   command=lambda: self._move(+1)).pack(side=tk.LEFT, padx=2)

        # run buttons
        run_frame = ttk.Frame(left, padding=(0, 2))
        run_frame.grid(row=3, column=0, columnspan=2, sticky=tk.W)
        self.run_btn = ttk.Button(run_frame, text="执行选中", command=self._run_selected)
        self.run_btn.pack(side=tk.LEFT, padx=2)
        self.run_all_btn = ttk.Button(run_frame, text="执行全部", command=self._run_all)
        self.run_all_btn.pack(side=tk.LEFT, padx=2)
        self.stop_btn = ttk.Button(run_frame, text="停止", command=self._stop,
                                   state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=2)

        # quick command entry
        quick_frame = ttk.Frame(left, padding=(0, 4))
        quick_frame.grid(row=4, column=0, columnspan=2, sticky=tk.EW)
        quick_frame.columnconfigure(1, weight=1)
        ttk.Label(quick_frame, text="快速执行:").grid(row=0, column=0)
        self.quick_var = tk.StringVar()
        quick_entry = ttk.Entry(quick_frame, textvariable=self.quick_var)
        quick_entry.grid(row=0, column=1, sticky=tk.EW, padx=4)
        quick_entry.bind("<Return>", lambda _: self._run_quick())

        # Add browse button for quick command
        self.quick_browse_btn = ttk.Button(quick_frame, text="浏览...", command=self._quick_browse_file, width=8)
        self.quick_browse_btn.grid(row=0, column=2, padx=2)

        # Update browse button visibility when quick command changes
        self.quick_var.trace_add('write', lambda *args: self._update_quick_browse_visibility())
        self._update_quick_browse_visibility()

        ttk.Button(quick_frame, text="执行", command=self._run_quick).grid(row=0, column=3)

        # ─── right: output log ─────────────────────────────────────────────────
        right = ttk.Frame(paned, padding=4)
        paned.add(right, weight=2)

        log_header = ttk.Frame(right)
        log_header.pack(fill=tk.X)
        ttk.Label(log_header, text="执行日志", font=("", 10, "bold")).pack(side=tk.LEFT)
        ttk.Button(log_header, text="清空", command=self._clear_log).pack(side=tk.RIGHT)

        self.log = tk.Text(right, wrap=tk.WORD, state=tk.DISABLED,
                           font=("Consolas", 10), background="#1e1e1e",
                           foreground="#d4d4d4", insertbackground="white")
        log_sb = ttk.Scrollbar(right, orient=tk.VERTICAL, command=self.log.yview)
        self.log.configure(yscrollcommand=log_sb.set)
        self.log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        log_sb.pack(side=tk.LEFT, fill=tk.Y)

        # colour tags
        self.log.tag_config("ok",    foreground="#6dbf67")
        self.log.tag_config("error", foreground="#f48771")
        self.log.tag_config("info",  foreground="#9cdcfe")
        self.log.tag_config("head",  foreground="#dcdcaa", font=("Consolas", 10, "bold"))
        self.log.tag_config("dim",   foreground="#808080")

        # ── status bar ─────────────────────────────────────────────────────────
        self.status_var = tk.StringVar(value="就绪")
        status_bar = ttk.Label(self.root, textvariable=self.status_var,
                               relief=tk.SUNKEN, anchor=tk.W, padding=3)
        status_bar.pack(fill=tk.X, side=tk.BOTTOM)

        # progress bar (hidden when idle)
        self.progress = ttk.Progressbar(self.root, mode="indeterminate")

    # ── list management ────────────────────────────────────────────────────────
    def _refresh_list(self, select_idx: Optional[int] = None):
        self.tree.delete(*self.tree.get_children())
        for item in self.commands:
            self.tree.insert("", tk.END, values=(item["cmd"], item.get("desc", "")))
        if select_idx is not None:
            children = self.tree.get_children()
            if 0 <= select_idx < len(children):
                self.tree.selection_set(children[select_idx])
                self.tree.see(children[select_idx])

    def _selected_indices(self) -> list:
        sel = self.tree.selection()
        return [self.tree.index(item) for item in sel] if sel else []

    def _selected_index(self) -> Optional[int]:
        """Return the index of the first selected item, or None if nothing is selected."""
        indices = self._selected_indices()
        return indices[0] if indices else None

    def _add_command(self):
        dlg = _CommandDialog(self.root, title="新增命令")
        if dlg.result:
            self.commands.append(dlg.result)
            save_commands(self.commands)
            self._refresh_list(len(self.commands) - 1)

    def _edit_command(self):
        idx = self._selected_index()
        if idx is None:
            messagebox.showinfo("提示", "请先选择一个命令")
            return
        dlg = _CommandDialog(self.root, title="编辑命令", initial=self.commands[idx])
        if dlg.result:
            self.commands[idx] = dlg.result
            save_commands(self.commands)
            self._refresh_list(idx)

    def _delete_command(self):
        idx = self._selected_index()
        if idx is None:
            messagebox.showinfo("提示", "请先选择一个命令")
            return
        cmd = self.commands[idx]["cmd"]
        if messagebox.askyesno("确认删除", f"确认删除命令：\n{cmd}"):
            self.commands.pop(idx)
            save_commands(self.commands)
            self._refresh_list(max(0, idx - 1))

    def _move(self, direction: int):
        idx = self._selected_index()
        if idx is None:
            return
        new_idx = idx + direction
        if 0 <= new_idx < len(self.commands):
            self.commands[idx], self.commands[new_idx] = self.commands[new_idx], self.commands[idx]
            save_commands(self.commands)
            self._refresh_list(new_idx)

    # ── run logic ──────────────────────────────────────────────────────────────
    def _get_connection(self):
        return self.ip_var.get().strip(), int(self.port_var.get().strip())

    def _set_running(self, running: bool):
        self._running = running
        state_run = tk.DISABLED if running else tk.NORMAL
        self.run_btn.config(state=state_run)
        self.run_all_btn.config(state=state_run)
        self.stop_btn.config(state=tk.NORMAL if running else tk.DISABLED)
        # Disable/enable utility buttons during execution
        self.ping_s100_btn.config(state=state_run)
        self.ping_x5_btn.config(state=state_run)
        if running:
            if self.progress.winfo_manager() != "pack":
                self.progress.pack(fill=tk.X, side=tk.BOTTOM)
            self.progress.start(12)
        else:
            self.progress.stop()
            if self.progress.winfo_manager() == "pack":
                self.progress.pack_forget()

    def _run_selected(self):
        indices = self._selected_indices()
        if not indices:
            messagebox.showinfo("提示", "请先选择一个命令")
            return
        for idx in indices:
            cmd = self.commands[idx]["cmd"]
            self._execute_command(cmd)

    def _update_quick_browse_visibility(self):
        """Show browse button only for commands that need file selection"""
        cmd = self.quick_var.get().lower()
        # Show button for motor_ota and transfer commands
        if cmd.startswith("motor_ota=") or cmd.startswith("transfer="):
            self.quick_browse_btn.grid()
        else:
            self.quick_browse_btn.grid_remove()

    def _quick_browse_file(self):
        """Open file dialog to select file path for quick command"""
        cmd = self.quick_var.get()

        # Determine if it's a directory or file selection
        if cmd.startswith("transfer="):
            # For transfer, could be file or directory
            file_path = filedialog.askopenfilename(
                title="选择文件",
                parent=self.root
            )
            if not file_path:
                # Try directory selection
                file_path = filedialog.askdirectory(
                    title="选择文件夹",
                    parent=self.root
                )
        else:
            # For motor_ota, select .bin file
            file_path = filedialog.askopenfilename(
                title="选择固件文件",
                filetypes=[("固件文件", "*.bin"), ("所有文件", "*.*")],
                parent=self.root
            )

        if file_path:
            # Update command with the selected file path
            # Parse current command to inject the file path
            import re
            if cmd.startswith("motor_ota="):
                # motor_ota=1,<file_path>% or motor_ota=2,<file_path>,<motor_ids>%
                match = re.match(r'(motor_ota=\d+),([^,]*)(,.*)?(%?)$', cmd)
                if match:
                    op_part = match.group(1)
                    rest = match.group(3) or ""
                    percent = match.group(4) or "%"
                    new_cmd = f"{op_part},{file_path}{rest}{percent}"
                    self.quick_var.set(new_cmd)
                else:
                    # Fallback: just replace <firmware_path> placeholder
                    new_cmd = cmd.replace("<firmware_path>", file_path)
                    if not new_cmd.endswith("%"):
                        new_cmd += "%"
                    self.quick_var.set(new_cmd)
            elif cmd.startswith("transfer="):
                # transfer=1,<addrA>,<addrB>% or transfer=2,<addrA>,<addrB>%
                match = re.match(r'(transfer=\d+),([^,]*)(,.*)?(%?)$', cmd)
                if match:
                    op_part = match.group(1)
                    rest = match.group(3) or ""
                    percent = match.group(4) or "%"
                    new_cmd = f"{op_part},{file_path}{rest}{percent}"
                    self.quick_var.set(new_cmd)

    def _has_placeholder(self, cmd: str) -> bool:
        """Check if command contains placeholder text"""
        import re
        # Common placeholders: <xxx>, {xxx}, or literal placeholder text
        placeholders = [
            r'<[^>]+>',  # <firmware_path>, <addrA>, etc.
            r'\{[^}]+\}',  # {firmware_path}, etc.
        ]
        for pattern in placeholders:
            if re.search(pattern, cmd):
                return True
        return False

    def _auto_select_file_for_command(self, cmd: str):
        """Automatically open file browser for command and update quick entry"""
        # Set the command in quick entry
        self.quick_var.set(cmd)
        # Trigger the browse file dialog
        self._quick_browse_file()

    def _run_quick(self):
        cmd = self.quick_var.get().strip()
        if not cmd:
            return
        self._execute_command(cmd)

    def _run_all(self):
        if self._running:
            return
        cmds = [c["cmd"] for c in self.commands]
        if not cmds:
            return
        self._set_running(True)
        ip, port = self._get_connection()
        self._log(f"═══ 开始批量执行 {len(cmds)} 条命令 ═══", "head")

        def _all():
            for i, cmd in enumerate(cmds):
                if not self._running:
                    break
                self.root.after(0, lambda c=cmd, n=i+1, t=len(cmds):
                                self._log(f"\n[{n}/{t}] {c}", "head"))
                ok, output = _sync_run(cmd, ip, port)
                self.root.after(0, lambda o=output, s=ok: self._append_output(o, s))

            # Only update UI if not already stopped
            if self._running:
                self.root.after(0, lambda: self._set_running(False))
                self.root.after(0, lambda: self._log("═══ 批量执行完毕 ═══", "head"))
                self.root.after(0, lambda: self.status_var.set("就绪"))

        threading.Thread(target=_all, daemon=True).start()

    def _stop(self):
        if not self._running:
            return
        self._running = False
        self._log("⏹ 已请求停止", "error")
        self.status_var.set("已停止")
        # Reset UI state immediately
        self._set_running(False)

    def _execute_command(self, cmd: str):
        if self._running:
            return

        # Check for placeholders in command
        if self._has_placeholder(cmd):
            result = messagebox.askyesno(
                "需要选择文件",
                f"命令中包含占位符，需要选择文件路径。\n\n是否打开文件选择器？\n\n命令: {cmd}",
                parent=self.root
            )
            if result:
                # Try to open file browser for the command
                self._auto_select_file_for_command(cmd)
            return

        ip, port = self._get_connection()
        self._set_running(True)
        self.status_var.set(f"执行中: {cmd}")
        self._log(f"\n▶ {cmd}  →  {ip}:{port}", "head")

        def _done(ok, output):
            # Only update if not stopped by user
            if self._running:
                self.root.after(0, lambda: self._append_output(output, ok))
                self.root.after(0, lambda: self._set_running(False))
                self.root.after(0, lambda: self.status_var.set(
                    f"✓ 成功: {cmd}" if ok else f"✗ 失败: {cmd}"))
            else:
                # Was stopped, just append output without changing status
                self.root.after(0, lambda: self._append_output(output, ok))

        def _run():
            ok, output = _sync_run(cmd, ip, port)
            _done(ok, output)

        threading.Thread(target=_run, daemon=True).start()

    # ── log helpers ────────────────────────────────────────────────────────────
    def _log(self, text: str, tag: str = ""):
        self.log.config(state=tk.NORMAL)
        ts = datetime.now().strftime("%H:%M:%S")
        self.log.insert(tk.END, f"[{ts}] ", "dim")
        self.log.insert(tk.END, text + "\n", tag or None)
        self.log.config(state=tk.DISABLED)
        self.log.see(tk.END)

    def _append_output(self, text: str, ok: bool):
        if not text.strip():
            return
        self.log.config(state=tk.NORMAL)
        for line in text.splitlines():
            if not line.strip():
                continue
            tag = "ok" if ok and "失败" not in line and "异常" not in line else (
                  "error" if ("失败" in line or "异常" in line or "Error" in line.lower()) else "info")
            self.log.insert(tk.END, "    " + line + "\n", tag)
        self.log.config(state=tk.DISABLED)
        self.log.see(tk.END)

    def _clear_log(self):
        self.log.config(state=tk.NORMAL)
        self.log.delete("1.0", tk.END)
        self.log.config(state=tk.DISABLED)

    # ── config management ──────────────────────────────────────────────────────
    def _save_current_config(self):
        """Save current UI settings to config file"""
        self.config["s100_ip"] = self.ip_var.get().strip()
        self.config["port"] = self.port_var.get().strip()
        self.config["x5_ip"] = self.x5_ip_var.get().strip()
        self.config["use_ssh_key"] = self.use_ssh_key_var.get()
        self.config["ssh_key_path"] = self.ssh_key_var.get().strip()
        save_config(self.config)

    def _save_config_manual(self):
        """Manually save config with user feedback"""
        try:
            self._save_current_config()
            config_path = CONFIG_FILE
            self._log(f"✓ 配置已保存到: {config_path}", "ok")
            self.status_var.set(f"配置已保存: {os.path.basename(config_path)}")
            # Flash the button to provide visual feedback
            original_text = self.save_config_btn.cget("text")
            self.save_config_btn.config(text="✓ 已保存")
            self.root.after(1500, lambda: self.save_config_btn.config(text=original_text))
        except Exception as e:
            self._log(f"✗ 配置保存失败: {e}", "error")
            messagebox.showerror("保存失败", f"配置保存失败:\n{e}", parent=self.root)

    def _on_close(self):
        """Handle window close event"""
        self._save_current_config()
        self.root.destroy()

    # ── SSH key helpers ────────────────────────────────────────────────────────
    def _update_ssh_key_controls(self):
        """Enable/disable SSH key input controls based on checkbox state"""
        if self.use_ssh_key_var.get():
            self.ssh_key_entry.config(state=tk.NORMAL)
            self.ssh_key_browse_btn.config(state=tk.NORMAL)
        else:
            self.ssh_key_entry.config(state=tk.DISABLED)
            self.ssh_key_browse_btn.config(state=tk.DISABLED)

    def _browse_ssh_key(self):
        """Open file dialog to select SSH private key file"""
        import platform
        home = os.path.expanduser("~")
        # Platform-aware .ssh directory path
        if platform.system().lower() == "windows":
            initial_dir = os.path.join(home, ".ssh")
        else:
            initial_dir = os.path.join(home, ".ssh")

        file_path = filedialog.askopenfilename(
            title="选择SSH私钥文件",
            initialdir=initial_dir if os.path.exists(initial_dir) else home,
            parent=self.root
        )
        if file_path:
            self.ssh_key_var.set(file_path)

    # ── ping helpers ───────────────────────────────────────────────────────────
    def _ping_s100(self):
        """Ping S100 board directly"""
        if self._running:
            messagebox.showinfo("提示", "已有任务在执行中，请稍后再试")
            return

        ip = self.ip_var.get().strip()
        if not ip:
            messagebox.showwarning("提示", "请先输入机器人IP")
            return

        self._set_running(True)
        self.status_var.set(f"Ping S100: {ip}")
        self._log(f"\n▶ Ping S100 → {ip}", "head")

        def _do_ping():
            import subprocess
            import platform

            # Determine ping command based on OS
            if platform.system().lower() == "windows":
                cmd = ["ping", "-n", "4", ip]
            else:
                cmd = ["ping", "-c", "4", ip]

            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                output = result.stdout + result.stderr
                success = result.returncode == 0

                # Only update if not stopped
                if self._running:
                    self.root.after(0, lambda: self._append_output(output, success))
                    self.root.after(0, lambda: self.status_var.set(
                        f"✓ S100 ({ip}) 连接成功" if success else f"✗ S100 ({ip}) 无响应"))
                else:
                    self.root.after(0, lambda: self._append_output(output, success))
            except subprocess.TimeoutExpired:
                if self._running:
                    self.root.after(0, lambda: self._append_output("Ping 超时", False))
                    self.root.after(0, lambda: self.status_var.set(f"✗ S100 ({ip}) 超时"))
            except Exception as e:
                if self._running:
                    self.root.after(0, lambda: self._append_output(f"Ping 异常: {e}", False))
                    self.root.after(0, lambda: self.status_var.set(f"✗ S100 ({ip}) 异常"))
            finally:
                if self._running:
                    self.root.after(0, lambda: self._set_running(False))

        threading.Thread(target=_do_ping, daemon=True).start()

    def _ping_x5(self):
        """Ping X5 board via S100 hop"""
        if self._running:
            messagebox.showinfo("提示", "已有任务在执行中，请稍后再试")
            return

        # Check if SSH is available
        if not check_ssh_available():
            import platform
            if platform.system().lower() == "windows":
                messagebox.showerror(
                    "SSH不可用",
                    "未找到SSH命令。\n\n"
                    "在Windows上需要安装OpenSSH客户端：\n"
                    "1. 设置 → 应用 → 可选功能\n"
                    "2. 添加功能 → OpenSSH客户端\n"
                    "3. 安装后重启应用",
                    parent=self.root
                )
            else:
                messagebox.showerror(
                    "SSH不可用",
                    "未找到SSH命令。\n\n"
                    "请确保已安装OpenSSH客户端。",
                    parent=self.root
                )
            return

        s100_ip = self.ip_var.get().strip()
        if not s100_ip:
            messagebox.showwarning("提示", "请先输入S100 IP地址")
            return

        x5_ip = self.x5_ip_var.get().strip()
        if not x5_ip:
            messagebox.showwarning("提示", "请先输入X5 IP地址")
            return

        # Check SSH key configuration
        use_key = self.use_ssh_key_var.get()
        ssh_key_path = ""

        if use_key:
            # User explicitly enabled SSH key
            ssh_key_path = os.path.expanduser(self.ssh_key_var.get().strip())
            if not os.path.exists(ssh_key_path):
                messagebox.showwarning("提示", f"SSH密钥文件不存在: {ssh_key_path}")
                return
        else:
            # SSH key not enabled, try to use default key
            # Use platform-aware default path
            default_key_path = get_default_ssh_key_path()
            default_key = os.path.expanduser(default_key_path)
            if os.path.exists(default_key):
                ssh_key_path = default_key
                use_key = True
            else:
                # No default key found
                import platform
                key_display = default_key if platform.system().lower() == "windows" else default_key_path
                result = messagebox.askyesno(
                    "需要SSH密钥",
                    f"连接S100板需要SSH密钥认证。\n\n"
                    f"未找到默认密钥\n{key_display}\n\n"
                    f"是否现在启用SSH密钥设置？",
                    parent=self.root
                )
                if result:
                    self.use_ssh_key_var.set(True)
                    self._update_ssh_key_controls()
                return

        self._set_running(True)
        key_info = f" (使用密钥: {ssh_key_path})" if ssh_key_path else ""
        self.status_var.set(f"Ping X5 via S100: {s100_ip} -> {x5_ip}{key_info}")
        self._log(f"\n▶ Ping X5 (经S100跳转) → {s100_ip} -> {x5_ip}{key_info}", "head")

        def _do_ping():
            import subprocess

            # SSH to S100 and ping X5
            ssh_cmd = ["ssh"]

            # Add SSH key if enabled
            if use_key:
                ssh_cmd.extend(["-i", ssh_key_path])

            ssh_cmd.extend([
                "-o", "StrictHostKeyChecking=no",
                "-o", "UserKnownHostsFile=/dev/null",
                "-o", "ConnectTimeout=5",
                f"root@{s100_ip}",
                f"ping -c 4 {x5_ip}"
            ])

            try:
                result = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=15)
                output = result.stdout + result.stderr
                success = result.returncode == 0

                # Only update if not stopped
                if self._running:
                    self.root.after(0, lambda: self._append_output(output, success))
                    self.root.after(0, lambda: self.status_var.set(
                        f"✓ X5 ({x5_ip}) 连接成功" if success else f"✗ X5 ({x5_ip}) 无响应"))
                else:
                    self.root.after(0, lambda: self._append_output(output, success))
            except subprocess.TimeoutExpired:
                if self._running:
                    self.root.after(0, lambda: self._append_output("SSH/Ping 超时", False))
                    self.root.after(0, lambda: self.status_var.set(f"✗ X5 ({x5_ip}) 超时"))
            except Exception as e:
                if self._running:
                    self.root.after(0, lambda: self._append_output(f"SSH/Ping 异常: {e}", False))
                    self.root.after(0, lambda: self.status_var.set(f"✗ X5 ({x5_ip}) 异常"))
            finally:
                if self._running:
                    self.root.after(0, lambda: self._set_running(False))

        threading.Thread(target=_do_ping, daemon=True).start()


# ── sync wrapper around async test_single_case ────────────────────────────────
def _sync_run(cmd: str, ip: str, port: int):
    """Run test_single_case synchronously, capturing stdout. Returns (ok, output)."""
    import io
    import builtins

    captured = io.StringIO()
    _orig = builtins.print

    def _print(*args, **kwargs):
        _orig(*args, **kwargs)
        captured.write(" ".join(str(a) for a in args) + "\n")

    builtins.print = _print
    ok = False
    try:
        ok = asyncio.run(test_single_case(cmd, ip, port))
    except Exception as e:
        captured.write(f"[异常] {e}\n")
    finally:
        builtins.print = _orig
    return ok, captured.getvalue()


# ── command edit dialog ────────────────────────────────────────────────────────
class _CommandDialog(tk.Toplevel):
    def __init__(self, parent, title="命令", initial=None):
        super().__init__(parent)
        self.title(title)
        self.transient(parent)          # attach to parent, never goes full-screen
        self.resizable(False, False)
        self.grab_set()
        self.result = None

        # position dialog near the center of the parent window
        parent.update_idletasks()
        px = parent.winfo_rootx() + parent.winfo_width() // 2 - 250
        py = parent.winfo_rooty() + parent.winfo_height() // 2 - 120
        self.geometry(f"500x200+{px}+{py}")

        ttk.Label(self, text="命令 (如 vel_cmd=2%):").grid(row=0, column=0, columnspan=2, sticky=tk.W, padx=10, pady=(10, 2))

        cmd_frame = ttk.Frame(self)
        cmd_frame.grid(row=1, column=0, columnspan=2, sticky=tk.EW, padx=10)
        cmd_frame.columnconfigure(0, weight=1)

        self.cmd_var = tk.StringVar(value=(initial or {}).get("cmd", ""))
        self.cmd_entry = ttk.Entry(cmd_frame, textvariable=self.cmd_var, width=50)
        self.cmd_entry.grid(row=0, column=0, sticky=tk.EW)

        # Add browse button for motor_ota and transfer commands
        self.browse_btn = ttk.Button(cmd_frame, text="浏览...", command=self._browse_file, width=10)
        self.browse_btn.grid(row=0, column=1, padx=(4, 0))

        # Check if command needs file selection
        self._update_browse_button_visibility()
        self.cmd_var.trace_add('write', lambda *args: self._update_browse_button_visibility())

        ttk.Label(self, text="描述:").grid(row=2, column=0, columnspan=2, sticky=tk.W, padx=10, pady=(8, 2))
        self.desc_var = tk.StringVar(value=(initial or {}).get("desc", ""))
        ttk.Entry(self, textvariable=self.desc_var, width=50).grid(row=3, column=0, columnspan=2, sticky=tk.EW, padx=10)

        btn_frame = ttk.Frame(self)
        btn_frame.grid(row=4, column=0, columnspan=2, pady=10)
        ttk.Button(btn_frame, text="确定", command=self._ok).pack(side=tk.LEFT, padx=6)
        ttk.Button(btn_frame, text="取消", command=self.destroy).pack(side=tk.LEFT, padx=6)

        self.bind("<Return>", lambda _: self._ok())
        self.bind("<Escape>", lambda _: self.destroy())
        self.wait_window()

    def _update_browse_button_visibility(self):
        """Show browse button only for commands that need file selection"""
        cmd = self.cmd_var.get().lower()
        # Show button for motor_ota and transfer commands
        if cmd.startswith("motor_ota=") or cmd.startswith("transfer="):
            self.browse_btn.grid()
        else:
            self.browse_btn.grid_remove()

    def _browse_file(self):
        """Open file dialog to select file path"""
        cmd = self.cmd_var.get()

        # Determine if it's a directory or file selection
        if cmd.startswith("transfer="):
            # For transfer, could be file or directory
            file_path = filedialog.askopenfilename(
                title="选择文件",
                parent=self
            )
            if not file_path:
                # Try directory selection
                file_path = filedialog.askdirectory(
                    title="选择文件夹",
                    parent=self
                )
        else:
            # For motor_ota, select .bin file
            file_path = filedialog.askopenfilename(
                title="选择固件文件",
                filetypes=[("固件文件", "*.bin"), ("所有文件", "*.*")],
                parent=self
            )

        if file_path:
            # Update command with the selected file path
            # Parse current command to inject the file path
            if cmd.startswith("motor_ota="):
                # motor_ota=1,<file_path>% or motor_ota=2,<file_path>,<motor_ids>%
                import re
                match = re.match(r'(motor_ota=\d+),([^,]*)(,.*)?(%?)$', cmd)
                if match:
                    op_part = match.group(1)
                    rest = match.group(3) or ""
                    percent = match.group(4) or "%"
                    new_cmd = f"{op_part},{file_path}{rest}{percent}"
                    self.cmd_var.set(new_cmd)
                else:
                    # Fallback: just replace <firmware_path> placeholder
                    new_cmd = cmd.replace("<firmware_path>", file_path)
                    self.cmd_var.set(new_cmd)
            elif cmd.startswith("transfer="):
                # transfer=1,<addrA>,<addrB>% or transfer=2,<addrA>,<addrB>%
                import re
                match = re.match(r'(transfer=\d+),([^,]*)(,.*)?(%?)$', cmd)
                if match:
                    op_part = match.group(1)
                    rest = match.group(3) or ""
                    percent = match.group(4) or "%"
                    new_cmd = f"{op_part},{file_path}{rest}{percent}"
                    self.cmd_var.set(new_cmd)

    def _ok(self):
        cmd = self.cmd_var.get().strip()
        if not cmd:
            messagebox.showwarning("提示", "命令不能为空", parent=self)
            return
        self.result = {"cmd": cmd, "desc": self.desc_var.get().strip()}
        self.destroy()


# ══════════════════════════════════════════════════════════════════════════════
def main():
    args = sys.argv[1:]

    # ── CLI mode: single command like test_engineer_client.py ─────────────────
    # Detect: first arg looks like a test case (contains '=') or no args
    if args and ("=" in args[0] or args[0].endswith("%")):
        cmd = args[0]
        ip  = args[1] if len(args) > 1 else "192.168.126.2"
        port = int(args[2]) if len(args) > 2 else 3579
        print(f"目标机器人: {ip}:{port}")
        print(f"测试用例: {cmd}")
        print("-" * 50)
        try:
            ok = asyncio.run(test_single_case(cmd, ip, port))
            sys.exit(0 if ok else 1)
        except KeyboardInterrupt:
            sys.exit(1)
        except Exception as e:
            print(f"异常: {e}")
            sys.exit(1)

    # ── GUI mode ───────────────────────────────────────────────────────────────
    default_ip = args[0] if args else "192.168.126.2"
    root = tk.Tk()
    app = EngineerCmdRunnerApp(root, default_ip=default_ip)
    root.mainloop()


if __name__ == "__main__":
    main()
