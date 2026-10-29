param(
    [string]$Version = "1.0.0",
    [switch]$OneFile
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

Write-Host "======================================================" -ForegroundColor Cyan
Write-Host " Building Alan-RIP-Dpi v$Version Release Package" -ForegroundColor Yellow
Write-Host "======================================================" -ForegroundColor Cyan

$PythonExe = $null
$LocalPy313 = Join-Path $env:LOCALAPPDATA "Programs\Python\Python313\python.exe"
if (Test-Path $LocalPy313) {
    $PythonExe = $LocalPy313
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $PythonExe = (Get-Command python).Source
} else {
    throw "Python executable not found."
}
Write-Host "[1/7] Using Python: $PythonExe" -ForegroundColor Gray

foreach ($procName in @("Alan-RIP-Dpi", "xray", "sing-box")) {
    Get-Process -Name $procName -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
}

Write-Host "[2/7] Synchronizing version v$Version across codebase..." -ForegroundColor Gray
$ModelsFile = Join-Path $ProjectRoot "alan_dpi\engine\models.py"
if (Test-Path $ModelsFile) {
    $mc = Get-Content $ModelsFile -Raw -Encoding UTF8
    $mc = [regex]::Replace($mc, 'APP_VERSION\s*=\s*"[^"]+"', "APP_VERSION = `"$Version`"")
    [System.IO.File]::WriteAllText($ModelsFile, $mc, [System.Text.UTF8Encoding]::new($false))
}

$TunFile = Join-Path $ProjectRoot "alan_dpi\engine\tun_manager.py"
if (Test-Path $TunFile) {
    $tc = Get-Content $TunFile -Raw -Encoding UTF8
    $tc = [regex]::Replace($tc, 'Alan-RIP-Dpi/[0-9\.]+', "Alan-RIP-Dpi/$Version")
    [System.IO.File]::WriteAllText($TunFile, $tc, [System.Text.UTF8Encoding]::new($false))
}

$UiFiles = Get-ChildItem -Path (Join-Path $ProjectRoot "alan_dpi\ui") -Filter "*.py" -Recurse -ErrorAction SilentlyContinue
foreach ($uf in $UiFiles) {
    $uc = Get-Content $uf.FullName -Raw -Encoding UTF8
    $ucUpdated = [regex]::Replace($uc, '"v[23]\.\d+(?:\.\d+)?(?:\s+CORE)?"', "`"v$Version`"")
    $ucUpdated = [regex]::Replace($ucUpdated, "'v[23]\.\d+(?:\.\d+)?(?:\s+CORE)?'", "'v$Version'")
    if ($ucUpdated -ne $uc) {
        [System.IO.File]::WriteAllText($uf.FullName, $ucUpdated, [System.Text.UTF8Encoding]::new($false))
    }
}

Write-Host "[3/7] Ensuring PyInstaller & Pillow are installed..." -ForegroundColor Gray
& $PythonExe -m pip install --quiet --upgrade pyinstaller pillow

$BuildDir = Join-Path $ProjectRoot "build"
$DistDir = Join-Path $ProjectRoot "dist"
$ReleaseDir = Join-Path $ProjectRoot "release"
foreach ($dir in @($BuildDir, $DistDir)) {
    if (Test-Path $dir) { Remove-Item $dir -Recurse -Force }
}
New-Item -ItemType Directory -Force -Path $BuildDir, $DistDir, $ReleaseDir, (Join-Path $ProjectRoot "assets") | Out-Null

Write-Host "[4/7] Preparing application icon & Windows version resource..." -ForegroundColor Gray
$IconScript = @"
import os
from PIL import Image, ImageDraw

assets = r'$ProjectRoot\assets'
ico_path = os.path.join(assets, 'logo.ico')
src_img = None
for name in ('logo.png', 'icon.png', 'logo.jpg', 'logo.jfif'):
    cand = os.path.join(assets, name)
    if os.path.exists(cand):
        src_img = Image.open(cand).convert('RGBA')
        break

if src_img is None:
    src_img = Image.new('RGBA', (256, 256), (0, 0, 0, 0))
    draw = ImageDraw.Draw(src_img)
    draw.rounded_rectangle((16, 16, 240, 240), radius=48, fill=(12, 15, 22, 255), outline=(255, 208, 0, 255), width=8)
    draw.polygon([(142, 46), (76, 138), (126, 138), (110, 210), (182, 114), (132, 114)], fill=(255, 208, 0, 255))
    src_img.save(os.path.join(assets, 'logo.png'))

src_img.save(ico_path, format='ICO', sizes=[(256,256), (128,128), (64,64), (48,48), (32,32), (16,16)])
"@
$IconPyFile = Join-Path $BuildDir "gen_icon.py"
[System.IO.File]::WriteAllText($IconPyFile, $IconScript, [System.Text.UTF8Encoding]::new($false))
& $PythonExe $IconPyFile
$IcoPath = Join-Path $ProjectRoot "assets\logo.ico"

$VerParts = ($Version -split '\.') + @("0","0","0","0")
$V1 = [int]$VerParts[0]; $V2 = [int]$VerParts[1]; $V3 = [int]$VerParts[2]; $V4 = [int]$VerParts[3]
$VersionResource = @"
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=($V1, $V2, $V3, $V4),
    prodvers=($V1, $V2, $V3, $V4),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040904B0',
        [
          StringStruct('CompanyName', 'Alan Network Engineering'),
          StringStruct('FileDescription', 'Alan-RIP-Dpi Anti-Censorship Client'),
          StringStruct('FileVersion', '$Version.0'),
          StringStruct('InternalName', 'Alan-RIP-Dpi'),
          StringStruct('OriginalFilename', 'Alan-RIP-Dpi.exe'),
          StringStruct('ProductName', 'Alan-RIP-Dpi'),
          StringStruct('ProductVersion', '$Version')
        ]
      )
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"@
$VerInfoFile = Join-Path $BuildDir "file_version_info.txt"
[System.IO.File]::WriteAllText($VerInfoFile, $VersionResource, [System.Text.UTF8Encoding]::new($false))

Write-Host "[5/7] Compiling executable with PyInstaller..." -ForegroundColor Gray
$PyArgs = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--windowed",
    "--name", "Alan-RIP-Dpi",
    "--icon", $IcoPath,
    "--version-file", $VerInfoFile,
    "--collect-submodules", "alan_dpi",
    "--hidden-import", "PySide6.QtCore",
    "--hidden-import", "PySide6.QtGui",
    "--hidden-import", "PySide6.QtWidgets",
    "--exclude-module", "tkinter",
    "--exclude-module", "matplotlib",
    "--exclude-module", "unittest"
)

