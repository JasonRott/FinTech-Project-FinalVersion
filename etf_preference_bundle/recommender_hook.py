# -*- coding: utf-8 -*-
"""
★★★ 交付接點（已接好本專案的 ETF 推薦主程式）★★★

把問答產出的 9 維 ETF 偏好權重，交給下游的 ETF 投組最佳化主程式。
本檔同時被「網頁版」(web/app.py) 與「函式庫版」(integrate_example.py) 呼叫，
所以不論使用者用哪種模式完成問答，權重都會落到同一個地方。

接法（檔案交付，跨行程）：
  問答完成 → 把 9 維權重寫成主系統下游認得的 `Global_Weights` JSON
  → 主系統 `json/stage2_ahp_global_weights.json`
  接著使用者跑 `python main.py`（preference_mode="web_preference"）即可讀取本次網頁問答結果，
  進入 Stage 2_2 / Stage 3 / 回測。

參數：
  weights  : dict   9 維權重，總和=1。
  snapshot : dict   完整快照（ranking、每維 90% 信賴區間、Sigma_alpha 確定度…），可選用
回傳：
  dict — 交付摘要（寫出的路徑、正規化後的權重、是否成功）。
"""
from __future__ import annotations

import json
from pathlib import Path

# 主系統 9 維正規順序（與 pipeline_stages._PREF_DIMS 一致）
_PREF_DIMS = [
    "Return_CAGR", "Return_Div", "Risk_Vol", "Risk_MaxDD", "Cost_ExpRatio",
    "Liq_Volume", "Liq_AUM", "Div_Score", "FinBERT_score",
]

# etf_preference_bundle/ 就在主專案根目錄底下 → 上一層即專案根
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_MAIN_WEIGHTS_JSON = _PROJECT_ROOT / "json" / "stage2_ahp_global_weights.json"


def _normalize_nine_dims(weights: dict) -> dict:
    """補齊 9 維、缺值補 0，並把總和正規化為 1。"""
    w = {d: float(weights.get(d, 0.0)) for d in _PREF_DIMS}
    total = sum(w.values()) or 1.0
    return {d: v / total for d, v in w.items()}


def deliver_weights(weights, snapshot=None):
    """把 9 維偏好權重寫進主系統 `json/stage2_ahp_global_weights.json`（下游 Stage 2_2/3/回測讀此檔）。"""
    snap = snapshot or {}
    w = _normalize_nine_dims(weights or {})

    payload = {
        "CR": 0.0,
        "Global_Weights": w,
        "Source": "etf_preference_bundle web/library (Phase3 BNN elicitation)",
        "Sigma_alpha": snap.get("Sigma_alpha"),
        "n_covered": snap.get("n_covered"),
        "ci_trustworthy": snap.get("ci_trustworthy"),
        "ci_note": snap.get("ci_note"),
    }

    _MAIN_WEIGHTS_JSON.parent.mkdir(parents=True, exist_ok=True)
    _MAIN_WEIGHTS_JSON.write_text(
        json.dumps(payload, ensure_ascii=False, indent=4), encoding="utf-8"
    )

    return {
        "delivered_to": str(_MAIN_WEIGHTS_JSON),
        "weights": w,
        "n_covered": snap.get("n_covered"),
        "ci_trustworthy": snap.get("ci_trustworthy"),
        "ok": True,
    }
