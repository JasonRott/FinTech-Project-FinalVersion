# -*- coding: utf-8 -*-
"""啟動 ETF 網頁版：python etf_web/run_web.py（或在 main.py 選 RUN_MODE="web"）。

開 http://127.0.0.1:8050 ，整個流程（偏好問答 → 執行分析 → 結果呈現）都在瀏覽器上完成。
首次啟動會載入偏好引擎的本地模型（BGE-M3 + 9 個 1D BNN），請稍候數秒。
"""
import os
os.environ.setdefault("MPLBACKEND", "Agg")  # 非互動後端：背景執行緒產圖不會觸發 Tk 崩潰

import sys
import threading
import time
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from etf_web.app import app  # noqa: E402

HOST, PORT = "127.0.0.1", 8050


def _open_browser():
    time.sleep(1.5)
    try:
        webbrowser.open(f"http://{HOST}:{PORT}")
    except Exception:
        pass


def main():
    print(f"啟動 ETF 網頁版… 載入模型後請開 http://{HOST}:{PORT}")
    threading.Thread(target=_open_browser, daemon=True).start()
    app.run(host=HOST, port=PORT, debug=False)


if __name__ == "__main__":
    main()
