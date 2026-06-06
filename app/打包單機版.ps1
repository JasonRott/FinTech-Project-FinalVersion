# 一鍵建立「完全免裝 Python 的單機資料夾」（PyInstaller onedir）並備好可發佈內容。
# 用法：powershell -ExecutionPolicy Bypass -File app\打包單機版.ps1
# 產出：C:\etf_build\dist\ETF偏好投組\（整包，含 exe + _internal + .env.example + 行情/情緒快取）
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $here
$out  = "C:\etf_build"   # OneDrive 以外，避免同步卡住

# 先關掉可能正在跑的同名 exe（否則檔案被鎖、無法覆蓋）
Get-Process "ETF偏好投組" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue

Write-Host "建置中（PyInstaller onedir，約 5–8 分鐘）…"
& python -m PyInstaller (Join-Path $here "etf_app.spec") --noconfirm `
    --distpath (Join-Path $out "dist") --workpath (Join-Path $out "build")

$dest = Join-Path $out "dist\ETF偏好投組"
if (-not (Test-Path (Join-Path $dest "ETF偏好投組.exe"))) { throw "建置失敗，找不到 exe" }

# .env.example 放到 exe 旁（使用者複製成 .env 填金鑰；展示用快取則免金鑰）
Copy-Item (Join-Path $root ".env.example") (Join-Path $dest ".env.example") -Force

# 複製行情/情緒快取 → 展示時免金鑰、免重抓（想要更小的包可自行刪除這些）
foreach ($d in @("csv", "json", "sentiment_engine\data")) {
    $src = Join-Path $root $d
    $dst = Join-Path $dest $d
    if (Test-Path $src) {
        New-Item -ItemType Directory -Force -Path $dst | Out-Null
        Copy-Item (Join-Path $src "*") $dst -Force -Recurse -ErrorAction SilentlyContinue
    }
}

# 清掉建置中間檔，只留 dist 交付物
Remove-Item (Join-Path $out "build") -Recurse -Force -ErrorAction SilentlyContinue

$mb = [math]::Round((Get-ChildItem $dest -Recurse | Measure-Object Length -Sum).Sum / 1GB, 2)
Write-Host "✅ 完成：$dest  （約 $mb GB）"
Write-Host "把整個 ETF偏好投組 資料夾壓成 zip 傳給別人；對方雙擊 ETF偏好投組.exe 即可（完全免裝 Python）。"
Write-Host "建立桌面捷徑：powershell -ExecutionPolicy Bypass -File app\建立桌面捷徑.ps1"
