# -*- coding: utf-8 -*-
"""啟動前自動檢查相依套件，缺了就自動 pip install -r requirements.txt，然後啟動網頁版。

被 app/啟動_ETF.bat 與打包出來的 exe 啟動器呼叫。
只在「偵測到缺套件」時才安裝（用 importlib 檢查，不真的 import 大套件），
所以裝過之後再開都很快；第一次會花幾分鐘裝套件 + 下載模型。
"""
import importlib.util
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REQ = os.path.join(ROOT, "requirements.txt")

# 關鍵套件（import 名）：缺任一就觸發安裝
_CHECK = ["flask", "torch", "sentence_transformers", "scipy", "numpy",
          "pandas", "matplotlib", "sklearn", "yfinance"]


def _have(mod: str) -> bool:
    try:
        return importlib.util.find_spec(mod) is not None
    except Exception:
        return False


def _missing():
    return [m for m in _CHECK if not _have(m)]


def ensure_deps():
    miss = _missing()
    if not miss:
        return
    print("=" * 60)
    print(f"偵測到缺少套件：{', '.join(miss)}")
    if not os.path.exists(REQ):
        print(f"找不到 requirements.txt（{REQ}）；請手動安裝相依套件。")
        input("按 Enter 關閉…")
        sys.exit(1)
    print("正在自動安裝相依套件： pip install -r requirements.txt")
    print("（第一次安裝可能需要幾分鐘，請耐心等候…）")
    print("=" * 60)
    try:
        subprocess.run([sys.executable, "-m", "pip", "install", "-r", REQ], check=True)
    except Exception as exc:
        print(f"\n自動安裝失敗：{exc}")
        print("請手動執行：  pip install -r requirements.txt")
        input("按 Enter 關閉…")
        sys.exit(1)
    still = _missing()
    if still:
        print(f"\n安裝後仍缺少：{', '.join(still)}")
        print("請手動執行：  pip install -r requirements.txt")
        input("按 Enter 關閉…")
        sys.exit(1)
    print("\n相依套件安裝完成，啟動中…")


def main():
    os.chdir(ROOT)
    ensure_deps()
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    from etf_web.run_web import main as run_web_main
    run_web_main()


if __name__ == "__main__":
    main()
