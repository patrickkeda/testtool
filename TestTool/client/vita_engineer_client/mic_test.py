#!/usr/bin/env python3
"""
命令行便捷入口：转调仓库内 ``Seq/scripts/mic_test.py``（无内置私钥）。

用法与 ``Seq/scripts/mic_test.py`` 相同，例如::

    python mic_test.py --jump-host 192.168.126.2 --target-host 192.168.127.10 \\
        --user root --private-key-file %USERPROFILE%\\.ssh\\id_ed25519
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path


def _repo_script() -> Path:
    # .../TestTool/client/vita_engineer_client/mic_test.py -> .../TestTool/Seq/scripts/mic_test.py
    return Path(__file__).resolve().parents[2] / "Seq" / "scripts" / "mic_test.py"


if __name__ == "__main__":
    target = _repo_script()
    if not target.is_file():
        print("错误: 未找到", target, file=sys.stderr)
        raise SystemExit(2)
    sys.argv[0] = str(target)
    runpy.run_path(str(target), run_name="__main__")
