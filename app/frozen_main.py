# -*- coding: utf-8 -*-
"""完全凍結（單機版）進入點 —— 由 PyInstaller --onedir 打包。

對方電腦**不需安裝 Python 或任何套件**，雙擊 exe 即可。
執行時把工作目錄切到 exe 所在資料夾（可寫），輸出（csv/png/report/user_results/json）都落在那。
模型 BGE-M3／FinBERT 仍會在「首次執行」自動下載（需聯網一次）。
"""
import os
import sys

os.environ.setdefault("MPLBACKEND", "Agg")

if getattr(sys, "frozen", False):
    APP_HOME = os.path.dirname(sys.executable)
    os.chdir(APP_HOME)
    for _d in ("csv", "json", "png", "report", "logs", "user_results"):
        os.makedirs(os.path.join(APP_HOME, _d), exist_ok=True)
    # 視窗模式（無 console）時 stdout/stderr 為 None → print/logging 會崩潰；導向 log 檔。
    if sys.stdout is None or sys.stderr is None:
        try:
            _logf = open(os.path.join(APP_HOME, "etf_app.log"), "a", encoding="utf-8", buffering=1)
            sys.stdout = _logf
            sys.stderr = _logf
        except Exception:
            pass

import threading  # noqa: E402
import time  # noqa: E402
import webbrowser  # noqa: E402

HOST, PORT = "127.0.0.1", 8050


def _open():
    time.sleep(2.5)
    try:
        webbrowser.open(f"http://{HOST}:{PORT}")
    except Exception:
        pass


def main():
    print(f"ETF 偏好驅動投資組合（單機版）啟動中… 載入模型後開 http://{HOST}:{PORT}")
    print("（首次執行會自動下載模型 BGE-M3，約 2.2GB，需聯網一次，請耐心等候）")
    from etf_web.app import app  # 觸發背景預熱
    threading.Thread(target=_open, daemon=True).start()
    app.run(host=HOST, port=PORT, debug=False)


if __name__ == "__main__":
    main()
