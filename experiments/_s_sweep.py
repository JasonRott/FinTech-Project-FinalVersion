# -*- coding: utf-8 -*-
"""s_full vs s_noCAGR 比較（Arm C）。
問題：傾斜目標 s 含資本利得排名(Norm_Return_CAGR)會不會只是追一個不預測未來報酬的訊號？
決議(03 §1.1)：sweep 兩版 s_full(含CAGR排名) vs s_noCAGR(去掉) 用 OOS 決定。
設計：3 profile × 2 s-version × 2 τ。τ=0 兩版相同故不跑。報表/圖片產生 no-op 以加速。
跑前備份權重檔，跑後還原；parameters 旗標跑後還原。"""
import json
import shutil
import os
import pandas as pd
import parameters
import backtest_engine as be
from backtest_engine import run_rolling_backtest, BacktestConfig

PREF_FILE = "json/stage2_ahp_global_weights.json"
BACKUP = PREF_FILE + ".s_sweep_bak"
OUT_DIR = "upgrade_figures/s_sweep"
os.makedirs(OUT_DIR, exist_ok=True)

# 加速：把重 I/O 的報表與圖片鏡像 no-op（不影響回測數字）
be._write_unified_backtest_report = lambda *a, **k: None
be._mirror_run_figures_to_upgrade = lambda *a, **k: None

PROFILES = ["conservative", "balanced", "return_leaning"]
TAUS = [0.1, 0.3]
S_VERSIONS = [("full", True), ("noCAGR", False)]

orig_arm = getattr(parameters, "OPTIMIZATION_ARM", "A")
orig_tau = getattr(parameters, "TILT_STRENGTH", 0.1)
orig_inc = getattr(parameters, "TILT_INCLUDE_CAGR", True)
shutil.copyfile(PREF_FILE, BACKUP)

parameters.OPTIMIZATION_ARM = "C"
rows = []
vt_ref = {}
try:
    payload = json.load(open(PREF_FILE, encoding="utf-8"))
    for profile in PROFILES:
        # 寫入此 profile 權重
        payload["Global_Weights"] = dict(parameters.USER_PROFILES[profile])
        payload["Source"] = f"s_sweep::{profile}"
        json.dump(payload, open(PREF_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        for tau in TAUS:
            for sname, inc in S_VERSIONS:
                parameters.TILT_STRENGTH = tau
                parameters.TILT_INCLUDE_CAGR = inc
                print(f"\n=== {profile} | tau={tau} | s={sname} ===", flush=True)
                res = run_rolling_backtest(BacktestConfig())
                summ = res["summary"].set_index("Strategy")
                pref = res["preference_scores"]
                pd_row = summ.loc["Preference_Driven"]
                win_vt = float((pref["Forward_Score_vs_Benchmark"] > 0).mean() * 100) \
                    if "Forward_Score_vs_Benchmark" in pref.columns else float("nan")
                vt_cagr = float(summ.loc["VT", "CAGR_%"]) if "VT" in summ.index else float("nan")
                vt_ref.setdefault("VT_CAGR", vt_cagr)
                rows.append({
                    "profile": profile, "tau": tau, "s": sname,
                    "Sharpe": round(float(pd_row["Sharpe"]), 4),
                    "Vol": round(float(pd_row["Annualized_Volatility_%"]), 2),
                    "MaxDD": round(float(pd_row["Max_Drawdown_%"]), 2),
                    "CAGR": round(float(pd_row["CAGR_%"]), 2),
                    "VT_CAGR": round(vt_cagr, 2),
                    "beats_VT_CAGR": bool(float(pd_row["CAGR_%"]) > vt_cagr),
                    "win_VT": round(win_vt, 1),
                })
                pd.DataFrame(rows).to_csv(f"{OUT_DIR}/s_sweep_summary.csv", index=False)
finally:
    shutil.copyfile(BACKUP, PREF_FILE)
    os.remove(BACKUP)
    parameters.OPTIMIZATION_ARM = orig_arm
    parameters.TILT_STRENGTH = orig_tau
    parameters.TILT_INCLUDE_CAGR = orig_inc

df = pd.DataFrame(rows)
print("\n\n========== s_full vs s_noCAGR 結果 ==========")
print(df.to_string(index=False))
print(f"\n已存：{OUT_DIR}/s_sweep_summary.csv")
