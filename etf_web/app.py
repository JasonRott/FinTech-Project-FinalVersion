# -*- coding: utf-8 -*-
"""ETF 偏好驅動投資組合 —— 網頁版後端（接口骨架）。

設計目標：在 main.py 選「web」模式時，整個流程都在瀏覽器上跑、結果也在瀏覽器上呈現。
本檔提供完整「接口」（API + 背景執行 + 結果讀取），實際展示內容（版面/文案/圖表挑選）之後再細定。

流程（單一會話 demo）：
  ① 偏好問答  → 重用 etf_preference_bundle 的 Phase3 引擎（與「語意萃取網頁」同一套）；
                完成時透過 recommender_hook 把 9 維權重寫進 json/stage2_ahp_global_weights.json。
  ② 執行分析  → 背景執行緒跑完整 pipeline（Stage0~3，preference_mode="web_preference"）+ 偏好回測。
  ③ 結果呈現  → 讀取本次 user_results/new_user_{n}/ 的圖與報表，直接在網頁顯示。

API：
  GET  /                         → index.html
  POST /api/pref/start  {philosophy}    → {snapshot, action}     # 偏好問答：開場
  POST /api/pref/answer {answer}        → {snapshot, last_turn, action}
  POST /api/pref/choose {kind,decision} → {action}               # 早停/續答提議點
  GET  /api/pref/weights                → {weights, snapshot, delivered}
  POST /api/run         {fetch,backtest,freq}  → {started}        # 啟動 pipeline（背景）
  GET  /api/status                       → {state, log, user_dir, error}
  GET  /api/results                      → {state, figures:[{name,url,group}], reports:[{name,text}]}
  GET  /results-file/<relpath>           → 提供 user_results/ 底下的檔（圖片/報表）
"""
from __future__ import annotations

import os
import sys
import threading
import traceback
from pathlib import Path

