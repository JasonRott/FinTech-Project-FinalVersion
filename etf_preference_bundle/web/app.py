"""Phase 3 互動偏好誘出 — Flask 後端（API 包同一個 phase3_system 引擎）。

單一會話（個人 demo / 口頭發表用）。流程控制（兩提議 + T3）在後端，前端只負責渲染與互動。
API：
  GET  /              → index.html
  POST /api/start     {philosophy}        → {snapshot, action}
  POST /api/answer    {answer}            → {snapshot, last_turn, action}
  POST /api/choose    {kind, decision}    → {action}     # 提議點：continue / stop
  POST /api/reset                          → {ok}
  GET  /api/result                         → {weights, snapshot, delivered}   # 外部程式取權重
action.type ∈ {question, offer(kind=T1|T2), done}
問答完成時自動把 9 維權重交付給 web/integration.deliver_weights()，並寫入 last_result.json。
"""
from __future__ import annotations
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # 讓 phase3_system 可匯入

from flask import Flask, request, jsonify, render_template
from phase3_system.engine import Phase3Engine, DIM_LABELS  # noqa: E402
from web.integration import deliver_weights  # noqa: E402  ← 你的交付鉤子

app = Flask(__name__)

SHORT = {"Return_CAGR": "資本增值", "Return_Div": "股息現金流", "Risk_Vol": "波動穩健",
         "Risk_MaxDD": "抗跌", "Cost_ExpRatio": "費用率", "Liq_Volume": "成交量",
         "Liq_AUM": "基金規模", "Div_Score": "分散度", "FinBERT_score": "市場情緒"}

_S = {"engine": None, "continue_full": False, "continue_reask": False, "reason": None,
      "last_weights": None, "last_snapshot": None, "delivered": False}

RESULT_PATH = Path(__file__).resolve().parent / "last_result.json"


def engine():
    if _S["engine"] is None:
        _S["engine"] = Phase3Engine()
    return _S["engine"]


def _finish(snap, reason):
    """問答完成的統一出口:把 9 維權重交付給外部推薦程式 + 保存最後結果。"""
    weights = snap.get("Ew", {})
    _S["last_weights"], _S["last_snapshot"] = weights, snap
    # ① in-process 交付鉤子(你在 web/integration.py 接推薦模組)
    try:
        _S["delivery_result"] = deliver_weights(weights, snap)
        _S["delivered"] = True
    except Exception as ex:  # 交付失敗不影響問答流程
        _S["delivered"], _S["delivery_error"] = False, str(ex)
    # ② 同時寫一份檔,方便「另一個會自己跑」的程式讀取
    try:
        RESULT_PATH.write_text(
            json.dumps({"weights": weights, "snapshot": snap}, ensure_ascii=False, indent=2),
            encoding="utf-8")
    except Exception:
        pass
    return {"type": "done", "reason": reason, "snapshot": snap}


def compute_next():
    e = _S["engine"]
    snap = e.snapshot()
    if e.phase == "coverage" and e.should_stop() and not _S["continue_full"]:
        return {"type": "offer", "kind": "T1", "snapshot": snap,
                "title": "已找到您最重視的面向",
                "message": f"系統已能排出您最重視的面向（已問 {snap['n_asked']} 題）。"
                           f"可以就此結束；或繼續問完整 9 個面向以取得完整、可信賴的結果。",
                "continue_label": "繼續問完整 9 面向", "stop_label": "結束（看排序）"}
    if e.all_covered() and e.t3_pending() and not _S["continue_reask"]:
        names = "、".join(SHORT.get(x, x) for x in snap["pending_conflicts"])
        return {"type": "offer", "kind": "T2", "snapshot": snap,
                "title": "9 個面向都問完了",
                "message": f"目前是完整、CI 可信的結果。可以就此結束；"
                           f"或讓系統對與您理念有出入的 {len(snap['pending_conflicts'])} 項（{names}）做最後重新確認。",
                "continue_label": "做最後確認", "stop_label": "結束（完整結果）"}
    q = e.next_question()
    if q is None:
        reason = ("已覆蓋全部面向，並完成衝突確認、信念穩定" if e.conflict_flags
                  else "已覆蓋全部面向，無與理念衝突需確認")
        _S["reason"] = reason
        return _finish(snap, reason)
    return {"type": "question", "q": q, "snapshot": snap}


@app.route("/")
def index():
    return render_template("index.html")


@app.post("/api/start")
def api_start():
    _S.update(continue_full=False, continue_reask=False, reason=None)
    e = engine()
    snap = e.start_session((request.json or {}).get("philosophy", ""))
    return jsonify({"snapshot": snap, "action": compute_next()})


@app.post("/api/answer")
def api_answer():
    e = _S["engine"]
    snap = e.submit_answer((request.json or {}).get("answer", ""))
    return jsonify({"snapshot": snap, "last_turn": snap.get("last_turn"), "action": compute_next()})


@app.post("/api/choose")
def api_choose():
    e = _S["engine"]
    body = request.json or {}
    kind, decision = body.get("kind"), body.get("decision")
    if decision == "stop":
        reason = ("系統判定已找到您最重視的面向（您選擇結束）" if kind == "T1"
                  else "已覆蓋全部 9 面向（完整可信結果），您選擇結束")
        _S["reason"] = reason
        return jsonify({"action": _finish(e.snapshot(), reason)})
    if kind == "T1":
        _S["continue_full"] = True
    else:
        _S["continue_reask"] = True
    return jsonify({"action": compute_next()})


@app.post("/api/reset")
def api_reset():
    _S.update(continue_full=False, continue_reask=False, reason=None)
    if _S["engine"] is not None:
        _S["engine"]._reset_state()
    return jsonify({"ok": True})


@app.get("/api/result")
def api_result():
    """外部程式可用 HTTP 取得「最近一次問答完成」的 9 維權重與完整快照。
    回傳 {"weights": {...} 或 null, "snapshot": {...} 或 null, "delivered": bool}"""
    return jsonify({"weights": _S.get("last_weights"),
                    "snapshot": _S.get("last_snapshot"),
                    "delivered": _S.get("delivered", False)})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000, debug=False)
