#!/usr/bin/env python3
"""
VITA Engineer Client 安装脚本
自动安装所需依赖
"""

import sys
import subprocess
import platform
import os
from pathlib import Path

def check_python_version():
    """检查Python版本"""
    if sys.version_info < (3, 8):
        print("❌ 需要Python 3.8或更高版本")
        print(f"当前版本: {sys.version}")
        return False
    print(f"✅ Python版本检查通过: {sys.version}")
    return True

def install_dependencies():
    """安装依赖包"""
    print("📦 安装Python依赖...")
    
    # 从pyproject.toml读取依赖
    pyproject_file = Path(__file__).parent / 'pyproject.toml'
    if not pyproject_file.exists():
        print("❌ 未找到pyproject.toml文件")
        return False
    
    # 基础依赖列表
    dependencies = [
        'cryptography>=3.4.8',
        'httpx>=0.24.0',
        'numpy>=1.21.0',
        'matplotlib>=3.5.0',
        'pytest>=6.0',
        'pytest-asyncio>=0.18.0',
        'black>=22.0',
        'flake8>=4.0',
        'opencv-python-headless>=4.5.5,<5.0.0'
    ]
    
    print(f"📋 将安装以下依赖:")
    for dep in dependencies:
        print(f"   - {dep}")
    
    # 安装依赖
    success_count = 0
    failed_deps = []
    
    for dep in dependencies:
        dep_name = dep.split('>=')[0]
        print(f"   安装 {dep_name}...")
        
        try:
            cmd = [sys.executable, '-m', 'pip', 'install', dep]
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            print(f"   ✅ {dep_name} 安装成功")
            success_count += 1
        except subprocess.CalledProcessError as e:
            print(f"   ❌ {dep_name} 安装失败")
            failed_deps.append(dep_name)
            if e.stderr:
                print(f"      错误: {e.stderr.strip()}")
    
    print(f"\n📊 安装结果: {success_count}/{len(dependencies)} 成功")
    
    if failed_deps:
        print(f"⚠️  失败的依赖: {', '.join(failed_deps)}")
        print("💡 可以尝试:")
        print("   1. 升级pip: python -m pip install --upgrade pip")
        print("   2. 手动安装失败的包")
        print("   3. 使用虚拟环境")
        
        if success_count >= len(dependencies) * 0.7:  # 70%以上成功
            print("✅ 主要依赖已安装，可以尝试运行程序")
            return True
        else:
            print("❌ 关键依赖安装失败，程序可能无法正常运行")
            return False
    else:
        print("✅ 所有依赖安装成功！")
        return True

def create_launcher_scripts():
    """创建启动脚本"""
    print("📝 创建启动脚本...")
    
    script_dir = Path(__file__).parent
    bin_dir = script_dir / 'bin'
    bin_dir.mkdir(exist_ok=True)
    
    # 测试脚本
    test_script = bin_dir / 'vita-engineer-test'
    test_content = f'''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
import os
from pathlib import Path

# 添加项目路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# 切换到项目目录
os.chdir(str(project_root))

# 导入并运行
from vita_engineer_client.test_engineer_client import main
main()
'''
    
    with open(test_script, 'w', encoding='utf-8') as f:
        f.write(test_content)
    
    # GUI脚本
    gui_script = bin_dir / 'vita-engineer-gui'
    gui_content = f'''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
import os
from pathlib import Path

# 添加项目路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# 切换到项目目录
os.chdir(str(project_root))

# 导入并运行
from vita_engineer_client.gui_example import main
main()
'''
    
    with open(gui_script, 'w', encoding='utf-8') as f:
        f.write(gui_content)
    
    # 设置可执行权限
    if hasattr(os, 'chmod'):
        test_script.chmod(0o755)
        gui_script.chmod(0o755)

    # 为Windows用户创建.bat文件
    if platform.system().lower() == 'windows':
        # 测试工具bat文件
        test_bat = bin_dir / 'vita-engineer-test.bat'
        test_bat_content = f'''@echo off
python.exe "%~dp0vita-engineer-test" %*
'''
        with open(test_bat, 'w', encoding='utf-8') as f:
            f.write(test_bat_content)

        # GUI工具bat文件
        gui_bat = bin_dir / 'vita-engineer-gui.bat'
        gui_bat_content = f'''@echo off
python.exe "%~dp0vita-engineer-gui"
'''
        with open(gui_bat, 'w', encoding='utf-8') as f:
            f.write(gui_bat_content)

        print("✅ 启动脚本创建完成")
        print(f"   - {test_script}")
        print(f"   - {gui_script}")
        print(f"   - {test_bat} (Windows)")
        print(f"   - {gui_bat} (Windows)")
    else:
        print("✅ 启动脚本创建完成")
        print(f"   - {test_script}")
        print(f"   - {gui_script}")

def main():
    """主函数"""
    print("🚀 VITA Engineer Client 安装程序")
    print("=" * 50)
    
    # 检查Python版本
    if not check_python_version():
        return 1
    
    # 显示系统信息
    print(f"🖥️  操作系统: {platform.system()} {platform.release()}")
    print(f"🏗️  架构: {platform.machine()}")
    print()
    
    # 安装依赖
    if not install_dependencies():
        print("\n❌ 依赖安装失败")
        return 1
    
    # 创建启动脚本
    create_launcher_scripts()
    
    print("\n🎉 安装完成！")
    print("\n📖 使用方法:")
    print("   测试工具: python3 bin/vita-engineer-test [test_case] [robot_ip]")
    print("   GUI界面: python3 bin/vita-engineer-gui")
    print("   直接运行: python3 vita_engineer_client/test_engineer_client.py tts 10.100.100.96")
    print("\n💡 测试用例: tts, lidar, camera, head, light, battery, all")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
