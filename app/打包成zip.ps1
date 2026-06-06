# 把整個專案打包成一個可傳送的 zip（排除 .git / 快取 / 大型模型 / 暫存 / 建置產物）。
# 模型（BGE-M3 ~2.2GB、FinBERT）與價格快取會在對方第一次執行時自動下載/重抓，故不放進 zip。
# 用法：powershell -ExecutionPolicy Bypass -File app\打包成zip.ps1
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $here
$stamp = Get-Date -Format "yyyyMMdd_HHmm"
$staging = Join-Path $env:TEMP "etf_pkg_$stamp"
$out = Join-Path ([Environment]::GetFolderPath("Desktop")) "ETF偏好投組_$stamp.zip"

Write-Host "整理檔案中（排除大型/快取/暫存）…"
# robocopy 鏡像到暫存，排除大型與不必要的資料夾/檔案
$xd = @('.git','__pycache__','encoder_model','dist','build_pyinstaller','backtest_report',
        'version_0','.vscode','build')
$xf = @('*.log','*.pyc','news_events_cache.csv')
$args = @($root, $staging, '/E', '/NFL', '/NDL', '/NJH', '/NJS', '/NP', '/R:1', '/W:1')
$args += '/XD'; $args += $xd
$args += '/XF'; $args += $xf
robocopy @args | Out-Null   # robocopy 回傳碼 0-7 為正常

if (Test-Path $out) { Remove-Item $out -Force }
Write-Host "壓縮中 -> $out"
Compress-Archive -Path (Join-Path $staging '*') -DestinationPath $out -Force
Remove-Item $staging -Recurse -Force

$mb = [math]::Round((Get-Item $out).Length / 1MB, 1)
Write-Host "✅ 完成：$out  （$mb MB）"
Write-Host "對方解壓後：1) pip install -r requirements.txt  2) 雙擊 app\啟動_ETF.bat（或先 python app\build_exe.py 做 exe）"
