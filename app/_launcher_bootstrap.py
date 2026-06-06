# -*- coding: utf-8 -*-
"""PyInstaller 打包用的「小型啟動器」。

它本身**不 import** torch / flask 等大型套件，只在執行時去找機器上的 Python，
再跑 `etf_web/run_web.py`。好處：打出來的 exe 很小、可隨整包資料夾一起傳；
壞處：執行的機器仍需裝 Python 與本專案相依（pip install -r requirements.txt）。
（若要「完全免安裝 Python」的單檔，需凍結 torch 等大套件，體積會到數 GB，見 README。）
"""
import os
import shutil
import subprocess
import sys


def main():
    base = os.path.dirname(os.path.abspath(sys.argv[0]))          # exe 所在資料夾
    root = os.path.abspath(os.path.join(base, os.pardir))          # 專案根（app/ 的上層）
    # 優先用 setup_and_run.py（會先自動 pip install 缺的相依套件再啟動）；退回 run_web.py
    candidates = [
        os.path.join(root, "app", "setup_and_run.py"),
        os.path.join(base, "app", "setup_and_run.py"),
        os.path.join(base, "setup_and_run.py"),
        os.path.join(root, "etf_web", "run_web.py"),
        os.path.join(base, "etf_web", "run_web.py"),
    ]
    script = next((c for c in candidates if os.path.exists(c)), None)
    if not script:
        print("找不到 app/setup_and_run.py 或 etf_web/run_web.py。請把這個 exe 放在專案的 app/ 資料夾內再執行。")
        input("按 Enter 關閉…")
        return
    # setup_and_run.py 在 app/ 下 → 專案根是上兩層；run_web.py 在 etf_web/ 下 → 也是上兩層
    project_root = os.path.dirname(os.path.dirname(script))
    py = shutil.which("py") or shutil.which("python") or "python"
    print("啟動 ETF 網頁版… 首次會自動安裝相依套件並下載模型，請稍候。")
    try:
        subprocess.run([py, script], cwd=project_root)
    except Exception as exc:
        print(f"啟動失敗：{exc}")
        input("按 Enter 關閉…")


if __name__ == "__main__":
    main()