# ── 路徑設定：專案根 + etf_preference_bundle（共用偏好引擎）──
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_BUNDLE_DIR = _PROJECT_ROOT / "etf_preference_bundle"
for _p in (str(_PROJECT_ROOT), str(_BUNDLE_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from flask import Flask, request, jsonify, render_template, send_from_directory, abort  # noqa: E402

# 偏好引擎（與語意萃取網頁同一套）+ 交付鉤子（寫 json/stage2_ahp_global_weights.json）
from phase3_system.engine import Phase3Engine  # noqa: E402
from recommender_hook import deliver_weights   # noqa: E402

app = Flask(__name__)

SHORT = {"Return_CAGR": "資本增值", "Return_Div": "股息現金流", "Risk_Vol": "波動穩健",
         "Risk_MaxDD": "抗跌", "Cost_ExpRatio": "費用率", "Liq_Volume": "成交量",
         "Liq_AUM": "基金規模", "Div_Score": "分散度", "FinBERT_score": "市場情緒"}

_USER_RESULTS_ROOT = _PROJECT_ROOT / "user_results"

# ── 偏好問答的單一會話狀態（沿用 bundle web 的提議流程）──
_S = {"engine": None, "continue_full": False, "continue_reask": False,
      "last_weights": None, "last_snapshot": None, "delivered": False}

# ── pipeline 背景執行狀態 ──
_RUN = {"state": "idle", "log": [], "user_dir": None, "error": None}
_RUN_LOCK = threading.Lock()


# =================== 偏好問答（重用 Phase3 引擎）===================
def _engine() -> Phase3Engine:
    if _S["engine"] is None:
        _S["engine"] = Phase3Engine()
    return _S["engine"]


def _finish(snap, reason):
    """問答完成出口：把 9 維權重交付到主系統 json（供 pipeline 的 web_preference 模式讀取）。"""
    weights = snap.get("Ew", {})
    _S["last_weights"], _S["last_snapshot"] = weights, snap
    try:
        deliver_weights(weights, snap)
        _S["delivered"] = True
    except Exception as ex:  # 交付失敗不影響問答流程
        _S["delivered"] = False
        _S["deliver_error"] = str(ex)
    return {"type": "done", "reason": reason, "snapshot": snap}


def _compute_next():
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
        return _finish(snap, reason)
    return {"type": "question", "q": q, "snapshot": snap}


@app.route("/")
def index():
    return render_template("index.html")


@app.post("/api/pref/start")
def api_pref_start():
    _S.update(continue_full=False, continue_reask=False, delivered=False)
    e = _engine()
    snap = e.start_session((request.json or {}).get("philosophy", ""))
    return jsonify({"snapshot": snap, "action": _compute_next()})


@app.post("/api/pref/answer")
def api_pref_answer():
    e = _S["engine"]
    snap = e.submit_answer((request.json or {}).get("answer", ""))
    return jsonify({"snapshot": snap, "last_turn": snap.get("last_turn"), "action": _compute_next()})


@app.post("/api/pref/choose")
def api_pref_choose():
    e = _S["engine"]
    body = request.json or {}
    kind, decision = body.get("kind"), body.get("decision")
    if decision == "stop":
        reason = ("系統判定已找到您最重視的面向（您選擇結束）" if kind == "T1"
                  else "已覆蓋全部 9 面向（完整可信結果），您選擇結束")
        return jsonify({"action": _finish(e.snapshot(), reason)})
    if kind == "T1":
        _S["continue_full"] = True
    else:
        _S["continue_reask"] = True
    return jsonify({"action": _compute_next()})


@app.get("/api/pref/weights")
def api_pref_weights():
    return jsonify({"weights": _S.get("last_weights"),
                    "snapshot": _S.get("last_snapshot"),
                    "delivered": _S.get("delivered", False)})


# =================== Pipeline 背景執行 ===================
class _Tee:
    """同時寫到原本的 stream 與記憶體緩衝，供網頁輪詢進度。"""
    def __init__(self, original, buf):
        self._o = original
        self._buf = buf

    def write(self, s):
        try:
            self._o.write(s)
        except Exception:
            pass
        if s:
            self._buf.append(s)
        return len(s)

    def flush(self):
        try:
            self._o.flush()
        except Exception:
            pass


def _emit(msg):
    _RUN["log"].append(str(msg) + "\n")


def _run_pipeline(opts):
    orig_out, orig_err = sys.stdout, sys.stderr
    buf = _RUN["log"]
    sys.stdout, sys.stderr = _Tee(orig_out, buf), _Tee(orig_err, buf)
    try:
        from pipeline_stages import (
            PipelineConfig, run_full_pipeline, run_preference_backtest_core,
        )
        import functions

        cfg = PipelineConfig(
            run_stage0_fetch=bool(opts.get("fetch", True)),
            run_stage0_feature_processing=bool(opts.get("fetch", True)),
            run_stage1_dea=True,
            run_stage2_1_preference=True,
            run_stage2_2_cluster_selection=True,
            run_stage3_optimization=True,
            run_stage3_backtest_prompt=False,        # 網頁版不在終端問
            preference_mode="web_preference",        # 讀剛剛瀏覽器問答產生的權重
            preference_output_path="json/stage2_ahp_global_weights.json",
        )
        run_full_pipeline(cfg)

        if bool(opts.get("backtest", True)):
            run_preference_backtest_core(
                rebalance_freq=str(opts.get("freq", "Q")),
                preference_file=cfg.preference_output_path,
                emit=_emit,
            )

        with _RUN_LOCK:
            _RUN["user_dir"] = getattr(functions, "LAST_MAIN_USER_DIR", None)
            _RUN["state"] = "done"
        _emit("\n✅ 全流程完成。")
    except Exception as ex:
        buf.append("\n[ERROR] " + traceback.format_exc())
        with _RUN_LOCK:
            _RUN["error"] = str(ex)
            _RUN["state"] = "error"
    finally:
        sys.stdout, sys.stderr = orig_out, orig_err


@app.post("/api/run")
def api_run():
    with _RUN_LOCK:
        if _RUN["state"] == "running":
            return jsonify({"started": False, "reason": "已在執行中"})
        _RUN.update(state="running", log=[], user_dir=None, error=None)
    opts = request.json or {}
    threading.Thread(target=_run_pipeline, args=(opts,), daemon=True).start()
    return jsonify({"started": True})


@app.get("/api/status")
def api_status():
    return jsonify({"state": _RUN["state"],
                    "log": "".join(_RUN["log"])[-12000:],   # 只回尾段，避免過大
                    "user_dir": _RUN["user_dir"],
                    "error": _RUN["error"]})


@app.get("/api/results")
def api_results():
    ud = _RUN.get("user_dir")
    figures, reports = [], []
    if ud and os.path.isdir(ud):
        root = str(_USER_RESULTS_ROOT)
        for dirpath, _dirs, files in os.walk(ud):
            group = os.path.relpath(dirpath, ud).replace("\\", "/")
            for f in sorted(files):
                full = os.path.join(dirpath, f)
                rel = os.path.relpath(full, root).replace("\\", "/")
                ext = f.lower().rsplit(".", 1)[-1] if "." in f else ""
                if ext == "png":
                    figures.append({"name": f, "url": "/results-file/" + rel,
                                    "group": "（根目錄）" if group == "." else group})
                elif ext in ("txt", "md"):
                    try:
                        text = Path(full).read_text(encoding="utf-8")
                    except Exception:
                        text = "(無法讀取)"
                    reports.append({"name": f, "group": group, "text": text})
    return jsonify({"state": _RUN["state"], "user_dir": ud,
                    "figures": figures, "reports": reports})


@app.get("/results-file/<path:relpath>")
def results_file(relpath):
    # 僅允許 user_results/ 底下的檔（send_from_directory 會擋路徑穿越）
    full = (_USER_RESULTS_ROOT / relpath).resolve()
    try:
        full.relative_to(_USER_RESULTS_ROOT.resolve())
    except ValueError:
        abort(404)
    if not full.is_file():
        abort(404)
    return send_from_directory(str(_USER_RESULTS_ROOT), relpath)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8050, debug=False)
