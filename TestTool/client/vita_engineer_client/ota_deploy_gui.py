#!/usr/bin/env python3
import os
import sys
import json
import subprocess
import threading
import fnmatch
import shlex
import re
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from datetime import datetime

# 依赖检查
try:
    import paramiko
except ImportError:
    print("错误: 缺少依赖库 paramiko。请执行: pip3 install paramiko")
    sys.exit(1)

# ── 升级包识别规则 ──────────────────────────────────────────────────
PKG_RULES = {
    "S100 APP": "*app*s100*.zip",
    "S100 SYS": "all_in_one-v*.zip",
    "X5 APP": "*app*x5*.zip",
    "X5 SYS": "all_in_one-LNX*.zip"
}

DEFAULT_CONFIG = {
    "s100_ip": "192.168.126.2",
    "x5_ip": "192.168.127.10",
    "username": "root",
    "password": "root",
    "ota_dir": "/ota",
    "connect_timeout": 5,
    "use_identity_file": False,
    "identity_file": "",
    "ota_target_s100": True, 
    "ota_target_x5": True,   
    "use_tmux": True,
    "sync_items": [],
    # Zenoh set_zenoh_mode_client.py：勾选则校验 COMMIT_HASH；不勾选则传 --skip-hash-check
    "zenoh_enforce_hash_check": False,
    "zenoh_client_script": "",
}

CONFIG_FILE = os.path.expanduser("~/.ota_deploy_config.json")

# 远端 OTA 目录内保留的升级轨迹子目录（清理包时不清除）
OTA_TRACE_DIRNAME = "_ota_deploy_trace"

def load_config():
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                saved = json.load(f)
            cfg.update(saved)
        except: pass
    return cfg

def save_config(cfg):
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        print(f"保存配置失败: {e}")

# ── SSH 助手类 ────────────────────────────────────────────────────────
class SSHHelper:
    def __init__(self, hostname, username, password=None, identity_file=None,
                 use_key=False, timeout=5, jump_client=None, logger=None):
        self.hostname = hostname
        self.username = username
        self.password = password
        self.identity_file = identity_file
        self.use_key = use_key
        self.timeout = timeout
        self.jump_client = jump_client
        self.logger = logger or (lambda msg: None)
        self.client = None

    def connect(self):
        sock = None
        if self.jump_client:
            transport = self.jump_client.get_transport()
            sock = transport.open_channel("direct-tcpip", (self.hostname, 22), ("127.0.0.1", 0))

        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        kwargs = {"hostname": self.hostname, "username": self.username, "timeout": self.timeout, "sock": sock}
        if self.use_key and self.identity_file:
            kwargs["key_filename"] = self.identity_file
            if self.password: kwargs["password"] = self.password
        else:
            kwargs["password"] = self.password
        self.client.connect(**kwargs)
        # 经 S100 跳转或大包 SFTP 时链路较长，避免中间 NAT/防火墙 idle 断连导致偶发传包失败
        t = self.client.get_transport()
        if t:
            t.set_keepalive(60)

    def upload_file(self, local_src, remote_dst, progress_cb=None):
        if remote_dst.endswith('/'):
            remote_dir = remote_dst.rstrip('/')
            remote_path = remote_dir + "/" + os.path.basename(local_src)
        else:
            remote_dir = os.path.dirname(remote_dst)
            remote_path = remote_dst

        # 等待 mkdir 完成后再上传，避免目录未就绪导致失败
        _, stdout_mk, _ = self.client.exec_command(f"mkdir -p '{remote_dir}'")
        stdout_mk.channel.recv_exit_status()
        sftp = self.client.open_sftp()
        try:
            sftp.put(local_src, remote_path, callback=progress_cb)
        finally:
            sftp.close()

    def close(self):
        if self.client: self.client.close()

