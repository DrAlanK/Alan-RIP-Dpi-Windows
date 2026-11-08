param(
    [string]$Version = "1.2.0"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

Write-Host "======================================================" -ForegroundColor Cyan
Write-Host " Building Alan-RIP-Dpi v$Version Release Package" -ForegroundColor Yellow
Write-Host "======================================================" -ForegroundColor Cyan

Get-Process -Name "Alan-RIP-Dpi", "xray", "tun2socks" -ErrorAction SilentlyContinue |
    Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 600

$PythonExe = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $PythonExe) {
    $PythonExe = "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe"
}
if (-not (Test-Path $PythonExe)) {
    throw "Python executable not found."
}
Write-Host "[1/7] Using Python: $PythonExe"

Write-Host "[2/7] Synchronizing version v$Version across codebase..."
$ModelsFile = Join-Path $Root "alan_dpi\engine\models.py"
if (Test-Path $ModelsFile) {
    $ModelsRaw = Get-Content $ModelsFile -Raw -Encoding UTF8
    $ModelsRaw = $ModelsRaw -replace 'APP_VERSION\s*=\s*"[^"]+"', "APP_VERSION = `"$Version`""
    [System.IO.File]::WriteAllText($ModelsFile, $ModelsRaw, [System.Text.UTF8Encoding]::new($false))
}

Write-Host "[3/7] Ensuring PyInstaller & Pillow are installed..."
& $PythonExe -m pip install --quiet --disable-pip-version-check pyinstaller pillow

Write-Host "[4/7] Preparing application icon & Windows version resource..."
$AssetsDir = Join-Path $Root "assets"
New-Item -ItemType Directory -Force -Path $AssetsDir | Out-Null
$IcoPath = Join-Path $AssetsDir "logo.ico"
if (-not (Test-Path $IcoPath)) {
    $AltIco = Join-Path $AssetsDir "app_icon.ico"
    if (Test-Path $AltIco) {
        $IcoPath = $AltIco
    }
}

$VerParts = ($Version -split '\.') + @("0", "0", "0", "0")
$V1 = [int]$VerParts[0]; $V2 = [int]$VerParts[1]; $V3 = [int]$VerParts[2]; $V4 = [int]$VerParts[3]
$VersionRcPath = Join-Path $Root "build_version_info.txt"
@"
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
          StringStruct('CompanyName', 'Alan Lab'),
          StringStruct('FileDescription', 'Alan-RIP-Dpi Adaptive Engine'),
          StringStruct('FileVersion', '$Version'),
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
"@ | Set-Content -Path $VersionRcPath -Encoding UTF8

Write-Host "[5/7] Compiling executable with PyInstaller..."
$PyiArgs = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--onedir",
    "--windowed",
    "--name", "Alan-RIP-Dpi",
    "--contents-directory", "runtime",
    "--collect-submodules", "alan_dpi",
    "--version-file", $VersionRcPath
)
if (Test-Path $IcoPath) {
    $PyiArgs += @("--icon", $IcoPath)
}
$PyiArgs += "main.py"

& $PythonExe @PyiArgs
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed with exit code $LASTEXITCODE"
}
Remove-Item $VersionRcPath -Force -ErrorAction SilentlyContinue

Write-Host "[6/7] Assembling sanitized portable release bundle..."
$ReleaseRoot = Join-Path $Root "release"
$PackageName = "Alan-RIP-Dpi-v$Version-windows-x64"
$BundleDir = Join-Path $ReleaseRoot $PackageName
$ZipPath = Join-Path $ReleaseRoot "$PackageName.zip"
$ShaPath = Join-Path $ReleaseRoot "$PackageName.sha256"

if (Test-Path $BundleDir) {
    Remove-Item $BundleDir -Recurse -Force
}
if (Test-Path $ZipPath) {
    Remove-Item $ZipPath -Force
}

New-Item -ItemType Directory -Force -Path $BundleDir | Out-Null
Copy-Item -Path (Join-Path $Root "dist\Alan-RIP-Dpi\*") -Destination $BundleDir -Recurse -Force

$DestCore = Join-Path $BundleDir "core"
$DestAssets = Join-Path $BundleDir "assets"
$DestConfigs = Join-Path $BundleDir "configs"
$DestLogs = Join-Path $BundleDir "logs"
foreach ($d in @($DestCore, $DestAssets, $DestConfigs, $DestLogs)) {
    New-Item -ItemType Directory -Force -Path $d | Out-Null
}

$SrcCore = Join-Path $Root "core"
if (Test-Path $SrcCore) {
    foreach ($binName in @("xray.exe", "wintun.dll", "geoip.dat", "geosite.dat")) {
        $srcFile = Join-Path $SrcCore $binName
        if (Test-Path $srcFile) {
            Copy-Item $srcFile -Destination $DestCore -Force
        }
    }
}
if (-not (Test-Path (Join-Path $DestCore "xray.exe"))) {
    Write-Warning "xray.exe was not found in .\core! Make sure core\xray.exe exists."
}

if (Test-Path $AssetsDir) {
    Copy-Item -Path (Join-Path $AssetsDir "*") -Destination $DestAssets -Recurse -Force -ErrorAction SilentlyContinue
}

$SecretPoolFile = Join-Path $Root "configs\.auto_pool_url"
if (Test-Path $SecretPoolFile) {
    Copy-Item $SecretPoolFile -Destination (Join-Path $DestConfigs ".auto_pool_url") -Force
}

Write-Host "[7/7] Creating ZIP archive & SHA-256 checksum (Lock-Safe Mode)..."
Start-Sleep -Milliseconds 800
Add-Type -AssemblyName System.IO.Compression

$ZipStream = [System.IO.File]::Open($ZipPath, [System.IO.FileMode]::Create, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
$ZipArchive = New-Object System.IO.Compression.ZipArchive($ZipStream, [System.IO.Compression.ZipArchiveMode]::Create, $false)

try {
    $AllFiles = Get-ChildItem -Path $BundleDir -Recurse -File -Force
    foreach ($FileItem in $AllFiles) {
        $RelPath = $FileItem.FullName.Substring($BundleDir.Length).TrimStart('\', '/') -replace '\\', '/'
        $EntryName = "$PackageName/$RelPath"
        $Entry = $ZipArchive.CreateEntry($EntryName, [System.IO.Compression.CompressionLevel]::Optimal)

        $Attempt = 0
        while ($true) {
            try {
                $SrcStream = [System.IO.File]::Open(
                    $FileItem.FullName,
                    [System.IO.FileMode]::Open,
                    [System.IO.FileAccess]::Read,
                    [System.IO.FileShare]::ReadWrite
                )
                $DstStream = $Entry.Open()
                try {
                    $SrcStream.CopyTo($DstStream)
                } finally {
                    $DstStream.Dispose()
                    $SrcStream.Dispose()
                }
                break
            } catch {
                $Attempt++
                if ($Attempt -ge 6) { throw }
                Start-Sleep -Milliseconds 500
            }
        }
    }
} finally {
    $ZipArchive.Dispose()
    $ZipStream.Dispose()
}

$HashObj = Get-FileHash -Path $ZipPath -Algorithm SHA256
$HashLine = "$($HashObj.Hash.ToLower())  $PackageName.zip"
Set-Content -Path $ShaPath -Value $HashLine -Encoding ASCII

$SizeMB = [math]::Round(((Get-Item $ZipPath).Length / 1MB), 2)
Write-Host ""
Write-Host "BUILD SUCCESSFUL!" -ForegroundColor Green
Write-Host "Archive : $ZipPath ($SizeMB MB)" -ForegroundColor Cyan
Write-Host "SHA-256 : $HashLine" -ForegroundColor Gray