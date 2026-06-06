# -*- coding: utf-8 -*-
"""
函式庫版整合範例(不開網頁)—— 直接在你的 Python 程式裡跑問答、拿 9 維權重。

與網頁版共用同一個接點 recommender_hook.deliver_weights():
  - 網頁版:python run_web.py(瀏覽器問答,完成後自動交付)
  - 函式庫版:本檔(程式內問答,完成後自動交付)

執行(互動測試):
    python integrate_example.py
首次會載入 BGE-M3(本機有 encoder_model/ 則離線,否則自動下載 BAAI/bge-m3,約 1–2 分鐘)。
"""
import sys
from pathlib import Path

BUNDLE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BUNDLE_DIR))

from phase3_system import Phase3Engine            # noqa: E402
from recommender_hook import deliver_weights      # noqa: E402  ← 共用接點


def extract_preferences(philosophy_text, answer_fn, max_questions=9):
    """跑完問答,回傳 (weights, snapshot)。weights = 9 維 dict,總和=1。"""
    engine = Phase3Engine()
    engine.start_session(philosophy_text)
    asked = 0
    while asked < max_questions:
        q = engine.next_question()
        if q is None:
            break
        snap = engine.submit_answer(answer_fn(q))
        asked += 1
        if snap.get("should_stop"):
            break
    snap = engine.snapshot()
    return snap["Ew"], snap


def run(philosophy_text, answer_fn, max_questions=9):
    """完整流程:萃取權重 → 透過 recommender_hook 交付給你的推薦程式 → 回傳交付結果。"""
    weights, snap = extract_preferences(philosophy_text, answer_fn, max_questions)
    result = deliver_weights(weights, snap)        # ← 你的推薦邏輯(在 recommender_hook.py)
    return weights, snap, result


def _interactive():
    print("=" * 60)
    print(" Phase 3 偏好誘出 — 函式庫版整合測試")
    print("=" * 60)
    phil = input("\n請輸入投資理念(直接 Enter 用預設範例):\n> ").strip()
    if not phil:
        phil = "我希望長期穩健成長,能接受一點波動但很怕大跌,偏好低費用、分散持股的標的。"
        print(f"(使用預設) {phil}")

    def ask(q):
        print(f"\n[第 {q['step']} 題 · {q['dim_label']}]")
        return input(f"  {q['question']}\n  > ").strip()

    weights, snap, result = run(phil, ask)
    print("\n" + "=" * 60)
    print(" 9 維 ETF 偏好權重(總和=1)")
    print("=" * 60)
    for it in snap["ranking"]:
        print(f"  {it['Ew']:.3f}  {'█'*int(it['Ew']*40):<40}  {it['dim_label']}")
    print(f"\n  確定度 Σα = {snap['Sigma_alpha']}  ｜  {snap['ci_note']}")
    print(f"\n  weights = {weights}")
    print(f"  recommender_hook 回傳 = {result}")


if __name__ == "__main__":
    _interactive()
