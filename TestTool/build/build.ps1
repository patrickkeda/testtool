param(
    [ValidateSet("full", "incremental")]
    [string]$PackageMode = "",
    [string]$PackageLibraryRoot = ""
)

# TestTool build script - PowerShell
# Packages the Python app as a standalone .exe

# Set console output encoding to UTF-8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

function Get-FileHashHex([string]$Path) {
    return (Get-FileHash -Path $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Get-LatestPackageBaseDir([string]$RootPath) {
    if (-not (Test-Path $RootPath)) {
        return $null
    }
    $items = Get-ChildItem -Path $RootPath -Directory -ErrorAction SilentlyContinue
    $validItems = @()
    foreach ($item in $items) {
        $exe = Join-Path $item.FullName "TestTool.exe"
        $internal = Join-Path $item.FullName "_internal"
        if ((Test-Path $exe) -and (Test-Path $internal)) {
            $validItems += $item
        }
    }

    if ($validItems.Count -eq 0) {
        return $null
    }

    # Prefer semantic version directories: v1.2.3 / 1.2.3 / release-1.2.3.4 ...
    $versioned = @()
    foreach ($item in $validItems) {
        $name = $item.Name
        $m = [regex]::Match($name, '(?i)(?:^|[^0-9])v?(\d+(?:\.\d+){1,3})(?:[^0-9]|$)')
        if ($m.Success) {
            $parts = $m.Groups[1].Value.Split('.')
            $major = [int]$parts[0]
            $minor = if ($parts.Length -ge 2) { [int]$parts[1] } else { 0 }
            $patch = if ($parts.Length -ge 3) { [int]$parts[2] } else { 0 }
            $build = if ($parts.Length -ge 4) { [int]$parts[3] } else { 0 }
            $versioned += [pscustomobject]@{
                Dir = $item
                Major = $major
                Minor = $minor
                Patch = $patch
                Build = $build
            }
        }
    }

    if ($versioned.Count -gt 0) {
        $best = $versioned |
            Sort-Object @{Expression='Major';Descending=$true},
                        @{Expression='Minor';Descending=$true},
                        @{Expression='Patch';Descending=$true},
                        @{Expression='Build';Descending=$true},
                        @{Expression={$_.Dir.LastWriteTime};Descending=$true} |
            Select-Object -First 1
        return $best.Dir.FullName
    }

    # Fallback: latest modified valid package
    return ($validItems | Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName
}

function Compare-And-CreateIncrementalPackage {
    param(
        [string]$BaseDir,
        [string]$FullDir,
        [string]$IncrementalDir
    )
    $allFiles = Get-ChildItem -Path $FullDir -Recurse -File | ForEach-Object {
        $_.FullName.Substring($FullDir.Length + 1)
    }

    $changed = @()
    foreach ($rel in $allFiles) {
        $fullFile = Join-Path $FullDir $rel
        $baseFile = Join-Path $BaseDir $rel
        if (-not (Test-Path $baseFile)) {
            $changed += $rel
            continue
        }
        if ((Get-FileHashHex $fullFile) -ne (Get-FileHashHex $baseFile)) {
            $changed += $rel
        }
    }

    if (Test-Path $IncrementalDir) {
        Remove-Item -Path $IncrementalDir -Recurse -Force -ErrorAction SilentlyContinue
    }
    New-Item -Path $IncrementalDir -ItemType Directory -Force | Out-Null

    $deleted = @()
    $baseFiles = Get-ChildItem -Path $BaseDir -Recurse -File | ForEach-Object {
        $_.FullName.Substring($BaseDir.Length + 1)
    }
    foreach ($rel in $baseFiles) {
        $fullFile = Join-Path $FullDir $rel
        if (-not (Test-Path $fullFile)) {
            $deleted += $rel
        }
    }

    foreach ($rel in $changed) {
        $src = Join-Path $FullDir $rel
        $dst = Join-Path $IncrementalDir $rel
        $dstParent = Split-Path -Parent $dst
        if (-not (Test-Path $dstParent)) {
            New-Item -Path $dstParent -ItemType Directory -Force | Out-Null
        }
        Copy-Item -Path $src -Destination $dst -Force
    }

    $manifestPath = Join-Path $IncrementalDir "incremental_manifest.txt"
    $manifest = @()
    $manifest += "# TestTool incremental package manifest"
    $manifest += ("# generated_at={0}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"))
    $manifest += ("# base_dir={0}" -f $BaseDir)
    $manifest += ("# full_dir={0}" -f $FullDir)
    $manifest += ""
    $manifest += "[CHANGED_OR_ADDED]"
    if ($changed.Count -eq 0) {
        $manifest += "(none)"
    } else {
        $manifest += ($changed | Sort-Object)
    }
    $manifest += ""
    $manifest += "[DELETED_IN_FULL]"
    if ($deleted.Count -eq 0) {
        $manifest += "(none)"
    } else {
        $manifest += ($deleted | Sort-Object)
    }
    Set-Content -Path $manifestPath -Value $manifest -Encoding UTF8

    return @{
        Changed = $changed
        Deleted = $deleted
        Manifest = $manifestPath
    }
}

function Test-IncrementalMergeConsistency {
    param(
        [string]$BaseDir,
        [string]$IncrementalDir,
        [string]$FullDir
    )
    $tempMergeRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("TestTool_merge_verify_" + [System.Guid]::NewGuid().ToString("N"))
    Copy-Item -Path $BaseDir -Destination $tempMergeRoot -Recurse -Force
    $tempMergedDir = Join-Path $tempMergeRoot (Split-Path -Leaf $BaseDir)

    $incrementalFiles = Get-ChildItem -Path $IncrementalDir -Recurse -File | Where-Object {
        $_.Name -ne "incremental_manifest.txt"
    }
    foreach ($file in $incrementalFiles) {
        $rel = $file.FullName.Substring($IncrementalDir.Length + 1)
        $target = Join-Path $tempMergedDir $rel
        $targetParent = Split-Path -Parent $target
        if (-not (Test-Path $targetParent)) {
            New-Item -Path $targetParent -ItemType Directory -Force | Out-Null
        }
        Copy-Item -Path $file.FullName -Destination $target -Force
    }

    $fullFiles = Get-ChildItem -Path $FullDir -Recurse -File | ForEach-Object {
        $_.FullName.Substring($FullDir.Length + 1)
    }
    $mergedFiles = Get-ChildItem -Path $tempMergedDir -Recurse -File | ForEach-Object {
        $_.FullName.Substring($tempMergedDir.Length + 1)
    }

    $fullSet = @{}
    $mergedSet = @{}
    $fullFiles | ForEach-Object { $fullSet[$_.ToLowerInvariant()] = $_ }
    $mergedFiles | ForEach-Object { $mergedSet[$_.ToLowerInvariant()] = $_ }

    $ok = $true
    foreach ($k in $fullSet.Keys) {
        if (-not $mergedSet.ContainsKey($k)) { $ok = $false; break }
        $f = $fullSet[$k]
        $mf = $mergedSet[$k]
        if ((Get-FileHashHex (Join-Path $FullDir $f)) -ne (Get-FileHashHex (Join-Path $tempMergedDir $mf))) {
            $ok = $false
            break
        }
    }
    if ($ok) {
        foreach ($k in $mergedSet.Keys) {
            if (-not $fullSet.ContainsKey($k)) { $ok = $false; break }
        }
    }

    Remove-Item -Path $tempMergeRoot -Recurse -Force -ErrorAction SilentlyContinue
    return $ok
}

# Switch to the parent directory of this script (project root)
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir
Set-Location $projectRoot

if ([string]::IsNullOrWhiteSpace($PackageMode)) {
    Write-Host "Select package mode:" -ForegroundColor Yellow
    Write-Host "  [1] Full package (complete output)" -ForegroundColor White
    Write-Host "  [2] Incremental package (compare latest package library)" -ForegroundColor White
    $modeInput = Read-Host "Input 1 or 2"
    if ($modeInput -eq "2") {
        $PackageMode = "incremental"
    } else {
        $PackageMode = "full"
    }
}
if ([string]::IsNullOrWhiteSpace($PackageLibraryRoot)) {
    $PackageLibraryRoot = Join-Path $projectRoot "build\TestTool_Package_build"
}

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "TestTool Build Script" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Current directory: $projectRoot" -ForegroundColor Yellow
Write-Host ("Package mode: {0}" -f $PackageMode) -ForegroundColor Yellow
if ($PackageMode -eq "incremental") {
    Write-Host ("Package library root: {0}" -f $PackageLibraryRoot) -ForegroundColor Yellow
}
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
$incrementalOutputRoot = Join-Path $distPath "incremental"

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
if ($PackageMode -eq "incremental") {
    $baseDir = Get-LatestPackageBaseDir -RootPath $PackageLibraryRoot
    if (-not $baseDir) {
        Write-Host "[ERROR] Incremental mode failed: no valid latest package found in package library." -ForegroundColor Red
        Write-Host '        Required structure: <version>\TestTool.exe and <version>\_internal' -ForegroundColor Yellow
        exit 1
    }

    Write-Host ""
    Write-Host "[POST] Building incremental package..." -ForegroundColor Green
    Write-Host ("Base package: {0}" -f $baseDir) -ForegroundColor Yellow
    $fullOutputDir = Join-Path $distPath $outputName
    $incrementalDir = Join-Path $incrementalOutputRoot ("TestTool_patch_{0}" -f (Get-Date -Format "yyyyMMdd_HHmmss"))

    $diffResult = Compare-And-CreateIncrementalPackage -BaseDir $baseDir -FullDir $fullOutputDir -IncrementalDir $incrementalDir
    Write-Host ("Changed/Added files: {0}" -f $diffResult.Changed.Count) -ForegroundColor Cyan
    Write-Host ("Deleted files in full package: {0}" -f $diffResult.Deleted.Count) -ForegroundColor Cyan
    Write-Host ("Manifest: {0}" -f $diffResult.Manifest) -ForegroundColor Cyan

    Write-Host ""
    Write-Host "[VERIFY] Checking merge consistency (base + patch == full)..." -ForegroundColor Green
    $isConsistent = Test-IncrementalMergeConsistency -BaseDir $baseDir -IncrementalDir $incrementalDir -FullDir $fullOutputDir
    if ($isConsistent) {
        Write-Host "[OK] Consistency verified. Copy patch files into base package will match full package." -ForegroundColor Green
    } else {
        Write-Host "[ERROR] Consistency check failed. Please use full package directly." -ForegroundColor Red
        exit 1
    }

    Write-Host ("Incremental output: {0}" -f $incrementalDir) -ForegroundColor Yellow
}
Write-Host ""
Write-Host "Directory structure:" -ForegroundColor Yellow
Write-Host ('  dist\{0}' -f $outputName) -ForegroundColor Cyan
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

