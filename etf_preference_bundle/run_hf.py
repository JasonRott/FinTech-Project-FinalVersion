"""Hugging Face Spaces / 雲端部署用入口。

與 run_web.py 相同的 Flask app，但：
  - 綁定 0.0.0.0、讀環境變數 PORT（HF Spaces Docker 預設 7860）
  - 不自動開瀏覽器（伺服器環境無 GUI）

本地測試： python run_hf.py  → http://127.0.0.1:7860
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from web.app import app  # noqa: E402

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7860))
    print(f"啟動中… 首次互動會載入 BGE-M3（約需 1–2 分鐘），請耐心等候。Port={port}")
    app.run(host="0.0.0.0", port=port, debug=False)