if ($OneFile) {
    $PyArgs += "--onefile"
} else {
    $PyArgs += @("--onedir", "--contents-directory", "runtime")
}
$PyArgs += "main.py"

& $PythonExe @PyArgs
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed with exit code $LASTEXITCODE"
}

Write-Host "[6/7] Assembling sanitized portable release bundle..." -ForegroundColor Gray
$PackageName = "Alan-RIP-Dpi-v$Version-windows-x64"
$StageDir = Join-Path $ReleaseDir $PackageName
if (Test-Path $StageDir) { Remove-Item $StageDir -Recurse -Force }
New-Item -ItemType Directory -Force -Path $StageDir | Out-Null

if ($OneFile) {
    Copy-Item (Join-Path $DistDir "Alan-RIP-Dpi.exe") -Destination $StageDir -Force
} else {
    Copy-Item (Join-Path $DistDir "Alan-RIP-Dpi\*") -Destination $StageDir -Recurse -Force
}

foreach ($sub in @("core", "configs", "logs", "assets")) {
    New-Item -ItemType Directory -Force -Path (Join-Path $StageDir $sub) | Out-Null
}

foreach ($binFile in @("xray.exe", "geoip.dat", "geosite.dat", "sing-box.exe", "wintun.dll")) {
    $srcBin = Join-Path $ProjectRoot "core\$binFile"
    if (Test-Path $srcBin) {
        Copy-Item $srcBin -Destination (Join-Path $StageDir "core\$binFile") -Force
    }
}

if (-not (Test-Path (Join-Path $StageDir "core\xray.exe"))) {
    Write-Warning "core\xray.exe was not found! Place xray.exe inside core\ before distributing."
}

Copy-Item (Join-Path $ProjectRoot "assets\*") -Destination (Join-Path $StageDir "assets") -Recurse -Force
[System.IO.File]::WriteAllText((Join-Path $StageDir "configs\repository.json"), "[]", [System.Text.UTF8Encoding]::new($false))
[System.IO.File]::WriteAllText((Join-Path $StageDir "configs\subscriptions.json"), "[]", [System.Text.UTF8Encoding]::new($false))

Write-Host "[7/7] Creating ZIP archive & SHA-256 checksum..." -ForegroundColor Gray
$ZipPath = Join-Path $ReleaseDir "$PackageName.zip"
if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }
Compress-Archive -Path (Join-Path $StageDir "*") -DestinationPath $ZipPath -Force

$HashObj = Get-FileHash -Path $ZipPath -Algorithm SHA256
$HashLine = "$($HashObj.Hash.ToLower())  $PackageName.zip"
[System.IO.File]::WriteAllText("$ZipPath.sha256", $HashLine, [System.Text.UTF8Encoding]::new($false))

Write-Host ""
Write-Host "BUILD COMPLETED SUCCESSFULLY!" -ForegroundColor Green
Write-Host "Portable Folder : $StageDir" -ForegroundColor White
Write-Host "GitHub ZIP      : $ZipPath" -ForegroundColor Yellow
Write-Host "SHA-256         : $($HashObj.Hash.ToLower())" -ForegroundColor Cyan