"""BGE-M3 編碼器（離線版）：從 app 內附的 encoder_model/bge-m3 載入，快取避免重載。

對齊 active_preference_v2/text_encoding.safe_encode 的關鍵設定：
  BAAI/bge-m3（max_seq_length 8192, dim 1024）、normalize_embeddings=True、不加 prefix、
  on_overflow='raise'（絕不靜默截斷）、use_safetensors=True（torch<2.6 必須）。
若 encoder_model/ 不存在，會 fallback 嘗試以 'BAAI/bge-m3' 線上下載（README 註明）。
"""
from __future__ import annotations
from pathlib import Path
import numpy as np

_CACHE: dict = {}


def get_encoder(model_path: str | Path, device: str | None = None):
    import torch
    from sentence_transformers import SentenceTransformer
    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"
    model_path = str(model_path)
    local = Path(model_path).exists()
    key = (model_path, device)
    if key not in _CACHE:
        _CACHE[key] = SentenceTransformer(
            model_path if local else "BAAI/bge-m3", device=device,
            local_files_only=local, model_kwargs={"use_safetensors": True},
        )
    return _CACHE[key]


def safe_encode(texts, model_path, *, normalize: bool = True, on_overflow: str = "raise",
                device: str | None = None):
    """回傳 (embeddings[N,1024], info)。超長 raise（防呆，與訓練一致）。"""
    model = get_encoder(model_path, device=device)
    max_len = int(model.max_seq_length)
    texts = list(texts)
    tk = model.tokenizer
    tok_len = [len(tk.encode(t, add_special_tokens=True)) for t in texts]
    n_over = sum(1 for L in tok_len if L > max_len)
    info = {"max_seq_length": max_len, "max_token_len": max(tok_len) if tok_len else 0,
            "n_over_limit": n_over, "truncated_ratio": float(n_over / max(1, len(texts))), "n": len(texts)}
    if n_over > 0 and on_overflow == "raise":
        raise ValueError(f"[safe_encode] {n_over}/{len(texts)} 筆超過 max_seq_length={max_len}，已中止以免靜默截斷。")
    emb = model.encode(texts, normalize_embeddings=normalize, convert_to_numpy=True,
                       show_progress_bar=False).astype(np.float32)
    return emb, info
