#!/usr/bin/env python3
"""
X5 8 路录音：经跳板 SSH 在目标机执行 arecord（与产线 case.mic_record_ssh 拓扑一致）。

私钥仅从文件读取，禁止写入仓库或 YAML。本机命令行示例：

  python Seq/scripts/mic_test.py --jump-host 192.168.126.2 --target-host 192.168.127.10 \\
      --user root --private-key-file ~/.ssh/id_ed25519

TestTool 序列中由 utility.run_python_script 调用，私钥路径可用「配置 → 测试站 → 私钥配置」注入的
``${ssh_private_key_path}`` 展开。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 与本目录 jump_ssh 同仓；打包后由 runpy 加载本脚本
sys.path.insert(0, str(Path(__file__).resolve().parent))
from jump_ssh import JumpSSHSession  # noqa: E402


def _ensure_utf8_stdio() -> None:
    """打包子进程在中文 Windows 上常为 gbk，打印非 GBK 字符会 UnicodeEncodeError。"""
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None:
            continue
        try:
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _detach_console_when_stdio_piped() -> None:
    """被 TestTool 以管道重定向启动时，脱离 Windows 控制台，减少闪窗/无关控制台弹层。"""
    if sys.platform != "win32":
        return
    try:
        out = getattr(sys, "__stdout__", None) or sys.stdout
        if out is not None and hasattr(out, "isatty") and not out.isatty():
            import ctypes

            ctypes.windll.kernel32.FreeConsole()
    except Exception:
        pass


def check_x5_audio_record(
    *,
    jump_host: str,
    target_host: str,
    username: str,
    private_key_file: str,
    command: str,
    jump_port: int = 22,
    target_port: int = 22,
    connect_timeout: int = 60,
    exec_timeout: int = 90,
) -> bool:
    try:
        with JumpSSHSession.connect(
            jump_host=jump_host,
            target_host=target_host,
            username=username,
            private_key_file=private_key_file,
            jump_port=jump_port,
            target_port=target_port,
            connect_timeout=connect_timeout,
        ) as sess:
            rc, full_output = sess.exec(command, exec_timeout=exec_timeout)
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        if "Authentication" in type(e).__name__ or "认证" in msg:
            print("[FAIL] 认证失败，请检查私钥。", file=sys.stderr)
        else:
            print(f"[FAIL] 运行过程中发生错误: {e}", file=sys.stderr)
        return False

    combined = full_output or ""
    has_wave = "Recording WAVE" in combined
    device_err = (
        "audio open error" in combined or "No such file or directory" in combined
    )

    if has_wave and rc == 0:
        print("[OK] [状态: 正常] X5 录音命令执行成功！")
        if combined.strip():
            print("设备返回信息:\n" + combined.strip())
        return True

    if has_wave and rc != 0:
        print(
            f"[FAIL] [状态: 异常] 出现 Recording WAVE 但退出码非 0 (exit={rc})",
            file=sys.stderr,
        )
        if combined.strip():
            print(combined.strip(), file=sys.stderr)
        return False

    if device_err:
        print("[FAIL] [状态: 异常] X5 找不到声卡或打开音频设备失败！", file=sys.stderr)
        if combined.strip():
            print(combined.strip(), file=sys.stderr)
        return False

    print(
        f"[WARN] [状态: 未知] 出现未预期的输出！(exit={rc})",
        file=sys.stderr,
    )
    if combined.strip():
        print(combined.strip(), file=sys.stderr)
    return False


def main(argv: list[str] | None = None) -> int:
    _ensure_utf8_stdio()
    _detach_console_when_stdio_piped()
    ap = argparse.ArgumentParser(description="X5 arecord 经跳板 SSH（Paramiko）")
    ap.add_argument("--jump-host", required=True, help="跳板机 IP（如 S100）")
    ap.add_argument("--target-host", required=True, help="目标机 IP（如 X5）")
    ap.add_argument("--user", default="root", help="SSH 用户名")
    ap.add_argument(
        "--private-key-file",
        required=True,
        help="本机 OpenSSH 私钥文件路径",
    )
    ap.add_argument(
        "--command",
        default="arecord -D remap8ch -c 8 -r 16000 -f S16_LE -d 5 /tmp/test.wav",
        help="在目标机上执行的录音命令",
    )
    ap.add_argument("--jump-port", type=int, default=22)
    ap.add_argument("--target-port", type=int, default=22)
    ap.add_argument("--connect-timeout", type=int, default=60)
    ap.add_argument("--exec-timeout", type=int, default=90)
    ns = ap.parse_args(argv)

    ok = check_x5_audio_record(
        jump_host=ns.jump_host.strip(),
        target_host=ns.target_host.strip(),
        username=ns.user.strip(),
        private_key_file=ns.private_key_file.strip(),
        command=ns.command.strip(),
        jump_port=ns.jump_port,
        target_port=ns.target_port,
        connect_timeout=ns.connect_timeout,
        exec_timeout=ns.exec_timeout,
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
