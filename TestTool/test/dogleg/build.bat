@echo off
REM Prevent script crash - catch all errors
setlocal enabledelayedexpansion

REM Set code page to GBK (Windows batch standard encoding)
chcp 936 >nul 2>&1

REM Switch to script directory (important!)
cd /d "%~dp0"
if errorlevel 1 (
    echo [ERROR] Cannot switch to script directory
    echo Script path: %~dp0
    echo.
    echo Press any key to exit...
    pause >nul
    exit /b 1
)

echo ========================================
echo Motor Control Program Build Script
echo ========================================
echo.
echo Current directory: %CD%
echo Script path: %~dp0
echo.

REM 初始化调试日志（使用完整路径，静默失败）
REM 尝试记录日志，但不影响主流程
python "%~dp0debug_logger.py" "A" "build.bat:25" "脚本开始执行" "{\"workdir\":\"%CD%\",\"script_dir\":\"%~dp0\"}" >nul 2>&1

REM Check if Python is installed
echo [*] Checking Python environment...
python "%~dp0debug_logger.py" "A" "build.bat:32" "Check Python" "{}" >nul 2>&1
python --version >nul 2>&1
if errorlevel 1 (
    python "%~dp0debug_logger.py" "A" "build.bat:35" "Python not found" "{}" >nul 2>&1
    echo.
    echo ========================================
    echo [ERROR] Python not found
    echo ========================================
    echo Please install Python 3.7 or higher
    echo Download: https://www.python.org/downloads/
    echo.
    echo Press any key to exit...
    pause >nul
    exit /b 1
)

echo [OK] Python environment check passed
python --version
python "%~dp0debug_logger.py" "A" "build.bat:38" "Python环境检查通过" "{}" >nul 2>&1

echo.
echo [2/4] Checking required packages...
python "%~dp0debug_logger.py" "B" "build.bat:54" "Check PyInstaller" "{}" >nul 2>&1
python -c "import PyInstaller" >nul 2>&1
if errorlevel 1 (
    python "%~dp0debug_logger.py" "B" "build.bat:57" "PyInstaller not installed" "{}" >nul 2>&1
    echo [WARN] PyInstaller not installed, installing...
    python -m pip install pyinstaller
    if errorlevel 1 (
        python "%~dp0debug_logger.py" "B" "build.bat:61" "PyInstaller install failed" "{\"errorlevel\":!ERRORLEVEL!}" >nul 2>&1
        echo [ERROR] PyInstaller installation failed
        pause
        exit /b 1
    )
    python "%~dp0debug_logger.py" "B" "build.bat:67" "PyInstaller installed" "{}" >nul 2>&1
)

REM Verify PyInstaller installation
python "%~dp0debug_logger.py" "B" "build.bat:71" "Verify PyInstaller" "{}" >nul 2>&1
python -c "import PyInstaller" >nul 2>&1
if errorlevel 1 (
    python "%~dp0debug_logger.py" "B" "build.bat:73" "PyInstaller verify failed" "{}" >nul 2>&1
    echo [ERROR] PyInstaller verification failed, please install manually: pip install pyinstaller
    pause
    exit /b 1
)
python "%~dp0debug_logger.py" "B" "build.bat:38" "PyInstaller验证通过" "{}" >nul 2>&1

REM Check other dependencies
python "%~dp0debug_logger.py" "D" "build.bat:82" "Check matplotlib" "{}" >nul 2>&1
python -c "import matplotlib" >nul 2>&1
if errorlevel 1 (
    python "%~dp0debug_logger.py" "D" "build.bat:84" "matplotlib not installed" "{}" >nul 2>&1
    echo [WARN] matplotlib not installed, installing...
    python -m pip install matplotlib
    python "%~dp0debug_logger.py" "D" "build.bat:87" "matplotlib installed" "{\"errorlevel\":!ERRORLEVEL!}" >nul 2>&1
)

python "%~dp0debug_logger.py" "D" "build.bat:91" "Check pymodbus" "{}" >nul 2>&1
python -c "import pymodbus" >nul 2>&1
if errorlevel 1 (
    python "%~dp0debug_logger.py" "D" "build.bat:93" "pymodbus not installed" "{}" >nul 2>&1
    echo [WARN] pymodbus not installed, installing...
    python -m pip install pymodbus
    python "%~dp0debug_logger.py" "D" "build.bat:96" "pymodbus installed" "{\"errorlevel\":!ERRORLEVEL!}" >nul 2>&1
)

python "%~dp0debug_logger.py" "D" "build.bat:100" "Check serial" "{}" >nul 2>&1
python -c "import serial" >nul 2>&1
if errorlevel 1 (
    python "%~dp0debug_logger.py" "D" "build.bat:102" "serial not installed" "{}" >nul 2>&1
    echo [WARN] pyserial not installed, installing...
    python -m pip install pyserial
    python "%~dp0debug_logger.py" "D" "build.bat:105" "serial installed" "{\"errorlevel\":!ERRORLEVEL!}" >nul 2>&1
)

echo.
echo [3/4] Cleaning old build files...
python "%~dp0debug_logger.py" "E" "build.bat:61" "开始清理构建文件" "{}" >nul 2>&1
if exist "build" (
    python "%~dp0debug_logger.py" "E" "build.bat:62" "删除build目录" "{}" >nul 2>&1
    rmdir /s /q "build"
)
if exist "dist" (
    python "%~dp0debug_logger.py" "E" "build.bat:63" "删除dist目录" "{}" >nul 2>&1
    rmdir /s /q "dist"
)
if exist "__pycache__" (
    python "%~dp0debug_logger.py" "E" "build.bat:64" "删除__pycache__目录" "{}" >nul 2>&1
    rmdir /s /q "__pycache__"
)
python "%~dp0debug_logger.py" "E" "build.bat:65" "清理完成" "{}" >nul 2>&1

