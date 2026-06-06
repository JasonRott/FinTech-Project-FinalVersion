"""啟動網頁版：python run_web.py → 自動開瀏覽器 http://127.0.0.1:5000

後端包同一個 phase3_system 引擎（與 #79 定案位元一致）；前端為自繪 HTML/CSS/JS（離線）。
"""
import sys
import threading
import time
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from web.app import app  # noqa: E402

HOST, PORT = "127.0.0.1", 8000


def _open():
    time.sleep(1.5)
    webbrowser.open(f"http://{HOST}:{PORT}")


if __name__ == "__main__":
    print(f"啟動中… 載入模型後請開 http://{HOST}:{PORT}")
    threading.Thread(target=_open, daemon=True).start()
    app.run(host=HOST, port=PORT, debug=False)
