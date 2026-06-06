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

import csv
import json
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
      "last_weights": None, "last_snapshot": None, "last_trace": [], "delivered": False}

# ── pipeline 背景執行狀態 ──
_RUN = {"state": "idle", "log": [], "user_dir": None, "error": None}
_RUN_LOCK = threading.Lock()

# 引擎鎖（防止「背景預熱」與「首個請求」重複建構；接上 bundle web/app.py 的改動）
_ENGINE_LOCK = threading.Lock()


# =================== 偏好問答（重用 Phase3 引擎）===================
def _engine() -> Phase3Engine:
    if _S["engine"] is None:
        with _ENGINE_LOCK:
            if _S["engine"] is None:
                _S["engine"] = Phase3Engine()
    return _S["engine"]


def _warmup():
    """背景預熱：伺服器一啟動就載 BGE-M3 + 9 個 BNN，使用者答第一題不必空等。"""
    try:
        _engine()
    except Exception:
        pass


# 模組載入（＝伺服器啟動）即背景預熱；daemon 執行緒不阻塞 Flask 綁定 port。
threading.Thread(target=_warmup, daemon=True, name="bge-warmup").start()


def _finish(snap, reason):
    """問答完成出口：把 9 維權重交付到主系統 json（供 pipeline 的 web_preference 模式讀取）。"""
    weights = snap.get("Ew", {})
    _S["last_weights"], _S["last_snapshot"] = weights, snap
    # 逐輪萃取過程 trace（每輪 μ 強度/σ 不確定性/gate/revision/Σα）—接上 bundle 的學術留存。
    _S["last_trace"] = list(getattr(_S.get("engine"), "history", []) or [])
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
                    "trace": _S.get("last_trace", []),
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


_DIM_ORDER = ["Return_CAGR", "Return_Div", "Risk_Vol", "Risk_MaxDD", "Cost_ExpRatio",
              "Liq_Volume", "Liq_AUM", "Div_Score", "FinBERT_score"]


def _csv_rows(path):
    try:
        with open(path, encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    except Exception:
        return []


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _dashboard_data(ud):
    """從本次 user_dir 蒐集敘事式儀表板要的結構化資料（數字/權重/持股/關鍵圖）。"""
    out = {"metrics": None, "weights": [], "holdings": [], "figures_map": {}, "key_urls": []}
    root = str(_USER_RESULTS_ROOT)
    png_by_name, summary_p, pref_p, port_w = {}, None, None, None
    for dp, _d, files in os.walk(ud):
        for f in files:
            full = os.path.join(dp, f)
            low = f.lower()
            if low.endswith(".png"):
                png_by_name[f] = "/results-file/" + os.path.relpath(full, root).replace("\\", "/")
            if low.endswith("backtest_q_summary.csv"):
                summary_p = full
            elif low.endswith("backtest_q_preference_scores.csv"):
                pref_p = full
            elif low.endswith("_weights.csv") and (os.sep + "02_portfolio" + os.sep) in full:
                port_w = full

    # 關鍵數字（系統 vs VT）
    if summary_p:
        rows = {r.get("Strategy"): r for r in _csv_rows(summary_p)}

        def _m(strat):
            r = rows.get(strat)
            if not r:
                return None
            return {"cagr": _num(r.get("CAGR_%")), "vol": _num(r.get("Annualized_Volatility_%")),
                    "sharpe": _num(r.get("Sharpe")), "mdd": _num(r.get("Max_Drawdown_%")),
                    "cum": _num(r.get("Cumulative_Return_%"))}

        sys_m, vt_m = _m("Preference_Driven"), _m("VT")
        win_vt = None
        if pref_p:
            pairs = [(_num(r.get("Portfolio_Forward_Preference_Score")),
                      _num(r.get("Benchmark_Forward_Preference_Score"))) for r in _csv_rows(pref_p)]
            pairs = [(a, b) for a, b in pairs if a is not None and b is not None]
            if pairs:
                win_vt = round(sum(1 for a, b in pairs if a > b) / len(pairs) * 100, 1)
        if sys_m:
            out["metrics"] = {"system": sys_m, "vt": vt_m, "win_vt": win_vt}

    # 9 維偏好權重（本次 run 的全域權重）
    try:
        gj = json_loads_safe(_PROJECT_ROOT / "json" / "stage2_ahp_global_weights.json")
        gw = (gj or {}).get("Global_Weights", {})
        out["weights"] = [{"dim": d, "label": SHORT.get(d, d), "weight": float(gw.get(d, 0.0) or 0.0)}
                          for d in _DIM_ORDER]
    except Exception:
        pass

    # 推薦投組持股（偏好組合權重 %）
    if port_w:
        for r in _csv_rows(port_w):
            etf = r.get("ETF")
            wcol = next((k for k in r.keys() if k and "偏好" in k), None)
            w = _num(r.get(wcol)) if wcol else None
            if etf and w and w > 0:
                out["holdings"].append({"etf": etf, "weight": w})
        out["holdings"].sort(key=lambda x: -x["weight"])

    # 關鍵圖（依檔名挑）
    def pick(*subs, exclude=()):
        for name, url in png_by_name.items():
            ln = name.lower()
            if all(s in ln for s in subs) and not any(e in ln for e in exclude):
                return url
        return None

    fm = {
        "nav": pick("_nav.png"),
        "metrics_comparison": pick("metrics_comparison"),
        "backtest_radar": pick("preference_radar_vs_benchmark"),
        "v6": pick("preference_score_timeseries"),
        "v1": pick("preference_predictive_scatter"),
        "main_radar": pick("radar_chart"),
        "frontier": pick("efficient frontier"),
        "drawdown": pick("_drawdown.png"),
    }
    out["figures_map"] = fm
    out["key_urls"] = [u for u in fm.values() if u]
    return out


def json_loads_safe(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None


@app.get("/api/results")
def api_results():
    ud = _RUN.get("user_dir")
    figures, reports, dash = [], [], None
    if ud and os.path.isdir(ud):
        dash = _dashboard_data(ud)
        key_urls = set(dash.get("key_urls", []))
        root = str(_USER_RESULTS_ROOT)
        for dirpath, _dirs, files in os.walk(ud):
            group = os.path.relpath(dirpath, ud).replace("\\", "/")
            for f in sorted(files):
                full = os.path.join(dirpath, f)
                rel = os.path.relpath(full, root).replace("\\", "/")
                url = "/results-file/" + rel
                ext = f.lower().rsplit(".", 1)[-1] if "." in f else ""
                if ext == "png":
                    if url in key_urls:
                        continue  # 關鍵圖已在儀表板上方呈現，明細區不重複
                    figures.append({"name": f, "url": url,
                                    "group": "（根目錄）" if group == "." else group})
                elif ext in ("txt", "md"):
                    try:
                        text = Path(full).read_text(encoding="utf-8")
                    except Exception:
                        text = "(無法讀取)"
                    reports.append({"name": f, "group": group, "text": text})
    return jsonify({"state": _RUN["state"], "user_dir": ud,
                    "dashboard": dash, "figures": figures, "reports": reports})


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
