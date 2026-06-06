# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 規格：把 ETF 網頁版凍結成「完全免安裝 Python」的單機資料夾（--onedir）。

建置（在專案根目錄執行）：
    pip install pyinstaller
    pyinstaller app/etf_app.spec --noconfirm --distpath <out>/dist --workpath <out>/build
產出：<out>/dist/ETF偏好投組/（整個資料夾可壓縮傳送；雙擊裡面的 ETF偏好投組.exe 即可）。
注意：體積大（torch 等，約 3–5GB）；模型 BGE-M3 仍於首次執行自動下載。
"""
import os
from PyInstaller.utils.hooks import collect_all

# SPECPATH 由 PyInstaller 注入＝本 spec 所在資料夾（app/）；專案根＝其上一層。
ROOT = os.path.dirname(SPECPATH)

datas, binaries, hiddenimports = [], [], []
for _pkg in ["torch", "sentence_transformers", "transformers", "sklearn", "scipy",
             "yfinance", "huggingface_hub", "tokenizers", "safetensors", "regex",
             "tqdm", "joblib", "threadpoolctl", "filelock", "sympy", "networkx"]:
    try:
        d, b, h = collect_all(_pkg)
        datas += d; binaries += b; hiddenimports += h
    except Exception as _e:
        print("collect_all skip", _pkg, _e)

# 專案資料檔（模板/靜態/偏好引擎 assets/相依清單）— 用絕對路徑避免相對解析歧義
datas += [
    (os.path.join(ROOT, "etf_web", "templates"), "etf_web/templates"),
    (os.path.join(ROOT, "etf_web", "static"), "etf_web/static"),
    (os.path.join(ROOT, "etf_preference_bundle", "assets"), "etf_preference_bundle/assets"),
    (os.path.join(ROOT, "requirements.txt"), "."),
]

# 延遲匯入的專案模組（PyInstaller 靜態分析抓不到）
hiddenimports += [
    "functions", "pipeline_stages", "backtest_engine", "parameters",
    "etf_web", "etf_web.app", "etf_web.run_web",
    "phase3_system", "phase3_system.engine", "phase3_system.core", "phase3_system.encoder",
    "recommender_hook", "integrate_example",
    "flask", "jinja2", "sklearn.utils._typedefs",
]

a = Analysis(
    [os.path.join(ROOT, "app", "frozen_main.py")],
    pathex=[ROOT, os.path.join(ROOT, "etf_preference_bundle")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name="ETF偏好投組", console=False,   # 視窗模式：雙擊不跳黑色 console（log 寫到 etf_app.log）
    icon=os.path.join(ROOT, "app", "etf_icon.ico"),
)
coll = COLLECT(exe, a.binaries, a.datas, name="ETF偏好投組")
