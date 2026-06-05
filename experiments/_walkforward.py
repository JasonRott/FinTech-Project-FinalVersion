# -*- coding: utf-8 -*-
"""Walk-forward 穩健性驗證：確認 C2(noCAGR) 的「贏 VT / 風險換報酬」不是 2021–26 單一路徑運氣。

資料：cache 2016-05 ~ 2026-05。兩軸：
  Axis A 時間窗（lookback=2y 固定）：6 個滾動 3 年 OOS 窗（2018-06 起），跨 COVID/2022 熊市/復甦。
  Axis B lookback（窗 2021-06~2026-05 固定）：lookback∈{1,2,3,5}y，看估計窗敏感度。
7 profile × C2(noCAGR)。VT/EqualWeight 每窗各自重算（VT 報酬隨窗變）。
報表/圖片 no-op 加速；跑前備份權重檔與 parameters，跑後全部還原。"""
import json, shutil, os
import pandas as pd
import parameters
import backtest_engine as be
from backtest_engine import run_rolling_backtest, BacktestConfig
from functions import derive_params_from_weights

PREF_FILE = "json/stage2_ahp_global_weights.json"
BACKUP = PREF_FILE + ".wf_bak"
OUT_DIR = "upgrade_figures/walkforward"
os.makedirs(OUT_DIR, exist_ok=True)
be._write_unified_backtest_report = lambda *a, **k: None
be._mirror_run_figures_to_upgrade = lambda *a, **k: None

PROFILES = ["aggressive_growth", "return_leaning", "income", "cost_liquidity",
            "balanced", "diversified_quality", "conservative"]
# Axis A: rolling 3y windows, lookback 2y
TIME_WINDOWS = [("2018-06-01","2021-06-01"), ("2019-06-01","2022-06-01"),
                ("2020-06-01","2023-06-01"), ("2021-06-01","2024-06-01"),
                ("2022-06-01","2025-06-01"), ("2023-06-01","2026-05-22")]
# Axis B: fixed window, varying lookback
LB_WINDOW = ("2021-06-01","2026-05-22")
LOOKBACKS = [1, 2, 3, 5]

orig = {k: getattr(parameters, k, None) for k in
        ["OPTIMIZATION_ARM", "TILT_INCLUDE_CAGR", "RISK_FRACTION_OVERRIDE"]}
shutil.copyfile(PREF_FILE, BACKUP)
payload = json.load(open(PREF_FILE, encoding="utf-8"))

def set_profile(p):
    payload["Global_Weights"] = dict(parameters.USER_PROFILES[p])
    payload["Source"] = f"walkforward::{p}"
    json.dump(payload, open(PREF_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

def cfg_run(start, end, lookback):
    return run_rolling_backtest(BacktestConfig(
        start_date=start, end_date=end, lookback_years=lookback, fetch_missing_data=False))

def metrics(res):
    summ = res["summary"].set_index("Strategy")
    pref = res["preference_scores"]
    pdr = summ.loc["Preference_Driven"]
    def g(s, c):
        return round(float(summ.loc[s, c]), 3) if s in summ.index else float("nan")
    win_vt = round(float((pref["Forward_Score_vs_Benchmark"] > 0).mean() * 100), 1) \
        if "Forward_Score_vs_Benchmark" in pref.columns else float("nan")
    vt_cagr = g("VT", "CAGR_%")
    return {"Sharpe": round(float(pdr["Sharpe"]), 3), "Vol": round(float(pdr["Annualized_Volatility_%"]), 2),
            "MaxDD": round(float(pdr["Max_Drawdown_%"]), 2), "CAGR": round(float(pdr["CAGR_%"]), 2),
            "VT_CAGR": vt_cagr, "VT_Sharpe": g("VT", "Sharpe"),
            "EW_CAGR": g("EqualWeight", "CAGR_%"), "EW_Sharpe": g("EqualWeight", "Sharpe"),
            "beats_VT_CAGR": bool(float(pdr["CAGR_%"]) > vt_cagr) if pd.notna(vt_cagr) else None,
            "beats_VT_Sharpe": bool(float(pdr["Sharpe"]) > g("VT", "Sharpe")) if pd.notna(g("VT","Sharpe")) else None,
            "win_VT": win_vt, "n_periods": int(len(pref))}

partA, partB = [], []
parameters.OPTIMIZATION_ARM = "C2"; parameters.TILT_INCLUDE_CAGR = False; parameters.RISK_FRACTION_OVERRIDE = None
try:
    # Axis A: time windows (lookback 2y)
    for p in PROFILES:
        set_profile(p)
        core = derive_params_from_weights(parameters.USER_PROFILES[p])["core_mode"]
        for (ws, we) in TIME_WINDOWS:
            print(f"\n=== [A] {p} ({core}) window {ws[:7]}->{we[:7]} lb=2 ===", flush=True)
            try:
                partA.append({"profile": p, "core": core, "window": f"{ws[:7]}_{we[:7]}", **metrics(cfg_run(ws, we, 2))})
            except Exception as e:
                partA.append({"profile": p, "core": core, "window": f"{ws[:7]}_{we[:7]}", "error": str(e)[:80]})
            pd.DataFrame(partA).to_csv(f"{OUT_DIR}/wf_timewindow.csv", index=False)
    # Axis B: lookback sensitivity (fixed window)
    for p in PROFILES:
        set_profile(p)
        core = derive_params_from_weights(parameters.USER_PROFILES[p])["core_mode"]
        for lb in LOOKBACKS:
            print(f"\n=== [B] {p} ({core}) lb={lb} window 2021-06->2026-05 ===", flush=True)
            try:
                partB.append({"profile": p, "core": core, "lookback": lb, **metrics(cfg_run(*LB_WINDOW, lb))})
            except Exception as e:
                partB.append({"profile": p, "core": core, "lookback": lb, "error": str(e)[:80]})
            pd.DataFrame(partB).to_csv(f"{OUT_DIR}/wf_lookback.csv", index=False)
finally:
    shutil.copyfile(BACKUP, PREF_FILE); os.remove(BACKUP)
    for k, v in orig.items():
        setattr(parameters, k, v)

print("\n\n===== Axis A: time-window robustness (lb=2y) =====")
print(pd.DataFrame(partA).to_string(index=False))
print("\n===== Axis B: lookback sensitivity (window 2021-06~2026-05) =====")
print(pd.DataFrame(partB).to_string(index=False))
print("\nDONE_WALKFORWARD")
