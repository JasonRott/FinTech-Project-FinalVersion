# -*- coding: utf-8 -*-
"""一鍵建立桌面可雙擊的 exe（小型啟動器）。

用法：
    pip install pyinstaller
    python app/build_exe.py

產出：dist/ETF偏好投組.exe（帶 app/etf_icon.ico 圖示）。
把它放到專案的 app/ 資料夾（或專案根）即可雙擊啟動網頁版。

注意：此 exe 是「啟動器」——執行的電腦仍需安裝 Python 與本專案相依套件
（pip install -r requirements.txt）。它刻意不凍結 torch 等大型套件，所以體積小、
可隨整包資料夾一起傳。若要做「完全免裝 Python」的單檔（會到數 GB），見 README 進階段落。
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ICON = os.path.join(HERE, "etf_icon.ico")
BOOT = os.path.join(HERE, "_launcher_bootstrap.py")


def main():
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("請先安裝 PyInstaller：\n    pip install pyinstaller")
        sys.exit(1)
    cmd = [
        sys.executable, "-m", "PyInstaller", "--onefile", "--console",
        "--name", "ETF偏好投組", "--icon", ICON,
        "--distpath", os.path.join(ROOT, "dist"),
        "--workpath", os.path.join(ROOT, "build_pyinstaller"),
        "--specpath", HERE,
        BOOT,
    ]
    print("建置中…（PyInstaller）")
    subprocess.run(cmd, check=True)
    print("\n✅ 完成！exe 在  dist/ETF偏好投組.exe")
    print("   建議把它複製到專案的 app/ 資料夾，雙擊即可啟動網頁版。")
    print("   再跑  app/建立桌面捷徑.ps1  就能在桌面建立帶圖示的捷徑。")


if __name__ == "__main__":
    main()
