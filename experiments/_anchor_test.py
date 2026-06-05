# -*- coding: utf-8 -*-
"""簡單驗證：beta/市場錨 VT vs VTI（整體美國市場）對「報酬導向 vs 保守」價差的影響。
解耦：報告基準維持 VT，只換 beta 錨。C2 noCAGR。少數窗（標準 5y + 2022 熊市窗）。
保守(minvar)不受錨影響，當控制組（兩錨應幾乎相同）。跑前備份/跑後還原。"""
import json, shutil, os
import pandas as pd
import parameters
import backtest_engine as be
from backtest_engine import run_rolling_backtest, BacktestConfig
from functions import derive_params_from_weights

PREF_FILE = "json/stage2_ahp_global_weights.json"
BACKUP = PREF_FILE + ".anchor_bak"
OUT = "upgrade_figures/anchor_test"
os.makedirs(OUT, exist_ok=True)
be._write_unified_backtest_report = lambda *a, **k: None
be._mirror_run_figures_to_upgrade = lambda *a, **k: None

PROFILES = ["aggressive_growth", "return_leaning", "balanced", "conservative"]
ANCHORS = ["VT", "VTI"]
WINDOWS = [("2021-06-01","2026-05-22"), ("2020-06-01","2023-06-01")]  # 標準5y + 含2022熊市

payload = json.load(open(PREF_FILE, encoding="utf-8"))
def set_profile(p):
    payload["Global_Weights"] = dict(parameters.USER_PROFILES[p]); payload["Source"] = f"anchor::{p}"
    json.dump(payload, open(PREF_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

def basic(res):
    s = res["summary"].set_index("Strategy"); pr = res["preference_scores"]; pd_ = s.loc["Preference_Driven"]
    def g(st, c): return round(float(s.loc[st, c]),3) if st in s.index else float("nan")
    vt = g("VT","CAGR_%")
    win = round(float((pr["Forward_Score_vs_Benchmark"]>0).mean()*100),1) if "Forward_Score_vs_Benchmark" in pr.columns else float("nan")
    return {"Sharpe":round(float(pd_["Sharpe"]),3),"Vol":round(float(pd_["Annualized_Volatility_%"]),2),
            "MaxDD":round(float(pd_["Max_Drawdown_%"]),2),"CAGR":round(float(pd_["CAGR_%"]),2),
            "VT_CAGR":vt,"beats_VT":bool(float(pd_["CAGR_%"])>vt) if pd.notna(vt) else None,"win_VT":win}

orig = {k:getattr(parameters,k,None) for k in ["OPTIMIZATION_ARM","TILT_INCLUDE_CAGR","RISK_FRACTION_OVERRIDE","BETA_ANCHOR_TICKER"]}
shutil.copyfile(PREF_FILE, BACKUP)
parameters.OPTIMIZATION_ARM="C2"; parameters.TILT_INCLUDE_CAGR=False; parameters.RISK_FRACTION_OVERRIDE=None
rows=[]
try:
    for anchor in ANCHORS:
        parameters.BETA_ANCHOR_TICKER = anchor
        for p in PROFILES:
            set_profile(p); core = derive_params_from_weights(parameters.USER_PROFILES[p])["core_mode"]
            for ws,we in WINDOWS:
                print(f"\n=== anchor={anchor} {p}({core}) {ws[:7]}->{we[:7]} ===", flush=True)
                try:
                    rows.append({"anchor":anchor,"profile":p,"core":core,"window":f"{ws[:7]}_{we[:7]}",
                                 **basic(run_rolling_backtest(BacktestConfig(start_date=ws,end_date=we,lookback_years=2,fetch_missing_data=False)))})
                except Exception as e:
                    rows.append({"anchor":anchor,"profile":p,"core":core,"window":f"{ws[:7]}_{we[:7]}","error":str(e)[:80]})
                pd.DataFrame(rows).to_csv(f"{OUT}/anchor_test.csv", index=False)
finally:
    shutil.copyfile(BACKUP, PREF_FILE); os.remove(BACKUP)
    for k,v in orig.items(): setattr(parameters,k,v)

df = pd.DataFrame(rows)
print("\n\n===== VT vs VTI 錨 =====")
print(df.to_string(index=False))
print("\nDONE_ANCHOR_TEST")
