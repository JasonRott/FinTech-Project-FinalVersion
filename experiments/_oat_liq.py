# -*- coding: utf-8 -*-
"""OAT-3：合併流動性下限 off vs on。C2 noCAGR + beta 評分。季度再平衡。
7 profile × 2 窗 × {off, liq}。預期幾乎全 inert(liq tightness 幾乎都 0)。量 CAGR/Sharpe/win_VT。"""
import json, shutil, os
import pandas as pd, numpy as np
import parameters
import backtest_engine as be
from backtest_engine import run_rolling_backtest, BacktestConfig
from functions import quality_tightness_map

PREF_FILE = "json/stage2_ahp_global_weights.json"; BACKUP = PREF_FILE + ".oat3_bak"
OUT = "upgrade_figures/oat_liq"; os.makedirs(OUT, exist_ok=True)
be._write_unified_backtest_report = lambda *a, **k: None
be._mirror_run_figures_to_upgrade = lambda *a, **k: None

PROFILES = ["aggressive_growth","return_leaning","balanced","income","conservative","cost_liquidity","diversified_quality"]
WINDOWS = [("2021-06-01","2026-05-22"), ("2020-06-01","2023-06-01")]

payload = json.load(open(PREF_FILE, encoding="utf-8"))
def set_profile(p):
    payload["Global_Weights"]=dict(parameters.USER_PROFILES[p]); payload["Source"]=f"oat3::{p}"
    json.dump(payload, open(PREF_FILE,"w",encoding="utf-8"), ensure_ascii=False, indent=2)

def metrics(res):
    s=res["summary"].set_index("Strategy"); pr=res["preference_scores"]; pd_=s.loc["Preference_Driven"]
    vt=round(float(s.loc["VT","CAGR_%"]),2) if "VT" in s.index else float("nan")
    win=round(float((pr["Forward_Score_vs_Benchmark"]>0).mean()*100),1) if "Forward_Score_vs_Benchmark" in pr.columns else float("nan")
    return {"Sharpe":round(float(pd_["Sharpe"]),3),"Vol":round(float(pd_["Annualized_Volatility_%"]),2),
            "MaxDD":round(float(pd_["Max_Drawdown_%"]),2),"CAGR":round(float(pd_["CAGR_%"]),2),
            "win_VT":win,"VT_CAGR":vt}

orig={k:getattr(parameters,k,None) for k in ["OPTIMIZATION_ARM","TILT_INCLUDE_CAGR","PREF_RETURN_BASIS","USE_QUALITY_CONSTRAINTS","QC_ENABLE_COST","QC_ENABLE_HHI","QC_ENABLE_LIQ","QC_ENABLE_SENT"]}
shutil.copyfile(PREF_FILE, BACKUP)
parameters.OPTIMIZATION_ARM="C2"; parameters.TILT_INCLUDE_CAGR=False; parameters.PREF_RETURN_BASIS="beta"
parameters.QC_ENABLE_COST=False; parameters.QC_ENABLE_HHI=False; parameters.QC_ENABLE_SENT=False
rows=[]
try:
    for p in PROFILES:
        set_profile(p)
        liq_ts = round(quality_tightness_map(parameters.USER_PROFILES[p])["liq"], 3)
        for mode in ["off","liq"]:
            parameters.USE_QUALITY_CONSTRAINTS = (mode=="liq")
            parameters.QC_ENABLE_LIQ = (mode=="liq")
            for ws,we in WINDOWS:
                print(f"\n=== {p} {mode} {ws[:7]}->{we[:7]} (Q) liq_ts={liq_ts} ===", flush=True)
                try: rows.append({"profile":p,"liq_ts":liq_ts,"mode":mode,"window":f"{ws[:7]}_{we[:7]}",**metrics(run_rolling_backtest(BacktestConfig(start_date=ws,end_date=we,lookback_years=2,rebalance_freq="Q",fetch_missing_data=False)))})
                except Exception as e: rows.append({"profile":p,"liq_ts":liq_ts,"mode":mode,"window":f"{ws[:7]}_{we[:7]}","error":str(e)[:90]})
                pd.DataFrame(rows).to_csv(f"{OUT}/oat_liq.csv", index=False)
finally:
    shutil.copyfile(BACKUP, PREF_FILE); os.remove(BACKUP)
    for k,v in orig.items(): setattr(parameters,k,v)

print("\n\n===== OAT-3 流動性 off vs on (季度) =====")
print(pd.DataFrame(rows).to_string(index=False))
print("\nDONE_OAT_LIQ")
