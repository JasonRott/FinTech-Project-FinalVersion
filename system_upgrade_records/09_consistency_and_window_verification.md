# 一致性與窗口驗證（任務 1 + 2）

建立：2026-06-05　驗證對象：主系統 `functions.py`（Stage 3）vs 回測 `backtest_engine.py`
生產演算法：`OPTIMIZATION_ARM="C2"`（已設為預設）+ beta 評分 + noCAGR + 品質約束全關。

---

## 任務 1：兩系統演算法邏輯一致性 ✅

### A. 五臂分支都在兩檔且結構對應
| 臂 | functions.py | backtest_engine.py |
|---|---|---|
| A/B/C/C2/BL | 2947/2975/3005/3057... | 1198/1227/1262/1317 |

### B. 共用 helper（單一真理來源：定義在 functions.py，backtest import）
`derive_params_from_weights`、`compute_benchmark_cov_vector`、`compute_feasible_vol_budget`、`build_quality_constraints`、`compute_cov_annual`、`shrink_mean_returns`、`robust_scale`、`custom_minmax_scaler`、`calculate_true_maxdd_score`、`build_sector_matrix`。
→ 這些是演算法的數學核心,**兩系統呼叫同一份程式**,不可能漂移。

### C. 生產臂 C2 逐行對應（已逐行比對）
| 元件 | 兩檔是否相同 |
|---|---|
| g(w)：core_mode / τ / risk_fraction | ✅ 同呼叫 `derive_params_from_weights` |
| 風險預算 | ✅ 同呼叫 `compute_feasible_vol_budget(cov, cap, risk_fraction)` |
| 傾斜 s（User_Pref_Score；noCAGR 減 Norm_Return_CAGR）| ✅ 同公式（functions 用 vec_cagr、backtest 用 scaled["Norm_Return_CAGR"]，皆為候選池 robust_scale 之 CAGR）|
| c/β（market/beta 核心）| ✅ 同呼叫 `compute_benchmark_cov_vector`；β=c/var_bench |
| 三核心目標函數 | ✅ 完全相同：beta `−(wᵀβ+τwᵀs)`；market `½wᵀΣw−wᵀc−τwᵀs`；minvar `½wᵀΣw−τwᵀs` |
| 約束 | ✅ `Σw=1` + `vol≤budget` + `build_quality_constraints`（同參數）|
| 取不到基準→退回 minvar | ✅ 兩檔皆有 |
| fallback 鏈 | ✅ 等價（full→去品質約束→僅 Σw=1）|

### D. 上游管線一致
- **DEA**：`Out_Return` 拆 `Out_CAGR`+`Out_Div`（選項 A）兩檔皆然；輸出維度 `[Out_CAGR,Out_Div,Out_Liquidity,Out_Diversity]` 一致。
- **候選池門檻**：兩檔皆用 `DEA_TOP_FRACTION=0.25`（取前 25%）取代絕對 0.80。
- **正規化**：兩檔 `Norm_*` 皆用 `robust_scale`（含 `PREF_SCORE_CAGR_UPPER_Q` 一致）。
- **相關分群**：`CORR_THRESHOLD≈0.99`、群內取 `User_Pref_Score` 最大者,兩檔一致。

### E. 發現的小差異（不影響數學,列為清理項）
1. `DEFAULT_BENCHMARK_TICKER`(="VT") 目前定義在 `backtest_engine.py`;functions.py 用 `getattr(parameters, "DEFAULT_BENCHMARK_TICKER", "VT")` → 因 parameters.py 無此常數,**回退到 "VT"**。兩者實際都用 VT,**行為一致**,但建議清理時把它移到 `parameters.py` 成為單一來源。
2. backtest 最終 fallback 多一個「仍失敗→回傳空 Series」守門;functions.py 對應 `sys.exit`。語意等價(都代表求解失敗)。

**結論（任務 1）：生產臂 C2 的最佳化數學、約束、DEA、正規化、分群在兩系統完全一致。核心數學透過共用 helper 共享,結構上保證不漂移。**

---

## 任務 2：窗口使用方式 ✅

| | 主系統（functions.py）| 回測（backtest_engine.py）|
|---|---|---|
| 資料窗 | `get_or_fetch_historical_prices` 抓 **period="3y"** | 每個再平衡點用 **`lookback_years`（預設=3）** |
| 計算方式 | **單次**最佳化（用最近 3 年）→ 輸出「當前推薦」 | **滾動**：每個再平衡日用過去 3 年 lookback 重新最佳化,前進到下一日 |
| lookback 長度 | 3 年 | 3 年（預設）|

→ **兩者 lookback 長度一致（3 年）**;差別只在「主系統算一次當前推薦 vs 回測歷史滾動多次」。這是設計本意（主系統=現在買什麼;回測=這套規則歷史上表現如何）。
（註：先前為加速 sweep 曾用 `lookback_years=2`,但**預設與主系統一致為 3 年**。）

---

## 維護鐵律（持續）
任何效用函數/風險/候選池/DEA/權重限制/正規化的改動,**必須兩檔同步並各自驗證**;數學核心優先放共用 helper（functions.py）由 backtest import,從源頭杜絕漂移。
