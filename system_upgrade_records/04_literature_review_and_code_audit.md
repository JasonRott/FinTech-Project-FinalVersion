# 文獻整理與最佳化系統程式碼稽核

建立日期：2026-06-04  
範圍：偏好如何轉成效用函數的文獻整理 + `functions.py` 最佳化核心的瑕疵稽核  
狀態：分析報告，未批准任何實作

---

## A. 偏好如何轉成效用函數（白話詳細版）

學術上「把使用者偏好變成一個可最佳化的目標」主要有四種做法，由弱到強：

### ① 線性加權加總（Weighted-Sum Scalarization）

公式：

```
U = Σ_i  w_i × score_i
```

- 每個維度先正規化成分數，乘上偏好權重後加總。
- 代表方法：AHP、TOPSIS、SAW、加權評分卡。
- **優點**：直覺、易解釋、易實作。
- **致命缺點**：
  1. 假設「最大化分數」等於「最大化真實結果」，但兩者不相等。
  2. 對正規化方式極度敏感（換一種 scaler，排名就變）。
  3. 假設各維度可線性互換、可共量（1 單位報酬分 = 1 單位風險分），這在經濟意義上不成立。
- **本專案現況**：Stage 3 的 `calc_utility` 就是這一類。

### ② 均值-變異數期望效用（Markowitz / von Neumann–Morgenstern）

公式：

```
U = E[r] − (λ/2) × Var(r)
```

- 偏好濃縮成單一**風險趨避係數 λ**。
- 風險不是獨立加分項，而是被 λ 縮放的**懲罰項**。
- 報酬導向使用者 = 小 λ；保守型 = 大 λ。
- **金融學主流**，理論基礎是期望效用理論。

### ③ 約束式 / 目標規劃（Goal Programming, Constraint-based）

公式：

```
maximize   報酬（或主偏好效用）
subject to portfolio volatility ≤ user risk budget
           max drawdown        ≤ user drawdown budget
           cost / liquidity / diversity ≥ 各自門檻
```

- 偏好用來**設定門檻與優先序**，而不是當加總項。
- 次要維度（成本、流動性、分散、情緒）當**約束或懲罰**，不與報酬等權相加，因此不稀釋主目標。
- 對應本專案的 P-02（風險預算）與 P-05（主目標/輔助拆分）。

### ④ 兩層式：MCDM 篩選層 + ②/③ 最佳化層（文獻最支持）

- 第一層：AHP / TOPSIS / DEA 負責「排序、篩掉劣勢標的」。
- 第二層：把篩選後的候選池交給均值-變異數或目標規劃做真正配重。
- 文獻中「MCDM 提升報酬」的正面結果，幾乎都是這種兩層分工，而非把加權分數當最終目標。
- **本專案的架構（DEA + AHP 篩選 → Stage 3 最佳化）已經非常接近這個形狀**，唯一缺口是 Stage 3 仍用 ① 當目標，而非 ② 或 ③。

### 核心結論

> 從 ① 升級到 ② 或 ③，就是把「偏好評分系統」升級為「偏好條件化的投組最佳化系統」。
> 偏好不再「直接被最大化」，而是用來「設定最佳化的參數（λ、約束邊界）」。

---

## B. 參考文獻（依主題分類）

### B1. 兩階段 DEA → 投組最佳化（對應 Stage 1 → Stage 3）

- Galagedera & Silvapulle, *A data envelopment analysis approach to measure mutual fund performance*. European Journal of Operational Research. （本專案 `literature/DEA_measure_mutual_fund.pdf`）
  https://www.sciencedirect.com/science/article/abs/pii/S0377221700003118
- *Assessing the performance of ETFs in the energy sector: a hybrid DEA multiobjective linear programming approach*. Annals of Operations Research.
  https://link.springer.com/article/10.1007/s10479-021-04323-6
- *A new network DEA model for mutual fund performance appraisal*. （兩階段：吸引資金 → 建構投組）
  https://www.sciencedirect.com/science/article/abs/pii/S0305048317301160

### B2. AHP / MCDM 作為偏好權重與篩選層（對應 Stage 2_1-A）

- *Decision-Making Model to Portfolio Selection Using AHP With Expert Knowledge*. IEEE Access.
  https://ieeexplore.ieee.org/document/9438610/
- *Portfolio Selection Using Fuzzy Analytic Hierarchy Process (FAHP)*.
  https://www.researchgate.net/publication/256032916_Portfolio_Selection_Using_Fuzzy_Analytic_Hierarchy_Process_FAHP
- *Optimal Selection of Stock Portfolios Using Multi-Criteria Decision-Making Methods*. Mathematics (MDPI), 2023.
  https://www.mdpi.com/2227-7390/11/2/415
- *An integrated TOPSIS and ARAS MCDM approach for optimizing investment portfolios using goal programming and genetic algorithm*. Scientific Reports, 2025.
  https://www.nature.com/articles/s41598-025-17604-y

