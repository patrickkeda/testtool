#!/usr/bin/env python3
"""兼容启动脚本：逻辑在 ota_deploy.main_cli。产线序列可继续引用本路径。"""

from ota_deploy import main_cli

if __name__ == "__main__":
    raise SystemExit(main_cli())
