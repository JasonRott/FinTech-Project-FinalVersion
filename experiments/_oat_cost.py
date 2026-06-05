# -*- coding: utf-8 -*-
"""OAT-1：成本約束(新框架) off vs on。C2 noCAGR + beta 評分(現行預設)。
7 profile × 2 窗 × {off, cost}。量 CAGR/Sharpe/MaxDD/win_VT + 投組加權平均費用率(確認約束有咬到)。"""
import json, shutil, os
import pandas as pd, numpy as np
import parameters
import backtest_engine as be
from backtest_engine import run_rolling_backtest, BacktestConfig

PREF_FILE = "json/stage2_ahp_global_weights.json"; BACKUP = PREF_FILE + ".oat_bak"
OUT = "upgrade_figures/oat_cost"; os.makedirs(OUT, exist_ok=True)
be._write_unified_backtest_report = lambda *a, **k: None
be._mirror_run_figures_to_upgrade = lambda *a, **k: None

PROFILES = ["aggressive_growth","return_leaning","balanced","income","conservative","cost_liquidity","diversified_quality"]
WINDOWS = [("2021-06-01","2026-05-22"), ("2020-06-01","2023-06-01")]
COSTS = pd.read_csv("csv/stage0_final_matrix.csv").set_index("ETF")["Cost_ExpRatio (%)"]

payload = json.load(open(PREF_FILE, encoding="utf-8"))
def set_profile(p):
    payload["Global_Weights"]=dict(parameters.USER_PROFILES[p]); payload["Source"]=f"oat::{p}"
    json.dump(payload, open(PREF_FILE,"w",encoding="utf-8"), ensure_ascii=False, indent=2)

def metrics(res):
    s=res["summary"].set_index("Strategy"); pr=res["preference_scores"]; pd_=s.loc["Preference_Driven"]
    vt=round(float(s.loc["VT","CAGR_%"]),2) if "VT" in s.index else float("nan")
    win=round(float((pr["Forward_Score_vs_Benchmark"]>0).mean()*100),1) if "Forward_Score_vs_Benchmark" in pr.columns else float("nan")
    # 投組加權平均費用率（逐期再平均）
    wdf=res["weights"].copy(); wdf["c"]=wdf["ETF"].map(COSTS)
    per=wdf.groupby("Rebalance_Date").apply(lambda g:(g["Weight"]*g["c"]).sum()/max(g["Weight"].sum(),1e-9))
    avgcost=round(float(per.mean()),4)
    return {"Sharpe":round(float(pd_["Sharpe"]),3),"Vol":round(float(pd_["Annualized_Volatility_%"]),2),
            "MaxDD":round(float(pd_["Max_Drawdown_%"]),2),"CAGR":round(float(pd_["CAGR_%"]),2),
            "win_VT":win,"VT_CAGR":vt,"avg_cost":avgcost}

orig={k:getattr(parameters,k,None) for k in ["OPTIMIZATION_ARM","TILT_INCLUDE_CAGR","PREF_RETURN_BASIS","USE_QUALITY_CONSTRAINTS","QC_ENABLE_COST","QC_ENABLE_HHI","QC_ENABLE_LIQ","QC_ENABLE_SENT"]}
shutil.copyfile(PREF_FILE, BACKUP)
parameters.OPTIMIZATION_ARM="C2"; parameters.TILT_INCLUDE_CAGR=False; parameters.PREF_RETURN_BASIS="beta"
parameters.QC_ENABLE_HHI=False; parameters.QC_ENABLE_LIQ=False; parameters.QC_ENABLE_SENT=False
rows=[]
try:
    for p in PROFILES:
        set_profile(p)
        for mode in ["off","cost"]:
            parameters.USE_QUALITY_CONSTRAINTS = (mode=="cost")
            parameters.QC_ENABLE_COST = (mode=="cost")
            for ws,we in WINDOWS:
                print(f"\n=== {p} {mode} {ws[:7]}->{we[:7]} ===", flush=True)
                try: rows.append({"profile":p,"mode":mode,"window":f"{ws[:7]}_{we[:7]}",**metrics(run_rolling_backtest(BacktestConfig(start_date=ws,end_date=we,lookback_years=2,fetch_missing_data=False)))})
                except Exception as e: rows.append({"profile":p,"mode":mode,"window":f"{ws[:7]}_{we[:7]}","error":str(e)[:90]})
                pd.DataFrame(rows).to_csv(f"{OUT}/oat_cost.csv", index=False)
finally:
    shutil.copyfile(BACKUP, PREF_FILE); os.remove(BACKUP)
    for k,v in orig.items(): setattr(parameters,k,v)

print("\n\n===== OAT-1 成本約束 off vs on =====")
print(pd.DataFrame(rows).to_string(index=False))
print("\nDONE_OAT_COST")
