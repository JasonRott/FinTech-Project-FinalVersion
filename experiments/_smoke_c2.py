# -*- coding: utf-8 -*-
"""Arm C2 煙霧測試：用合成資料跑三個核心（minvar/market/beta），確認無 runtime 錯誤、
權重合法（Σ≈1、界內）。不碰快取/網路。"""
import numpy as np
import pandas as pd
import parameters
parameters.OPTIMIZATION_ARM = "C2"

from backtest_engine import optimize_preference_portfolio, BacktestConfig
from functions import derive_params_from_weights, compute_benchmark_cov_vector, compute_feasible_vol_budget

rng = np.random.RandomState(42)
tickers = ["AAA", "BBB", "CCC", "DDD"]
dates = pd.date_range("2020-01-01", periods=300, freq="B")
# 合成日報酬：不同 beta 對基準
bench = pd.Series(rng.normal(0.0004, 0.01, len(dates)), index=dates)
betas = [0.5, 1.0, 1.5, 0.8]
ret = pd.DataFrame({t: betas[i] * bench.values + rng.normal(0, 0.006, len(dates))
                    for i, t in enumerate(tickers)}, index=dates)

selected = pd.DataFrame({
    "ETF": tickers,
    "User_Pref_Score": [0.8, 0.6, 0.9, 0.5],
    "Cost_ExpRatio (%)": [0.03, 0.10, 0.20, 0.05],
    "Return_Div (%)": [1.0, 2.0, 0.5, 3.0],
})
scaled = pd.DataFrame({"ETF": tickers, "Norm_Return_CAGR": [0.9, 0.5, 1.0, 0.3]})
cfg = BacktestConfig()

# 三組權重分別命中 minvar / market / beta 核心
profiles = {
    "conservative(minvar)": {"Return_CAGR": 0.08, "Return_Div": 0.12, "Risk_Vol": 0.28, "Risk_MaxDD": 0.22},
    "balanced(market)":     {"Return_CAGR": 0.22, "Return_Div": 0.13, "Risk_Vol": 0.15, "Risk_MaxDD": 0.12},
    "aggressive(beta)":     {"Return_CAGR": 0.55, "Return_Div": 0.00, "Risk_Vol": 0.05, "Risk_MaxDD": 0.05},
}

# 先確認 c 向量 / beta 方向
c_vec, var_b = compute_benchmark_cov_vector(ret, bench)
print("c (cov vs bench):", np.round(c_vec, 5))
print("beta = c/var_b  :", np.round(c_vec / var_b, 3), " (真值≈", betas, ")")
print("-" * 60)

cov_test = ret.cov().values * 252
for name, w in profiles.items():
    gp = derive_params_from_weights(w)
    vb, vmin, vmax = compute_feasible_vol_budget(cov_test, cfg.max_weight_limit, gp["risk_fraction"])
    weights = optimize_preference_portfolio(selected, scaled, ret, w, cfg, benchmark_returns=bench)
    ok = (not weights.empty) and abs(weights.sum() - 1.0) < 1e-4 and (weights >= -1e-6).all()
    port_beta = float(np.dot(weights.values, c_vec / var_b)) if not weights.empty else float("nan")
    port_vol = float(np.sqrt(weights.values @ cov_test @ weights.values)) if not weights.empty else float("nan")
    print(f"{name:<22} core={gp['core_mode']:<7} tau={gp['tau']:.3f} rfrac={gp['risk_fraction']:.2f} "
          f"vbudget={vb:.3f} (range {vmin:.3f}~{vmax:.3f}) | sum={weights.sum():.4f} "
          f"port_vol={port_vol:.3f} port_beta={port_beta:.3f} OK={ok}")
    print("   weights:", {k: round(v, 3) for k, v in weights.items()})