# ── 执行逻辑引擎 ───────────────────────────────────────────────────────
class DeployExecutor:
    def __init__(self, cfg, logger):
        self.cfg = cfg
        self.log = logger

    def run_sync(self):
        self.log("🚀 开始【独立文件同步】任务...")
        self._run_task(mode="sync")

    def run_ota(self):
        self.log("🚀 开始【独立 OTA 升级】任务...")
        self._run_task(mode="ota")

    def _run_task(self, mode):
        s100_ssh = None
        x5_ssh = None
        try:
            self.log(f">>> 连接 S100 @ {self.cfg['s100_ip']}")
            s100_ssh = SSHHelper(self.cfg["s100_ip"], self.cfg["username"], self.cfg["password"],
                                identity_file=self.cfg["identity_file"], use_key=self.cfg["use_identity_file"],
                                timeout=self.cfg["connect_timeout"], logger=self.log)
            s100_ssh.connect()

            needs_x5 = False
            if mode == "ota":
                needs_x5 = self.cfg.get("ota_target_x5", False)
            else:
                needs_x5 = any(item.get("x5") for item in self.cfg.get("sync_items", []))

            if needs_x5:
                self.log(f">>> 连接 X5 @ {self.cfg['x5_ip']} (通过隧道)")
                x5_ssh = SSHHelper(self.cfg["x5_ip"], self.cfg["username"], self.cfg["password"],
                                  identity_file=self.cfg["identity_file"], use_key=self.cfg["use_identity_file"],
                                  jump_client=s100_ssh.client, logger=self.log)
                x5_ssh.connect()

            if mode == "sync":
                self._do_sync_work(s100_ssh, x5_ssh)
            else:
                self._do_ota_work(s100_ssh, x5_ssh)

            self.log("🎉 任务执行完毕。")
            return True
        except Exception as e:
            self.log(f"❌ 运行失败: {e}")
            return False
        finally:
            if x5_ssh: x5_ssh.close()
            if s100_ssh: s100_ssh.close()

    def _exec_and_check(self, ssh, cmd, label="", log_fail=True):
        """执行远程命令，等待完成并返回 (exit_code, stdout_str, stderr_str)"""
        _, stdout, stderr = ssh.client.exec_command(cmd)
        out = stdout.read().decode("utf-8", errors="replace").strip()
        err = stderr.read().decode("utf-8", errors="replace").strip()
        exit_code = stdout.channel.recv_exit_status()
        if log_fail and exit_code != 0 and err:
            self.log(f"[{label}] ⚠️ 命令失败 (exit {exit_code}): {err}")
        return exit_code, out, err

    def _start_tmux_session(self, ssh, session_name, inner_cmd, label):
        """安全启动 tmux 会话并校验是否成功。"""
        self._exec_and_check(ssh, f"tmux kill-session -t {session_name}", label, log_fail=False)

        rc, out, err = self._exec_and_check(ssh, f"tmux new-session -d -s {session_name}", label, log_fail=False)
        if rc != 0:
            reason = err or out or "未知错误"
            raise RuntimeError(f"[{label}] 启动 tmux 失败 (exit {rc}): {reason}")

        send_cmd = f"tmux send-keys -t {session_name} -- {shlex.quote(inner_cmd)} C-m"
        rc_send, out_send, err_send = self._exec_and_check(ssh, send_cmd, label, log_fail=False)
        if rc_send != 0:
            reason = err_send or out_send or "未知错误"
            raise RuntimeError(f"[{label}] 下发 tmux 命令失败 (exit {rc_send}): {reason}")

        rc2, _, err2 = self._exec_and_check(ssh, f"tmux has-session -t {session_name}", label, log_fail=False)
        if rc2 != 0:
            reason = (err2 or "").strip()
            if "no server running" in reason.lower() or "can't find session" in reason.lower():
                self.log(f"[{label}] ℹ️ tmux 会话已快速结束，任务可能已完成或快速失败，请检查结果/日志文件")
            else:
                self.log(f"[{label}] ⚠️ 无法确认 tmux 会话状态: {reason or '未知原因'}")

    def _build_s100_to_x5_auth(self, s100_ssh):
        s100_x5_key_path = "/tmp/ota_x5_fetch_id"
        use_key = self.cfg.get("use_identity_file") and self.cfg.get("identity_file")
        identity_file_local = self.cfg.get("identity_file", "")

        if use_key and os.path.exists(identity_file_local):
            try:
                s100_ssh.upload_file(identity_file_local, s100_x5_key_path)
                self._exec_and_check(s100_ssh, f"chmod 600 '{s100_x5_key_path}'", "S100 OTA", log_fail=False)
                return (
                    f"-i '{s100_x5_key_path}' -o IdentitiesOnly=yes "
                    f"-o PreferredAuthentications=publickey -o BatchMode=yes",
                    f"rm -f '{s100_x5_key_path}'; "
                )
            except Exception:
                pass

        return (
            "-o PreferredAuthentications=publickey,password,keyboard-interactive -o BatchMode=yes",
            ""
        )
        
    def _build_screen_cmds(self, ip):
        """构建通过 HTTP 请求控制屏幕颜色的 curl 命令"""
        base_cmd = f"curl -s -X POST 'http://{ip}:3579/command' -H 'Content-Type: application/json'"
        eng_cmd = f"{base_cmd} -d '{{\"command\":\"enfac=1,1%\",\"params\":{{\"op\":\"1\",\"en\":\"1\"}}}}'"
        grn_cmd = f"{base_cmd} -d '{{\"command\":\"lcd=1,green%\",\"params\":{{\"op\":\"1\",\"color\":\"green\"}}}}'"
        red_cmd = f"{base_cmd} -d '{{\"command\":\"lcd=1,red%\",\"params\":{{\"op\":\"1\",\"color\":\"red\"}}}}'"
        
        # 组装命令，确保先进入工程模式并缓冲 1 秒，再发送颜色指令
        return f"{eng_cmd} >/dev/null 2>&1 && sleep 1", f"{grn_cmd} >/dev/null 2>&1", f"{red_cmd} >/dev/null 2>&1"

    def _do_sync_work(self, s100_ssh, x5_ssh):
        items = self.cfg.get("sync_items", [])
        total = sum(1 for item in items if item.get("src") and item.get("dst") and os.path.exists(item.get("src", "")) and (item.get("s100") or item.get("x5")))
        done = 0
        for item in items:
            src, dst = item.get("src"), item.get("dst")
            if not (src and dst and os.path.exists(src)):
                continue
            file_size = os.path.getsize(src)
            size_str = f"{file_size / 1024 / 1024:.1f}MB" if file_size > 1024 * 1024 else f"{file_size / 1024:.1f}KB"
            fname = os.path.basename(src)
            make_exec = item.get("executable", False)

            if item.get("s100") and s100_ssh:
                try:
                    rc, _, err = self._exec_and_check(s100_ssh, "systemctl stop vita01.target", "stop robot")
                    if rc != 0:
                        self.log(f"[S100 Stop Robot] ⚠️ 停止机器人服务失败: {err}")
                    rc, _, err = self._exec_and_check(s100_ssh, "mount -o remount,rw /app", "S100 Sync")
                    if rc != 0:
                        self.log(f"[S100 Sync] ⚠️ mount 失败: {err}")
                    self.log(f"[S100 Sync] 上传 {fname} ({size_str}) → {dst}")
                    s100_ssh.upload_file(src, dst, progress_cb=self._make_progress_cb(f"S100 Sync", fname, file_size))
                    remote_path = dst + os.path.basename(src) if dst.endswith('/') else dst
                    if make_exec:
                        rc_chmod, _, err_chmod = self._exec_and_check(s100_ssh, f"chmod +x '{remote_path}'", "S100 Sync")
                        if rc_chmod == 0:
                            self.log(f"[S100 Sync] 已赋予可执行权限: {remote_path}")
                        else:
                            self.log(f"[S100 Sync] ⚠️ chmod +x 失败: {err_chmod}")
                    rc, out, _ = self._exec_and_check(s100_ssh, f"stat '{remote_path}' 2>&1", "S100 Sync")
                    if rc == 0:
                        self.log(f"[S100 Sync] ✅ {fname} 同步成功")
                    else:
                        self.log(f"[S100 Sync] ❌ {fname} 同步失败: {out}")
                except Exception as e:
                    self.log(f"[S100 Sync] ❌ {fname} 同步异常: {e}")

            if item.get("x5") and x5_ssh:
                try:
                    rc, _, err = self._exec_and_check(x5_ssh, "systemctl stop vita01.target", "stop robot")
                    if rc != 0:
                        self.log(f"[X5 Stop Robot] ⚠️ 停止机器人服务失败: {err}")   
                        
                    rc, _, err = self._exec_and_check(x5_ssh, "mount -o remount,rw /app", "X5 Sync")
                    if rc != 0:
                        self.log(f"[X5 Sync] ⚠️ mount /app 失败: {err}")
                    rc, _, err = self._exec_and_check(x5_ssh, "mount -o remount,rw /usr/hobot", "X5 Sync")
                    if rc != 0:
                        self.log(f"[X5 Sync] ⚠️ mount /usr/hobot 失败: {err}")
                    self.log(f"[X5 Sync] 上传 {fname} ({size_str}) → {dst}")
                    x5_ssh.upload_file(src, dst, progress_cb=self._make_progress_cb(f"X5 Sync", fname, file_size))
                    remote_path = dst + os.path.basename(src) if dst.endswith('/') else dst
                    if make_exec:
                        rc_chmod, _, err_chmod = self._exec_and_check(x5_ssh, f"chmod +x '{remote_path}'", "X5 Sync")
                        if rc_chmod == 0:
                            self.log(f"[X5 Sync] 已赋予可执行权限: {remote_path}")
                        else:
                            self.log(f"[X5 Sync] ⚠️ chmod +x 失败: {err_chmod}")
                    rc, out, _ = self._exec_and_check(x5_ssh, f"stat '{remote_path}' 2>&1", "X5 Sync")
                    if rc == 0:
                        self.log(f"[X5 Sync] ✅ {fname} 同步成功")
                    else:
                        self.log(f"[X5 Sync] ❌ {fname} 同步失败: {out}")
                except Exception as e:
                    self.log(f"[X5 Sync] ❌ {fname} 同步异常: {e}")

            done += 1
            self.log(f"--- 同步进度: {done}/{total} ---")

    def _ota_trace_path(self, ota_dir):
        return f"{ota_dir.rstrip('/')}/{OTA_TRACE_DIRNAME}"

    def _ota_prep_cmd(self, ota_dir):
        """准备 OTA 目录：清空旧包，保留轨迹子目录。"""
        q = shlex.quote(ota_dir.rstrip("/"))
        return (
            "mount -o remount,rw /app && "
            f"mkdir -p {q} && "
            f"for _ota_f in {q}/*; do "
            f'[ -e "$_ota_f" ] || continue; '
            f'[ "$(basename "$_ota_f")" = "{OTA_TRACE_DIRNAME}" ] && continue; '
            f'rm -rf "$_ota_f"; done'
        )

    def _ota_cleanup_keep_trace_shell(self, ota_dir):
        q = shlex.quote(ota_dir.rstrip("/"))
        return (
            f"for _ota_f in {q}/*; do "
            f'[ -e "$_ota_f" ] || continue; '
            f'[ "$(basename "$_ota_f")" = "{OTA_TRACE_DIRNAME}" ] && continue; '
            f'rm -rf "$_ota_f"; done'
        )

    def _ota_trace_init_shell(self, ota_dir):
        """在远端 shell 中定义 ota_tr，写入 session.log（位于 ota 目录下的轨迹子目录）。"""
        td = self._ota_trace_path(ota_dir)
        return (
            f"OTA_T={shlex.quote(td)}; "
            "ota_tr() { mkdir -p \"$OTA_T\" && printf '%s %s\\n' "
            "\"$(date '+%Y-%m-%d %H:%M:%S' 2>/dev/null || date)\" \"$*\" >> \"$OTA_T/session.log\"; }"
        )

    def _remote_ota_trace(self, ssh, ota_dir, message, log_label="OTA trace"):
        """经当前 SSH 在远端 ota 轨迹目录追加一行（用于非 tmux 路径或上传后节点）。"""
        line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {message}".replace("\n", " ").replace("\r", " ")
        esc = line.replace("'", "'\"'\"'")
        td = self._ota_trace_path(ota_dir)
        cmd = f"mkdir -p '{td}' && printf '%s\\n' '{esc}' >> '{td}/session.log'"
        self._exec_and_check(ssh, cmd, log_label, log_fail=False)

    def _make_progress_cb(self, label, filename, total_size):
        last_pct = [-1]
        def _cb(transferred, total):
            if total == 0: return
            pct = int(transferred * 100 / total)
            step = (pct // 10) * 10
            if step > last_pct[0]:
                last_pct[0] = step
                t_mb = transferred / 1024 / 1024
                total_mb = total / 1024 / 1024
                self.log(f"[{label}] 📦 {filename}: {t_mb:.1f}/{total_mb:.1f}MB ({pct}%)")
        return _cb

    def _do_ota_work(self, s100_ssh, x5_ssh):
        targets = [("S100", s100_ssh, self.cfg.get("ota_target_s100")), ("X5", x5_ssh, self.cfg.get("ota_target_x5"))]
        valid_targets = []
        for label, ssh, enabled in targets:
            if not (enabled and ssh): continue
            app_p, sys_p = self.cfg.get(f"{label.lower()}_app_path"), self.cfg.get(f"{label.lower()}_sys_path")
            if not (app_p and sys_p):
                self.log(f"[{label} OTA] 缺少包路径，跳过。")
                continue
            valid_targets.append((label, ssh, app_p, sys_p))

        if not valid_targets:
            return

        for label, ssh, app_p, sys_p in valid_targets:
            ota_dir = self.cfg["ota_dir"]
            self.log(f"[{label} OTA] 上传升级包...")
            prep = self._ota_prep_cmd(ota_dir)
            rc_prep, _, err_prep = self._exec_and_check(ssh, prep, f"{label} OTA prep", log_fail=True)
            if rc_prep != 0:
                detail = err_prep or f"mount/mkdir/rm 未全部成功，请检查 /app 是否可写、{ota_dir} 是否可用"
                raise RuntimeError(f"[{label} OTA] 准备目录失败 (exit {rc_prep}): {detail}")
            self._remote_ota_trace(ssh, ota_dir, f"[{label}] OTA 目录已准备，开始上传包", f"{label} OTA")
            sftp = ssh.client.open_sftp()
            app_name = os.path.basename(app_p)
            sys_name = os.path.basename(sys_p)
            app_sz = os.path.getsize(app_p)
            sys_sz = os.path.getsize(sys_p)
            r_app = f"{ota_dir}/{app_name}"
            r_sys = f"{ota_dir}/{sys_name}"
            try:
                sftp.put(app_p, r_app, callback=self._make_progress_cb(f"{label} OTA", app_name, app_sz))
                sftp.put(sys_p, r_sys, callback=self._make_progress_cb(f"{label} OTA", sys_name, sys_sz))
            finally:
                sftp.close()
            for rpath, expect, fname in ((r_app, app_sz, app_name), (r_sys, sys_sz, sys_name)):
                rc_sz, out_sz, _ = self._exec_and_check(
                    ssh, f"wc -c < '{rpath}' 2>/dev/null", f"{label} OTA", log_fail=False
                )
                if rc_sz != 0:
                    raise RuntimeError(f"[{label} OTA] 上传后无法读取远程文件大小: {fname}")
                try:
                    got = int((out_sz or "").strip())
                except ValueError:
                    raise RuntimeError(f"[{label} OTA] 远程大小解析失败: {fname} → {out_sz!r}")
                if got != expect:
                    raise RuntimeError(
                        f"[{label} OTA] 远程文件大小不一致（可能传包中断）: {fname} 本地 {expect} 字节, 远程 {got} 字节"
                    )
            self.log(f"[{label} OTA] 上传完成（已校验大小）。")
            self._remote_ota_trace(
                ssh,
                ota_dir,
                f"[{label}] 升级包已上传并校验大小 OK app={app_name} sys={sys_name}",
                f"{label} OTA",
            )

        if self.cfg["use_tmux"]:
            for label, ssh, _, _ in valid_targets:
                rc, _, _ = self._exec_and_check(ssh, "command -v tmux >/dev/null 2>&1", f"{label} OTA", log_fail=False)
                if rc != 0:
                    raise RuntimeError(f"[{label} OTA] 目标设备未安装 tmux，请安装 tmux 或关闭『Tmux 后台』后重试")

            target_map = {label: (ssh, app_p, sys_p) for label, ssh, app_p, sys_p in valid_targets}

            if "S100" in target_map and "X5" in target_map:
                x5_ssh, x5_app_p, x5_sys_p = target_map["X5"]
                x5_ota_cmd = (
                    f"cd {self.cfg['ota_dir']} && /usr/hobot/bin/ota_tool -n "
                    f"-p {os.path.basename(x5_app_p)} -p {os.path.basename(x5_sys_p)}"
                )
                x5_session = "ota_x5"
                x5_result_file = "/tmp/ota_x5.result"
                x5_log_file = "/tmp/ota_x5.log"
                self._exec_and_check(x5_ssh, f"rm -f '{x5_result_file}'", "X5 OTA", log_fail=False)
                self._exec_and_check(x5_ssh, f"rm -f '{x5_log_file}'", "X5 OTA", log_fail=False)
                x5_td = self._ota_trace_init_shell(self.cfg["ota_dir"])
                x5_clean = self._ota_cleanup_keep_trace_shell(self.cfg["ota_dir"])
                x5_inner_cmd = (
                    f"{x5_td}; ota_tr \"[X5] ota_tool 即将执行 (tmux)\"; "
                    f"{x5_ota_cmd} > '{x5_log_file}' 2>&1; "
                    f"x5_rc=$?; "
                    f"ota_tr \"[X5] ota_tool 已退出 rc=$x5_rc\"; "
                    f"echo $x5_rc > '{x5_result_file}'; "
                    f"echo x5_rc=$x5_rc >> '{x5_log_file}'; "
                    f"ota_tr \"[X5] 清理 OTA 目录(保留 {OTA_TRACE_DIRNAME})\"; "
                    f"{x5_clean}; "
                    f"echo tmux_done_x5_rc=$x5_rc >> '{x5_log_file}'"
                )
                self._start_tmux_session(x5_ssh, x5_session, x5_inner_cmd, "X5 OTA")
                self.log(f"[X5 OTA] 已在 tmux 后台启动 (session: {x5_session})")
                self.log(f"[X5 OTA] 可后续查询结果文件: {x5_result_file}")
                self.log(f"[X5 OTA] 可后续查询日志文件: {x5_log_file}")

                s100_ssh, s100_app_p, s100_sys_p = target_map["S100"]
                s100_ota_cmd = (
                    f"cd {self.cfg['ota_dir']} && /usr/hobot/bin/ota_tool -n "
                    f"-p {os.path.basename(s100_app_p)} -p {os.path.basename(s100_sys_p)}"
                )
                s100_session = "ota_s100"
                s100_result_file = "/tmp/ota_s100.result"
                s100_log_file = "/tmp/ota_s100.log"
                merge_detail_file = "/tmp/ota_merge.detail"
                self._exec_and_check(s100_ssh, f"rm -f '{s100_result_file}'", "S100 OTA", log_fail=False)
                self._exec_and_check(s100_ssh, f"rm -f '{s100_log_file}'", "S100 OTA", log_fail=False)
                self._exec_and_check(s100_ssh, f"rm -f '{merge_detail_file}'", "S100 OTA", log_fail=False)

                x5_ssh_auth, cleanup_key_cmd = self._build_s100_to_x5_auth(s100_ssh)

                x5_fetch_cmd = (
                    f"ssh -o LogLevel=ERROR -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "
                    f"-o ConnectTimeout=3 {x5_ssh_auth} root@{self.cfg['x5_ip']} \"cat /tmp/ota_x5.result 2>/dev/null\""
                )
                
                eng_cmd, grn_cmd, red_cmd = self._build_screen_cmds("localhost")

                s100_td = self._ota_trace_init_shell(self.cfg["ota_dir"])
                s100_clean = self._ota_cleanup_keep_trace_shell(self.cfg["ota_dir"])
                s100_inner_cmd = (
                    f"{s100_td}; ota_tr \"[S100] ota_tool 即将执行 (tmux 双机)\"; "
                    f"{s100_ota_cmd} > '{s100_log_file}' 2>&1; "
                    f"s100_rc=$?; "
                    f"ota_tr \"[S100] ota_tool 已退出 rc=$s100_rc\"; "
                    f"echo $s100_rc > '{s100_result_file}'; "
                    f"echo s100_rc=$s100_rc >> '{s100_log_file}'; "
                    f"x5_rc=125; "
                    f"x5_fetch_status=timeout; "
                    f"for i in $(seq 1 7200); do "
                    f"x5_val=$({x5_fetch_cmd}); "
                    f"if [ -n \"$x5_val\" ]; then x5_rc=$x5_val; x5_fetch_status=ok; break; fi; "
                    f"sleep 1; "
                    f"done; "
                    f"ota_tr \"[S100] 已轮询 X5 结果 x5_rc=$x5_rc fetch=$x5_fetch_status\"; "
                    f"echo s100_rc=$s100_rc > '{merge_detail_file}'; "
                    f"echo x5_rc=$x5_rc >> '{merge_detail_file}'; "
                    f"echo x5_fetch_status=$x5_fetch_status >> '{merge_detail_file}'; "
                    f"if [ \"$s100_rc\" = \"0\" ] && [ \"$x5_rc\" = \"0\" ]; then "
                    f"echo screen=green >> '{merge_detail_file}'; "
                    f"{eng_cmd}; {grn_cmd}; "
                    f"else "
                    f"echo screen=red >> '{merge_detail_file}'; "
                    f"{eng_cmd}; {red_cmd}; "
                    f"fi; "
                    f"ota_tr \"[S100] 双机汇总完成 s100_rc=$s100_rc x5_rc=$x5_rc fetch=$x5_fetch_status\"; "
                    f"{cleanup_key_cmd}"
                    f"ota_tr \"[S100] 清理 OTA 目录(保留 {OTA_TRACE_DIRNAME})\"; "
                    f"{s100_clean}; "
                    f"echo tmux_done_s100_rc=$s100_rc >> '{s100_log_file}'"
                )
                self._start_tmux_session(s100_ssh, s100_session, s100_inner_cmd, "S100 OTA")
                self.log(f"[S100 OTA] 已在 tmux 后台启动 (session: {s100_session})")
                self.log(f"[S100 OTA] 可后续查询结果文件: {s100_result_file}")
                self.log(f"[S100 OTA] 可后续查询日志文件: {s100_log_file}")
                self.log(f"[S100 OTA] 可后续查询汇总详情: {merge_detail_file}")
                self.log("[S100 OTA] 将负责汇总 S100+X5 结果并触发屏幕颜色提示")

            else:
                label, ssh, app_p, sys_p = valid_targets[0]
                ota_dir = self.cfg["ota_dir"]
                cmd = f"cd {ota_dir} && /usr/hobot/bin/ota_tool -n -p {os.path.basename(app_p)} -p {os.path.basename(sys_p)}"
                session_name = f"ota_{label.lower()}"
                result_file = f"/tmp/{session_name}.result"
                log_file = f"/tmp/{session_name}.log"
                self._exec_and_check(ssh, f"rm -f '{result_file}'", f"{label} OTA", log_fail=False)
                self._exec_and_check(ssh, f"rm -f '{log_file}'", f"{label} OTA", log_fail=False)
                
                api_ip = "localhost" if label == "S100" else "192.168.127.2"
                eng_cmd, grn_cmd, red_cmd = self._build_screen_cmds(api_ip)

                one_td = self._ota_trace_init_shell(ota_dir)
                one_clean = self._ota_cleanup_keep_trace_shell(ota_dir)
                tmux_inner_cmd = (
                    f"{one_td}; ota_tr \"[{label}] ota_tool 即将执行 (tmux 单机)\"; "
                    f"{cmd} > '{log_file}' 2>&1; "
                    f"ota_rc=$?; "
                    f"ota_tr \"[{label}] ota_tool 已退出 rc=$ota_rc\"; "
                    f"echo $ota_rc > '{result_file}'; "
                    f"echo ota_rc=$ota_rc >> '{log_file}'; "
                    f"if [ \"$ota_rc\" = \"0\" ]; then "
                    f"echo screen=green >> '{log_file}'; {eng_cmd}; {grn_cmd}; "
                    f"else "
                    f"echo screen=red >> '{log_file}'; {eng_cmd}; {red_cmd}; "
                    f"fi; "
                    f"ota_tr \"[{label}] 清理 OTA 目录(保留 {OTA_TRACE_DIRNAME})\"; "
                    f"{one_clean}; "
                    f"echo tmux_done_ota_rc=$ota_rc >> '{log_file}'"
                )
                self._start_tmux_session(ssh, session_name, tmux_inner_cmd, f"{label} OTA")
                self.log(f"[{label} OTA] 已在 tmux 后台启动 (session: {session_name})")
                self.log(f"[{label} OTA] 可后续查询结果文件: {result_file}")
                self.log(f"[{label} OTA] 可后续查询日志文件: {log_file}")
                self.log(f"[{label} OTA] 将在执行完成后触发屏幕颜色提示")

            self.log("✅ tmux 任务已全部提交，当前连接可断开，不影响后台升级。")
            td = self._ota_trace_path(self.cfg["ota_dir"])
            self.log(f"ℹ️ 远端 OTA 关键节点记录在: {td}/session.log")
            self.log("ℹ️ 后续可 SSH 登录执行: tmux ls / tmux attach -t ota_s100|ota_x5 / cat /tmp/ota_*.result")
            return
        else:
            threads = []
            for label, ssh, app_p, sys_p in valid_targets:
                t = threading.Thread(target=self._ota_exec_and_monitor, args=(label, ssh, app_p, sys_p), daemon=True)
                threads.append((label, t))
                t.start()
                self.log(f"[{label} OTA] 前台执行中...")

            if len(threads) > 1:
                self.log("⏳ S100 与 X5 正在并行升级，请等待全部完成...")

            for label, t in threads:
                t.join()

    def _ota_exec_and_monitor(self, label, ssh, app_p, sys_p):
        ota_dir = self.cfg["ota_dir"]
        cmd = f"cd {ota_dir} && /usr/hobot/bin/ota_tool -n -p {os.path.basename(app_p)} -p {os.path.basename(sys_p)}"
        clean = self._ota_cleanup_keep_trace_shell(ota_dir)
        try:
            self._remote_ota_trace(ssh, ota_dir, f"[{label}] 前台 ota_tool 开始执行", f"{label} OTA")
            _, stdout, stderr = ssh.client.exec_command(cmd, timeout=None)
            for line in iter(stdout.readline, ""):
                line = line.rstrip('\n\r')
                if line:
                    self.log(f"[{label} OTA] {line}")
            err_output = stderr.read().decode("utf-8", errors="replace").strip()
            if err_output:
                for err_line in err_output.splitlines():
                    self.log(f"[{label} OTA ⚠️] {err_line}")
            exit_code = stdout.channel.recv_exit_status()
            if exit_code == 0:
                self.log(f"[{label} OTA] ✅ 升级成功 (exit code: 0)")
                self._remote_ota_trace(ssh, ota_dir, f"[{label}] 前台 ota_tool 成功 exit=0，清理 OTA 目录(保留轨迹)", f"{label} OTA")
                ssh.client.exec_command(clean)
                self.log(f"[{label} OTA] 设备即将重启...")
                ssh.client.exec_command("reboot")
            else:
                self._remote_ota_trace(ssh, ota_dir, f"[{label}] 前台 ota_tool 失败 exit={exit_code}", f"{label} OTA")
                self.log(f"[{label} OTA] ❌ 升级失败 (exit code: {exit_code})")
        except Exception as e:
            self._remote_ota_trace(ssh, ota_dir, f"[{label}] 前台 ota_tool 异常: {e}", f"{label} OTA")
            self.log(f"[{label} OTA] ❌ 执行异常: {e}")

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

# ── GUI 界面 ──────────────────────────────────────────────────────────
class OTADeployGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("VITA 部署工具")
        self.root.geometry("1100x950")
        self.bg = "#f5f5f5"
        self.root.configure(bg=self.bg)
        
        self.cfg = load_config()
        self.sync_rows = [] 
        self.last_sn = "" # 缓存上次输入的 SN
        
        self._build_ui()
        self._load_fields()

    def _build_ui(self):
        container = tk.Frame(self.root, bg=self.bg, padx=15, pady=5)
        container.pack(fill=tk.BOTH, expand=True)

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

        f_zenoh = tk.LabelFrame(container, text=" Zenoh 客户端模式脚本（可选） ", bg=self.bg, padx=10, pady=5)
        f_zenoh.pack(fill=tk.X, pady=2)
        rz = tk.Frame(f_zenoh, bg=self.bg)
        rz.pack(fill=tk.X, pady=2)
        self.zenoh_enforce_hash = tk.BooleanVar(value=False)
        tk.Checkbutton(
            rz,
            text="校验 COMMIT_HASH（与脚本内期望版本一致；不勾选则跳过该校验）",
            variable=self.zenoh_enforce_hash,
            bg=self.bg,
        ).pack(anchor="w")
        rz2 = tk.Frame(f_zenoh, bg=self.bg)
        rz2.pack(fill=tk.X, pady=2)
        tk.Label(rz2, text="脚本路径:", bg=self.bg).pack(side=tk.LEFT)
        self.zenoh_script_path = tk.Entry(rz2, width=70, bg="white")
        self.zenoh_script_path.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        tk.Button(rz2, text="浏览…", command=self._browse_zenoh_script).pack(side=tk.LEFT)
        tk.Button(rz2, text="▶ 运行脚本", command=self._run_zenoh_client_script).pack(side=tk.LEFT, padx=6)

        f_ota = tk.LabelFrame(container, text=" 2. OTA 升级功能 ", bg="#e8f4f8", padx=10, pady=5)
        f_ota.pack(fill=tk.X, pady=5)
        r_o_t = tk.Frame(f_ota, bg="#e8f4f8"); r_o_t.pack(fill=tk.X, pady=2)
        self.ota_s100_v, self.ota_x5_v, self.use_tmux = tk.BooleanVar(), tk.BooleanVar(), tk.BooleanVar()
        tk.Checkbutton(r_o_t, text="升级 S100", variable=self.ota_s100_v, bg="#e8f4f8").pack(side=tk.LEFT)
        tk.Checkbutton(r_o_t, text="升级 X5", variable=self.ota_x5_v, bg="#e8f4f8", padx=15).pack(side=tk.LEFT)
        tk.Checkbutton(r_o_t, text="Tmux 后台", variable=self.use_tmux, bg="#e8f4f8").pack(side=tk.LEFT, padx=15)
        tk.Button(r_o_t, text="📂 扫描填充包", command=self._smart_scan).pack(side=tk.RIGHT)
        self.ota_paths = {}
        for l, p in PKG_RULES.items():
            r = tk.Frame(f_ota, bg="#e8f4f8"); r.pack(fill=tk.X, pady=1)
            tk.Label(r, text=f"{l}:", width=12, anchor="e", bg="#e8f4f8").pack(side=tk.LEFT)
            ent = tk.Entry(r, bg="white"); ent.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
            tk.Button(r, text="选择", command=lambda e=ent, p=p: self._browse_ota(e, p)).pack(side=tk.RIGHT)
            self.ota_paths[l] = ent
        
        # 将原直接调用 _start("ota") 改为调用前置校验方法
        self.ota_btn = tk.Button(f_ota, text="🚀 执行 OTA 升级", bg="#007aff", font=("Arial", 10, "bold"), command=self._pre_start_ota)
        self.ota_btn.pack(pady=5)

        f_sync = tk.LabelFrame(container, text=" 3. 快速文件同步 ", bg="#eef9f0", padx=10, pady=5)
        f_sync.pack(fill=tk.X, pady=5)
        cv_f = tk.Frame(f_sync, bg="white")
        cv_f.pack(fill=tk.X)
        # 增大canvas宽度，防止内容被裁剪
        canvas_width = 1200
        self.canvas = tk.Canvas(cv_f, bg="white", height=150, highlightthickness=0, width=canvas_width)
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
        tk.Button(f_config_ctrl, text="清理日志框", command=lambda: self.log_area.delete(1.0, tk.END), width=12).pack(side=tk.RIGHT)
        tk.Label(f_config_ctrl, text="配置自动保存在 ~/.ota_deploy_config.json", bg="#eeeeee", fg="gray").pack(side=tk.RIGHT, padx=10)

        tk.Label(container, text="执行日志:", bg=self.bg).pack(anchor="w", pady=(5,0))
        self.log_area = scrolledtext.ScrolledText(container, height=12, bg="#1e1e1e", fg="#00ff00", font=("Menlo", 11))
        self.log_area.pack(fill=tk.BOTH, expand=True, pady=(0, 5))

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

    def _pre_start_ota(self):
        """OTA执行前的校验逻辑"""
        cfg = self._get_ui_cfg()
        if not (cfg["ota_target_s100"] or cfg["ota_target_x5"]):
            return messagebox.showwarning("提示", "未选择任何 OTA 升级目标。")
        
        if cfg["ota_target_s100"] and not cfg["s100_app_path"]:
            return messagebox.showwarning("提示", "已勾选 S100，但未选择 S100 APP 升级包。")
            
        if cfg["ota_target_x5"] and not cfg["x5_app_path"]:
            return messagebox.showwarning("提示", "已勾选 X5，但未选择 X5 APP 升级包。")

        # 弹出 SN 输入窗口
        dialog = SNDialog(self.root, initial_sn=self.last_sn)
        
        if dialog.result == "cancel" or dialog.result is None:
            return  # 用户取消操作
            
        if dialog.result == "skip":
            self._start("ota")
            return
            
        if dialog.result == "confirm":
            sn = dialog.sn_value
            self.last_sn = sn # 缓存本次输入的SN
            
            # 1. 校验 SN 格式 (19位，仅字母和数字)
            if not re.match(r'^[A-Za-z0-9]{19}$', sn):
                messagebox.showerror("校验失败", "SN 格式错误：必须是精确的 19 位字符，且只能包含字母和数字。")
                return
                
            # 2. 判断对应版本特征字符
            required_keyword = None
            if "8010001" in sn or "8010002" in sn:
                required_keyword = "edu"
            elif "8010003" in sn or "8010004" in sn:
                required_keyword = "pro"
            elif "8010005" in sn or "8010006" in sn:
                required_keyword = "max"
                
            # 3. 校验 APP 包名
            if required_keyword:
                errors = []
                if cfg["ota_target_s100"]:
                    s100_app = os.path.basename(cfg["s100_app_path"]).lower()
                    if required_keyword not in s100_app:
                        errors.append(f"S100 APP ({s100_app}) 未包含特征字 '{required_keyword}'")
                
                if cfg["ota_target_x5"]:
                    x5_app = os.path.basename(cfg["x5_app_path"]).lower()
                    if required_keyword not in x5_app:
                        errors.append(f"X5 APP ({x5_app}) 未包含特征字 '{required_keyword}'")
                        
                if errors:
                    err_msg = "\n".join(errors)
                    messagebox.showerror("校验失败", f"该 SN 对应需要【{required_keyword.upper()}】版本的 APP 包，但检查不匹配：\n\n{err_msg}")
                    return
            
            # 校验全部通过，执行后续
            self._start("ota")

    def _start(self, mode):
        cfg = self._get_ui_cfg()
        if mode == "sync":
            valid = [i for i in cfg["sync_items"] if i["src"].strip() and (i["s100"] or i["x5"])]
            if not valid: return messagebox.showwarning("提示", "同步列表为空或未选目标。")
        
        save_config(cfg)
        self.log_area.delete(1.0, tk.END)
        self.ota_btn.config(state=tk.DISABLED); self.sync_btn.config(state=tk.DISABLED)
        threading.Thread(target=lambda: [DeployExecutor(cfg, self._log)._run_task(mode), self.root.after(0, lambda: [self.ota_btn.config(state=tk.NORMAL), self.sync_btn.config(state=tk.NORMAL)])], daemon=True).start()

    def _get_ui_cfg(self):
        sync_items = [{
            "src": r["src"].get(),
            "dst": r["dst"].get(),
            "s100": r["s100"].get(),
            "x5": r["x5"].get(),
            "executable": r["executable"].get()
        } for r in self.sync_rows]
        return {
            "s100_ip": self.s100_ip.get(), "x5_ip": self.x5_ip.get(), "username": "root", "password": "root",
            "ota_dir": self.cfg["ota_dir"], "connect_timeout": 5, "use_identity_file": self.use_key.get(),
            "identity_file": self.key_path.get(), "ota_target_s100": self.ota_s100_v.get(), "ota_target_x5": self.ota_x5_v.get(),
            "s100_app_path": self.ota_paths["S100 APP"].get(), "s100_sys_path": self.ota_paths["S100 SYS"].get(),
            "x5_app_path": self.ota_paths["X5 APP"].get(), "x5_sys_path": self.ota_paths["X5 SYS"].get(),
            "use_tmux": self.use_tmux.get(), "sync_items": sync_items,
            "zenoh_client_script": self.zenoh_script_path.get().strip(),
            "zenoh_enforce_hash_check": self.zenoh_enforce_hash.get(),
        }

    def _labeled_entry(self, p, t, w, padx=0):
        tk.Label(p, text=t, bg=self.bg).pack(side=tk.LEFT, padx=(padx,0))
        e = tk.Entry(p, width=w, bg="white"); e.pack(side=tk.LEFT, padx=5); return e
    def _log(self, msg):
        def _append(): self.log_area.insert(tk.END, f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n"); self.log_area.see(tk.END)
        self.root.after(0, _append)
    def _save_all(self): save_config(self._get_ui_cfg()); messagebox.showinfo("OK", "配置已成功保存")
    def _clear_cfg(self):
        if messagebox.askyesno("?", "确定要重置所有配置吗？"):
            if os.path.exists(CONFIG_FILE): os.remove(CONFIG_FILE)
            self.cfg = dict(DEFAULT_CONFIG); self._load_fields()
    def _browse_ota(self, e, p):
        f = filedialog.askopenfilename()
        if f and fnmatch.fnmatch(os.path.basename(f).lower(), p.lower()): e.delete(0, tk.END); e.insert(0, f)
        elif f: messagebox.showerror("错误", "文件名不匹配")
    def _smart_scan(self):
        d = filedialog.askdirectory()
        if d:
            for l, p in PKG_RULES.items():
                ms = [os.path.join(d, f) for f in os.listdir(d) if fnmatch.fnmatch(f.lower(), p.lower())]
                if ms: self.ota_paths[l].delete(0, tk.END); self.ota_paths[l].insert(0, max(ms, key=os.path.getmtime))
    def _on_key_toggle(self): self.key_path.config(state=tk.NORMAL if self.use_key.get() else tk.DISABLED)
    def _browse_key(self):
        f = filedialog.askopenfilename()
        if f: self.key_path.delete(0, tk.END); self.key_path.insert(0, f)

    def _browse_zenoh_script(self):
        f = filedialog.askopenfilename(filetypes=[("Python", "*.py"), ("所有文件", "*.*")])
        if f:
            self.zenoh_script_path.delete(0, tk.END)
            self.zenoh_script_path.insert(0, f)

    def _run_zenoh_client_script(self):
        path = self.zenoh_script_path.get().strip()
        if not path or not os.path.isfile(path):
            messagebox.showerror("错误", "请先选择有效的 set_zenoh_mode_client.py 文件。")
            return
        cfg = self._get_ui_cfg()
        save_config(cfg)

        def work():
            cmd = [
                sys.executable,
                os.path.abspath(path),
                "--s100-host",
                cfg["s100_ip"].strip(),
                "--x5-host",
                cfg["x5_ip"].strip(),
            ]
            if cfg.get("use_identity_file") and (cfg.get("identity_file") or "").strip():
                keyf = cfg["identity_file"].strip()
                if os.path.isfile(keyf):
                    cmd.extend(["--key", os.path.abspath(keyf)])
            if not cfg.get("zenoh_enforce_hash_check"):
                cmd.append("--skip-hash-check")
            self._log(">>> Zenoh 脚本: " + " ".join(shlex.quote(c) for c in cmd))
            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=900,
                )
                if proc.stdout:
                    for line in proc.stdout.splitlines():
                        self._log(line)
                if proc.stderr:
                    for line in proc.stderr.splitlines():
                        self._log("[stderr] " + line)
                if proc.returncode == 0:
                    self._log(">>> Zenoh 脚本执行完成 (exit 0)")
                    self.root.after(0, lambda: messagebox.showinfo("完成", "Zenoh 脚本已执行完成。"))
                else:
                    self._log(f">>> Zenoh 脚本退出码: {proc.returncode}")
                    self.root.after(
                        0,
                        lambda c=proc.returncode: messagebox.showerror("失败", f"脚本退出码 {c}，请查看日志。"),
                    )
            except subprocess.TimeoutExpired:
                self._log(">>> Zenoh 脚本超时（>900s）")
                self.root.after(0, lambda: messagebox.showerror("超时", "脚本执行超时。"))
            except Exception as e:
                self._log(f">>> Zenoh 脚本异常: {e}")
                self.root.after(0, lambda err=str(e): messagebox.showerror("错误", err))

        threading.Thread(target=work, daemon=True).start()
    def _browse_sync_file(self, v):
        f = filedialog.askopenfilename()
        if f: v.set(f)

    def _load_fields(self):
        for e in [self.s100_ip, self.x5_ip, self.key_path]: e.delete(0, tk.END)
        self.s100_ip.insert(0, self.cfg.get("s100_ip", "")); self.x5_ip.insert(0, self.cfg.get("x5_ip", ""))
        self.use_key.set(self.cfg.get("use_identity_file", False)); self.key_path.insert(0, self.cfg.get("identity_file", ""))
        self.ota_s100_v.set(self.cfg.get("ota_target_s100", True)); self.ota_x5_v.set(self.cfg.get("ota_target_x5", True))
        for l, e in self.ota_paths.items(): e.delete(0, tk.END); e.insert(0, self.cfg.get(l.lower().replace(" ","_")+"_path", ""))
        self.use_tmux.set(self.cfg.get("use_tmux", True))
        self.zenoh_script_path.delete(0, tk.END)
        self.zenoh_script_path.insert(0, self.cfg.get("zenoh_client_script", ""))
        self.zenoh_enforce_hash.set(self.cfg.get("zenoh_enforce_hash_check", False))
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

if __name__ == "__main__":
    root = tk.Tk()
    if sys.platform == "darwin": root.tk.call('tk', 'scaling', 2.0)
    OTADeployGUI(root)
    root.mainloop()