### B3. 風險預算 vs 風險加分（支持 P-02 / P-06）

- *Constrained Risk Budgeting Portfolios: Theory, Algorithms, Applications & Puzzles*. (Richard & Roncalli)
  https://arxiv.org/pdf/1902.05710
- *Portfolio optimization with optimal expected utility risk measures*. Annals of Operations Research.
  https://link.springer.com/article/10.1007/s10479-021-04403-7
- 重要數學事實：約束式與懲罰式在最優點等價（懲罰係數 = 約束的 shadow price），可漸進改造，不必一次重寫。

### B4. 次要目標當約束而非加總（支持 P-05，以 ESG 文獻為天然實驗場）

- *ESG integration in portfolio selection: A robust preference-based multicriteria approach*.
  https://www.sciencedirect.com/science/article/pii/S2214716024000095
- *A multi-criteria approach to ESG-based portfolio optimization … credibilistic CVaR*. Scientific Reports, 2025.
  https://www.nature.com/articles/s41598-025-24242-x

### B5. 偏好學習 / 貝式偏好探測（對應 active_preference，本輪暫不延伸）

- *Active Preference Learning for Personalized Portfolio Construction*. arXiv:1708.07567.
  https://arxiv.org/pdf/1708.07567
- *Robo-advising: Learning Investors' Risk Preferences via Portfolio Choices*. arXiv:1911.02067.
  https://arxiv.org/pdf/1911.02067
- *Learning Risk Preferences from Investment Portfolios Using Inverse Optimization*. arXiv:2010.01687.
  https://arxiv.org/pdf/2010.01687

---

## C. 最佳化系統程式碼稽核（functions.py）

稽核日期：2026-06-04。嚴重度：🔴 結構性 / 🟡 方法 / 🟢 穩健性。

### 🔴 F1 — 報酬項是排名分數 proxy，風險項是真實投組值（確定）

位置：`functions.py:2501-2541`（`calc_utility`）

- 報酬等 6 維：`port_cagr = np.dot(w, vec_cagr)`，`vec_cagr` 是每檔 ETF CAGR 的 `[0,1]` 排名分數。
- 風險 2 維：`port_vol = sqrt(wᵀ Σ w)`、`true_maxdd_score` 是真實投組層級值。
- 後果：最佳化器面對不對稱賽局——降風險能拿到共變異數的凸性實質好處，提報酬只能讓排名分數線性上升。結構性偏向保守，**是「報酬導向使用者拉不高 CAGR」的主因**。
- 建議方向：報酬項改用真實年化報酬向量（`functions.py:2570` 的 `annual_returns_array` 已存在），讓報酬與風險站在同一經濟基礎。

### 🔴 F2 — Max Sharpe 對照組樣本內過擬合（確定）

位置：`functions.py:2570-2577`

- 期望報酬用歷史樣本幾何平均當 μ，最大化 Sharpe，屬 Markowitz 誤差最大化。
- 偏好組合與 Max Sharpe 都是樣本內最佳，兩者比較非樣本外公平比較。
- 任何報表上的勝負結論，需經 `backtest_engine.py` 樣本外驗證才可信。

### 🔴 F3 — DEA 閘門對純成長型 ETF 雙重不利（確定）

位置：`functions.py:1213`、`1235`

- `Out_Return = (CAGR + Div)/2`：高成長零配息 ETF 的報酬產出被配息半段稀釋。
- 風險為 input：高成長高波動 ETF 在 DEA 被雙重懲罰（報酬被砍半 + 風險投入高）。
- 在偏好生效前就傷害成長股，確認問題 #3。

### 🔴 F4 — Cross-efficiency 與 Super-efficiency 算了但未接上管線（確定，待確認是否刻意）

位置：`functions.py:1464-1538`（cross）、`1388-1462`（super）、`1754`（Stage 2_2 取候選）

- cross/super 只輸出資訊與排序，Stage 2_2 用 `df_candidates['ETF'].tolist()` 取全部 DEA≥0.8 標的，未用 Cross_Score 篩選。
- 實際閘門只有「標準 DEA ≥ 0.8」。若非刻意，等於兩個 DEA 變體未接上下游。

### 🟡 F5 — 風險以加分而非約束進入目標（確定，設計選擇）

位置：`functions.py:2530-2541`

- `port_vol_score = 1 − penalty`，floor/cap 固定 8%/30% 對所有使用者一致。
- 「降波動永遠加分」持續把報酬導向使用者拉回保守。對應 P-02 / P-06。

### 🟡 F6 — 分群選代表用偏好分數，可能丟掉群內高報酬者（確定）

位置：`functions.py:1831`

