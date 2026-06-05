# -*- coding: utf-8 -*-
"""DCA 公平重測：XIRR(金額加權報酬率,消掉在場時間偏差) + 跨起始點離散度(進場時機風險)。
C2 noCAGR + beta 評分,季度。3 profile(高/中/低波動)× 6 個 3年窗(=6 起始點)× {單筆, DCA}。
假設：DCA 的 XIRR 跨起始點離散度更低(降進場時機風險),且高波動 profile 降幅更大。"""
import json, shutil, os
import pandas as pd, numpy as np
import parameters
import backtest_engine as be
from backtest_engine import run_rolling_backtest, BacktestConfig

PREF_FILE="json/stage2_ahp_global_weights.json"; BACKUP=PREF_FILE+".dca_bak"
OUT="upgrade_figures/dca_irr"; os.makedirs(OUT, exist_ok=True)
be._write_unified_backtest_report=lambda *a,**k:None; be._mirror_run_figures_to_upgrade=lambda *a,**k:None

PROFILES=["aggressive_growth","balanced","conservative"]
WINDOWS=[("2018-06-01","2021-06-01"),("2019-06-01","2022-06-01"),("2020-06-01","2023-06-01"),
         ("2021-06-01","2024-06-01"),("2022-06-01","2025-06-01"),("2023-06-01","2026-05-22")]
LUMP=dict(initial=1_000_000.0, contrib=0.0)
DCA =dict(initial=0.0, contrib=100_000.0)   # XIRR 為比率、尺度不變,不必精配總額

def xirr(flow_by_date):
    dates=sorted(flow_by_date); t0=dates[0]
    yrs=np.array([(d-t0).days/365.0 for d in dates]); cf=np.array([flow_by_date[d] for d in dates])
    def npv(r): return float(np.sum(cf/(1.0+r)**yrs))
    lo,hi=-0.9999,10.0; flo,fhi=npv(lo),npv(hi)
    if flo*fhi>0: return float("nan")
    for _ in range(200):
        mid=(lo+hi)/2.0; fm=npv(mid)
        if abs(fm)<1e-4: return mid
        if flo*fm<0: hi=mid
        else: lo=mid; flo=fm
    return (lo+hi)/2.0

def run_one(ws,we,mc):
    res=run_rolling_backtest(BacktestConfig(start_date=ws,end_date=we,lookback_years=2,rebalance_freq="Q",
                                            initial_capital=mc["initial"],periodic_contribution=mc["contrib"],fetch_missing_data=False))
    cf=res["cashflows"]["Preference_Driven"].dropna(); nav=res["nav"]["Preference_Driven"].dropna()
    fbd={}
    for d,c in cf.items():
        if abs(float(c))>0: fbd[pd.Timestamp(d)]=fbd.get(pd.Timestamp(d),0.0)-float(c)  # 投入=負
    td=pd.Timestamp(nav.index[-1]); fbd[td]=fbd.get(td,0.0)+float(nav.iloc[-1])          # 期末=正
    xr=xirr(fbd)
    term=float(nav.iloc[-1]); cash=float(cf.sum())
    s=res["summary"].set_index("Strategy"); cagr=round(float(s.loc["Preference_Driven","CAGR_%"]),2)
    return {"XIRR_%":round(xr*100,2) if xr==xr else None,"wealth_mult":round(term/cash,4) if cash>0 else None,"tw_CAGR":cagr}

orig={k:getattr(parameters,k,None) for k in ["OPTIMIZATION_ARM","TILT_INCLUDE_CAGR","PREF_RETURN_BASIS","USE_QUALITY_CONSTRAINTS"]}
shutil.copyfile(PREF_FILE,BACKUP); payload=json.load(open(PREF_FILE,encoding="utf-8"))
parameters.OPTIMIZATION_ARM="C2"; parameters.TILT_INCLUDE_CAGR=False; parameters.PREF_RETURN_BASIS="beta"; parameters.USE_QUALITY_CONSTRAINTS=True
rows=[]
try:
    for p in PROFILES:
        payload["Global_Weights"]=dict(parameters.USER_PROFILES[p]); payload["Source"]=f"dca::{p}"
        json.dump(payload,open(PREF_FILE,"w",encoding="utf-8"),ensure_ascii=False,indent=2)
        for mode,mc in [("lump",LUMP),("DCA",DCA)]:
            for ws,we in WINDOWS:
                print(f"\n=== {p} {mode} {ws[:7]}->{we[:7]} ===",flush=True)
                try: rows.append({"profile":p,"mode":mode,"window":f"{ws[:7]}_{we[:7]}",**run_one(ws,we,mc)})
                except Exception as e: rows.append({"profile":p,"mode":mode,"window":f"{ws[:7]}_{we[:7]}","error":str(e)[:90]})
                pd.DataFrame(rows).to_csv(f"{OUT}/dca_irr.csv",index=False)
finally:
    shutil.copyfile(BACKUP,PREF_FILE); os.remove(BACKUP)
    for k,v in orig.items(): setattr(parameters,k,v)

df=pd.DataFrame(rows)
print("\n\n===== DCA: XIRR per (profile,mode,window) =====")
print(df.to_string(index=False))
print("\n===== 跨起始點離散度 (XIRR 平均±標準差) =====")
for p in PROFILES:
    for m in ["lump","DCA"]:
        x=df[(df.profile==p)&(df['mode']==m)]['XIRR_%'].dropna()
        if len(x): print(f"{p:<20} {m:<5} XIRR mean={x.mean():.2f}%  std={x.std():.2f}  (n={len(x)})")
print("\nDONE_DCA_IRR")
