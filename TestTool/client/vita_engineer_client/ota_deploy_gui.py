#!/usr/bin/env python3
import os
import sys
import json
import threading
import fnmatch
import shlex
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
    "S100 SYS": "all_in_one-v2*.zip",
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
    "sync_items": [] 
}

CONFIG_FILE = os.path.expanduser("~/.ota_deploy_config.json")

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
        # 必须先读完输出，再获取退出码，否则大输出时会死锁
        out = stdout.read().decode("utf-8", errors="replace").strip()
        err = stderr.read().decode("utf-8", errors="replace").strip()
        exit_code = stdout.channel.recv_exit_status()
        if log_fail and exit_code != 0 and err:
            self.log(f"[{label}] ⚠️ 命令失败 (exit {exit_code}): {err}")
        return exit_code, out, err

    def _start_tmux_session(self, ssh, session_name, inner_cmd, label):
        """安全启动 tmux 会话并校验是否成功。"""
        # 清理同名旧会话，避免 name 冲突
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
        """构建 S100 侧 ssh 到 X5 的认证参数；必要时下发临时私钥。"""
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

    def _do_sync_work(self, s100_ssh, x5_ssh):
        items = self.cfg.get("sync_items", [])
        total = sum(1 for item in items if item.get("src") and item.get("dst") and os.path.exists(item.get("src", "")) and (item.get("s100") or item.get("x5")))
        done = 0
        for item in items:
            src, dst = item.get("src"), item.get("dst")
            if not (src and dst and os.path.exists(src)): continue
            file_size = os.path.getsize(src)
            size_str = f"{file_size / 1024 / 1024:.1f}MB" if file_size > 1024 * 1024 else f"{file_size / 1024:.1f}KB"
            fname = os.path.basename(src)

            if item.get("s100") and s100_ssh:
                try:
                    rc, _, err = self._exec_and_check(s100_ssh, "mount -o remount,rw /app", "S100 Sync")
                    if rc != 0:
                        self.log(f"[S100 Sync] ⚠️ mount 失败: {err}")
                    self.log(f"[S100 Sync] 上传 {fname} ({size_str}) → {dst}")
                    s100_ssh.upload_file(src, dst, progress_cb=self._make_progress_cb(f"S100 Sync", fname, file_size))
                    # 验证远端文件
                    remote_path = dst + os.path.basename(src) if dst.endswith('/') else dst
                    rc, out, _ = self._exec_and_check(s100_ssh, f"stat '{remote_path}' 2>&1", "S100 Sync")
                    if rc == 0:
                        self.log(f"[S100 Sync] ✅ {fname} 同步成功")
                    else:
                        self.log(f"[S100 Sync] ❌ {fname} 同步失败: {out}")
                except Exception as e:
                    self.log(f"[S100 Sync] ❌ {fname} 同步异常: {e}")

            if item.get("x5") and x5_ssh:
                try:
                    rc, _, err = self._exec_and_check(x5_ssh, "mount -o remount,rw /app", "X5 Sync")
                    if rc != 0:
                        self.log(f"[X5 Sync] ⚠️ mount /app 失败: {err}")
                    rc, _, err = self._exec_and_check(x5_ssh, "mount -o remount,rw /usr/hobot", "X5 Sync")
                    if rc != 0:
                        self.log(f"[X5 Sync] ⚠️ mount /usr/hobot 失败: {err}")
                    self.log(f"[X5 Sync] 上传 {fname} ({size_str}) → {dst}")
                    x5_ssh.upload_file(src, dst, progress_cb=self._make_progress_cb(f"X5 Sync", fname, file_size))
                    remote_path = dst + os.path.basename(src) if dst.endswith('/') else dst
                    rc, out, _ = self._exec_and_check(x5_ssh, f"stat '{remote_path}' 2>&1", "X5 Sync")
                    if rc == 0:
                        self.log(f"[X5 Sync] ✅ {fname} 同步成功")
                    else:
                        self.log(f"[X5 Sync] ❌ {fname} 同步失败: {out}")
                except Exception as e:
                    self.log(f"[X5 Sync] ❌ {fname} 同步异常: {e}")

            done += 1
            self.log(f"--- 同步进度: {done}/{total} ---")

    def _make_progress_cb(self, label, filename, total_size):
        """返回一个 sftp.put 进度回调，每 10% 打印一次"""
        last_pct = [-1]  # mutable container for closure
        def _cb(transferred, total):
            if total == 0: return
            pct = int(transferred * 100 / total)
            # 每 10% 报告一次，以及 100% 时报告
            step = (pct // 10) * 10
            if step > last_pct[0]:
                last_pct[0] = step
                t_mb = transferred / 1024 / 1024
                total_mb = total / 1024 / 1024
                self.log(f"[{label}] 📦 {filename}: {t_mb:.1f}/{total_mb:.1f}MB ({pct}%)")
        return _cb

    def _do_ota_work(self, s100_ssh, x5_ssh):
        targets = [("S100", s100_ssh, self.cfg.get("ota_target_s100")), ("X5", x5_ssh, self.cfg.get("ota_target_x5"))]
        # 筛选出有效的目标
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

        # 上传阶段（串行，因为 X5 通过 S100 隧道，带宽共享）
        for label, ssh, app_p, sys_p in valid_targets:
            ota_dir = self.cfg["ota_dir"]
            self.log(f"[{label} OTA] 上传升级包...")
            _, mk_out, _ = ssh.client.exec_command(f"mount -o remount,rw /app && mkdir -p {ota_dir} && rm -rf {ota_dir}/*")
            mk_out.channel.recv_exit_status()  # 等待目录准备完成
            sftp = ssh.client.open_sftp()
            app_name = os.path.basename(app_p)
            sys_name = os.path.basename(sys_p)
            sftp.put(app_p, f"{ota_dir}/{app_name}", callback=self._make_progress_cb(f"{label} OTA", app_name, os.path.getsize(app_p)))
            sftp.put(sys_p, f"{ota_dir}/{sys_name}", callback=self._make_progress_cb(f"{label} OTA", sys_name, os.path.getsize(sys_p)))
            sftp.close()
            self.log(f"[{label} OTA] 上传完成。")

        # 执行阶段
        if self.cfg["use_tmux"]:
            # 先确认每个目标都具备 tmux，避免提交后无会话
            for label, ssh, _, _ in valid_targets:
                rc, _, _ = self._exec_and_check(ssh, "command -v tmux >/dev/null 2>&1", f"{label} OTA", log_fail=False)
                if rc != 0:
                    raise RuntimeError(f"[{label} OTA] 目标设备未安装 tmux，请安装 tmux 或关闭『Tmux 后台』后重试")

            light_green_cmd = (
                "source /app/script/env.sh && "
                "ros2 service call /light_node/control peripheral_msgs/srv/LightControl "
                "\"{target_state: 1, pre_check: false, mode: 3, red: 0, green: 255, blue: 0, brightness: 255, speed: 1.0, duration_ms: 0}\""
            )
            light_red_cmd = (
                "source /app/script/env.sh && "
                "ros2 service call /light_node/control peripheral_msgs/srv/LightControl "
                "\"{target_state: 1, pre_check: false, mode: 3, red: 255, green: 0, blue: 0, brightness: 255, speed: 1.0, duration_ms: 0}\""
            )

            target_map = {label: (ssh, app_p, sys_p) for label, ssh, app_p, sys_p in valid_targets}

            if "S100" in target_map and "X5" in target_map:
                # 1) 先启动 X5：仅执行 OTA 并写结果
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
                x5_inner_cmd = (
                    f"{x5_ota_cmd} > '{x5_log_file}' 2>&1; "
                    f"x5_rc=$?; "
                    f"echo $x5_rc > '{x5_result_file}'; "
                    f"echo x5_rc=$x5_rc >> '{x5_log_file}'; "
                    f"rm -rf {self.cfg['ota_dir']}/*; "
                    f"echo tmux_done_x5_rc=$x5_rc >> '{x5_log_file}'"
                )
                self._start_tmux_session(x5_ssh, x5_session, x5_inner_cmd, "X5 OTA")
                self.log(f"[X5 OTA] 已在 tmux 后台启动 (session: {x5_session})")
                self.log(f"[X5 OTA] 可后续查询结果文件: {x5_result_file}")
                self.log(f"[X5 OTA] 可后续查询日志文件: {x5_log_file}")

                # 2) 启动 S100：执行自身 OTA，并通过 SSH 读取 X5 结果后统一控灯
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
                s100_inner_cmd = (
                    f"{s100_ota_cmd} > '{s100_log_file}' 2>&1; "
                    f"s100_rc=$?; "
                    f"echo $s100_rc > '{s100_result_file}'; "
                    f"echo s100_rc=$s100_rc >> '{s100_log_file}'; "
                    f"x5_rc=125; "
                    f"x5_fetch_status=timeout; "
                    f"for i in $(seq 1 7200); do "
                    f"x5_val=$({x5_fetch_cmd}); "
                    f"if [ -n \"$x5_val\" ]; then x5_rc=$x5_val; x5_fetch_status=ok; break; fi; "
                    f"sleep 1; "
                    f"done; "
                    f"echo s100_rc=$s100_rc > '{merge_detail_file}'; "
                    f"echo x5_rc=$x5_rc >> '{merge_detail_file}'; "
                    f"echo x5_fetch_status=$x5_fetch_status >> '{merge_detail_file}'; "
                    f"if [ \"$s100_rc\" = \"0\" ] && [ \"$x5_rc\" = \"0\" ]; then "
                    f"echo light=green >> '{merge_detail_file}'; "
                    f"{light_green_cmd}; "
                    f"else "
                    f"echo light=red >> '{merge_detail_file}'; "
                    f"{light_red_cmd}; "
                    f"fi; "
                    f"{cleanup_key_cmd}"
                    f"rm -rf {self.cfg['ota_dir']}/*; "
                    f"echo tmux_done_s100_rc=$s100_rc >> '{s100_log_file}'"
                )
                self._start_tmux_session(s100_ssh, s100_session, s100_inner_cmd, "S100 OTA")
                self.log(f"[S100 OTA] 已在 tmux 后台启动 (session: {s100_session})")
                self.log(f"[S100 OTA] 可后续查询结果文件: {s100_result_file}")
                self.log(f"[S100 OTA] 可后续查询日志文件: {s100_log_file}")
                self.log(f"[S100 OTA] 可后续查询汇总详情: {merge_detail_file}")
                self.log("[S100 OTA] 将负责汇总 S100+X5 结果并触发灯光提示")

            else:
                # 仅单平台升级：由该平台自检并控灯
                label, ssh, app_p, sys_p = valid_targets[0]
                ota_dir = self.cfg["ota_dir"]
                cmd = f"cd {ota_dir} && /usr/hobot/bin/ota_tool -n -p {os.path.basename(app_p)} -p {os.path.basename(sys_p)}"
                session_name = f"ota_{label.lower()}"
                result_file = f"/tmp/{session_name}.result"
                log_file = f"/tmp/{session_name}.log"
                self._exec_and_check(ssh, f"rm -f '{result_file}'", f"{label} OTA", log_fail=False)
                self._exec_and_check(ssh, f"rm -f '{log_file}'", f"{label} OTA", log_fail=False)
                tmux_inner_cmd = (
                    f"{cmd} > '{log_file}' 2>&1; "
                    f"ota_rc=$?; "
                    f"echo $ota_rc > '{result_file}'; "
                    f"echo ota_rc=$ota_rc >> '{log_file}'; "
                    f"if [ \"$ota_rc\" = \"0\" ]; then {light_green_cmd}; else {light_red_cmd}; fi; "
                    f"rm -rf {ota_dir}/*; "
                    f"echo tmux_done_ota_rc=$ota_rc >> '{log_file}'"
                )
                self._start_tmux_session(ssh, session_name, tmux_inner_cmd, f"{label} OTA")
                self.log(f"[{label} OTA] 已在 tmux 后台启动 (session: {session_name})")
                self.log(f"[{label} OTA] 可后续查询结果文件: {result_file}")
                self.log(f"[{label} OTA] 可后续查询日志文件: {log_file}")

            self.log("✅ tmux 任务已全部提交，当前连接可断开，不影响后台升级。")
            self.log("ℹ️ 后续可 SSH 登录执行: tmux ls / tmux attach -t ota_s100|ota_x5 / cat /tmp/ota_*.result")
            return
        else:
            # 非 Tmux 模式：并行执行，实时显示输出
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
        """在独立线程中执行 OTA 并实时读取输出"""
        ota_dir = self.cfg["ota_dir"]
        cmd = f"cd {ota_dir} && /usr/hobot/bin/ota_tool -n -p {os.path.basename(app_p)} -p {os.path.basename(sys_p)}"
        try:
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
                ssh.client.exec_command(f"rm -rf {ota_dir}/*")
                self.log(f"[{label} OTA] 设备即将重启...")
                ssh.client.exec_command("reboot")
            else:
                self.log(f"[{label} OTA] ❌ 升级失败 (exit code: {exit_code})")
        except Exception as e:
            self.log(f"[{label} OTA] ❌ 执行异常: {e}")

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
        
        self._build_ui()
        self._load_fields()

    def _build_ui(self):
        # 使用一个主容器承载所有内容
        container = tk.Frame(self.root, bg=self.bg, padx=15, pady=5)
        container.pack(fill=tk.BOTH, expand=True)

        # --- 1. SSH 配置 ---
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

        # --- 2. OTA 功能 ---
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
        self.ota_btn = tk.Button(f_ota, text="🚀 执行 OTA 升级", bg="#007aff", font=("Arial", 10, "bold"), command=lambda: self._start("ota"))
        self.ota_btn.pack(pady=5)

        # --- 3. 同步功能 ---
        f_sync = tk.LabelFrame(container, text=" 3. 快速文件同步 ", bg="#eef9f0", padx=10, pady=5)
        f_sync.pack(fill=tk.X, pady=5)
        cv_f = tk.Frame(f_sync, bg="white")
        cv_f.pack(fill=tk.X)
        self.canvas = tk.Canvas(cv_f, bg="white", height=150, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(cv_f, orient="vertical", command=self.canvas.yview)
        self.scroll_f = tk.Frame(self.canvas, bg="white")
        self.scroll_f.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0, 0), window=self.scroll_f, anchor="nw", width=1000)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        rsb = tk.Frame(f_sync, bg="#eef9f0", pady=5); rsb.pack(fill=tk.X)
        tk.Button(rsb, text="➕ 增加同步项", command=self.add_sync_row, fg="green").pack(side=tk.LEFT)
        self.sync_btn = tk.Button(rsb, text="📁 执行文件同步", bg="#34c759", font=("Arial", 10, "bold"), command=lambda: self._start("sync"))
        self.sync_btn.pack(side=tk.RIGHT)

        # --- 4. 配置管理工具栏 (放在日志上方) ---
        f_config_ctrl = tk.Frame(container, bg="#eeeeee", padx=10, pady=8)
        f_config_ctrl.pack(fill=tk.X, pady=(10, 0))
        
        tk.Button(f_config_ctrl, text="💾 保存当前配置", command=self._save_all, width=15).pack(side=tk.LEFT)
        tk.Button(f_config_ctrl, text="🗑️ 重置所有配置", command=self._clear_cfg, fg="red", width=15).pack(side=tk.LEFT, padx=15)
        tk.Button(f_config_ctrl, text="清理日志框", command=lambda: self.log_area.delete(1.0, tk.END), width=12).pack(side=tk.RIGHT)
        tk.Label(f_config_ctrl, text="配置自动保存在 ~/.ota_deploy_config.json", bg="#eeeeee", fg="gray").pack(side=tk.RIGHT, padx=10)

        # --- 5. 日志区域 ---
        tk.Label(container, text="执行日志:", bg=self.bg).pack(anchor="w", pady=(5,0))
        self.log_area = scrolledtext.ScrolledText(container, height=12, bg="#1e1e1e", fg="#00ff00", font=("Menlo", 11))
        self.log_area.pack(fill=tk.BOTH, expand=True, pady=(0, 5))

    def add_sync_row(self, src="", dst="", s100=True, x5=False):
        f = tk.Frame(self.scroll_f, bg="white", pady=2)
        f.pack(fill=tk.X)
        sv, dv = tk.StringVar(value=src), tk.StringVar(value=dst)
        s100v, x5v = tk.BooleanVar(value=s100), tk.BooleanVar(value=x5)
        tk.Entry(f, textvariable=sv, width=40).pack(side=tk.LEFT, padx=2)
        tk.Button(f, text="..", width=2, command=lambda: self._browse_sync_file(sv)).pack(side=tk.LEFT)
        tk.Label(f, text="➔", bg="white").pack(side=tk.LEFT, padx=5)
        tk.Entry(f, textvariable=dv, width=40).pack(side=tk.LEFT, padx=2)
        tk.Checkbutton(f, text="S100", variable=s100v, bg="white").pack(side=tk.LEFT, padx=2)
        tk.Checkbutton(f, text="X5", variable=x5v, bg="white").pack(side=tk.LEFT, padx=2)
        obj = {"frame": f, "src": sv, "dst": dv, "s100": s100v, "x5": x5v}
        tk.Button(f, text="✖", fg="red", command=lambda: [f.destroy(), self.sync_rows.remove(obj)]).pack(side=tk.RIGHT, padx=5)
        self.sync_rows.append(obj)

    def _start(self, mode):
        cfg = self._get_ui_cfg()
        if mode == "sync":
            valid = [i for i in cfg["sync_items"] if i["src"].strip() and (i["s100"] or i["x5"])]
            if not valid: return messagebox.showwarning("提示", "同步列表为空或未选目标。")
        elif mode == "ota" and not (cfg["ota_target_s100"] or cfg["ota_target_x5"]):
            return messagebox.showwarning("提示", "未选择 OTA 目标。")
        
        save_config(cfg)
        self.log_area.delete(1.0, tk.END)
        self.ota_btn.config(state=tk.DISABLED); self.sync_btn.config(state=tk.DISABLED)
        threading.Thread(target=lambda: [DeployExecutor(cfg, self._log)._run_task(mode), self.root.after(0, lambda: [self.ota_btn.config(state=tk.NORMAL), self.sync_btn.config(state=tk.NORMAL)])], daemon=True).start()

    def _get_ui_cfg(self):
        sync_items = [{"src": r["src"].get(), "dst": r["dst"].get(), "s100": r["s100"].get(), "x5": r["x5"].get()} for r in self.sync_rows]
        return {
            "s100_ip": self.s100_ip.get(), "x5_ip": self.x5_ip.get(), "username": "root", "password": "root",
            "ota_dir": self.cfg["ota_dir"], "connect_timeout": 5, "use_identity_file": self.use_key.get(),
            "identity_file": self.key_path.get(), "ota_target_s100": self.ota_s100_v.get(), "ota_target_x5": self.ota_x5_v.get(),
            "s100_app_path": self.ota_paths["S100 APP"].get(), "s100_sys_path": self.ota_paths["S100 SYS"].get(),
            "x5_app_path": self.ota_paths["X5 APP"].get(), "x5_sys_path": self.ota_paths["X5 SYS"].get(),
            "use_tmux": self.use_tmux.get(), "sync_items": sync_items
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
    def _browse_sync_file(self, v):
        f = filedialog.askopenfilename()
        if f: v.set(f)

    def _load_fields(self):
        # 清空
        for e in [self.s100_ip, self.x5_ip, self.key_path]: e.delete(0, tk.END)
        self.s100_ip.insert(0, self.cfg.get("s100_ip", "")); self.x5_ip.insert(0, self.cfg.get("x5_ip", ""))
        self.use_key.set(self.cfg.get("use_identity_file", False)); self.key_path.insert(0, self.cfg.get("identity_file", ""))
        self.ota_s100_v.set(self.cfg.get("ota_target_s100", True)); self.ota_x5_v.set(self.cfg.get("ota_target_x5", True))
        for l, e in self.ota_paths.items(): e.delete(0, tk.END); e.insert(0, self.cfg.get(l.lower().replace(" ","_")+"_path", ""))
        self.use_tmux.set(self.cfg.get("use_tmux", True))
        for r in self.sync_rows: r["frame"].destroy()
        self.sync_rows = []
        for item in self.cfg.get("sync_items", []): self.add_sync_row(item["src"], item["dst"], item["s100"], item["x5"])
        if not self.sync_rows: self.add_sync_row()
        self._on_key_toggle()

if __name__ == "__main__":
    root = tk.Tk()
    if sys.platform == "darwin": root.tk.call('tk', 'scaling', 2.0)
    OTADeployGUI(root)
    root.mainloop()