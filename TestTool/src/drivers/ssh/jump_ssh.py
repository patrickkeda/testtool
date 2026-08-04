"""经跳板机（S100）连接目标（X5）的 Paramiko 会话。

产线拓扑：PC → jump_host:22 → direct-tcpip → target_host:22。
供 ``utility.ssh_exec`` / ``case.mic_record_ssh`` / Seq 脚本复用，避免多处复制隧道逻辑。
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any, Tuple


def load_pkey_from_file(path: str):
    import paramiko

    expanded = str(Path(path).expanduser())
    errs: list[str] = []
    for cls in (paramiko.Ed25519Key, paramiko.RSAKey, paramiko.ECDSAKey):
        try:
            return cls.from_private_key_file(expanded)
        except Exception as e:  # noqa: BLE001
            errs.append(f"{cls.__name__}: {e}")
    raise ValueError("无法解析私钥文件: " + "; ".join(errs))


def load_pkey_from_string(key_text: str):
    import paramiko

    buf = io.StringIO(key_text.strip())
    errs: list[str] = []
    for cls in (paramiko.Ed25519Key, paramiko.RSAKey, paramiko.ECDSAKey):
        try:
            buf.seek(0)
            return cls.from_private_key(buf)
        except Exception as e:  # noqa: BLE001
            errs.append(f"{cls.__name__}: {e}")
    raise ValueError("无法解析私钥字符串: " + "; ".join(errs))


class JumpSSHSession:
    """持有 jump + target 两个 SSHClient；``close()`` 时一并关闭。"""

    def __init__(self, jump_client: Any, target_client: Any) -> None:
        self.jump_client = jump_client
        self.target_client = target_client

    @classmethod
    def connect(
        cls,
        *,
        jump_host: str,
        target_host: str,
        username: str,
        private_key_file: str = "",
        pkey: Any = None,
        password: str = "",
        jump_port: int = 22,
        target_port: int = 22,
        connect_timeout: int = 60,
        strict_host_key: bool = False,
        allow_agent: bool = False,
        look_for_keys: bool = False,
    ) -> "JumpSSHSession":
        import paramiko

        if pkey is None and private_key_file:
            pkey = load_pkey_from_file(private_key_file)
        if pkey is None and not password and not allow_agent and not look_for_keys:
            raise ValueError("缺少 SSH 认证：请提供 private_key_file / pkey / password")

        policy: Any = (
            paramiko.RejectPolicy() if strict_host_key else paramiko.AutoAddPolicy()
        )
        jump_client = paramiko.SSHClient()
        target_client = paramiko.SSHClient()
        jump_client.set_missing_host_key_policy(policy)
        target_client.set_missing_host_key_policy(policy)

        base_kw: dict[str, Any] = {
            "username": username,
            "timeout": connect_timeout,
            "allow_agent": allow_agent,
            "look_for_keys": look_for_keys,
        }
        if pkey is not None:
            base_kw["pkey"] = pkey
        if password:
            base_kw["password"] = password

        try:
            jump_client.connect(
                hostname=jump_host,
                port=jump_port,
                **base_kw,
            )
            jump_transport = jump_client.get_transport()
            if jump_transport is None:
                raise RuntimeError("跳板 Transport 不可用")
            channel = jump_transport.open_channel(
                "direct-tcpip",
                dest_addr=(target_host, target_port),
                src_addr=("127.0.0.1", 0),
            )
            target_client.connect(
                hostname=target_host,
                port=target_port,
                sock=channel,
                **base_kw,
            )
        except Exception:
            try:
                target_client.close()
            except Exception:
                pass
            try:
                jump_client.close()
            except Exception:
                pass
            raise

        return cls(jump_client, target_client)

    def exec(self, command: str, exec_timeout: int = 120) -> Tuple[int, str]:
        stdin, stdout, stderr = self.target_client.exec_command(
            command, timeout=exec_timeout
        )
        _ = stdin
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        rc = int(stdout.channel.recv_exit_status())
        return rc, (out + err).strip()

    def sftp_put(self, local: Path, remote: str) -> None:
        sftp = self.target_client.open_sftp()
        try:
            remote_posix = str(Path(remote).as_posix())
            remote_dir = remote_posix.rsplit("/", 1)[0] if "/" in remote_posix else ""
            if remote_dir:
                try:
                    sftp.stat(remote_dir)
                except OSError:
                    try:
                        sftp.mkdir(remote_dir)
                    except OSError:
                        pass
            sftp.put(str(local), remote_posix)
        finally:
            sftp.close()

    def set_keepalive(self, keepalive_sec: int) -> None:
        if keepalive_sec <= 0:
            return
        t = self.target_client.get_transport()
        if t is not None:
            t.set_keepalive(keepalive_sec)

    def close(self) -> None:
        try:
            self.target_client.close()
        except Exception:
            pass
        try:
            self.jump_client.close()
        except Exception:
            pass

    def __enter__(self) -> "JumpSSHSession":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


def connect_direct(
    *,
    host: str,
    username: str,
    private_key_file: str = "",
    pkey: Any = None,
    password: str = "",
    port: int = 22,
    connect_timeout: int = 60,
    strict_host_key: bool = False,
    allow_agent: bool = False,
    look_for_keys: bool = False,
) -> Any:
    """直连（无跳板），返回已连接的 ``paramiko.SSHClient``。"""
    import paramiko

    if pkey is None and private_key_file:
        pkey = load_pkey_from_file(private_key_file)
    if pkey is None and not password and not allow_agent and not look_for_keys:
        raise ValueError("缺少 SSH 认证：请提供 private_key_file / pkey / password")

    client = paramiko.SSHClient()
    if strict_host_key:
        client.load_system_host_keys()
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
    else:
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    kw: dict[str, Any] = {
        "hostname": host,
        "port": port,
        "username": username,
        "timeout": connect_timeout,
        "allow_agent": allow_agent,
        "look_for_keys": look_for_keys,
    }
    if pkey is not None:
        kw["pkey"] = pkey
    if password:
        kw["password"] = password
    client.connect(**kw)
    return client
