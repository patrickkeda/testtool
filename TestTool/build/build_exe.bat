@echo off
setlocal EnableExtensions

cd /d "%~dp0"
for %%I in ("%~dp0..") do set "PROJECT_ROOT=%%~fI"
set "DIST_DIR=%PROJECT_ROOT%\dist\TestTool"

echo ========================================
echo TestTool Build Launcher
echo ========================================
echo.

echo [0/4] Pre-clean: close TestTool.exe and clean dist\TestTool...
taskkill /F /IM TestTool.exe >nul 2>&1

if exist "%DIST_DIR%" (
    set "CLEAN_OK="
    for /L %%N in (1,1,5) do (
        rmdir /S /Q "%DIST_DIR%" >nul 2>&1
        if not exist "%DIST_DIR%" (
            set "CLEAN_OK=1"
            goto :clean_done
        )
        echo Cleanup attempt %%N/5 failed, retrying in 2 seconds...
        timeout /T 2 /NOBREAK >nul
    )
)

:clean_done
if exist "%DIST_DIR%" (
    echo [WARNING] dist\TestTool is still locked and could not be removed.
    echo Please close Explorer/antivirus/TestTool.exe, then run again.
    echo.
    choice /C YN /M "Continue build anyway"
    if errorlevel 2 exit /b 1
)

echo.
echo Running PowerShell build script...
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0build.ps1"
set "BUILD_RESULT=%ERRORLEVEL%"

echo.
if not "%BUILD_RESULT%"=="0" (
    echo ========================================
    echo Build failed. Exit code: %BUILD_RESULT%
    echo ========================================
) else (
    echo ========================================
    echo Build finished successfully.
    echo ========================================
)

echo.
pause
exit /b %BUILD_RESULT%
