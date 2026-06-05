# -*- coding: utf-8 -*-
"""U-C2 多 profile 驗證 + risk_fraction 行為地圖（自主長跑）。

Part 1：7 profile × {C2(noCAGR), C2(full), Arm C baseline τ=0.1} — C2 三核心自動切換 vs 最小變異基線。
Part 2：risk_fraction 行為地圖 — beta/market 核心 profile × rf∈{0..1} step .1，
        檢驗「拉高風險預算（買 beta）能否真的換到更高 CAGR、逼近 VT 13.51%」。

報表/圖片 no-op 加速；跑前備份權重檔與 parameters，跑後全部還原。結果寫 upgrade_figures/c2_experiment/。"""
import json
import shutil
import os
import pandas as pd
import parameters
import backtest_engine as be
from backtest_engine import run_rolling_backtest, BacktestConfig
from functions import derive_params_from_weights

PREF_FILE = "json/stage2_ahp_global_weights.json"
BACKUP = PREF_FILE + ".c2_bak"
OUT_DIR = "upgrade_figures/c2_experiment"
os.makedirs(OUT_DIR, exist_ok=True)

be._write_unified_backtest_report = lambda *a, **k: None
be._mirror_run_figures_to_upgrade = lambda *a, **k: None

ALL_PROFILES = ["aggressive_growth", "return_leaning", "income", "cost_liquidity",
                "balanced", "diversified_quality", "conservative"]
RF_MAP_PROFILES = ["aggressive_growth", "return_leaning", "balanced"]
RF_GRID = [round(x / 10, 1) for x in range(0, 11)]  # 0.0..1.0

# 備份
orig = {k: getattr(parameters, k, None) for k in
        ["OPTIMIZATION_ARM", "TILT_STRENGTH", "TILT_INCLUDE_CAGR", "RISK_FRACTION_OVERRIDE"]}
shutil.copyfile(PREF_FILE, BACKUP)
payload = json.load(open(PREF_FILE, encoding="utf-8"))


def set_profile(profile):
    payload["Global_Weights"] = dict(parameters.USER_PROFILES[profile])
    payload["Source"] = f"c2_experiment::{profile}"
    json.dump(payload, open(PREF_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def metrics(res):
    summ = res["summary"].set_index("Strategy")
    pref = res["preference_scores"]
    pdr = summ.loc["Preference_Driven"]
    win_vt = float((pref["Forward_Score_vs_Benchmark"] > 0).mean() * 100) \
        if "Forward_Score_vs_Benchmark" in pref.columns else float("nan")
    def g(strat, col):
        return round(float(summ.loc[strat, col]), 3) if strat in summ.index else float("nan")
    return {
        "Sharpe": round(float(pdr["Sharpe"]), 4),
        "Vol": round(float(pdr["Annualized_Volatility_%"]), 2),
        "MaxDD": round(float(pdr["Max_Drawdown_%"]), 2),
        "CAGR": round(float(pdr["CAGR_%"]), 2),
        "win_VT": round(win_vt, 1),
        "VT_CAGR": g("VT", "CAGR_%"), "VT_Sharpe": g("VT", "Sharpe"), "VT_Vol": g("VT", "Annualized_Volatility_%"),
        "EW_CAGR": g("EqualWeight", "CAGR_%"), "EW_Sharpe": g("EqualWeight", "Sharpe"),
    }


part1, part2 = [], []
try:
    # ---------- Part 1：多 profile C2 vs Arm C ----------
    for profile in ALL_PROFILES:
        set_profile(profile)
        gp = derive_params_from_weights(parameters.USER_PROFILES[profile])
        base = {"profile": profile, "core_mode": gp["core_mode"], "T_growth": round(gp["T_growth"], 3),
                "tau": round(gp["tau"], 4), "risk_fraction": round(gp["risk_fraction"], 3)}
        # C2 noCAGR
        parameters.RISK_FRACTION_OVERRIDE = None
        for sname, inc in [("C2_noCAGR", False), ("C2_full", True)]:
            parameters.OPTIMIZATION_ARM = "C2"; parameters.TILT_INCLUDE_CAGR = inc
            print(f"\n=== Part1 {profile} | {sname} (core={gp['core_mode']}) ===", flush=True)
            part1.append({**base, "config": sname, **metrics(run_rolling_backtest(BacktestConfig()))})
            pd.DataFrame(part1).to_csv(f"{OUT_DIR}/c2_multiprofile_summary.csv", index=False)
        # Arm C baseline τ=0.1 s_full
        parameters.OPTIMIZATION_ARM = "C"; parameters.TILT_STRENGTH = 0.1; parameters.TILT_INCLUDE_CAGR = True
        print(f"\n=== Part1 {profile} | ArmC_tau0.1 ===", flush=True)
        part1.append({**base, "config": "ArmC_tau0.1", **metrics(run_rolling_backtest(BacktestConfig()))})
        pd.DataFrame(part1).to_csv(f"{OUT_DIR}/c2_multiprofile_summary.csv", index=False)

    # ---------- Part 2：risk_fraction 行為地圖（C2, noCAGR）----------
    parameters.OPTIMIZATION_ARM = "C2"; parameters.TILT_INCLUDE_CAGR = False
    for profile in RF_MAP_PROFILES:
        set_profile(profile)
        gp = derive_params_from_weights(parameters.USER_PROFILES[profile])
        for rf in RF_GRID:
            parameters.RISK_FRACTION_OVERRIDE = rf
            print(f"\n=== Part2 {profile} | rf={rf} (core={gp['core_mode']}) ===", flush=True)
            row = {"profile": profile, "core_mode": gp["core_mode"], "risk_fraction": rf,
                   **metrics(run_rolling_backtest(BacktestConfig()))}
            part2.append(row)
            pd.DataFrame(part2).to_csv(f"{OUT_DIR}/c2_riskfraction_map.csv", index=False)
finally:
    shutil.copyfile(BACKUP, PREF_FILE); os.remove(BACKUP)
    for k, v in orig.items():
        setattr(parameters, k, v)

print("\n\n========== Part 1: 多 profile C2 vs Arm C ==========")
print(pd.DataFrame(part1).to_string(index=False))
print("\n========== Part 2: risk_fraction 行為地圖 ==========")
print(pd.DataFrame(part2).to_string(index=False))
print(f"\n已存：{OUT_DIR}/c2_multiprofile_summary.csv 與 c2_riskfraction_map.csv")
print("DONE_C2_EXPERIMENT")
