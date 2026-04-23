#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
打包工具：将 tool.py 打包成独立的 exe 文件
使用方法：python build_exe.py
"""

import os
import sys
import subprocess
import shutil

def check_pyinstaller():
    """检查是否安装了 PyInstaller"""
    try:
        import PyInstaller
        print("✓ PyInstaller 已安装")
        # 验证 pyinstaller 命令是否可用
        try:
            result = subprocess.run([sys.executable, "-m", "PyInstaller", "--version"], 
                                  capture_output=True, timeout=5)
            if result.returncode == 0:
                print(f"✓ PyInstaller 版本: {result.stdout.decode('utf-8', errors='ignore').strip()}")
                return True
        except:
            pass
        return True
    except ImportError:
        print("✗ PyInstaller 未安装，正在安装...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"], 
                                timeout=300)
            print("✓ PyInstaller 安装成功")
            return True
        except subprocess.CalledProcessError:
            print("✗ PyInstaller 安装失败，请手动安装：pip install pyinstaller")
            return False
        except Exception as e:
            print(f"✗ PyInstaller 安装失败: {str(e)}")
            return False

def clean_build_dirs():
    """清理之前的构建目录"""
    dirs_to_clean = ['build', 'dist', '__pycache__']
    for dir_name in dirs_to_clean:
        if os.path.exists(dir_name):
            print(f"清理目录: {dir_name}")
            shutil.rmtree(dir_name)
    
    # 清理 spec 文件
    if os.path.exists('tool.spec'):
        os.remove('tool.spec')
        print("清理文件: tool.spec")

def build_exe():
    """执行打包"""
    print("\n" + "="*60)
    print("开始打包 tool.py 为 exe 文件...")
    print("="*60 + "\n")
    
    # 检查是否有PCANBasic DLL，如果有则包含
    pcan_dll_path = None
    possible_dll_paths = [
        "PCANBasic.dll",
        "C:/Windows/System32/PCANBasic.dll",
        "C:/Program Files/PEAK/PCAN-Basic API/PCANBasic.dll"
    ]
    
    for dll_path in possible_dll_paths:
        if os.path.exists(dll_path):
            pcan_dll_path = dll_path
            print(f"找到 PCANBasic.dll: {dll_path}")
            break
    
    # PyInstaller 命令参数（使用 python -m PyInstaller 确保能找到）
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name=电机控制工具",  # exe 文件名
        "--onefile",  # 打包成单个文件
        "--windowed",  # 不显示控制台窗口（GUI应用）
        "--icon=NONE",  # 如果有图标文件可以指定
        "--hidden-import=PCANBasic",  # 隐藏导入，确保PCANBasic被包含
        "--hidden-import=pymodbus",  # 确保pymodbus被包含
        "--hidden-import=serial",  # 确保serial被包含
        "--hidden-import=serial.tools.list_ports",  # 串口工具
        "--hidden-import=matplotlib.backends.backend_tkagg",  # matplotlib后端
        "--hidden-import=matplotlib.backends.backend_agg",  # matplotlib后端
        "--hidden-import=tkinter",  # tkinter
        "--hidden-import=tkinter.ttk",  # ttk
        "--hidden-import=tkinter.messagebox",  # messagebox
        "--hidden-import=tkinter.filedialog",  # filedialog
        "--collect-all=matplotlib",  # 收集matplotlib的所有数据文件
        "--collect-all=pymodbus",  # 收集pymodbus的所有数据文件
        "--collect-binaries=PCANBasic",  # 收集PCANBasic相关二进制文件
        "--noconfirm",  # 覆盖输出目录而不询问
        "--clean",  # 清理临时文件
    ]
    
    # 如果找到PCANBasic DLL，添加到打包中
    if pcan_dll_path:
        # 规范化路径，确保使用正斜杠
        pcan_dll_normalized = os.path.normpath(pcan_dll_path).replace("\\", "/")
        cmd.append(f"--add-binary={pcan_dll_normalized};.")
    
    cmd.append("tool.py")
    
    try:
        print("执行打包命令...")
        print(f"命令: {' '.join(cmd)}")
        result = subprocess.run(cmd, check=True, capture_output=True, text=True, encoding='utf-8', errors='ignore')
        print("\n" + "="*60)
        print("✓ 打包成功！")
        print("="*60)
        print(f"\n输出目录: {os.path.abspath('dist')}")
        print(f"exe 文件: {os.path.abspath(os.path.join('dist', '电机控制工具.exe'))}")
        print("\n提示：")
        print("1. exe 文件位于 dist 目录中")
        print("2. 可以将整个 dist 目录复制到其他 Windows 10 电脑上运行")
        print("3. 首次运行可能需要几秒钟的启动时间")
        return True
    except subprocess.CalledProcessError as e:
        print("\n" + "="*60)
        print("✗ 打包失败！")
        print("="*60)
        if e.stderr:
            print(f"\n错误信息：\n{e.stderr}")
        if e.stdout:
            print(f"\n输出信息：\n{e.stdout}")
        return False
    except FileNotFoundError as e:
        print("\n" + "="*60)
        print("✗ 打包失败！")
        print("="*60)
        print(f"\n错误：找不到 PyInstaller 命令")
        print("请确保已安装 PyInstaller: pip install pyinstaller")
        return False
    except Exception as e:
        print("\n" + "="*60)
        print("✗ 打包失败！")
        print("="*60)
        print(f"\n错误信息：{str(e)}")
        return False

def create_portable_package():
    """创建便携版打包（文件夹形式，而不是单文件）"""
    print("\n" + "="*60)
    print("创建便携版打包（文件夹形式）...")
    print("="*60 + "\n")
    
    # 检查是否有PCANBasic DLL
    pcan_dll_path = None
    possible_dll_paths = [
        "PCANBasic.dll",
        "C:/Windows/System32/PCANBasic.dll",
        "C:/Program Files/PEAK/PCAN-Basic API/PCANBasic.dll"
    ]
    
    for dll_path in possible_dll_paths:
        if os.path.exists(dll_path):
            pcan_dll_path = dll_path
            print(f"找到 PCANBasic.dll: {dll_path}")
            break
    
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name=电机控制工具",  # exe 文件名
        "--onedir",  # 打包成文件夹
        "--windowed",  # 不显示控制台窗口
        "--hidden-import=PCANBasic",
        "--hidden-import=pymodbus",
        "--hidden-import=serial",
        "--hidden-import=serial.tools.list_ports",
        "--hidden-import=matplotlib.backends.backend_tkagg",
        "--hidden-import=matplotlib.backends.backend_agg",
        "--hidden-import=tkinter",
        "--hidden-import=tkinter.ttk",
        "--hidden-import=tkinter.messagebox",
        "--hidden-import=tkinter.filedialog",
        "--collect-all=matplotlib",
        "--collect-all=pymodbus",
        "--collect-binaries=PCANBasic",
        "--noconfirm",
        "--clean",
    ]
    
    # 如果找到PCANBasic DLL，添加到打包中
    if pcan_dll_path:
        # 规范化路径，确保使用正斜杠
        pcan_dll_normalized = os.path.normpath(pcan_dll_path).replace("\\", "/")
        cmd.append(f"--add-binary={pcan_dll_normalized};.")
    
    cmd.append("tool.py")
    
    try:
        print("执行打包命令...")
        print(f"命令: {' '.join(cmd)}")
        result = subprocess.run(cmd, check=True, capture_output=True, text=True, encoding='utf-8', errors='ignore')
        print("\n" + "="*60)
        print("✓ 便携版打包成功！")
        print("="*60)
        print(f"\n输出目录: {os.path.abspath('dist')}")
        print(f"可执行文件: {os.path.abspath(os.path.join('dist', '电机控制工具', '电机控制工具.exe'))}")
        print("\n提示：")
        print("1. 整个 '电机控制工具' 文件夹可以复制到其他电脑运行")
        print("2. 文件夹形式启动更快，但文件较多")
        return True
    except subprocess.CalledProcessError as e:
        print("\n" + "="*60)
        print("✗ 打包失败！")
        print("="*60)
        if e.stderr:
            print(f"\n错误信息：\n{e.stderr}")
        if e.stdout:
            print(f"\n输出信息：\n{e.stdout}")
        return False
    except FileNotFoundError as e:
        print("\n" + "="*60)
        print("✗ 打包失败！")
        print("="*60)
        print(f"\n错误：找不到 PyInstaller 命令")
        print("请确保已安装 PyInstaller: pip install pyinstaller")
        return False
    except Exception as e:
        print("\n" + "="*60)
        print("✗ 打包失败！")
        print("="*60)
        print(f"\n错误信息：{str(e)}")
        return False

def main():
    """主函数"""
    print("="*60)
    print("电机控制工具 - 打包脚本")
    print("="*60)
    
    # 检查 tool.py 是否存在
    if not os.path.exists("tool.py"):
        print("✗ 错误：找不到 tool.py 文件")
        return
    
    # 检查并安装 PyInstaller
    if not check_pyinstaller():
        return
    
    # 清理之前的构建
    clean_build_dirs()
    
    # 询问用户选择打包方式
    print("\n请选择打包方式：")
    print("1. 单文件模式（推荐）- 生成单个 exe 文件，启动稍慢但便于分发")
    print("2. 文件夹模式 - 生成文件夹，启动快但文件较多")
    
    choice = input("\n请输入选择 (1/2，默认1): ").strip()
    
    if choice == "2":
        success = create_portable_package()
    else:
        success = build_exe()
    
    if success:
        print("\n" + "="*60)
        print("打包完成！")
        print("="*60)
    else:
        print("\n" + "="*60)
        print("打包失败，请检查错误信息")
        print("="*60)
        sys.exit(1)

if __name__ == "__main__":
    main()
