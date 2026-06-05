# -*- coding: utf-8 -*-
"""出門期間排隊實驗（在 walk-forward 之後依序自動跑）。三個實驗：
  Exp3 noCAGR vs full 跨區穩健性（Arm C τ=0.3，3 profile × 2 s × 6 窗）
  Exp4 risk_fraction 跨區穩定性（C2 noCAGR，3 profile × 5 rf × 3 規制窗）
  Exp5 DCA 定期定額（C2 noCAGR，4 profile × 6 窗 × {單筆,DCA}，金額加權終值/IRR）
報表/圖片 no-op；跑前備份權重檔+parameters，跑後全部還原。每個實驗各寫一個 CSV。"""
import json, shutil, os
import numpy as np, pandas as pd
import parameters
import backtest_engine as be
from backtest_engine import run_rolling_backtest, BacktestConfig
from functions import derive_params_from_weights

PREF_FILE = "json/stage2_ahp_global_weights.json"
BACKUP = PREF_FILE + ".q_bak"
OUT = "upgrade_figures/queued"
os.makedirs(OUT, exist_ok=True)
be._write_unified_backtest_report = lambda *a, **k: None
be._mirror_run_figures_to_upgrade = lambda *a, **k: None

TIME_WINDOWS = [("2018-06-01","2021-06-01"), ("2019-06-01","2022-06-01"),
                ("2020-06-01","2023-06-01"), ("2021-06-01","2024-06-01"),
                ("2022-06-01","2025-06-01"), ("2023-06-01","2026-05-22")]
REGIME_WINDOWS = [("2018-06-01","2021-06-01"), ("2020-06-01","2023-06-01"), ("2023-06-01","2026-05-22")]

