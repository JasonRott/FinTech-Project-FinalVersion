# -*- coding: utf-8 -*-
"""測試：偏好分數的「報酬維度」改用 beta 為基礎，能否讓報酬導向使用者的 win_VT 跳高。
最佳化器不變(C2 noCAGR)→ 投組完全相同 → 乾淨 A/B,只有評分基礎(PREF_RETURN_BASIS)變。
比較每 profile 在 cagr-basis vs beta-basis 下的 win_VT（事後偏好分數贏 VT 的期數佔比）。"""
import json, shutil, os
import pandas as pd
import parameters
import backtest_engine as be
from backtest_engine import run_rolling_backtest, BacktestConfig
from functions import derive_params_from_weights

PREF_FILE = "json/stage2_ahp_global_weights.json"
BACKUP = PREF_FILE + ".beta_bak"
OUT = "upgrade_figures/beta_score_test"
os.makedirs(OUT, exist_ok=True)
be._write_unified_backtest_report = lambda *a, **k: None
be._mirror_run_figures_to_upgrade = lambda *a, **k: None

PROFILES = ["aggressive_growth", "return_leaning", "balanced", "income", "conservative"]
WINDOWS = [("2021-06-01","2026-05-22"), ("2020-06-01","2023-06-01")]
BASES = ["cagr", "beta"]

payload = json.load(open(PREF_FILE, encoding="utf-8"))
def set_profile(p):
    payload["Global_Weights"] = dict(parameters.USER_PROFILES[p]); payload["Source"]=f"betatest::{p}"
    json.dump(payload, open(PREF_FILE,"w",encoding="utf-8"), ensure_ascii=False, indent=2)

def winrates(res):
    pr = res["preference_scores"]
    def wr(col): return round(float((pr[col]>0).mean()*100),1) if col in pr.columns else float("nan")
    s = res["summary"].set_index("Strategy"); pd_=s.loc["Preference_Driven"]
    return {"win_VT": wr("Forward_Score_vs_Benchmark"), "win_EW": wr("Forward_Score_vs_EqualWeight"),
            "win_MS": wr("Forward_Score_vs_MaxSharpe"),
            "CAGR": round(float(pd_["CAGR_%"]),2), "Sharpe": round(float(pd_["Sharpe"]),3)}

orig = {k:getattr(parameters,k,None) for k in ["OPTIMIZATION_ARM","TILT_INCLUDE_CAGR","RISK_FRACTION_OVERRIDE","PREF_RETURN_BASIS"]}
shutil.copyfile(PREF_FILE, BACKUP)
parameters.OPTIMIZATION_ARM="C2"; parameters.TILT_INCLUDE_CAGR=False; parameters.RISK_FRACTION_OVERRIDE=None
rows=[]
try:
    for p in PROFILES:
        set_profile(p); core=derive_params_from_weights(parameters.USER_PROFILES[p])["core_mode"]
        for ws,we in WINDOWS:
            for basis in BASES:
                parameters.PREF_RETURN_BASIS = basis
                print(f"\n=== {p}({core}) {ws[:7]}->{we[:7]} basis={basis} ===", flush=True)
                try:
                    rows.append({"profile":p,"core":core,"window":f"{ws[:7]}_{we[:7]}","basis":basis,
                                 **winrates(run_rolling_backtest(BacktestConfig(start_date=ws,end_date=we,lookback_years=2,fetch_missing_data=False)))})
                except Exception as e:
                    rows.append({"profile":p,"core":core,"window":f"{ws[:7]}_{we[:7]}","basis":basis,"error":str(e)[:80]})
                pd.DataFrame(rows).to_csv(f"{OUT}/beta_score_test.csv", index=False)
finally:
    shutil.copyfile(BACKUP, PREF_FILE); os.remove(BACKUP)
    for k,v in orig.items(): setattr(parameters,k,v)

df = pd.DataFrame(rows)
print("\n\n===== win_VT: cagr-basis vs beta-basis =====")
# pivot for readability
try:
    piv = df.pivot_table(index=["profile","core","window"], columns="basis", values="win_VT")
    print(piv.to_string())
except Exception:
    print(df.to_string(index=False))
print("\nDONE_BETA_SCORE_TEST")
