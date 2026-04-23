#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
打包脚本 - 使用PyInstaller将程序打包成exe
"""

import os
import sys
import subprocess
import shutil

def check_python_version():
    """检查Python版本"""
    if sys.version_info < (3, 7):
        print("错误: 需要Python 3.7或更高版本")
        print(f"当前版本: {sys.version}")
        return False
    print(f"✓ Python版本: {sys.version}")
    return True

def check_and_install_package(package_name, import_name=None):
    """检查并安装包"""
    if import_name is None:
        import_name = package_name
    
    try:
        __import__(import_name)
        print(f"✓ {package_name} 已安装")
        return True
    except ImportError:
        print(f"✗ {package_name} 未安装，正在安装...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", package_name])
            print(f"✓ {package_name} 安装成功")
            return True
        except subprocess.CalledProcessError:
            print(f"✗ {package_name} 安装失败")
            return False

def clean_build_dirs():
    """清理构建目录"""
    dirs_to_clean = ['build', 'dist', '__pycache__']
    for dir_name in dirs_to_clean:
        if os.path.exists(dir_name):
            print(f"清理目录: {dir_name}")
            shutil.rmtree(dir_name)

def check_pcan_dll():
    """检查PCANBasic.dll是否存在"""
    dll_paths = [
        'PCANBasic.dll',
        './PCANBasic.dll',
        '../PCANBasic.dll',
    ]
    
    for dll_path in dll_paths:
        if os.path.exists(dll_path):
            print(f"✓ 找到PCANBasic.dll: {dll_path}")
            return True
    
    print("⚠ 警告: 未找到PCANBasic.dll")
    print("  请确保PCANBasic.dll与tool.py在同一目录下")
    print("  或者打包后将PCANBasic.dll放在exe文件旁边")
    return False

def build_exe():
    """执行打包"""
    print("\n开始打包...")
    print("这可能需要几分钟时间，请耐心等待...\n")
    
    try:
        # 使用spec文件打包
        cmd = [sys.executable, "-m", "PyInstaller", "build_exe.spec", "--clean"]
        subprocess.check_call(cmd)
        print("\n✓ 打包成功！")
        return True
    except subprocess.CalledProcessError as e:
        print(f"\n✗ 打包失败: {e}")
        return False

def main():
    """主函数"""
    print("=" * 50)
    print("电机控制程序打包脚本")
    print("=" * 50)
    print()
    
    # 检查Python版本
    if not check_python_version():
        return 1
    
    # 检查并安装必要的包
    print("\n检查依赖包...")
    packages = [
        ("pyinstaller", "PyInstaller"),
        ("matplotlib", "matplotlib"),
        ("pymodbus", "pymodbus"),
        ("pyserial", "serial"),
    ]
    
    for package, import_name in packages:
        if not check_and_install_package(package, import_name):
            print(f"\n错误: {package} 安装失败，请手动安装")
            return 1
    
    # 检查PCANBasic.dll
    print("\n检查PCANBasic.dll...")
    check_pcan_dll()
    
    # 清理旧的构建文件
    print("\n清理旧的构建文件...")
    clean_build_dirs()
    
    # 执行打包
    if build_exe():
        print("\n" + "=" * 50)
        print("打包完成！")
        print("=" * 50)
        print("\n可执行文件位置: dist/电机控制程序.exe")
        print("\n注意事项:")
        print("1. 请确保PCANBasic.dll与exe文件在同一目录下")
        print("2. 首次运行可能需要几秒钟加载时间")
        print("3. 如果遇到问题，请检查dist目录下的文件")
        return 0
    else:
        return 1

if __name__ == "__main__":
    sys.exit(main())
