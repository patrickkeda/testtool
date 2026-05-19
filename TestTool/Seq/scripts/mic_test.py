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


def _load_pkey(path: str):
    import paramiko

    expanded = str(Path(path).expanduser())
    errs: list[str] = []
    for cls in (paramiko.Ed25519Key, paramiko.RSAKey, paramiko.ECDSAKey):
        try:
            return cls.from_private_key_file(expanded)
        except Exception as e:  # noqa: BLE001
            errs.append(f"{cls.__name__}: {e}")
    raise ValueError("无法解析私钥文件: " + "; ".join(errs))


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
    import paramiko

    pkey = _load_pkey(private_key_file)
    policy = paramiko.AutoAddPolicy()
    jump_client = paramiko.SSHClient()
    target_client = paramiko.SSHClient()
    jump_client.set_missing_host_key_policy(policy)
    target_client.set_missing_host_key_policy(policy)

    try:
        jump_client.connect(
            hostname=jump_host,
            port=jump_port,
            username=username,
            pkey=pkey,
            timeout=connect_timeout,
            allow_agent=False,
            look_for_keys=False,
        )
        jump_transport = jump_client.get_transport()
        if jump_transport is None:
            print("跳板 Transport 不可用", file=sys.stderr)
            return False

        channel = jump_transport.open_channel(
            "direct-tcpip",
            dest_addr=(target_host, target_port),
            src_addr=("127.0.0.1", 0),
        )
        target_client.connect(
            hostname=target_host,
            port=target_port,
            username=username,
            pkey=pkey,
            sock=channel,
            timeout=connect_timeout,
            allow_agent=False,
            look_for_keys=False,
        )

        stdin, stdout, stderr = target_client.exec_command(command, timeout=exec_timeout)
        _ = stdin
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        combined = out + err
        full_output = combined.strip()

        if "Recording WAVE" in combined:
            print("✅ [状态: 正常] X5 录音命令执行成功！")
            if full_output:
                print("设备返回信息:\n" + full_output)
            return True

        if "audio open error" in full_output or "No such file or directory" in full_output:
            print("❌ [状态: 异常] X5 找不到声卡或打开音频设备失败！", file=sys.stderr)
            if full_output:
                print(full_output, file=sys.stderr)
            return False

        print("⚠️ [状态: 未知] 出现未预期的输出！", file=sys.stderr)
        if full_output:
            print(full_output, file=sys.stderr)
        return False

    except paramiko.AuthenticationException:
        print("❌ 认证失败，请检查私钥。", file=sys.stderr)
        return False
    except Exception as e:  # noqa: BLE001
        print(f"❌ 运行过程中发生错误: {e}", file=sys.stderr)
        return False
    finally:
        target_client.close()
        jump_client.close()


def main(argv: list[str] | None = None) -> int:
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
