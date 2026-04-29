# TestTool build script - PowerShell
# Packages the Python app as a standalone .exe

# Set console output encoding to UTF-8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

# Switch to the parent directory of this script (project root)
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir
Set-Location $projectRoot

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "TestTool Build Script" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Current directory: $projectRoot" -ForegroundColor Yellow
Write-Host ""

# Check whether Python is available
try {
    $pythonVersion = python --version 2>&1
    Write-Host "[1/4] Checking Python version..." -ForegroundColor Green
    Write-Host $pythonVersion
} catch {
    Write-Host "[ERROR] Python not found. Please install Python 3.10+ first." -ForegroundColor Red
    exit 1
}

# Verify required files exist
$mainPy = Join-Path $projectRoot "src\app\main.py"
if (-not (Test-Path $mainPy)) {
    Write-Host "[ERROR] src\app\main.py was not found. Run this script from the correct project." -ForegroundColor Red
    Write-Host "Current directory: $projectRoot" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "[2/4] Checking and installing dependencies..." -ForegroundColor Green
$requirementsFile = Join-Path $projectRoot "requirements.txt"
if (-not (Test-Path $requirementsFile)) {
    Write-Host "[ERROR] requirements.txt was not found" -ForegroundColor Red
    exit 1
}
python -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Failed to upgrade pip" -ForegroundColor Red
    exit 1
}

python -m pip install -r $requirementsFile
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Failed to install dependencies" -ForegroundColor Red
    exit 1
}

python -m pip install pyinstaller
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Failed to install PyInstaller" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "[3/4] Cleaning old build files..." -ForegroundColor Green

# Try to close any running TestTool.exe process
$testToolProcesses = Get-Process -Name "TestTool" -ErrorAction SilentlyContinue
if ($testToolProcesses) {
    Write-Host "Detected a running TestTool.exe process. Stopping it..." -ForegroundColor Yellow
    $testToolProcesses | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
}

$distPath = Join-Path $projectRoot "dist"
$workPath = Join-Path $projectRoot "build\pyinstaller"
$testToolDir = Join-Path $distPath "TestTool"
$outputName = "TestTool"

# Retry directory cleanup a few times
if (Test-Path $testToolDir) {
    Write-Host "Cleaning dist\\TestTool directory..." -ForegroundColor Yellow
    $maxRetries = 3
    $retryCount = 0
    $deleted = $false
    
    while ($retryCount -lt $maxRetries -and -not $deleted) {
        try {
            Remove-Item -Path $testToolDir -Recurse -Force -ErrorAction Stop
            $deleted = $true
            Write-Host "Cleanup succeeded" -ForegroundColor Green
        } catch {
            $retryCount++
            if ($retryCount -lt $maxRetries) {
                Write-Host "Cleanup failed, retrying in 2 seconds ($retryCount/$maxRetries)..." -ForegroundColor Yellow
                Start-Sleep -Seconds 2
            } else {
                Write-Host "[WARNING] Could not delete dist\\TestTool. It may be in use." -ForegroundColor Red
                Write-Host "Please close related processes such as TestTool.exe or antivirus tools, then retry." -ForegroundColor Yellow
                $response = Read-Host "Continue building anyway? (Y/N)"
                if ($response -ne "Y" -and $response -ne "y") {
                    exit 1
                }
                # 旧目录被锁时，改为输出到新目录，避免 PyInstaller 在 COLLECT 阶段删除失败
                $outputName = "TestTool_{0}" -f (Get-Date -Format "yyyyMMdd_HHmmss")
                Write-Host ("[INFO] Fallback output directory: dist\{0}" -f $outputName) -ForegroundColor Yellow
            }
        }
    }
}

