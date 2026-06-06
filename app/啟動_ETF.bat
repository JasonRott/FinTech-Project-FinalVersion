@echo off
chcp 65001 >nul
title ETF 偏好驅動投資組合 - 網頁版
cd /d "%~dp0.."
echo ============================================================
echo   ETF 偏好驅動投資組合 - 網頁版
echo   啟動中... 首次會自動安裝相依套件 + 下載模型 BGE-M3（需幾分鐘）
echo   完成後會自動開啟瀏覽器 http://127.0.0.1:8050
echo ============================================================
where py >nul 2>nul
if %errorlevel%==0 (
  py app\setup_and_run.py
) else (
  python app\setup_and_run.py
)
echo.
echo (伺服器已停止，按任意鍵關閉視窗)
pause >nul
