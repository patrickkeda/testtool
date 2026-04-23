"""
工具模块启动脚本
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from .sequence_editor import main as editor_main
from .step_library import main as library_main


def main():
    """主函数"""
    if len(sys.argv) < 2:
        print("用法:")
        print("  python -m src.app.tools sequence_editor  # 启动序列编辑器")
        print("  python -m src.app.tools step_library     # 启动步骤库管理器")
        return
    
    tool_name = sys.argv[1]
    
    if tool_name == "sequence_editor":
        editor_main()
    elif tool_name == "step_library":
        library_main()
    else:
        print(f"未知的工具: {tool_name}")
        print("可用的工具: sequence_editor, step_library")


if __name__ == "__main__":
    main()
