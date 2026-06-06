# One-command builder for the no-Python standalone folder (PyInstaller onedir).
# Usage:  powershell -ExecutionPolicy Bypass -File app\打包單機版.ps1
# Output: C:\etf_build\dist\ETF偏好投組\  (exe + _internal + .env.example + data caches)
# (ASCII-only content on purpose: PowerShell 5.1 mis-decodes non-ASCII .ps1 without a BOM.)
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $here
$out  = "C:\etf_build"   # keep outside OneDrive to avoid sync churn

# stop any running instance so files are not locked
Get-Process "ETF偏好投組" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue

Write-Host "Building (PyInstaller onedir, ~5-8 min)..."
& python -m PyInstaller (Join-Path $here "etf_app.spec") --noconfirm `
    --distpath (Join-Path $out "dist") --workpath (Join-Path $out "build")

$dest = Join-Path $out "dist\ETF偏好投組"
if (-not (Test-Path (Join-Path $dest "ETF偏好投組.exe"))) { throw "build failed: exe not found" }

# place .env.example next to the exe (users copy it to .env and fill keys)
Copy-Item (Join-Path $root ".env.example") (Join-Path $dest ".env.example") -Force

# copy market/sentiment caches so a demo run needs no API key / no re-fetch
foreach ($d in @("csv", "json", "sentiment_engine\data")) {
    $src = Join-Path $root $d
    $dst = Join-Path $dest $d
    if (Test-Path $src) {
        New-Item -ItemType Directory -Force -Path $dst | Out-Null
        Copy-Item (Join-Path $src "*") $dst -Force -Recurse -ErrorAction SilentlyContinue
    }
}

# drop intermediate workpath, keep only dist
Remove-Item (Join-Path $out "build") -Recurse -Force -ErrorAction SilentlyContinue

$gb = [math]::Round((Get-ChildItem $dest -Recurse | Measure-Object Length -Sum).Sum / 1GB, 2)
Write-Host "DONE: $dest  (~$gb GB)"
Write-Host "Zip the whole ETF偏好投組 folder to share; double-click the exe (no Python needed)."