if (Test-Path (Join-Path $distPath "TestTool.exe")) {
    Remove-Item -Path (Join-Path $distPath "TestTool.exe") -Force -ErrorAction SilentlyContinue
}
if (Test-Path $workPath) {
    Remove-Item -Path $workPath -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host ""
Write-Host "[4/4] Starting packaging..." -ForegroundColor Green

# Check whether CAN DLLs are ready for packaging.
# Recommended location: build\can_dll\ECanVci64.dll and/or ECANFDVCI64.dll
$canDllDir = Join-Path $projectRoot "build\can_dll"
$canDll1 = Join-Path $canDllDir "ECanVci64.dll"
$canDll2 = Join-Path $canDllDir "ECANFDVCI64.dll"
$canDll3 = Join-Path $canDllDir "CHUSBDLL64.dll"
$hasCanDll = (Test-Path $canDll1) -or (Test-Path $canDll2) -or (Test-Path $canDll3)
if ($hasCanDll) {
    Write-Host "[INFO] CAN DLL detected and will be packaged into _internal\test\canapp" -ForegroundColor Green
} else {
    Write-Host "[WARNING] CAN DLL not found in build\can_dll" -ForegroundColor Yellow
    Write-Host "          If target PC has no driver runtime, CAN connect may fail." -ForegroundColor Yellow
    Write-Host "          Put ECanVci64.dll / ECANFDVCI64.dll / CHUSBDLL64.dll into build\can_dll and rebuild." -ForegroundColor Yellow
}

Set-Location (Join-Path $projectRoot "build")
$env:TESTTOOL_OUTPUT_NAME = $outputName
python -m PyInstaller TestTool.spec --clean --noconfirm --distpath $distPath --workpath $workPath

if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Packaging failed" -ForegroundColor Red
    Set-Location $projectRoot
    exit 1
}

Set-Location $projectRoot

# Verify output
$distExe = Join-Path $projectRoot ("dist\{0}\TestTool.exe" -f $outputName)
if (Test-Path $distExe) {
    Write-Host ""
    Write-Host "[VERIFY] Checking output files..." -ForegroundColor Green
    $configPath = Join-Path $projectRoot ("dist\{0}\_internal\Config" -f $outputName)
    $seqPath = Join-Path $projectRoot ("dist\{0}\_internal\Seq" -f $outputName)
    $clientPath = Join-Path $projectRoot ("dist\{0}\_internal\client" -f $outputName)
    $canDllPath1 = Join-Path $projectRoot ("dist\{0}\_internal\test\canapp\ECanVci64.dll" -f $outputName)
    $canDllPath2 = Join-Path $projectRoot ("dist\{0}\_internal\test\canapp\ECANFDVCI64.dll" -f $outputName)
    $canDllPath3 = Join-Path $projectRoot ("dist\{0}\_internal\test\canapp\CHUSBDLL64.dll" -f $outputName)
    if (Test-Path $configPath) {
        Write-Host "[OK] Config directory is included" -ForegroundColor Green
    } else {
        Write-Host "[WARNING] Config directory was not found" -ForegroundColor Yellow
    }
    if (Test-Path $seqPath) {
        Write-Host "[OK] Seq directory is included" -ForegroundColor Green
    } else {
        Write-Host "[WARNING] Seq directory was not found" -ForegroundColor Yellow
    }
    if (Test-Path $clientPath) {
        Write-Host "[OK] client directory is included" -ForegroundColor Green
    } else {
        Write-Host "[WARNING] client directory was not found" -ForegroundColor Yellow
    }
    if ((Test-Path $canDllPath1) -or (Test-Path $canDllPath2) -or (Test-Path $canDllPath3)) {
        Write-Host "[OK] CAN DLL is included" -ForegroundColor Green
    } else {
        Write-Host "[WARNING] CAN DLL was not found in packaged output" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Build completed!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host ("Output: dist\{0}\TestTool.exe" -f $outputName) -ForegroundColor Yellow
Write-Host ""
Write-Host "Directory structure:" -ForegroundColor Yellow
Write-Host ("  dist\{0}\" -f $outputName) -ForegroundColor Cyan
Write-Host "    +-- TestTool.exe          (main program)" -ForegroundColor Cyan
Write-Host "    +-- _internal\            (dependencies and config)" -ForegroundColor Cyan
Write-Host "        +-- Config\           (config files)" -ForegroundColor Cyan
Write-Host "        +-- Seq\              (test sequences)" -ForegroundColor Cyan
Write-Host "        +-- client\           (engineer client)" -ForegroundColor Cyan
Write-Host "        +-- examples\         (example files)" -ForegroundColor Cyan
Write-Host "        +-- [other dependencies]" -ForegroundColor Cyan
Write-Host ""
Write-Host "Usage:" -ForegroundColor Yellow
Write-Host "1. Open the dist\TestTool directory" -ForegroundColor White
Write-Host "2. Double-click TestTool.exe to run it" -ForegroundColor White
Write-Host "3. Copy the entire TestTool folder when distributing it" -ForegroundColor White
Write-Host ""

