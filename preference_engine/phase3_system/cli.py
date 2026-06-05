"""Phase 3 互動式偏好誘出 — 終端機介面（portable）。"""
from __future__ import annotations
import argparse

from .engine import Phase3Engine

STOP_WORDS = {"結束", "stop", "quit", "q", "exit", "離開"}
MORE_WORDS = {"more", "繼續", "continue"}
OPENING = "請用幾句話描述您整體的 ETF 投資理念，以及您最重視的幾個方向。"
BAR_W = 24
_LABEL = {"Return_CAGR": "資本增值", "Return_Div": "股息現金流", "Risk_Vol": "波動穩健",
          "Risk_MaxDD": "抗跌", "Cost_ExpRatio": "費用率", "Liq_Volume": "成交量",
          "Liq_AUM": "基金規模", "Div_Score": "分散度", "FinBERT_score": "市場情緒"}


def ask(prompt="> "):
    """讀取輸入；EOF（輸入流結束/Ctrl-D）視為結束，回傳 stop。"""
    try:
        return input(prompt)
    except (EOFError, KeyboardInterrupt):
        return "stop"


def bar(frac):
    n = int(round(max(0.0, min(1.0, frac)) * BAR_W))
    return "█" * n + "·" * (BAR_W - n)


def _short(k):
    return _LABEL.get(k, k)


def show_readout(snap, top_k=4):
    print(f"\n  Σα {snap['Sigma_alpha']:.2f} / τ {snap['tau']:.2f}  [{bar(snap['stop_progress'])}] {int(snap['stop_progress']*100)}%")
    print(f"  目前偏好排序（E[w]，已問 {snap['n_asked']} 題 / 覆蓋 {snap['n_covered']}/9）：")
    for row in snap["ranking"][:top_k]:
        lo, hi = row["ci90"]
        print(f"    {row['rank']}. {row['dim_label']:<16s} {row['Ew']:.3f}  90%CI[{lo:.2f},{hi:.2f}]")
    print(f"  仍最不確定：{'、'.join([_short(x) for x in snap['uncertainty_rank_dims'][:3]])}")
    if snap["pending_conflicts"]:
        print(f"  待稍後確認的衝突項：{'、'.join([_short(x) for x in snap['pending_conflicts']])}")
    if not snap["ci_trustworthy"]:
        print("  （此階段：偏好『排序』可參考；精確比例與 CI 尚未校準，覆蓋完 9 面向才可信 — #79 兩操作點）")


