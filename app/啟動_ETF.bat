@echo off
chcp 65001 >nul
title ETF 偏好驅動投資組合 - 網頁版
cd /d "%~dp0.."
echo ============================================================
echo   ETF 偏好驅動投資組合 - 網頁版
echo   啟動中... 載入模型後會自動開啟瀏覽器 http://127.0.0.1:8050
echo   (首次啟動需下載/載入模型 BGE-M3，請耐心等候數十秒)
echo ============================================================
where py >nul 2>nul
if %errorlevel%==0 (
  py etf_web\run_web.py
) else (
  python etf_web\run_web.py
)
echo.
echo (伺服器已停止，按任意鍵關閉視窗)
pause >nul
