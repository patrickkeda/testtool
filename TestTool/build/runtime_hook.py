"""
PyInstaller 运行时钩子
用于在打包后的程序中设置正确的路径
"""
import os
import sys
from pathlib import Path

# 获取可执行文件所在目录
if getattr(sys, 'frozen', False):
    # 如果是打包后的程序
    base_path = Path(sys.executable).parent
else:
    # 如果是开发环境
    base_path = Path(__file__).parent.parent

# 将可执行文件目录添加到 Python 路径
if str(base_path) not in sys.path:
    sys.path.insert(0, str(base_path))

# 设置工作目录为可执行文件所在目录
os.chdir(str(base_path))

# 确保 Config 目录存在（如果不存在则创建小写别名）
config_dir = base_path / 'Config'
config_lower_dir = base_path / 'config'

# 如果存在 Config 但不存在 config，创建符号链接或复制（Windows 上可能需要管理员权限）
# 为了简单起见，我们只确保路径解析能工作
# Windows 文件系统不区分大小写，所以这通常不是问题