- 每群用 `User_Pref_Score.idxmax()` 選勝出，分數含反向低風險/低成本加分。
- `CORR_THRESHOLD = 0.99` 過高，實際少觸發，影響有限。確認問題 #6。

### 🟡 F7 — Max Sharpe 也被 40% 上限約束（確定，需標註）

位置：`functions.py:2577`

- 用 `weight_bounds`（含 40% cap），非教科書無約束切點組合。命名需標清楚以免誤導。

### 🟢 F8 — AHP 特徵向量符號（值得查）

位置：`functions.py:1591`

- `weights = eigenvector / (sum + 1e-6)`；`np.linalg.eig` 可能回傳負倍數導致權重全負。
- 建議加 `eigenvector = np.abs(eigenvector)` 或強制符號。

### 🟢 F9 — 兩套 scaler 範圍不一致（值得查，目前無害）

位置：`functions.py:1172`（`custom_minmax_scaler` → [0.1,1]）、`1712`（`robust_scale` → [0,1]）

- 縮尾分位數也不同。Stage 3 用 robust_scale 版本，內部一致，但並存易在未來改動時混淆。

### 🟢 F10 — 硬編碼無風險利率 0.04（小問題）

位置：`functions.py:2575`、`2599`

- 兩處 risk-free 寫死 0.04，建議移到 `parameters.py`。

---

## D. 建議優先序（未批准）

1. **F1（報酬項改真實報酬）+ F5（風險預算）** — 直接打中「分數贏但報酬輸」的根因，理論支撐最強。
2. **F3（DEA 報酬產出不該砍半成長股）+ P-01 rescue list** — 低成本，緩解 DEA 過早殺高報酬標的。
3. **F2 驗證層** — 在回測加入「偏好分數排名 vs 樣本外實現報酬排名」的相關性檢驗，用數據證明是否需要從 ① 轉向 ②/③。
4. **F4** — 確認 cross/super-efficiency 是否該接上管線。
5. F7/F8/F9/F10 — 標註與穩健性清理。

---

## E. 回測引擎一致性與視覺化稽核（2026-06-04）

### E1. 主系統 vs 回測：完全同邏輯（已逐行確認）

比對 `functions.py` Stage 3（`run_stage3_pipeline.calc_utility`）與 `backtest_engine.py`（`optimize_preference_portfolio.calc_utility`、`calculate_portfolio_utility`、`optimize_max_sharpe_portfolio`）：

| 項目 | 主系統 | 回測 | 一致 |
|---|---|---|---|
| 融合權重 | `α·base+(1−α)·user` | `_blended_preference_weights` 同式 | ✅ |
| 正規化 | `robust_scale`(Stage 2_2) | `scale_preference_features` 同邏輯 | ✅ |
| 報酬項 | `dot(w, Norm_CAGR/Div)` | 同 | ✅（同有 F1）|
| 波動 | `√(wᵀΣw)`, Σ=cov×252 | 同 | ✅ |
| MaxDD | `calculate_true_maxdd_score` | 同（共用 import）| ✅ |
| HHI | `1−Σexposure²` | 同 | ✅ |
| 求解器 | SLSQP bounds(0,cap) Σw=1 | 同 | ✅ |
| 常數 | DEA 0.80 / corr 0.99 / rf 0.04 / cap 0.40 | `BacktestConfig` 預設全同 | ✅ |
| MaxSharpe 年化 | `prod^(252/n)−1` | 同 | ✅ |

**結論：目前兩者數學完全一致，F1–F10 在兩邊同樣存在。維持一致是鐵律，升級時兩檔同步改。**

### E2. 視覺化現況

`_write_unified_backtest_report`（`backtest_engine.py:1859-1908`）實際呼叫的圖：

- ✅ `portfolio_performance.png`（NAV + 回撤雙面板）
- ✅ `annual_returns.png`、`weight_evolution.png`、`radar_chart.png`
- ✅ `nav.png` + `drawdown.png`（`_plot_backtest_outputs`）
- ✅ 4 張分布網格（hist/box，DEA 前/後）、`dea_score_distribution.png`
- ❌ `_plot_final_period_frontiers`（`backtest_engine.py:1503`）**定義了但從未被呼叫**，且內含 8000 次蒙地卡羅 → 死碼，待清理（V-5）。

### E3. 尚未被視覺化、但資料已算好的金礦

回測 `build_period_dimension_row` / `period_dimension_df` 逐期記錄了但目前只進 CSV/文字、沒畫圖：

- `Preference_Score` × `Forward_Period_Return`（逐期）→ **V-1 散佈圖**，可直接驗證「偏好分數能否預測 OOS 報酬」。
- 各維度逐期分數 → V-2 維度 OOS 貢獻分解。
- `_calc_turnover` 已算但沒畫 → V-4 換手率/成本侵蝕。

詳細 V-1 ~ V-5 升級項目見 `03_planned_upgrade_items.md` 第 2 節。