echo.
echo [4/4] Starting build...
echo This may take a few minutes, please wait...
echo.

REM Build using spec file (using python -m method)
echo Executing build command...
python "%~dp0debug_logger.py" "C" "build.bat:132" "Prepare PyInstaller" "{\"spec_file\":\"build_exe.spec\"}" >nul 2>&1
python "%~dp0debug_logger.py" "E" "build.bat:134" "Check spec file" "{}" >nul 2>&1
if not exist "build_exe.spec" (
    python "%~dp0debug_logger.py" "E" "build.bat:135" "spec file not found" "{}" >nul 2>&1
    echo [ERROR] build_exe.spec file not found
    pause
    exit /b 1
)
python "%~dp0debug_logger.py" "E" "build.bat:141" "Check tool.py" "{}" >nul 2>&1
if not exist "tool.py" (
    python "%~dp0debug_logger.py" "E" "build.bat:142" "tool.py not found" "{}" >nul 2>&1
    echo [ERROR] tool.py file not found
    pause
    exit /b 1
)
python "%~dp0debug_logger.py" "C" "build.bat:73" "开始执行PyInstaller命令" "{\"workdir\":\"%CD%\",\"spec_file\":\"build_exe.spec\"}" >nul 2>&1
if not exist "build_exe.spec" (
    python "%~dp0debug_logger.py" "E" "build.bat:129" "spec文件不存在" "{\"workdir\":\"%CD%\"}" >nul 2>&1
    echo [错误] build_exe.spec 文件不存在于当前目录: %CD%
    pause
    exit /b 1
)
python "%~dp0debug_logger.py" "C" "build.bat:135" "spec文件存在，开始打包" "{\"spec_path\":\"%~dp0build_exe.spec\",\"workdir\":\"%CD%\"}" >nul 2>&1
REM 确保在正确目录执行PyInstaller（已经在脚本开头切换了，这里再次确认）
cd /d "%~dp0"
echo.
echo ========================================
echo Execute Build Command
echo ========================================
echo Working directory: %CD%
echo Script directory: %~dp0
echo.
echo Checking required files:
if exist "build_exe.spec" (
    echo   [OK] build_exe.spec exists
) else (
    echo   [FAIL] build_exe.spec not found!
    echo     Current directory: %CD%
    echo     Please ensure you are in the correct directory
    pause
    exit /b 1
)
if exist "tool.py" (
    echo   [OK] tool.py exists
) else (
    echo   [FAIL] tool.py not found!
    pause
    exit /b 1
)
echo.
echo ========================================
echo Starting PyInstaller
echo ========================================
echo Command: python -m PyInstaller build_exe.spec --clean --workpath build --distpath dist
echo.
echo Executing PyInstaller, this may take a few minutes...
echo.
python -m PyInstaller build_exe.spec --clean --workpath build --distpath dist
set PACK_EXIT_CODE=!ERRORLEVEL!
echo.
echo ========================================
echo PyInstaller Execution Complete
echo Exit code: !PACK_EXIT_CODE!
echo ========================================
echo.
python "%~dp0debug_logger.py" "C" "build.bat:198" "PyInstaller complete" "{\"exit_code\":!PACK_EXIT_CODE!}" >nul 2>&1
if errorlevel 1 (
    python "%~dp0debug_logger.py" "C" "build.bat:200" "Build failed" "{\"exit_code\":!PACK_EXIT_CODE!}" >nul 2>&1
    echo.
    echo ========================================
    echo [ERROR] Build failed!
    echo ========================================
    echo Exit code: !PACK_EXIT_CODE!
    echo Please check the error messages above
    echo.
    pause
    exit /b 1
)
python "%~dp0debug_logger.py" "C" "build.bat:211" "Build success" "{}" >nul 2>&1

echo.
echo ========================================
echo Build Complete!
echo ========================================
echo.

REM Check output files
echo.
echo Checking build results...
python "%~dp0debug_logger.py" "E" "build.bat:163" "检查输出文件" "{}" >nul 2>&1
if exist "dist\电机控制程序\电机控制程序.exe" (
    python "%~dp0debug_logger.py" "E" "build.bat:223" "Found exe (directory mode)" "{\"path\":\"dist\\电机控制程序\\电机控制程序.exe\"}" >nul 2>&1
    echo [OK] Executable location: dist\电机控制程序\电机控制程序.exe
    echo [OK] Build successful! All files in dist\电机控制程序\ directory
) else if exist "dist\电机控制程序.exe" (
    python "%~dp0debug_logger.py" "E" "build.bat:227" "Found exe (onefile mode)" "{\"path\":\"dist\\电机控制程序.exe\"}" >nul 2>&1
    echo [OK] Executable location: dist\电机控制程序.exe
    echo [OK] Build successful! One-file mode
) else (
    python "%~dp0debug_logger.py" "E" "build.bat:231" "Exe file not found" "{}" >nul 2>&1
    echo [WARN] Expected exe file not found
    echo    Please check dist directory and error messages above
    if exist "dist" (
        echo    dist directory exists, but exe file not found
        dir /b dist
    ) else (
        echo    dist directory does not exist, build may have failed
    )
)

echo.
echo Notes:
echo 1. Please ensure PCANBasic.dll is in the same directory as the exe file
echo 2. First run may take a few seconds to load
echo 3. If you encounter problems, check files in dist directory
echo.
echo ========================================
echo Script Execution Complete
echo ========================================
echo.
echo Press any key to exit...
pause >nul
