@echo off
REM 设置代码页为GBK（Windows批处理标准编码）
chcp 936 >nul 2>&1
setlocal enabledelayedexpansion
title 电机控制程序 - 一键打包
color 0A

echo.
echo ╔══════════════════════════════════════════════════════╗
echo ║        电机控制程序 - 一键打包工具                  ║
echo ╚══════════════════════════════════════════════════════╝
echo.

REM 检查Python
echo [*] 正在检查Python环境...
python --version >nul 2>&1
if errorlevel 1 (
    color 0C
    echo [×] 错误: 未找到Python
    echo.
    echo 请先安装Python 3.7或更高版本
    echo 下载地址: https://www.python.org/downloads/
    echo.
    echo 按任意键退出...
    pause
    exit /b 1
)

echo [√] Python环境检查通过
echo.

REM 检查必要文件
if not exist "tool.py" (
    color 0C
    echo [×] 错误: 未找到 tool.py 文件
    echo 请确保在正确的目录下运行此脚本
    echo.
    echo 按任意键退出...
    pause
    exit /b 1
)

echo [√] 找到主程序文件 tool.py
echo.

REM 检查PCANBasic.dll
if exist "PCANBasic.dll" (
    echo [√] 找到 PCANBasic.dll
) else (
    color 0E
    echo [!] 警告: 未找到 PCANBasic.dll
    echo    程序可以打包，但PCAN功能可能无法使用
    echo    请确保打包后将PCANBasic.dll放在exe文件旁边
)
echo.

REM 询问是否继续
set /p confirm="是否开始打包? (Y/N): "
if /i not "%confirm%"=="Y" (
    echo 已取消打包
    pause
    exit /b 0
)

echo.
echo [*] 开始打包流程...
echo.

REM 检查并安装PyInstaller
echo [*] 检查PyInstaller...
python -c "import PyInstaller" >nul 2>&1
if errorlevel 1 (
    echo [*] 正在安装PyInstaller...
    python -m pip install pyinstaller
    if errorlevel 1 (
        color 0C
        echo [×] PyInstaller安装失败
        echo 请检查网络连接或手动安装: pip install pyinstaller
        echo.
        echo 按任意键退出...
        pause
        exit /b 1
    )
)

REM 调用build.bat
call build.bat
if errorlevel 1 (
    echo.
    color 0C
    echo [×] 打包过程出现错误
    echo 请查看上方的错误信息
    echo.
    echo 按任意键退出...
    pause
    exit /b 1
)

echo.
color 0A
echo [√] 打包完成！
echo.
echo 按任意键退出...
pause