payload = json.load(open(PREF_FILE, encoding="utf-8"))
def set_profile(p):
    payload["Global_Weights"] = dict(parameters.USER_PROFILES[p]); payload["Source"] = f"queued::{p}"
    json.dump(payload, open(PREF_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

def run(start, end, lb=2, initial=None, contrib=None):
    kw = dict(start_date=start, end_date=end, lookback_years=lb, fetch_missing_data=False)
    if initial is not None: kw["initial_capital"] = initial
    if contrib is not None: kw["periodic_contribution"] = contrib
    return run_rolling_backtest(BacktestConfig(**kw))

def basic(res):
    s = res["summary"].set_index("Strategy"); pr = res["preference_scores"]; pd_ = s.loc["Preference_Driven"]
    def g(st, c): return round(float(s.loc[st, c]), 3) if st in s.index else float("nan")
    vt = g("VT", "CAGR_%")
    win = round(float((pr["Forward_Score_vs_Benchmark"] > 0).mean()*100), 1) if "Forward_Score_vs_Benchmark" in pr.columns else float("nan")
    return {"Sharpe": round(float(pd_["Sharpe"]),3), "Vol": round(float(pd_["Annualized_Volatility_%"]),2),
            "MaxDD": round(float(pd_["Max_Drawdown_%"]),2), "CAGR": round(float(pd_["CAGR_%"]),2),
            "VT_CAGR": vt, "beats_VT_CAGR": bool(float(pd_["CAGR_%"])>vt) if pd.notna(vt) else None,
            "win_VT": win, "n": int(len(pr))}

orig = {k: getattr(parameters, k, None) for k in ["OPTIMIZATION_ARM","TILT_STRENGTH","TILT_INCLUDE_CAGR","RISK_FRACTION_OVERRIDE"]}
shutil.copyfile(PREF_FILE, BACKUP)
try:
    # ===== Exp3: noCAGR vs full 跨區（Arm C, τ=0.3）=====
    rows = []
    parameters.OPTIMIZATION_ARM = "C"; parameters.TILT_STRENGTH = 0.3; parameters.RISK_FRACTION_OVERRIDE = None
    for p in ["conservative","balanced","return_leaning"]:
        set_profile(p)
        for sname, inc in [("noCAGR",False),("full",True)]:
            parameters.TILT_INCLUDE_CAGR = inc
            for ws,we in TIME_WINDOWS:
                print(f"\n=== Exp3 {p} {sname} {ws[:7]}->{we[:7]} ===", flush=True)
                try: rows.append({"profile":p,"s":sname,"window":f"{ws[:7]}_{we[:7]}",**basic(run(ws,we,2))})
                except Exception as e: rows.append({"profile":p,"s":sname,"window":f"{ws[:7]}_{we[:7]}","error":str(e)[:80]})
                pd.DataFrame(rows).to_csv(f"{OUT}/exp3_nocagr_robustness.csv", index=False)

    # ===== Exp4: risk_fraction 跨區（C2 noCAGR）=====
    rows = []
    parameters.OPTIMIZATION_ARM = "C2"; parameters.TILT_INCLUDE_CAGR = False
    for p in ["aggressive_growth","return_leaning","balanced"]:
        set_profile(p); core = derive_params_from_weights(parameters.USER_PROFILES[p])["core_mode"]
        for rf in [0.0,0.25,0.5,0.75,1.0]:
            parameters.RISK_FRACTION_OVERRIDE = rf
            for ws,we in REGIME_WINDOWS:
                print(f"\n=== Exp4 {p}({core}) rf={rf} {ws[:7]}->{we[:7]} ===", flush=True)
                try: rows.append({"profile":p,"core":core,"rf":rf,"window":f"{ws[:7]}_{we[:7]}",**basic(run(ws,we,2))})
                except Exception as e: rows.append({"profile":p,"core":core,"rf":rf,"window":f"{ws[:7]}_{we[:7]}","error":str(e)[:80]})
                pd.DataFrame(rows).to_csv(f"{OUT}/exp4_riskfraction_regime.csv", index=False)
    parameters.RISK_FRACTION_OVERRIDE = None

    # ===== Exp5: DCA（C2 noCAGR）單筆 vs 定期定額 =====
    rows = []
    parameters.OPTIMIZATION_ARM = "C2"; parameters.TILT_INCLUDE_CAGR = False
    LUMP = dict(initial=1_200_000.0, contrib=0.0)
    DCA  = dict(initial=0.0, contrib=33_333.0)   # ~36 個月 × 33,333 ≈ 1.2M，與單筆同總額
    for p in ["aggressive_growth","return_leaning","balanced","conservative"]:
        set_profile(p)
        for mode, mc in [("lump",LUMP),("DCA",DCA)]:
            for ws,we in TIME_WINDOWS:
                print(f"\n=== Exp5 {p} {mode} {ws[:7]}->{we[:7]} ===", flush=True)
                try:
                    res = run(ws,we,2, initial=mc["initial"], contrib=mc["contrib"])
                    b = basic(res)
                    term = float(res["nav"]["Preference_Driven"].dropna().iloc[-1])
                    cash = float(res["cashflows"]["Preference_Driven"].sum())
                    mult = term/cash if cash>0 else float("nan")  # 金額加權財富倍數（終值/總投入）
                    rows.append({"profile":p,"mode":mode,"window":f"{ws[:7]}_{we[:7]}",
                                 "wealth_mult":round(mult,4),"terminal":round(term,0),"total_cash":round(cash,0),
                                 "Sharpe":b["Sharpe"],"CAGR":b["CAGR"],"MaxDD":b["MaxDD"],"VT_CAGR":b["VT_CAGR"]})
                except Exception as e:
                    rows.append({"profile":p,"mode":mode,"window":f"{ws[:7]}_{we[:7]}","error":str(e)[:80]})
                pd.DataFrame(rows).to_csv(f"{OUT}/exp5_dca.csv", index=False)
finally:
    shutil.copyfile(BACKUP, PREF_FILE); os.remove(BACKUP)
    for k,v in orig.items(): setattr(parameters, k, v)

print("\nDONE_QUEUED_EXPERIMENTS")
