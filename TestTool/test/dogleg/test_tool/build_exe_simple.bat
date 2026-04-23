@echo off
chcp 65001 >nul
echo ============================================================
echo 电机控制工具 - 快速打包脚本
echo ============================================================
echo.

REM 检查 Python 是否安装
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.7 或更高版本
    pause
    exit /b 1
)

echo [1/3] 检查并安装依赖...
python -m pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo [错误] 依赖安装失败
    pause
    exit /b 1
)

echo [2/3] 清理旧文件...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist tool.spec del /q tool.spec

echo [3/3] 开始打包...
python build_exe.py

echo.
echo ============================================================
echo 打包完成！请查看 dist 目录
echo ============================================================
pause