def final_summary(snap, reason):
    print("\n" + "=" * 60)
    print(f"訪談結束（{reason}）。共回答 {snap['n_asked']} 題（覆蓋 {snap['n_covered']}/9、重問 {snap['n_reasks']}）。")
    print("=" * 60)
    print("您的 ETF 偏好權重（E[w]，總和=1）：")
    for row in snap["ranking"]:
        lo, hi = row["ci90"]
        print(f"  {row['rank']}. {row['dim_label']:<16s} {row['Ew']:.3f}   90%CI[{lo:.2f}, {hi:.2f}]")
    print(f"\n  Σα={snap['Sigma_alpha']:.2f}（證據量）；CI 校準 M={snap['ci_M']}")
    print(f"  CI 可信度：{snap['ci_note']}")
    if snap["n_covered"] < 9:
        print("  ※ 早停（排序模式）：排序通常已穩定，但精確量級與可信 CI 需覆蓋完 9 面向（#79 兩操作點）。")
    print("  ※ 自由打字屬自然語氣 regime，語言→強度天花板約 spearman 0.45–0.47（E5i 結構性，非錯誤）。")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top-k", type=int, default=4)
    args = ap.parse_args()

    print("=" * 60)
    print("  ETF 投資偏好訪談（Phase 3 互動原型）")
    print("=" * 60)
    print("我會問您幾個關於 ETF 投資偏好的問題，依您的回答即時推估您的偏好權重。\n")
    print("【作答方式｜請盡量具體、明確地表達您的偏好】")
    print("  • 對您越重視的面向：請清楚強調它對您有多重要、會如何影響您的投資選擇與取捨。")
    print("  • 對您越不在乎的面向：也請明確說出您願意妥協、不太在意。")
    print("  這樣我才能準確判斷您每個面向偏好的強弱。\n")
    print("隨時可輸入「結束 / stop」中止；系統理解足夠時會主動收尾。")
    print("（首次啟動需載入模型，請稍候…）")

    engine = Phase3Engine()

    print("\n[開場] " + OPENING)
    philo = ask().strip()
    if philo.lower() in STOP_WORDS:
        print("已取消。"); return
    snap = engine.start_session(philo)
    print("\n（已依您的理念建立個人化先驗）")
    show_readout(snap, args.top_k)

    reason = "已完成"
    continue_full = False
    continue_reask = False
    while True:
        # 提議點 1（T1 排序操作點）：覆蓋階段達 Σα≥τ → 提議結束
        if engine.phase == "coverage" and engine.should_stop() and not continue_full:
            print("\n" + "·" * 60)
            print(f"系統已能排出您最重視的面向（已問 {snap['n_asked']} 題，Σα≥τ）。")
            print("直接按 Enter 結束；或輸入 more 續問完整 9 面向（並對與理念有出入的回答做確認）。")
            choice = ask().strip().lower()
            if choice in MORE_WORDS:
                continue_full = True
            else:
                reason = "系統判定已找到您最重視的面向（您選擇結束）"
                break
        # 提議點 2（9 維到齊＝完整可信操作點）：有待確認衝突時，提議停或續做重問
        if engine.all_covered() and engine.t3_pending() and not continue_reask:
            names = "、".join(_short(x) for x in snap["pending_conflicts"])
            print("\n" + "·" * 60)
            print(f"9 個面向都問完了——目前是完整、CI 可信的結果。")
            print(f"直接按 Enter 結束；或輸入 more 讓系統對與您理念有出入的 {len(snap['pending_conflicts'])} 項（{names}）做最後重新確認。")
            choice = ask().strip().lower()
            if choice in MORE_WORDS:
                continue_reask = True
            else:
                reason = "已覆蓋全部 9 面向（完整可信結果），您選擇結束"
                break
        q = engine.next_question()
        if q is None:
            reason = ("已覆蓋全部面向，並完成衝突確認、信念穩定" if engine.conflict_flags
                      else "已覆蓋全部面向，無與理念衝突需確認")
            break
        print("\n" + "-" * 60)
        if q["is_reask"]:
            print(f"[重新確認 · {q['dim_label']}]")
            if q["reask_reason"]:
                print(f"  ↳ {q['reask_reason']}")
        else:
            src = "" if q["question_source"] == "canonical" else "（換個說法）"
            print(f"[第 {q['step']} 題 · {q['dim_label']}]{src}")
        print(q["question"])
        ans = ask().strip()
        if ans.lower() in STOP_WORDS or ans in STOP_WORDS:
            reason = "您主動結束"
            break
        if not ans:
            print("（未輸入內容，跳過本題）")
            continue
        snap = engine.submit_answer(ans)
        lt = snap["last_turn"]
        flag = "" if lt["gate_rel"] > 0.8 else f"  ⚠ 偵測到回答可能離題 rel={lt['gate_rel']:.2f}（已降權）"
        print(f"  → 本題推估強度 mu={lt['mu']:.2f}（gate={lt['gate_rel']:.2f}）{flag}")
        if lt["flagged_for_reask"]:
            print("  → 這項與您開場理念有些出入，已記下，稍後會再確認一次。")
        if lt["is_reask"]:
            r = lt["revision"]
            note = ("與先前一致，估計穩定" if abs(r) < 0.05
                    else (f"已下修此面向估計（Δ{r:.2f}）" if r < 0 else f"已上修此面向估計（Δ+{r:.2f}）"))
            print(f"  → 重新確認：{note}（修正，非重複計分）。")
        show_readout(snap, args.top_k)

    final_summary(snap, reason)


if __name__ == "__main__":
    main()
