# -*- coding: utf-8 -*-
"""
preference_engine 整合範例 —— 把「投資理念 + 逐輪問答」轉成 9 維 ETF 偏好權重。

把這個資料夾(preference_engine/)放進你的專案後,你的推薦主程式只要照
`extract_preferences()` 的寫法即可拿到權重,再餵給你的 ETF 評分/排序邏輯。

執行方式(互動測試):
    python preference_engine/integrate_example.py
首次會載入 BGE-M3(本機有 encoder_model/ 則離線載入,否則自動下載 BAAI/bge-m3,約 1–2 分鐘)。
"""
import sys
from pathlib import Path

# 讓 phase3_system 可被 import:把本檔所在的 preference_engine/ 放進 sys.path
ENGINE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ENGINE_DIR))

from phase3_system import Phase3Engine          # noqa: E402
from phase3_system.engine import DIM_LABELS     # noqa: E402


# ── 你的推薦主程式只需要這個函式 ───────────────────────────────────────────
def extract_preferences(philosophy_text, answer_fn, max_questions=9):
    """
    參數:
      philosophy_text : str          投資者的開場投資理念
      answer_fn(q)    : callable      給定問題 dict、回傳使用者答案字串
      max_questions   : int           最多問幾題(引擎也會自行判斷何時可停)
    回傳:
      weights : dict   9 維 ETF 偏好權重(總和=1),例如 {"Return_CAGR": 0.21, ...}
      snap    : dict   完整快照(含 ranking、每維 90% 信賴區間、確定度 Sigma_alpha 等)
    """
    engine = Phase3Engine()
    engine.start_session(philosophy_text)

    asked = 0
    while asked < max_questions:
        q = engine.next_question()
        if q is None:                 # 沒有更多題目
            break
        ans = answer_fn(q)
        snap = engine.submit_answer(ans)
        asked += 1
        if snap.get("should_stop"):   # 引擎判斷已足夠(排序操作點),可提早停
            break

    snap = engine.snapshot()
    return snap["Ew"], snap


# ── 你把這裡換成你真正的 ETF 推薦邏輯 ───────────────────────────────────────
def recommend_etfs(weights, etf_table=None):
    """
    範例:用偏好權重對每支 ETF 的 9 維特徵做加權打分。
    etf_table: {etf_code: {dim_key: 0~1 的特徵分數}}  ← 換成你的 ETF 資料
    """
    if not etf_table:
        print("\n[recommend_etfs] 這裡接你的 ETF 評分邏輯,例如:")
        print("    score(etf) = Σ weights[dim] * etf_feature[dim]")
        return []
    scored = []
    for code, feat in etf_table.items():
        score = sum(weights.get(d, 0.0) * feat.get(d, 0.0) for d in weights)
        scored.append((code, score))
    scored.sort(key=lambda x: -x[1])
    return scored


# ── 互動式測試 ─────────────────────────────────────────────────────────────
def _interactive():
    print("=" * 60)
    print(" Phase 3 偏好誘出 — 整合測試")
    print("=" * 60)
    phil = input("\n請輸入投資理念(直接 Enter 用預設範例):\n> ").strip()
    if not phil:
        phil = "我希望長期穩健成長,能接受一點波動但很怕大跌,偏好低費用、分散持股的標的。"
        print(f"(使用預設) {phil}")

    def ask(q):
        print(f"\n[第 {q['step']} 題 · {q['dim_label']}]")
        return input(f"  {q['question']}\n  > ").strip()

    weights, snap = extract_preferences(phil, ask)

    print("\n" + "=" * 60)
    print(" 萃取結果:9 維 ETF 偏好權重(總和=1)")
    print("=" * 60)
    for item in snap["ranking"]:
        bar = "█" * int(item["Ew"] * 40)
        print(f"  {item['Ew']:.3f}  {bar:<40}  {item['dim_label']}")
    print(f"\n  確定度 Σα = {snap['Sigma_alpha']}  ｜  {snap['ci_note']}")
    print(f"\n  weights dict = {weights}")

    recommend_etfs(weights)   # ← 你的推薦邏輯接這裡


if __name__ == "__main__":
    _interactive()
