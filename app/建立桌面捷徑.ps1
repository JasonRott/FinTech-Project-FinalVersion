# 在桌面建立「ETF 偏好投組」捷徑（帶 app/etf_icon.ico 圖示）。
# 用法：在檔案上按右鍵 -> 用 PowerShell 執行；或 powershell -ExecutionPolicy Bypass -File app\建立桌面捷徑.ps1
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $here
$icon = Join-Path $here "etf_icon.ico"

# 優先用已建好的 exe（app/ 或 dist/）；否則退回 .bat 啟動器
$exeApp = Join-Path $here "ETF偏好投組.exe"
$exeDist = Join-Path $root "dist\ETF偏好投組.exe"
$bat = Join-Path $here "啟動_ETF.bat"
if (Test-Path $exeApp) { $target = $exeApp }
elseif (Test-Path $exeDist) { $target = $exeDist }
else { $target = $bat }

$desktop = [Environment]::GetFolderPath("Desktop")
$lnk = Join-Path $desktop "ETF 偏好投組.lnk"

$ws = New-Object -ComObject WScript.Shell
$s = $ws.CreateShortcut($lnk)
$s.TargetPath = $target
$s.WorkingDirectory = $root
if (Test-Path $icon) { $s.IconLocation = "$icon,0" }
$s.Description = "ETF 偏好驅動投資組合（網頁版）"
$s.Save()

Write-Host "已在桌面建立捷徑：" $lnk
Write-Host "指向：" $target
Write-Host "（雙擊桌面圖示即可啟動網頁版）"
