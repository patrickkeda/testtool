"""Seq 脚本用跳板 SSH：优先复用 ``src.drivers.ssh.jump_ssh``，保证与 HMI 同一实现。"""

from __future__ import annotations

import sys
from pathlib import Path


def _bootstrap_src() -> None:
    here = Path(__file__).resolve().parent
    candidates = [
        here.parent.parent,  # TestTool/
        here.parent.parent.parent,  # repo root if scripts nested differently
    ]
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        candidates.extend([exe_dir, exe_dir / "_internal"])
    for root in candidates:
        s = str(root)
        if (root / "src" / "drivers" / "ssh" / "jump_ssh.py").is_file() and s not in sys.path:
            sys.path.insert(0, s)
            return
        # frozen: src already on path as package
        if s not in sys.path:
            sys.path.insert(0, s)


_bootstrap_src()

try:
    from src.drivers.ssh.jump_ssh import (  # noqa: E402
        JumpSSHSession,
        load_pkey_from_file,
        load_pkey_from_string,
    )
except ImportError:  # pragma: no cover - 开发/打包异常时的兜底
    from drivers.ssh.jump_ssh import (  # type: ignore  # noqa: E402
        JumpSSHSession,
        load_pkey_from_file,
        load_pkey_from_string,
    )

__all__ = ["JumpSSHSession", "load_pkey_from_file", "load_pkey_from_string"]
