# 演算法升級改動紀錄

建立日期：2026-05-25  
狀態：尚未開始演算法升級  
目前批准狀態：尚未批准任何演算法改動

## 1. 文件目的

本文件用來記錄接下來針對演算法本身的所有升級。  
目前只建立紀錄模板，不寫入具體實作方案，因為使用者尚未 approve 任何演算法改動。

## 2. 使用規則

每次演算法改動開始前，先在此文件新增一節，記錄：

1. 改動日期。
2. 改動目標。
3. 改動前觀察到的問題。
4. 核准的設計方向。
5. 實際修改的檔案。
6. 修改後的驗證方式。
7. 修改後的結果。
8. 是否影響主程式與回測系統的一致性。

## 3. 待討論但尚未批准的方向

以下只列問題方向，不代表已批准實作：

1. DEA 後加入 preference-aware rescue list。
2. 將風險從效用加分項改為風險預算或風險約束。
3. 讓單檔 ETF 權重上限依使用者風格調整。
4. 延後 correlation clustering，或改為相關性懲罰。
5. 區分主要目標與輔助品質分數。
6. 對報酬導向使用者重新設計效用函數。

## 4. 預期可升級項目

### 4.1 波動率風險設計升級

目前舊演算法使用固定尺度將投組年化波動率轉成風險分數：

```text
VOL_SCORE_FLOOR = 8%
VOL_SCORE_CAP   = 30%
```

目前邏輯：

```text
年化波動率 <= 8%  -> volatility score = 1
年化波動率 >= 30% -> volatility score = 0
8% 到 30% 之間線性扣分
```

這個設計的優點是所有使用者、所有 run 都使用同一把尺，因此結果可比較。缺點是風險偏好表達不夠細：報酬導向使用者可能願意承擔較高波動，卻仍被同一套低波動加分機制懲罰。

預期升級方向：

1. 保留固定尺度概念，但依使用者風格分層。
2. 範例設定：

```text
保守型：floor 5%,  cap 18%
平衡型：floor 8%,  cap 30%
成長型：floor 12%, cap 45%
```

3. 更進一步的版本：對報酬導向使用者，不再把低波動當作效用加分項，而是改成風險預算。

```text
maximize return / preference utility
subject to portfolio volatility <= user risk budget
```

這樣可以讓報酬導向使用者「允許高風險換高報酬」，而不是被低波動分數拉回保守投組。

狀態：尚未批准實作。

## 5. 已批准並開始實作的改動

### 2026-05-25：效用函數改用真實投組 MaxDD

狀態：已實作，待持續測速觀察  
是否已批准：已批准  

#### 目標

將舊版 `Risk_MaxDD` 的線性加權 proxy，升級為使用投組實際 buy-and-hold NAV 路徑計算的 true portfolio MaxDD score。

#### 改動前問題

舊版效用函數中的 `Risk_MaxDD` 是：

```text
portfolio_maxdd_score = sum(weight_i * normalized_single_etf_maxdd_score_i)
```

這不是投組真實最大回撤，因為最大回撤應該由整個投組路徑決定，會受到 ETF 報酬相關性與權重互動影響。

#### 核准設計

1. 主程式與回測引擎都改用 true portfolio MaxDD score。
2. 分數尺度使用同一 lookback 期間內各 ETF 自身真實 MaxDD 的分布建立上下界。
3. 舊版線性加權 MaxDD proxy 保留為 fallback。
4. 若最佳化耗時超過 30 秒，系統輸出警告；之後若測試發現太慢，可切回舊 proxy。

#### 修改檔案

1. `functions.py`
2. `backtest_engine.py`
3. `system_upgrade_records/02_algorithm_upgrade_change_log.md`

#### 驗證方式

1. `functions.py` 與 `backtest_engine.py` 已通過 `py_compile`。
2. 已執行主程式 Stage 3，確認 true MaxDD 效用函數可正常最佳化並輸出報表與圖表。
3. 已匯入 `backtest_engine.py`，確認回測引擎在同步引用 true MaxDD helper 後可正常載入。

#### 結果

Stage 3 正常完成，未觸發 30 秒最佳化警告。  
本次結果中，偏好組合由舊版的 `SCHF 40% / SCHG 40% / VOO 20%`，調整為 `VOO 40% / SCHG 34.31% / SCHF 25.69%`。  
偏好組合最大回撤由前次約 `-29.63%` 改善為約 `-28.56%`，CAGR 約 `13.16%`，Sharpe 約 `0.560`。

#### 對主程式與回測一致性的影響

主程式與回測引擎已同步改成同一種 true portfolio MaxDD scoring 邏輯，避免主程式和回測最佳化目標分歧。

## 2026-06-04：最佳化核心程式碼稽核（分析，未改動程式碼）

狀態：已完成稽核，未動任何程式碼  
是否已批准：N/A（純分析）

### 目標
在動手升級前，完整閱讀 `functions.py` 與 `backtest_engine.py` 的最佳化核心，確認架構正確、找出瑕疵、確認主系統與回測是否同邏輯。

### 結論
1. **主系統與回測目前完全同邏輯（已逐行確認）。** 偏好最佳化與 Max Sharpe 對照組的融合權重、正規化、`√(wᵀΣw)` 波動、true MaxDD、`1−ΣHHI²`、SLSQP 設定、DEA 0.80 / corr 0.99 / rf 0.04 / cap 0.40 全部一致，且常數由 `functions.py` import 共用。
2. **認知更正**：風險量測本來就是真實投組層級（正確，不需改）；真正的根因是報酬項用排名分數 proxy（F1）。
3. 完成 10 項瑕疵稽核（F1–F10），詳見 `04_literature_review_and_code_audit.md`。
4. 升級目標重新定義為「樣本外回測成績」，不是樣本內偏好分數。

### 後續
升級項目已在 `03_planned_upgrade_items.md` 重寫為 U-1 ~ U-7（演算法）與 V-1 ~ V-5（視覺化），建議從 U-1（報酬真實化）+ U-2（風險預算）+ V-1（偏好分數 vs 未來報酬散佈圖）啟動。

### 對主程式與回測一致性的影響
本次未改程式碼，一致性維持。重申鐵律：U 項目每次改動必須同步改兩個檔案並各自驗證。

## 2026-06-04：移除回測雷達圖 + 新增 V-1/V-6 偏好分數圖（視覺化，不碰最佳化）

狀態：已實作並通過 py_compile + 合成資料煙霧測試  
是否已批准：已批准（使用者指示）

### 改動內容
1. **移除雷達圖**：`backtest_engine.py` 的 `_write_unified_backtest_report` 不再呼叫 `_plot_backtest_radar`，不再輸出 `radar_chart.png`。函式保留並標 `[DORMANT]`，待日後以偏好分數為核心重新設計重用。
2. **V-1 `_plot_preference_predictive_scatter`**：偏好分數樣本外預測力散佈圖。經使用者決議做兩個 Y 軸——左圖 Y=事後偏好分數（profile-adaptive，自動適應保守/報酬型）、右圖 Y=未來實現報酬（僅對報酬導向 profile 有效，已標註）。X 軸=事前偏好分數，附回歸線與 Pearson r。輸出 `{prefix}_preference_predictive_scatter.png`。
3. **V-6 `_plot_preference_score_timeseries`**：隨時間變化的偏好分數。上=各策略事後偏好分數時間序列 + OOS 勝率（標題）；下=本系統事前 vs 事後偏好分數，差距即樣本外衰減。輸出 `{prefix}_preference_score_timeseries.png`。

### 資料來源
全部取自既有的 `preference_scores_df`（`backtest_engine.py:2206`），純畫圖，**未動任何最佳化邏輯**。

### 設計決議（使用者確認）
- V-1 的 Y 軸不可寫死成報酬（會偏袒報酬導向）。主用 forward 偏好分數（已內含使用者權重，profile-adaptive），報酬版僅作報酬導向視角補充。
- 演算法升級採**兩臂賽馬**：Arm A=現有線性加權偏好分數（baseline）、Arm B=受約束均值-變異數+風險預算（U-1+U-2），用回測 OOS 當裁判。

### 驗證
1. `py_compile backtest_engine.py` 通過。
2. 合成 `preference_scores_df` 煙霧測試：V-1、V-6 正常產圖，空資料/缺欄位防護正確跳過。

### 對主程式與回測一致性的影響
無。本次只動回測視覺化，不涉及最佳化函式，主系統不受影響。

## 2026-06-04：Arm A（現況 baseline）真實回測基準數據

狀態：已用真實快取資料跑完 rolling backtest（月再平衡，lookback 3y，2021→2026，64 期）  
用途：作為兩臂賽馬中 Arm A 的 OOS 基準，Arm B（U-1+U-2）改完後與此對照  
使用者情境：`CASE_NAME = Neutral_user`（中性預設，非報酬導向）

### OOS 績效（總財富口徑）

| 策略 | CAGR % | 年化波動 % | Sharpe | MaxDD % |
|---|---:|---:|---:|---:|
| **Preference_Driven（本系統）** | **10.02** | **14.13** | **0.464** | **-24.47** |
| EqualWeight | 12.54 | 13.16 | 0.661 | -18.67 |
| MaxSharpe | 10.01 | 13.02 | 0.492 | -21.98 |
| VOO | 16.29 | 16.24 | 0.766 | -23.49 |
| VT | 13.51 | 15.30 | 0.645 | -24.57 |

**關鍵發現：本系統的偏好投組被 EqualWeight 完全宰制**（報酬更低、波動更高、回撤更深、Sharpe 更低），CAGR 是所有策略最差。這在真實數據上確認了 F1/F2，是 U-1/U-2 的最強動機。

### V-1 散佈圖（偏好分數的樣本外意義）

- 左圖（偏好滿足度）：Pearson **r = +0.60** → 事前偏好分數**能**預測事後偏好分數，偏好效用**確實能樣本外推廣**。
- 右圖（報酬）：Pearson **r = −0.00** → 偏好分數與未來報酬**完全無關**（因為目標函數裡沒有真實報酬，F1）。

→ 印證了「Y 軸不能用報酬」的決議：用報酬當 Y 會讓特色看起來無用（r=0），用 forward 偏好分數才看出它其實很強（r=0.60）。

### V-6 時間序列

- V-6a OOS 勝率：本系統事後偏好分數贏 **VOO 83% / EqualWeight 100% / MaxSharpe 88%** 的期間。
- V-6b：事前（lookback）偏好分數系統性高於事後（forward），紅色陰影即樣本外衰減，印證使用者直覺「下一段不一定真的比較高」。但即使衰減後，系統相對其他策略仍勝。

### 結論（升級論述定調）

1. **偏好分數這個特色「成立」**：r=0.60 樣本外推廣 + 83~100% OOS 勝率，是誠實且有力的結果，保留為招牌。
2. **但財務報酬「不成立」**：偏好投組 OOS 報酬最差、被等權宰制，因為偏好分數 ≠ 報酬（r=0）。
3. **升級方向確認**：偏好分數留在「提取 + 評估」層（強），最佳化器換成真實報酬 + 風險預算（U-1/U-2），目標是 Arm B 在 OOS 財務指標贏過 Arm A，同時維持偏好滿足度勝率。

### 已知小問題（非致命）
- Windows cp950 主控台無法顯示 log 裡的 emoji（如 `functions.py:1927` 的 📊），跑回測時會噴 `UnicodeEncodeError` 紀錄錯誤，但被 logging 攔截、不影響計算與輸出。建議日後把 log 訊息的 emoji 移除，或將 stream handler 設為 UTF-8。

## 2026-06-04：實作 U-1 + U-2（Arm B）+ 兩臂賽馬首次對照

狀態：已實作（toggle 預設仍為 Arm A）+ 已跑 Arm B 真實回測對照  
是否已批准：已批准（使用者指示「可以改 U-1, U-2」）

### 改動內容
1. `parameters.py` 新增開關：`OPTIMIZATION_ARM`（"A"/"B"）、`RISK_AVERSION_LAMBDA`、`RISK_BUDGET_VOL`。
2. `functions.py` Stage 3 與 `backtest_engine.py` `optimize_preference_portfolio` **同步**新增 Arm B 分支（一致性鐵律遵守）。
3. Arm B 目標：`max w·μ_total − (λ/2)·wᵀΣw  s.t. √(wᵀΣw) ≤ 風險預算`。
   - μ_total = 資本利得算術年化（`returns.mean()×252`，呼應 Max Sharpe 偏低的幾何/算術討論）+ 殖利率。
   - 品質維度偏好留在 Stage 2_2 篩選層（兩層式）。
   - 偏好分數不動，仍作 V-1/V-6 評估指標。
4. `upgrade_figures/` 改為每次執行一個專屬子資料夾 `{run_id}_arm{X}_{timestamp}/`，並複製該次所有圖（含 portfolio_performance 等）。

### Arm A vs Arm B 對照（Neutral_user, 月再平衡, λ=2.0, 波動預算 30%）

| 指標 | Arm A | Arm B | 變化 |
|---|---:|---:|---|
| CAGR % | 10.02 | 10.15 | +0.13 |
| 年化波動 % | 14.13 | 12.76 | −1.37（更好）|
| Sharpe | 0.464 | 0.510 | +0.046（更好）|
| MaxDD % | −24.47 | −20.40 | +4.07（更好）|
| 資本利得 % | 53.10 | 43.08 | −10.0 |
| 股息 % | 12.73 | 23.84 | +11.1（重壓高股息）|
| 偏好勝率 vs VOO | 83% | 23% | −60pp（變差）|
| 偏好勝率 vs EqualWeight | 100% | 91% | −9pp |
| 偏好勝率 vs MaxSharpe | 88% | 42% | −46pp（變差）|
| V-1 偏好預測力 r | +0.60 | +0.71 | 更強 |
| V-1 報酬預測力 r | −0.00 | +0.06 | 仍≈0 |

### 解讀（重要）
1. **Arm B 在風險調整上勝過 Arm A**：Sharpe、波動、回撤、CAGR 全部小幅改善。mean-variance 目標確實比線性加權分數更有效率。
2. **但 Arm B 犧牲了偏好滿足度優勢**：對 VOO/MaxSharpe 的偏好勝率大跌（因為 Arm B 不再最大化偏好分數）。這是專案核心張力的量化：**最大化「偏好滿足」vs 最大化「財務效率」是有取捨的**。
3. **λ=2 讓 Arm B 偏保守**：重壓高股息低波動 ETF（股息占比翻倍、波動降到 12.76%），30% 波動預算從未綁定。要真正衝報酬（逼近 VOO 16%）需調低 λ。
4. **兩臂都還沒在純報酬上贏過 EqualWeight/VOO。**

### 下一步候選實驗
- 調低 λ（如 0.5~1.0）讓 Arm B 真正衝報酬，看 CAGR 能否逼近 VOO、波動預算是否開始綁定。
- 檢視殖利率進入 μ 的方式（1:1 加總可能造成過強股息傾斜）。
- 考慮**混合臂**（mean-variance + 小幅偏好分數項），在保住部分偏好優勢的同時取得效率。

### 對主程式與回測一致性的影響
Arm B 已同步寫入 `functions.py` 與 `backtest_engine.py`，讀同一個 `OPTIMIZATION_ARM` 開關，邏輯一致。預設維持 Arm A。

## 2026-06-04：視覺化與 Max Sharpe 求解器統一改算術平均；upgrade_figures 精簡

狀態：已實作，主系統 Stage 3 已跑通驗證（雷達/MPT 正常產圖）  
是否已批准：已批准（使用者指示）

### 改動內容
1. **視覺化報酬軸改算術平均**（資本利得 = `returns.mean()×252`，與 Sharpe 口徑一致）：
   - `functions.py` MPT 圖（`plot_portfolio_analytics_and_mpt`）的 `annual_returns`。
   - `functions.py` 雷達圖「歷史報酬」軸改用 `Arithmetic_Ret`（含分數映射、label、`run_stage3_pipeline` 的雷達尺度 bound）。
2. **Max Sharpe 求解器改算術平均**（Sharpe 定義所需，避免幾何低估分子）：`functions.py:run_stage3_pipeline` 與 `backtest_engine.py:optimize_max_sharpe_portfolio`。
3. **報表同時保留兩個口徑**：`backtest_engine.py:_performance_summary` 新增 `Arithmetic_Annual_Return_%`，與既有 `CAGR_%`（幾何）並存。主系統 analytics 本來就同時有 Arithmetic 與 CAGR。
4. **upgrade_figures 精簡**：每次只複製 6 張圖（weight_evolution、portfolio_performance、dea_score_distribution、annual_returns、preference_predictive_scatter(V-1)、preference_score_timeseries(V-6)）。

### 設計決議（回答使用者 #2）
求解器期望報酬一律用**算術平均**：
- Sharpe 比率定義就是用算術平均 → Max Sharpe 必須算術。
- Arm B mean-variance：算術 μ 為單期期望，且 `−(λ/2)σ²` 已近似幾何修正（幾何≈算術−σ²/2）；用 CAGR 會雙重扣風險、過度保守。

### 驗證
主系統 Stage 3 跑通：Arithmetic Annual Return 14.11%（偏好）/12.44%（MaxSharpe），Sharpe 0.569/0.640（皆算術）。

### 對主程式與回測一致性的影響
Max Sharpe 求解器兩邊同步改算術；偏好最佳化（Arm B）本就用算術。一致性維持。

## 2026-06-04：Arm B 殖利率改偏好比例加權（#2）

狀態：已實作，編譯通過（預設仍 Arm A）  
是否已批准：已批准（使用者指示）

### 改動內容
Arm B 的 `μ_total` 由「資本利得 + 殖利率(1:1)」改為「資本利得 + (Return_Div/Return_CAGR)·殖利率」。
- `div_pref_ratio = global_weights["Return_Div"] / max(global_weights["Return_CAGR"], 1e-6)`
- 預設 Neutral_user：0.10/0.40 = 0.25，即 1% 股息在此使用者眼中值 0.25% 資本利得。
- `functions.py` Stage 3 與 `backtest_engine.py optimize_preference_portfolio` 同步。

### 理由
使用者偏好的報酬子維度比例（CAGR:Div）應反映在期望報酬上，比 1:1 更「偏好驅動」，且對 CAGR 導向使用者會降低過強的股息傾斜。

### 對主程式與回測一致性的影響
兩邊同步，邏輯一致；只影響 Arm B。

## 2026-06-04：DEA 取前25% + Ledoit-Wolf 共變異數收縮 + Arm B v2 回測（重要負面結果）

狀態：已實作，已跑完整回測（預設已改回 Arm A）  
是否已批准：已批准（使用者指示）

### 改動內容
1. **DEA 候選池改「取前 25%」百分位門檻**（`parameters.DEA_TOP_FRACTION=0.25`），取代絕對 0.80。`functions.py` 與 `backtest_engine.py` 同步。
2. **Ledoit-Wolf 共變異數收縮**（`parameters.USE_LEDOIT_WOLF_COV=True`，新 helper `functions.compute_cov_annual`），套用於兩個求解器（Arm B + Max Sharpe）；評估用偏好分數 vol 仍用樣本共變異數。

### Arm B 三版對照（Preference_Driven，Neutral_user，月再平衡）

| 指標 | Arm A 基準 | Arm B v1（λ2,股息1:1,樣本cov,幾何MS） | Arm B v2（λ2,股息0.25,LedoitWolf,算術,DEA前25%） |
|---|---:|---:|---:|
| CAGR % | 10.02 | 10.15 | **9.18** |
| 年化波動 % | 14.13 | 12.76 | **17.10** |
| Sharpe | 0.464 | 0.510 | **0.366** |
| MaxDD % | -24.47 | -20.40 | **-29.82** |
| 偏好勝率 vs VOO | 83% | 23% | 30% |
| 偏好勝率 vs EqualWeight | 100% | 91% | 78% |
| V-1 偏好預測力 r | +0.60 | +0.71 | +0.16 |

對照：EqualWeight CAGR 12.15%/Sharpe 0.622；VOO 16.29%/0.766。

### 關鍵診斷（為何 v2 反而更差）
1. **算術 μ 讓求解器更激進**：算術 > 幾何約 σ²/2，Max Sharpe 與 Arm B 改算術後都去追高均值（高波動）標的（Arm B 波動 12.76→17.10、Max Sharpe 13.02→15.89）。先前的幾何均值其實在當隱性正則化（壓低高波動資產）。
2. **股息降權（0.25）移除了防禦性傾斜**：v1 重壓的高股息低波動 ETF 意外有防禦效果；降權後轉向高波動資本利得標的。
3. **Ledoit-Wolf 只收縮共變異數、沒收縮均值**：而**均值才是大問題**。樣本算術均值是極差的 OOS 預測子，收縮 cov 救不了。
4. **波動預算 30% 從未綁定**（波動 17.10% < 30%），λ=2 不足以壓制算術 μ 的激進。
5. **EqualWeight 持續贏過所有最佳化組合** → 經典的「1/N 之謎」（DeMiguel et al. 2009）：樣本估計下的 mean-variance 因估計誤差常輸給等權。本結果重現此現象。

### 結論與下一步
- **μ 估計是真正的瓶頸**，已被本實驗清楚暴露。共變異數收縮是必要但不充分。
- **下一步優先：均值收縮 / Black-Litterman**（產生有理的後驗 μ），這是現在最有實證依據的方向。
- 待議：求解器算術 μ 是否該配合均值收縮才用（單用原始樣本算術均值太激進）。

### 對主程式與回測一致性的影響
所有改動兩邊同步。預設已改回 Arm A。

## 2026-06-04：均值收縮（Arm B v3）+ 撞上 1/N 之謎

狀態：已實作並回測（預設已改回 Arm A）  
是否已批准：已批准

### 改動內容
- 新 helper `functions.shrink_mean_returns`（μ_shrunk=(1-δ)μ_sample+δ·grand_mean），參數 `USE_MEAN_SHRINKAGE`、`MEAN_SHRINKAGE_INTENSITY=0.5`。套用於 Arm B 的資本利得樣本平均（殖利率不收縮）。兩邊同步。
- DEA 分布圖改畫「取前 25% 門檻線」（取代寫死的 0.80），主系統與回測同步。

### 完整對照（Preference_Driven，Neutral_user）

| 指標 | Arm A | B v1 | B v2 | **B v3(+均值收縮δ0.5)** | EqualWeight | VOO |
|---|---:|---:|---:|---:|---:|---:|
| CAGR % | 10.02 | 10.15 | 9.18 | **8.32** | 12.15 | 16.29 |
| 波動 % | 14.13 | 12.76 | 17.10 | **14.87** | 13.49 | 16.24 |
| Sharpe | 0.464 | 0.510 | 0.366 | **0.344** | 0.622 | 0.766 |
| MaxDD % | -24.47 | -20.40 | -29.82 | **-27.64** | -20.16 | -23.49 |
| 偏好勝率 vs EqualWeight | 100% | 91% | 78% | 72% | — | — |

### 關鍵結論
1. **均值收縮（δ=0.5）沒幫上忙**：波動降了（17.10→14.87），但報酬也降（9.18→8.32），Sharpe 微降（0.366→0.344）。
2. **EqualWeight（Sharpe 0.622）打敗所有最佳化臂**（Arm A/B 各版、Max Sharpe）→ **1/N 之謎完整重現**（DeMiguel 2009）。在這個 universe + 期間，任何用 μ 的最佳化都因估計誤差而輸給天真等權。
3. **診斷升級**：問題不只是「μ 估計差」，而是「在這個候選池，最優權重本來就≈1/N」——最佳化的編輯空間有限。

### 策略性下一步（待使用者選擇）
- **Arm C：μ-free 穩健加權（最小變異 / 風險平價）+ 偏好當約束/傾斜**。只用 Σ（已用 Ledoit-Wolf 收縮好），不碰不可估的 μ。最快測試：把 `MEAN_SHRINKAGE_INTENSITY` 設 1.0（μ 全部相等 ≈ 最小變異）跑一次。
- **重新定義價值主張**：財務上接近 1/N 已是天花板；系統差異化在「偏好滿足度（V-1/V-6 OOS 驗證）」。
- Black-Litterman（較完整但工程量大，且 1/N 結果顯示即使好的 μ 估計效益也有限）。

### 對主程式與回測一致性的影響
所有改動兩邊同步。預設已改回 Arm A。

## 2026-06-04：μ-free 實驗（Arm B δ=1.0 = 最小變異 + 股息傾斜）— ⚠️ 結論已更正

狀態：實驗完成（參數已還原 ARM=A, δ=0.5）  
是否已批准：實驗

> ⚠️ **更正（2026-06-05 τ sweep 後）**：本節原把 Sharpe 1.07 當成「純最小變異的勝利」、稱「明確證實 μ 是毒藥、OOS 一流」，這個結論**過度樂觀、已更正**。1.07 其實是「最小變異 **+ 強股息傾斜**（0.25·股息）」，且押中 2021–2026『防禦/高股息』贏家因子（期間運氣）。**純最小變異（Arm C τ=0）只有 Sharpe 0.655。** 下表「δ=1.0」欄請理解為「最小變異+股息傾斜」，非純最小變異。可保留的穩健結論僅為：用噪音樣本 μ（v2/v3）表現最差，少用/不用 μ 較穩。

### 設定
`OPTIMIZATION_ARM=B`、`MEAN_SHRINKAGE_INTENSITY=1.0`（資本利得樣本平均完全收縮 → μ 只剩穩定的股息傾斜，等於「最小變異 + 小幅收益傾斜」，完全不靠不可估的資本利得 μ）。共變異數用 Ledoit-Wolf 收縮。

### 完整對照（Preference_Driven，Neutral_user）

| 指標 | Arm A | B v1 | B v2 | B v3(δ0.5) | **B δ1.0(最小變異+股息傾斜)** | EqualWeight | VOO |
|---|---:|---:|---:|---:|---:|---:|---:|
| CAGR % | 10.02 | 10.15 | 9.18 | 8.32 | **14.74** | 12.15 | 16.29 |
| 波動 % | 14.13 | 12.76 | 17.10 | 14.87 | **9.56** | 13.49 | 16.24 |
| Sharpe | 0.464 | 0.510 | 0.366 | 0.344 | **1.070** | 0.622 | 0.766 |
| MaxDD % | -24.47 | -20.40 | -29.82 | -27.64 | **-10.59** | -20.16 | -23.49 |
| 偏好勝率 vs VOO | 83% | 23% | 30% | 30% | **0%** | — | — |
| 偏好勝率 vs EqualWeight | 100% | 91% | 78% | 72% | **6%** | — | — |
| 偏好勝率 vs MaxSharpe | 88% | 42% | 47% | 47% | **12%** | — | — |

### 兩個重大發現
1. **財務上：此配置 Sharpe 1.070、波動 9.56%、MaxDD -10.59%、CAGR 14.74%。** ⚠️ 但這是「最小變異 + 強股息傾斜」，**股息傾斜做了大部分的工並押中期間因子**，非純最小變異（純最小變異 = Arm C τ=0 = 0.655）。可保留的穩健結論僅為：**用噪音樣本 μ（v2/v3）表現最差，少用 μ 較穩**；「1.07」不可當成穩健的純最小變異成績。
2. **偏好上：最小變異幾乎全輸。** 偏好勝率 VOO 0% / EqualWeight 6% / MaxSharpe 12%。因為它為了最小化波動，**完全忽略使用者的報酬偏好**（Neutral_user 報酬權重 50%）。

### 核心張力被清楚定位（兩個極端）
- **Arm A**：偏好勝率 83~100%，Sharpe 0.464（財務最差）→ 純偏好滿足。
- **最小變異+股息傾斜（B δ1.0）**：偏好勝率 0~12%，Sharpe 1.070（含期間因子運氣）→ 偏財務效率端。（純最小變異 Arm C τ=0 為 Sharpe 0.655）
- 真正的解在中間：**以最小變異為穩健核心，再把偏好以「傾斜 + 約束」層疊上去**，用「偏好強度」當旋鈕在「財務效率 ↔ 偏好滿足」之間取點（Pareto 前緣）。

### 誠實的但書
- 最小變異組合高度偏防禦/高股息（股息占比 43%），在含 2022 空頭的 2021–2026 特別吃香；單一歷史路徑，需注意期間依賴（但已是 64 期 rolling OOS）。
- 「偏好勝率 0%」是相對於「報酬導向的 Neutral_user」；對保守型使用者，最小變異反而會是高偏好分數。即偏好分數正確反映了「最小變異 ≠ 報酬導向使用者要的」。

### 下一步：建立 Arm C
**Arm C = 最小變異核心（μ-free, Ledoit-Wolf Σ）+ 偏好傾斜/約束 + 偏好強度旋鈕。** 目標：在穩健核心上把偏好勝率拉回。（後續 τ sweep 顯示 Arm C 實際 Sharpe 區間約 0.65–0.69，非 1.07。）

### 對主程式與回測一致性的影響
本次只調參數實驗，程式邏輯兩邊已同步（δ 收縮、Ledoit-Wolf 皆在兩檔）。預設已還原 ARM=A, δ=0.5。

## 2026-06-05：★Arm C v1 成功★ 最小變異核心 + 偏好傾斜 = 綜合解

狀態：已實作並回測（預設已還原 ARM=A，Arm C 參數保留）  
是否已批准：已批准（使用者指示）

### 實作
- 新 `OPTIMIZATION_ARM="C"` 分支（functions.py Stage 3 + backtest 同步）。
- 目標：`min ½wᵀΣw − τ·(wᵀs)`，Σ=Ledoit-Wolf，s=User_Pref_Score（排名式）。
- 參數：`TILT_STRENGTH=0.1`、`TILT_INCLUDE_CAGR=True`、品質約束（`COST_BUDGET_QUANTILE=0.75` + `HHI_CEILING=0.50`）、`RISK_BUDGET_VOL=0.30`、cap 0.40。無解 fallback：丟品質約束→丟波動預算。

### Pareto 對照（Preference_Driven，Neutral_user）

| 配置 | Sharpe | 波動% | MaxDD% | CAGR% | 偏好勝率 VOO/EqW/MaxSharpe |
|---|---:|---:|---:|---:|---|
| Arm A（純偏好） | 0.464 | 14.13 | -24.47 | 10.02 | 83 / 100 / 88 |
| B δ1.0(最小變異+股息,期間運氣) | 1.070 | 9.56 | -10.59 | 14.74 | 0 / 6 / 12 |
| 純最小變異(Arm C τ=0) | 0.655 | 10.61 | -15.8 | 10.93 | 1.6 / 84 / 42 |
| **Arm C（τ=0.1）** | **0.666** | 12.26 | -14.21 | 12.07 | **72 / 100 / 91** |
| EqualWeight | 0.622 | 13.49 | -20.16 | 12.15 | — |
| VOO | 0.766 | 16.24 | -23.49 | 16.29 | — |

### 關鍵結論：Arm C 是綜合解
1. **Arm C 在財務上全面優於 Arm A**：Sharpe 0.666 vs 0.464、MaxDD -14.21 vs -24.47、CAGR 12.07 vs 10.02、波動更低。
2. **偏好滿足度幾乎追平 Arm A**：勝率 72/100/91% vs 83/100/88%。
3. **同時打敗天真等權**：Sharpe 0.666 > 0.622、MaxDD -14.21 > -20.16，且額外滿足使用者偏好（等權沒有）。
4. → τ 旋鈕設計成立：τ=0（最小變異，財務最佳、偏好 0%）→ τ=0.1（甜蜜點）→ τ↑ 趨近 Arm A。**核心張力被解決。**

### 下一步
- τ sweep（{0.01, 0.05, 0.1, 0.5}）建完整 Pareto 前緣，找最佳操作點（τ=0.1 已很好，或可略降 τ 換更高 Sharpe）。
- s_full vs s_noCAGR sweep。
- 逐一加入其餘品質約束（流動性、情緒…）並記錄 OOS。
- 之後設計「偏好 → τ / 預算 / 門檻」映射。

### 對主程式與回測一致性的影響
Arm C 兩檔同步。預設已還原 ARM=A。

## 2026-06-05：Arm C τ sweep — Pareto 前緣 + 對「1.07」的誠實更正

狀態：sweep 完成（只掃 τ，其餘固定；單參數方法論決議見 05）  
輸出：`upgrade_figures/tau_sweep/tau_sweep_summary.csv`、`tau_pareto_frontier.png`

### τ sweep（Arm C，Preference_Driven，Neutral_user）

| τ | Sharpe | 波動% | MaxDD% | CAGR% | 偏好勝率 VOO/等權/MaxSharpe |
|---:|---:|---:|---:|---:|---|
| 0.0（純最小變異） | 0.655 | 10.61 | -15.8 | 10.93 | 1.6 / 84 / 42 |
| 0.05 | **0.691** | 11.28 | -13.82 | 11.78 | 47 / 100 / 66 |
| 0.1 | 0.666 | 12.26 | -14.21 | 12.07 | 72 / 100 / 91 |
| 0.2 | 0.569 | 13.12 | -17.54 | 11.17 | 75 / 100 / 91 |
| 0.5 | 0.477 | 14.61 | -22.17 | 10.39 | 78 / 100 / 92 |

（對照：等權 0.622、VOO 0.766）

### 重要更正：先前的「Sharpe 1.07」不是純最小變異
- 純最小變異 = Arm C τ=0 = **Sharpe 0.655**。
- 先前 1.07 是 **Arm B δ=1.0**＝「最小變異 + 強的純股息傾斜（0.25·股息）」，**股息傾斜做了大部分的工，且押中 2021–2026『防禦/高股息』贏家因子**。→ 1.07 相當程度是期間因子運氣，非穩健結果。Arm C 的 0.65–0.69 是更誠實/穩健的範圍（傾斜分散在完整偏好剖面，而非集中單一因子）。

### Pareto 前緣與最佳操作區
- 形狀：拱形 + 右側陡降。τ=0.05 為財務峰值（Sharpe 0.691，甚至高於 τ=0；小傾斜同時改善財務與偏好）；τ=0.1 偏好最佳；τ≥0.2 報酬遞減（Sharpe 陡降、偏好只微增）。
- **建議操作區：τ ∈ [0.05, 0.1]**。重財務→0.05；重偏好→0.1。所有 τ 對等權偏好勝率皆 100%。

### 下一步
- s_full vs s_noCAGR sweep（驗證資本利得排名幫不幫忙）。
- 逐一加品質約束（OAT）。
- 設計「偏好 → τ / 預算 / 門檻（百分位）」映射。
- 注意：股息似乎是穩定且有價值的傾斜，但勿過度依賴（期間相關）。

## 2026-06-05：VT 設為主基準 + VT 錨定 τ sweep

狀態：已實作（DEFAULT_BENCHMARK_TICKER=VT，欄位改 benchmark-generic 命名）+ 已跑 VT 錨定 τ sweep  
輸出：`upgrade_figures/tau_sweep_vt/{tau_sweep_vt_summary.csv, tau_pareto_vt.png}`

### 改動
- `DEFAULT_BENCHMARK_TICKER` VOO→VT（全球市值加權≈市場組合，更適合當無偏好錨；VOO 留 comparison 當 aspirational 目標）。
- 偏好分數欄位 `VOO_Forward*`→`Benchmark_Forward*`、`Forward_Score_vs_VOO`→`Forward_Score_vs_Benchmark`（避免改基準後標籤錯置）。兩檔同步。
- 新增 `parameters.USER_PROFILES`（7 個原型）供多 profile 驗證。

### VT 錨定 τ sweep（Arm C，return_leaning 使用者）
VT 參考：Sharpe 0.645、波動 15.30%、MaxDD -24.57%、CAGR 13.51%。

| τ | Sharpe | 波動% | MaxDD% | CAGR% | 偏好勝率 vs VT |
|---:|---:|---:|---:|---:|---:|
| 0.0 | 0.655 | 10.61 | -15.8 | 10.93 | 35.9 |
| 0.05 | 0.691 | 11.28 | -13.82 | 11.78 | 65.6 |
| 0.1 | 0.666 | 12.26 | -14.21 | 12.07 | 89.1 |
| 0.2 | 0.569 | 13.12 | -17.54 | 11.17 | 93.8 |
| 0.5 | 0.477 | 14.61 | -22.17 | 10.39 | 98.4 |

（財務數字與 VOO 錨定 sweep 完全相同 → 確認財務與基準選擇無關。）

### 關鍵發現（誠實對照使用者目標「風險≈VT、報酬>VT」）
- **Arm C 在風險調整與安全性上勝過 VT**：Sharpe（甜蜜區 0.66–0.69）> VT 0.645；波動（11–12%）遠低於 VT 15.30%；MaxDD（-14%）遠優於 VT -24.57%。
- **但 Arm C 報酬低於 VT**：CAGR 10.9–12.1% < VT 13.51%（所有 τ 皆然）。
- → **「風險≈VT、報酬>VT」未達成，且以目前誠實（μ-free）工具難以達成**：要打敗 VT 的報酬需要可靠的報酬預測，而 1/N 之謎已證明做不到。提高 τ 把波動推到接近 VT（τ=0.5 波動 14.6%）也不會換到更高報酬（CAGR 反降至 10.39%），因為傾斜是往偏好排名、非預測性報酬。
- **誠實的價值主張改寫**：不是「打敗市場報酬」（沒人能可靠做到），而是「**比 VT 更安全、風險調整更好（更高 Sharpe、更低回撤），同時貼合使用者偏好**」。τ=0.1 時對 VT 偏好勝率 89%。
- 旁註：VT 偏好勝率（89%）> VOO 偏好勝率（72%），因為對 return-leaning 使用者，VOO（高 CAGR）偏好分數較高、較難打敗 → 確認「VOO=難打敗的目標、VT=合理基準」的定位。

### 待辦
- 多 profile τ sweep（USER_PROFILES）→ 驗證 trade-off 的 profile 依賴性。
- 偏好→參數映射用「權重向量的函數」（見 05 §4.57）。

## 2026-06-05：多 profile τ sweep（完成）

狀態：完成（3 profile × 3 τ，Arm C，VT 基準）。輸出：`upgrade_figures/profile_sweep/profile_sweep_summary.csv`  
VT 參考：Sharpe 0.645、波動 15.30%、CAGR 13.51%、MaxDD -24.57%。

### 結果

| profile | τ | Sharpe | 波動% | MaxDD% | CAGR% | 贏VT報酬? | 對VT偏好勝率 |
|---|---:|---:|---:|---:|---:|:--:|---:|
| aggressive_growth | 0.0 | 0.658 | 10.48 | -15.5 | 10.88 | ✗ | 17.2 |
| aggressive_growth | 0.1 | **0.373** | 15.10 | **-26.3** | 8.85 | ✗ | 89.1 |
| aggressive_growth | 0.3 | 0.371 | 16.92 | **-30.14** | 9.23 | ✗ | 93.8 |
| balanced | 0.0 | 0.665 | 10.64 | -15.81 | 11.06 | ✗ | 34.4 |
| balanced | 0.1 | 0.690 | 11.98 | -14.38 | 12.23 | ✗ | 48.4 |
| balanced | 0.3 | **0.711** | 12.63 | -15.73 | **12.93** | ✗ | 62.5 |
| conservative | 0.0 | **0.664** | 10.64 | -15.87 | 11.05 | ✗ | **57.8** |
| conservative | 0.1 | 0.560 | 10.98 | -15.25 | 10.00 | ✗ | 34.4 |
| conservative | 0.3 | 0.601 | 11.61 | -15.20 | 10.83 | ✗ | 45.3 |

### 結論：trade-off 形狀**強烈** profile 依賴（確認 `05` §5 / §4.9）
1. **aggressive_growth：τ 傾斜是「災難」。** τ↑ → 波動衝到 16.9%、MaxDD 惡化到 -30%、Sharpe 崩到 0.37、**CAGR 反降到 ~9%**。偏好勝率雖升到 94%，但**承擔大量風險卻換到負的報酬報償**。→ **強力佐證：往「CAGR 排名」傾斜 ≠ 拿到報酬，只是白白加風險。報酬導向使用者不能用排名傾斜服務，必須 U-C2（系統性風險溢酬/beta）。**
2. **balanced：τ 傾斜是「雙贏」。** τ↑ → Sharpe(0.665→0.711) 與 CAGR(11.06→12.93) 同升、偏好勝率也升。**無 trade-off，甚至正相關。** balanced τ=0.3 是全場最佳全方位點（Sharpe 0.711 > VT 0.645、CAGR 12.93% 近 VT 但波動低很多）。
3. **conservative：τ≈0（純最小變異）已是甜蜜點。** τ=0 同時拿到最高 Sharpe(0.664) 與最高偏好勝率(57.8%)；加 τ 反而兩者皆降。**最小變異本身就最大化保守型的偏好，不需傾斜。**
4. **沒有任何 profile 在任何 τ 贏過 VT 的 CAGR(13.51%)**（最接近：balanced τ=0.3 的 12.93%）。確認：現有工具無法贏過 VT 絕對報酬。

### 對 τ 映射的含義
τ 應 profile 依賴：**保守型 → τ≈0；平衡型 → τ 中高（雙贏）；報酬導向 → 不用排名傾斜，改走 U-C2。**

## 2026-06-05：升級 A 完成 — 偏好→參數映射 g(w)（U-C2 前置）

狀態：完成並驗收（純 helper，預設關閉，不影響 Arm A/C 現有行為）。

### 改了什麼
- `parameters.py`：新增 `USE_PREF_PARAM_MAPPING`（預設 False）+ 映射係數（`CORE_MODE_T_LOW=0.40`、`CORE_MODE_T_HIGH=0.65`、`VOL_BUDGET_BASE=0.10`、`VOL_BUDGET_SLOPE=0.40`、`VOL_BUDGET_MIN/MAX=0.10/0.45`、`TAU_MAP_COEF=0.30`）。
- `functions.py`：新增 `derive_params_from_weights(global_weights)`，回傳 `{R, T_growth, core_mode, vol_budget, tau}`。
- `backtest_engine.py`：直接 `from functions import derive_params_from_weights`（**單一真理來源，保證兩系統數值完全一致**，免去手動同步風險）。
- 驗收腳本：`_verify_gw_mapping.py`（印 7 profile 映射表）。

### 設計決議（2026-06-05，使用者確認）
1. **核心類型用「資本利得渴望」選，不用總報酬**：`T_growth = CAGR/(CAGR+Vol+MaxDD)`。理由：核心=「要不要買成長/市場風險」，股息渴望不該把收入型推進 beta 核心。修正了初版 income 被誤分到 beta（高波動低股息）的問題。股息偏好改由 τ 傾斜處理。
2. **τ 保平滑小量級、只編碼方向**：`τ = 0.30·(1−T_growth)·R̂`。不硬擬合單一路徑 sweep 的甜蜜點（避免 overfit），精確量級交給 walk-forward。beta 核心（高 T_growth）自動低 τ；收入型（低 T_growth、高 R）自動拿到較高 τ 做股息傾斜。

### 驗收結果（7 profile，方向全部合理）
| profile | R | T_growth | core | vol_budget | τ |
|---|---:|---:|:--|---:|---:|
| aggressive_growth | 0.550 | 0.846 | beta | 0.438 | 0.025 |
| return_leaning | 0.500 | 0.667 | beta | 0.367 | 0.050 |
| cost_liquidity | 0.280 | 0.474 | market | 0.289 | 0.044 |
| balanced | 0.350 | 0.449 | market | 0.280 | 0.058 |
| diversified_quality | 0.250 | 0.405 | market | 0.262 | 0.045 |
| income | 0.500 | 0.312 | minvar | 0.225 | 0.103 |
| conservative | 0.200 | 0.138 | minvar | 0.155 | 0.052 |

- income → minvar + 低 vol_budget + 最高 τ（股息傾斜）✓；conservative → minvar + 最低 vol_budget ✓；beta 核心 → 低 τ ✓。

## 2026-06-05：升級 B 完成 — U-C2 profile-dependent 三核心（Arm "C2"）

狀態：實作完成 + 煙霧測試通過（合成資料，三核心皆正常）。尚未跑真實多 profile 回測。

### 改了什麼（兩檔同步）
- `functions.py`：
  - 新增共用 helper `compute_benchmark_cov_vector(etf_returns, benchmark_returns)` → 回傳 `(c, var_bench)`，`c[i]=Cov(rᵢ,r_bench)·252`、`beta=c/var_bench`。只需每日報酬。
  - 新增主系統用 `get_benchmark_returns_aligned()`（抓 VT 價格、對齊 returns_matrix 交易日）。
  - Stage 3 新增 `OPTIMIZATION_ARM=="C2"` 分支：用 `derive_params_from_weights()` 取 core_mode/τ/vol_budget，三核心目標：minvar=`½wᵀΣw−τ·wᵀs`、market=`½wᵀΣw−wᵀc−τ·wᵀs`、beta=`max wᵀβ+τ·wᵀs`；共同約束 Σw=1 / 界內 / 波動預算 / 成本 / HHI；三層 fallback。
- `backtest_engine.py`：
  - `from functions import compute_benchmark_cov_vector`（c 向量算法單一真理來源）。
  - `optimize_preference_portfolio` 加 `benchmark_returns` 參數 + 與主系統逐項相同的 C2 分支。
  - `run_rolling_backtest`：ARM=="C2" 時從 `prices[benchmark]` 取 lookback 報酬流傳入（只用報酬，不需成分權重）。
- `parameters.py`：`OPTIMIZATION_ARM` 註解加 "C2"。
- 煙霧測試 `_smoke_c2.py`：beta 估計 ≈ 真值；minvar→分散、market→port_beta≈1.00、beta→往高 beta 傾斜，權重皆 Σ=1 合法。

### 設計要點
- market 核心 `min ½wᵀΣw − wᵀc` 等價於對 VT 報酬流最小化追蹤誤差（`min Var(r_p−r_VT)`），用真實 VT 報酬流，**不需任何成分權重**。
- 取不到基準共變異時 market/beta 核心自動退回 minvar（兩檔一致）。
- C2 一律使用 g(w)（`USE_PREF_PARAM_MAPPING` 旗標保留供未來讓 Arm C 也吃 g(w)，目前 C2 不依賴它）。

### 待驗證（下一步）
- 真實多 profile rolling backtest：C2 vs Arm C vs VT。**關鍵驗收**：aggressive_growth 在 C2(beta 核心) 下 CAGR 須突破 Arm C 的 ~9%、逼近/超過 VT 13.51%（C2 存在的唯一理由）；balanced/conservative 不得低於 Arm C 甜蜜點。
- 跑前設 `OPTIMIZATION_ARM="C2"`，**跑後務必還原 "A"**。

## 2026-06-05：C2 風險預算改「相對候選池可行波動範圍」（修正無解 + 脫離池子問題）

狀態：實作完成 + 煙霧測試通過。使用者確認採此版（非單純 floor）。

### 問題（使用者指出）
g(w) 原本輸出絕對 `vol_budget`（aggressive 0.438、conservative 0.155）。兩個缺陷：
1. **可能無解**：若候選池最小變異組合的波動 > vol_budget，`√(wᵀΣw)≤vol_budget` 約束無解（舊版只能逐層 drop 掉約束 → beta 核心會失去風險控制，壓到最高 beta 標的）。
2. **脫離當期池子**：絕對值可能高到沒意義（0.438）或低到不可行，與當期選到的 ETF 實際可達波動範圍無關。

### 修法
- g(w) 改輸出無量綱 `risk_fraction∈[0,1]`（= clip(T_growth, RISK_FRACTION_MIN=0.05, MAX=0.95)；另有 `RISK_FRACTION_OVERRIDE` 供實驗掃描）。
- 新增共用 helper `compute_feasible_vol_budget(cov_annual, max_weight, risk_fraction)`（functions.py，backtest import）：
  - `v_min` = 最小變異組合波動（min wᵀΣw s.t. Σw=1,0≤w≤cap）
  - `v_max` = 最大變異組合波動（max wᵀΣw 同約束）
  - `vol_budget = v_min + risk_fraction·(v_max−v_min)`，夾 ≥ v_min·(1+1e-3) → **恆可行**。
- 兩檔 C2 分支改呼叫此 helper 算 vol_budget。

### 煙霧測試（合成池可行範圍 [12.4%,19.2%]）
- conservative rfrac=0.14 → 預算 13.3%（貼 v_min）、實際 port_vol 13.4% ✓
- balanced rfrac=0.45 → 預算 15.5%（中段）、beta 0.94 ✓
- aggressive rfrac=0.85 → 預算 18.2%（貼 v_max）、**port_vol 18.2% 卡到預算**、beta 1.12 ✓（風險預算成為主動控制，用滿去買 beta）

→ 永不無解、永遠相對當期池子、beta 核心的風險控制有效。

## 2026-06-05：s_full vs s_noCAGR 比較（完成）— ★資本利得排名有害★

狀態：完成（Arm C，3 profile × 2 s-version × 2 τ = 12 回測）。輸出：`upgrade_figures/s_sweep/s_sweep_summary.csv`。
VT 參考 CAGR 13.51%。問題：傾斜目標 s 含資本利得排名(Norm_Return_CAGR)是否幫得上 OOS？

### 結果
| profile | τ | s | Sharpe | Vol% | MaxDD% | CAGR% | 贏VT | win_VT |
|---|---:|:--|---:|---:|---:|---:|:--:|---:|
| conservative | 0.1 | full | 0.560 | 10.98 | -15.25 | 10.00 | ✗ | 34.4 |
| conservative | 0.1 | **noCAGR** | 0.624 | 11.23 | -16.75 | 10.91 | ✗ | 25.0 |
| conservative | 0.3 | full | 0.601 | 11.61 | -15.20 | 10.83 | ✗ | 45.3 |
| conservative | 0.3 | **noCAGR** | 0.670 | 11.75 | -17.37 | 11.81 | ✗ | 54.7 |
| balanced | 0.1 | full | 0.691 | 11.98 | -14.38 | 12.23 | ✗ | 48.4 |
| balanced | 0.1 | **noCAGR** | 0.756 | 11.86 | -16.97 | 13.02 | ✗ | 56.2 |
| balanced | 0.3 | full | 0.711 | 12.63 | -15.73 | 12.93 | ✗ | 62.5 |
| balanced | 0.3 | **noCAGR** | **0.782** | 12.50 | -17.83 | **13.84** | ✓ | 70.3 |
| return_leaning | 0.1 | full | 0.666 | 12.26 | -14.21 | 12.07 | ✗ | 89.1 |
| return_leaning | 0.1 | **noCAGR** | 0.685 | 11.53 | -16.44 | 11.87 | ✗ | 68.8 |
| return_leaning | 0.3 | full | 0.558 | 13.85 | -19.22 | 11.35 | ✗ | 92.2 |
| return_leaning | 0.3 | **noCAGR** | **0.841** | 12.28 | -17.03 | **14.50** | ✓ | 93.8 |

### 結論（決定性）
1. **noCAGR 在 Sharpe 上 6/6 勝過 full**；CAGR 5/6 勝（唯一例外 return_leaning τ=0.1，CAGR 12.07 vs 11.87 接近，但 noCAGR Sharpe 仍較高）。
2. **高 τ 時差距爆炸**：含 CAGR 排名在強傾斜(τ=0.3)下**有毒**——return_leaning τ=0.3 full 崩到 0.558/CAGR11.35，noCAGR 飆到 **0.841/CAGR14.50**。即「CAGR 排名」正是讓強傾斜變壞的元兇；拿掉它，強傾斜反而大有助益。
3. **兩個 noCAGR 配置贏過 VT**（皆 τ=0.3）：balanced 13.84%、return_leaning 14.50%，且**波動更低、回撤更淺、Sharpe 更高**（return_leaning：vol 12.28% < VT 15.3%、MaxDD -17% < VT -24.6%）。**重大更正：先前「沒有 profile 贏過 VT」是含 CAGR 排名(s_full)的假象！**
4. 代價：noCAGR 回撤略深（約 -17% vs -15%），但遠優於 VT。
5. 機制（呼應 03 §1.1 / 05 §4.9）：資本利得排名=追過去贏家（會均值回歸），不預測未來報酬；拿掉後傾斜改載在較持久的訊號（股息/品質/低成本/低風險）。

### 行動
- **決議：`TILT_INCLUDE_CAGR` 預設改 False（noCAGR）** 套用於 Arm C / C2（預設 ARM="A" 不受影響）。C2 實驗 Part 2 用 noCAGR。
- ⚠️ 單一路徑結果，須 walk-forward 驗證（尤其「贏 VT」的 τ=0.3 noCAGR 是否跨期穩健）。方向性結論（CAGR 排名有害）跨 12 格一致，較可信。

## 2026-06-05：U-C2 多 profile 驗證 + risk_fraction 行為地圖（完成）— ★U-C2 驗證成功★

狀態：完成。**完整成果見 `06_overnight_experiment_report_2026-06-05.md`。** 輸出：`upgrade_figures/c2_experiment/{c2_multiprofile_summary,c2_riskfraction_map}.csv`。

### Part 1：多 profile C2 vs Arm C（重點）
- C2 在 Sharpe+CAGR 上 **6/7 profile 勝過 Arm C**。
- **aggressive_growth：Arm C 8.85% CAGR → C2 beta 核心 13.80%（贏 VT 13.51%）**，代價 vol 18.65%、Sharpe 0.573（<VT）→ U-C2 核心目的達成。
- C2(noCAGR) 4 profile CAGR 贏 VT：aggressive 13.80 / return_leaning 14.12 / income 14.27 / cost_liquidity 14.15。
- income(minvar+強股息傾斜) 最佳全方位：Sharpe 0.858、CAGR 14.27、vol 11.71、win_VT 100%。
- **張力**：beta 核心 win_VT 低（aggressive 42%、return_leaning 11%）= 報酬導向用 beta 核心會犧牲「偏好分數招牌」；minvar/market 核心保住招牌（income 100%、balanced 64%）。

### Part 2：risk_fraction 行為地圖（回答「能否用風險換報酬」）
- **能**：beta 核心 rf 0→1 呈乾淨「風險↑→報酬↑」（aggressive 9.2%vol/13.47%CAGR → 19.8%vol/15.54%CAGR）。
- **但 Sharpe 遞減**（0.99→0.63）→ 印證低波動異常：買得到絕對報酬，買不到風險調整報酬。
- **rf=0（最小變異端）Sharpe 最高(0.99)、CAGR 已近 VT(13.47%)、vol 僅 9.2%** → 此期間防禦端 CP 值最高（強烈受 2021–26 因子運氣影響，須 walk-forward）。
- market 核心 rf≥0.5 飽和（預算不再綁定，符合設計）。

### 結論與待辦
- U-C2 驗證成功；最大可推廣發現是 noCAGR（不動核心就讓多 profile 贏 VT）。
- **下一步：walk-forward（多視窗）驗證**「贏 VT」非單期運氣；定調兩個張力（beta vs 偏好招牌、rf 高低）。
- ⚠️ 全為單一路徑，數字僅指示性。

## 2026-06-05：偏好分數結構分析 + 資本利得成長獎勵修正（展示層）

### 結構分析（使用者提問：偏好分數有沒有獎勵資本利得成長？）
- `Norm_Return_CAGR` = `robust_scale`：clip 到 [p1,p99] 後線性 min-max（**winsorized min-max，非純排名**）。
- 全宇宙 491 檔實測：clip 上界 p99=55.15%，**前 5 名（CAGR 56%~132%）分數全被砍平到 1.0**；p99 以上「每多 1% CAGR → +0.0000 分」。區間內線性 +0.0179/1%。
- **三層結構限制讓成長獎勵不足**：① winsorize 砍平上尾（極端成長零差別）；② 橫斷面相對、每期重正規化（無法表達絕對成長）；③ 上限 [0,1] 與其他 8 維同天花板（卓越成長無法壓過其他維度）。
- 加上 V-1：此「過去 CAGR」分數不預測未來報酬（r≈0）。
- **結論：使用者直覺正確**——分數對成長幅度（尤其極端/絕對成長）獎勵不足。

### 「拿掉 CAGR 權重去哪」的答案
- `s_noCAGR = s_full − w_CAGR·Norm_CAGR = Σ_{k≠CAGR} w_k·Norm_k`：**CAGR 權重直接丟掉、不重分配**；其餘 8 維維持原絕對權重（總和=1−w_CAGR），方向不變、強度縮小。
- 解釋了為何成長型需要 beta 核心：拿掉 CAGR 後成長型的傾斜幾乎被掏空。

### 修正（使用者決議：現在就修，但只為招牌/展示，不進最佳化器）
- **關鍵安全性**：最佳化器為 noCAGR → `s_noCAGR` 中 `Norm_Return_CAGR` 完全抵消（User_Pref_Score 的 +w_CAGR·Norm_CAGR 與被減項對消，代數上恆等），故改 `Norm_Return_CAGR` 只影響展示/評估分數（V-1/V-6、維度比較），**不影響 Arm C/C2 noCAGR 最佳化**。僅改 CAGR 一維（Div 等若改會經 s_noCAGR 漏進最佳化，故不動）。
- 作法：新增 `PREF_SCORE_CAGR_UPPER_Q`（預設 0.999，原 0.99），放寬 CAGR 上尾 winsorize，讓極端高成長不再被砍平到同一個 1.0。兩處同步：functions.py（主管線 stage2 正規化）+ backtest_engine.py（scale_preference_features）。
- 限制（誠實）：只能修 ①（砍平）；②橫斷面相對 與 ③同天花板 是 min-max 加權和的結構特性，要動需重新設計整個分數（會牽動其他維度與最佳化器），本次不做。

## 2026-06-05：Walk-forward 穩健性驗證（完成）— ★修正單期樂觀★

狀態：完成。完整分析見 `06` §6.5。輸出：`upgrade_figures/walkforward/{wf_timewindow,wf_lookback}.csv`。
設計：7 profile × 6 滾動時間窗(lb=2y) + 4 lookback(窗 2021-26)。資料 2016-2026。

### 關鍵結論
- **跨 6 窗後，只有 beta 核心 profile 穩健贏 VT 絕對 CAGR**：aggressive 4/6、return_leaning 5/6。其餘(income/balanced/cost_liquidity/diversified_quality/conservative)贏 VT 0-1/6 CAGR。
- **單一路徑 2021-26 的「4 profile 贏 VT」大半是該窗運氣** → 已修正：minvar/market profile 的價值在 Sharpe/回撤/偏好分數(win_VT)，非絕對報酬。
- 風險換報酬跨規制一致：beta 贏 CAGR 不贏 Sharpe；market/minvar 贏 Sharpe 不贏 CAGR，從不兼得。
- 強多頭窗(2022-26 VT 20%+)誰都贏不過 VT。
- lookback：lb=2~3 甜蜜區、lb=1 雜訊；beta「贏 VT」對 lookback 略脆弱。
- **誠實對外論述 = 報酬導向(beta)跨規制贏 VT 絕對報酬；其他 profile 贏在風險效率與偏好滿足。**（取代「人人贏 VT」）

## 2026-06-05：排隊實驗（noCAGR 穩健性 / risk_fraction 跨區 / DCA）完成

完整分析見 `06` §6.6。輸出：`upgrade_figures/queued/{exp3_nocagr_robustness,exp4_riskfraction_regime,exp5_dca}.csv`。

- **Exp3 ★第二個更正★**：noCAGR vs full 跨 6 窗是 **regime-dependent、大致 wash**（full 在 2018-22、2021-24 還贏，return_leaning full 甚至兩窗 CAGR 贏 VT）。單期「noCAGR 壓倒 full」也是 2021-26 窗現象。→ **`TILT_INCLUDE_CAGR=False` 預設翻轉不被跨區證據支持（財務 wash）；決策待使用者定調**（principle noCAGR vs signature full）。已在 parameters.py 標註待定。
- **Exp4 ★強化 U-C2★**：risk_fraction 0→1「風險↑→報酬↑」跨 3 規制窗全成立、Sharpe 隨 rf 遞減全成立、高 rf 在非強多頭窗能贏 VT、market 核心 rf≥0.5 飽和。**U-C2 核心機制跨規制穩健（最可靠發現）。**
- **Exp5 DCA**：時間加權 Sharpe/CAGR 單筆≈DCA（同持股）；財富倍數單筆>DCA 每窗（多頭早投入贏）；DCA 降跨窗離散度、高波動組合絕對降幅最大（弱支持使用者直覺）但同降平均、CV 不變。量測限制：未調投入時點，宜改用 IRR。

## 2026-06-05：beta 錨 VT vs VTI 解耦實驗（完成）— 結論：錨是弱槓桿

新增 `BETA_ANCHOR_TICKER`（parameters.py，預設 None=沿用報告基準），讓 C2 beta/market 核心的市場錨可與報告基準解耦（兩檔同步：functions.py + backtest_engine.py）。動機：使用者構想「換 VTI(整體美國市場)是否拉開報酬導向 vs 保守的價差，讓偏好敘事更一致」。
實驗：4 profile × {VT,VTI} 錨 × 2 窗（2021-26、2020-23含熊）。報告基準維持 VT。輸出 `upgrade_figures/anchor_test/anchor_test.csv`。

### 結論
- **解耦正確**：conservative(minvar)在兩錨下數字完全相同（控制組通過）。
- **VTI 效果又小又混**：aggressive 近窗微好(+0.43% CAGR)、2022 熊市窗更差(-1.09%)；return_leaning/balanced 兩窗皆略差。
- **價差未穩健拉開**：近窗 aggressive−conservative CAGR 價差 2.89%→3.32%(微增)，熊市窗 5.60%→4.51%(反縮)。
- **根因**：候選池(DEA+分群後)幾乎全是美國 ETF，故 VT(全球) vs VTI(美國)的 beta 排序幾乎不變 → 換錨效果天生很小。
- **真正的價差槓桿 = 核心類型(beta vs minvar) + risk_fraction(rf)**，非錨。Exp4 已證 rf 0→1 把 aggressive 從 ~9%vol/13%CAGR 推到 ~20%/20%，遠大於換錨。且現有 VT 設定下「報酬導向高波動高報酬Sharpe不定 / 保守低波動穩Sharpe」的敘事已成立。
- **決議**：錨維持 VT(理論乾淨=全球市場/CAPM先驗、誠實基準)；`BETA_ANCHOR_TICKER` 解耦功能保留備用。要更大價差改調 rf 映射。

## 2026-06-05：偏好分數「報酬維度」改用 beta 評分（A/B 測試成功）

動機（使用者 Q3/Q6）：目標是讓「每種使用者類型的偏好分數都容易贏」。報酬維度用「過去 CAGR 排名」不持續(V-1 r≈0) → 報酬導向 win_VT 墊底。改用 beta(系統性風險曝險，會持續、beta 核心交付得了)。
實作：新增 `PREF_RETURN_BASIS`("cagr"/"beta")、`PREF_BETA_REF=2.0`；報酬分數 = `clip(beta_vs_anchor/REF,0,1)`(VT beta=1→0.5)。**只動評估/偏好分數(win_VT)，不動最佳化器傾斜 s → 投組完全相同 → 乾淨 A/B**。`calculate_portfolio_utility` 加 `benchmark_returns` 參數，5 個評分呼叫點傳入(forward/benchmark/equal/maxsharpe 用評估截面 VT、ex-ante 用 lookback VT)。輸出 `upgrade_figures/beta_score_test/`。

### 結果（CAGR/Sharpe 兩基礎完全相同 → 確認最佳化器未動）
- win_VT（cagr→beta）：aggressive 13.6→**66.1**(2021-26)、5.6→**38.9**(2020-23)；return_leaning 11.9→25.4、5.6→13.9；balanced 72.9→69.5；income 100→100；conservative 57.6→42.4。
- **vs EqualWeight/MaxSharpe：beta 基礎幾乎全部→~100%**（aggressive vs EW 59→100、vs MS 25→100）。
- 解讀：✅ 核心假設成立(報酬導向 win 大幅提升)。對 VT 未達 100% 因 VT 在成本/分散/流動性結構維度近滿分，集中型高 beta 投組本就不該贏分散度(誠實)。return_leaning 改善較小=偏好矛盾(要報酬又給抗波動 0.14)；conservative 微降=低 beta 報酬維度本就該低分(誠實)，且仍贏 EW/MS。
- **評估**：beta 基礎明確更好、理論更乾淨(獎勵持續的系統性風險曝險=預期報酬誠實來源)。

### 修正：低 beta 不懲罰（使用者要求）
公式改為 `報酬分數 = 0.5 + 0.5·clip((beta−1)/(REF−1),0,1)`：市場(beta=1)=0.5、低於市場 floor 0.5(不扣)、beta=REF→1.0。
重跑結果（win_VT，cagr→修正beta）：aggressive 13.6→**67.8**/5.6→**47.2**(維持);conservative 57.6→**64.4**/36.1→**38.9**(從被扣的 42.4 回升、甚至高於 cagr);return_leaning 11.9→37.3/5.6→22.2;balanced 72.9→84.7;income 100→100。對 EW/MS 全部 ~85-100%。
**結論：每個 profile win_VT 都「不降反升」，達成「每種使用者偏好分數都容易贏」。CAGR/Sharpe 兩基礎完全相同 → 求解器未動(純展示/評估層)。**
### 正式採用 + 主系統同步（2026-06-05，使用者確認）
- `PREF_RETURN_BASIS` 預設改 **"beta"**。
- **主系統 functions.py 同步**：`calc_utility(w, for_display=False)` 加旗標；`for_display=True` 且 basis="beta" 時報酬維度用 `beta_score_vec`（同公式，市場錨 VT，與 backtest 一致）。`pref_utility_score`/`ms_utility_score` 4 處改 `for_display=True`。
- **★求解器完全未動★**：`objective_function` 用 `calc_utility(w)`（不帶 for_display）→ Arm A 目標仍 CAGR；Arm C/C2 自有目標、不經 calc_utility。per-ETF `User_Pref_Score`（傾斜 s）也仍 CAGR。
- 驗證(主系統 Stage 3 跑通)：pref_utility_score cagr=0.7027 → beta=0.5907（展示已同步、不崩）；求解器投組相同為結構保證。
- CAGR 仍保留(Norm_Return_CAGR)供 V-1 展示。

## 2026-06-05：品質約束系統化框架 + OAT-1（成本）★負面結果★

### 框架（設計見 07）
門檻 = 該維度當期候選池可行範圍 [v_min,v_max] 內的偏好加權位置（恆可行）。tightness 中性點 = 該使用者品質 5-slot 平均權重；fully tight at FULL_RATIO(=2)×平均。新 helper（functions.py，backtest import）：`quality_tightness_map / feasible_linear_range / quality_threshold / feasible_hhi_range / liq_composite_vector / build_quality_constraints`。四個品質區塊（functions Arm C/C2 + backtest Arm C/C2）全換成框架；魔術數字 0.75/0.50 棄用。逐維度開關 `QC_ENABLE_COST/HHI/LIQ/SENT`。流動性合併依 Vol:AUM 比例。

### OAT-1：成本約束 off vs on（C2 noCAGR + beta 評分，7 profile × 2 窗，月度）
- 框架正確：ts=0 的 profile（aggressive、diversified_quality）off==on 完全相同。
- 本來就便宜的 profile（return_leaning、balanced）→ 約束不綁定、零影響。
- 持高費用 ETF 的 profile：約束有壓低費用率但**傷 OOS**：income avg_cost 0.286→0.142、Sharpe 0.759→0.692；conservative 0.312→0.221、Sharpe 0.682→0.572、win_VT 72.9→59.3；**cost_liquidity（ts=1.0）win_VT 96.6→57.6（傷最重）**。
- **★洞察：成本這種「逐檔線性特徵」已軟性在偏好傾斜(User_Pref_Score)+DEA 篩選裡；再加硬約束＝重複計算+過度強調，把投組推離最佳點，甚至跟 income/conservative 的主偏好(高股息/防禦)打架。★**
- **決議：不採用硬成本約束（`QC_ENABLE_COST=False`）。** 推論：逐檔線性維度(成本/流動性/情緒)都可能同此問題；唯一真正需要硬約束的是 **HHI(投組層級湧現性質，軟傾斜表達不了)** → OAT-2 測 HHI（季度）。

## 2026-06-05：OAT-2(HHI) + OAT-3(流動性) + 品質約束收尾結論 ★硬品質約束無益★

（季度再平衡加速；C2 noCAGR + beta 評分；7 profile × 2 窗 × off/on）
- **OAT-2 HHI**：6/7 profile off==on **完全相同**（連 tightness 0.71 的 balanced 都不綁定）；唯一 ts=0.89 的 diversified_quality 微綁定且**輕微負面**（Sharpe 0.562→0.544）。→ **多餘**：C2 核心 + DEA + 分群已使投組夠分散（每期 ~33-35 檔、權重分散）。
- **OAT-3 流動性**：**每一格 off==on 完全相同**（連 cost_liquidity liq_ts=0.058 都不綁定）→ **完全 inert**。
- 輸出：`upgrade_figures/{oat_hhi,oat_liq}/`。

### ★收尾結論：硬品質約束對本系統無價值★
三個 OAT：成本=有害、HHI=多餘、流動性=inert。情緒(OAT-4)同為逐檔線性維度+資料不穩(使用者指出)→ 跳過。
**品質已由三層處理：軟性偏好傾斜(User_Pref_Score 含 9 維)+ DEA 篩選(基線)+ 核心(分散自然湧現)。** 硬約束只重複計算/扭曲。
**決議：所有 `QC_ENABLE_*=False`（框架保留但預設全關）。** 奧坎剃刀：用更簡潔的「軟傾斜+DEA+核心」處理品質。
- 系統現況：C2 求解約束僅 `Σw=1 + 界內 + vol_budget`（品質約束全關）。
- 框架程式碼(`build_quality_constraints` 等)保留備用，魔術數字 0.75/0.50 已棄用。

## 2026-06-05：Black-Litterman 路(a) 實作 + A/B（統一 BL vs 三核心 C2）

實作 `OPTIMIZATION_ARM="BL"`（與 C2 並存,兩檔同步）：統一目標 `max wᵀΠ + τ·wᵀs s.t. vol≤budget`，Π=市場隱含報酬(用 β=c/var_bench)、約束式（λ_mkt 縮放不變消去、λ_user 由 vol_budget 取代）、risk_fraction 不變、保留傾斜。設計與結論見 `08`。

### A/B 結論（季度,7 profile × 2 窗；`upgrade_figures/bl_ab/`）★負面結果但確立三核心★
- beta 端(aggressive/return_leaning)：**C2==BL 完全相同**。
- minvar/market 端：**統一 BL 明顯更差**（balanced win_VT 80→0、conservative 60→5、income Sharpe 0.776→0.597、cost_liquidity 100→50、diversified_quality 80→0;回撤普遍更深）。
- 原因：保守型 vol_budget>v_min,BL「在預算內衝 beta」會花掉風險預算買 beta → 推向市場、失去低波動/防禦優勢 → win_VT 崩。
- **敘事**：以 BL 為理論基礎開發統一模式 → 發現市場/保守型在「給定風險預算下追 beta」反而結果變差、偏好分數大降 → 因此用三核心(minvar/market/beta)解決,而三核心正是 BL 不同風險趨避的效率前緣點。
- **決議**：維持三核心 C2 為運作設計;**BL 當 C2 的理論正名(Π=CAPM 市場隱含報酬,三核心=BL 前緣點)**;BL 臂保留為消融對照。`OPTIMIZATION_ARM` 還原 "A"。

## 2026-06-05：rf 上限封頂測試（負面結果，已還原）— 「衝報酬 Sharpe 遞減」張力收尾

動機：Exp4 顯示報酬導向 rf 高(~0.85)時 Sharpe 低。假設「封 rf 上限到 0.6 可避開回撤、保留多數報酬」。
驗證(`_rf_cap`,C2 noCAGR+beta,aggressive/return_leaning × {cap0.95,cap0.60} × 2 窗,季度;`upgrade_figures/rf_cap/`)：
- **封到 0.6 全面更差**：aggressive 2020-23 CAGR 19.81→17.23、MaxDD -22.4→**-25.7(更深)**、Sharpe 0.864→0.819;2021-26 13.01→11.92、-22.9→-26.0。return_leaning 同向。
- **兩個誤判**：(i) 先前「rf>0.6 只增回撤不增報酬」過度套用 2023-26 多頭窗;其他窗高 rf 確實多賺。(ii) **vol 約束 ≠ 回撤控制** → 壓低 vol 預算反而出現更深回撤。
- **結論**：張力是低波動異常的本質,**無免費修法**。報酬導向維持高 rf（最大絕對報酬,低 Sharpe 是誠實代價）。`RISK_FRACTION_MAX` 還原 0.95。
- 方法論價值：假設→驗證→資料推翻建議→誠實還原（若要控回撤,正解是 MaxDD 約束而非壓 vol 預算,列未來）。

## 2026-06-05：DCA 公平重測（XIRR + 跨起始點離散度）— 假設未獲支持

修正 Exp5 的不公平(財富倍數懲罰 DCA 的在場時間)。用 **XIRR(日期感知金額加權報酬率)** + 跨 6 個 3年窗(=6 起始點)離散度。C2 noCAGR+beta,季度,aggressive/balanced/conservative × {lump,DCA}。`_dca_irr.py`、`upgrade_figures/dca_irr/`。
- 量測驗證：lump XIRR ≈ 時間加權 CAGR（16.94 vs 16.95）✓。
- **① 公平 XIRR：DCA 反而略勝**（aggressive +1.20、balanced +2.04、conservative +0.93 %）→ **Exp5「單筆完勝」確為在場時間假象**。但 DCA 略勝是**路徑依賴**（這些窗前跌後漲,DCA 買低）,非結構性優勢。
- **② 進場時機風險(XIRR 跨起始點 std)：DCA 沒更低、反略高**（aggressive 2.96→3.12、balanced 3.31→3.68、conservative 持平）;**高波動組合未更受益**（balanced 受益最多）。→ **使用者假設「DCA 降進場時機風險、高成長更受益」未獲支持。**
- 量測限制：6 個不同窗混了「進場時機 + 市場規制」;更乾淨測法=固定未來、平移起始點小步長（未來精修）。
- **結論**：DCA vs 單筆 ≈ 路徑依賴平手;DCA 可當使用者選項但不宣稱系統性幫高成長。`OPTIMIZATION_ARM` 還原 "A"。

## 2026-06-06：產品化修正 — 偏好回測可用性 + 雷達圖口徑 + 輸出整理（純展示/UX，未動最佳化器）

狀態：完成 + `py_compile` 通過。**最佳化器邏輯完全未動**（兩檔 optimizer 仍逐項相同）；本批僅改使用者體驗：回測前置、雷達圖展示口徑、圖表輸出整理。

### 問題（使用者直接跑 main + 選回測時回報）
1. **偏好回測跑不出來**：`run_rolling_backtest` 擲 `No ETF passes the minimum history filter`。根因＝回測價格快取只有約 3 年，但 prompt 回測窗 `2018-06-01`（近 8 年）＋ lookback 3 年需要 2015-06 起的歷史，`filter_min_history` 全數淘汰。
2. **雷達圖報酬軸口徑矛盾**：報酬軸已改用 beta 評分（與偏好分數一致），但軸上標註仍印「算術年化報酬率 %」→ 出現「偏好解報酬 23.92% < 夏普解 29.57% 但紅線反而更外擴」的矛盾（因為偏好解 beta 較高）。
3. **殖利率軸放大假象**：殖利率用「相對勝負映射」(贏家固定 0.9、輸家固定 0.4)，把「1.76% vs 1.77%」這種 0.01% 微差畫成巨大落差。
4. **要移除兩類圖**：`{case}_portfolio_performance.png`、`{case}_*efficient_frontier*.png`（效率前緣非 C2/BL 實際最佳化所在，描述性、易誤導）。
5. **輸出未分類**：希望 DEA 分布＋EDA 一夾、投組/報表一夾。

### 改了什麼
- **`pipeline_stages.py / stage3b_optional_preference_backtest`**：prompt 回測**資料/視窗固定在 10 年內**（使用者指定）。新增常數 `PROMPT_BACKTEST_WINDOW_YEARS=7`、`PROMPT_BACKTEST_LOOKBACK_YEARS=3`（和=10），移除舊的 `DEFAULT_PROMPT_BACKTEST_START="2018-06-01"`。OOS 起點改**動態**「今天往前推 7 年、取當月 1 號」（隨時間滑動但跨度恆 ≤10 年）；lookback 固定 3 年。`fetch_missing_data=True, fetch_period="max"` 改為**安全網**（既有 ~2016 快取已涵蓋 → 通常不補抓；fresh clone 無快取才補；回測無論如何只用到 10 年資料）。保留「起點漸進回退」`[7y → 5y → 3y]`（仍 ≤10 年），遇 minimum-history 錯誤自動換較近起點，確保一定有結果並告知實際採用窗。
  - 根因確認：回測快取實際從 **2016-05-20** 起；舊 `2018-06-01` 起點 + 3y lookback 需 `2015-06` 資料 → 全淘汰。新 `2019-06-01`（7 年前）起點僅需 `2016-06` 資料 → 既有快取直接涵蓋，免補抓。
- **`functions.py / plot_preference_radar_chart`**：
  - 報酬軸標籤改「報酬（以β對VT評分）」；`metric_map["Return_CAGR"]` 原始代理值由 `Arithmetic_Ret %` 改 `Beta_vs_VT`（`β=…`），讓標註數字與雷達位置（皆 beta）一致。
  - 殖利率軸改「固定尺度映射」`bounded_score(Div_Yield, 0%, 5%)`（取代相對勝負映射）→ 微差忠實重疊、高殖利率才外擴。
  - axis label 取值加 `ms_metrics` 在場 + `notna` 防呆（beta 缺值時優雅退回「無單一原始代理值」）。
- **`functions.py / run_stage3_pipeline`**：停用 `plot_portfolio_analytics_and_mpt(...)` 呼叫（不再輸出績效圖與效率前緣圖；雷達圖保留）。
- **`functions.py` user_results 收集器**：每次主系統推薦輸出改分兩個子夾 `01_screening_eda/`（eda_*、*dea* 圖＋`stage1_dea_results.csv`）與 `02_portfolio/`（`{case}_radar_chart.png`＋推薦報表）；02 改精準收雷達圖，避免把舊殘檔（已停用的績效/前緣圖）一起複製進來。

### 驗證
- `py_compile`：functions.py、pipeline_stages.py 皆 COMPILE_OK。
- 安全性：未觸碰任何 optimizer 分支、傾斜 s、約束、g(w)；`Beta_vs_VT` 已由 `get_portfolio_metrics` 對 pref/ms 兩組計算（functions.py L3185），標籤可用。

## 2026-06-06：輸出整理 / 雷達β尺度 / 集中式 log / 最終系統瘦身（均非 optimizer 改動）

狀態：完成 + 核心模組 import 驗證通過。**optimizer 仍逐項相同、未動。** 本批屬 UX / 輸出 / 打包。

### (1) 回測夾巢狀 + 四分類 + 還原數學前緣（使用者要求）
- `BacktestConfig.user_results_parent`（新欄位）：主系統 prompt 回測會帶入剛建立的 `user_results/main_*/` 路徑 → 回測夾巢狀其中；獨立執行時 None=自成一夾。functions.py 在收集器設模組全域 `LAST_MAIN_USER_DIR`，stage3b 讀取後傳入。
- `_mirror_run_figures_to_upgrade` 改**四子夾**：`01_text_reports`(.txt/.md) / `02_eda_dea_figures`(含 eda/dea 的 png) / `03_performance_figures`(nav/drawdown/績效/雷達/年報酬/權重演化) / `04_data_csv`(.csv)，依副檔名+檔名分類。
- 主系統**還原輸出「數學解效率前緣圖」**（使用者要求保留 Mathematical Efficient Frontier）：重新啟用 `plot_portfolio_analytics_and_mpt` 呼叫；函式內仍停用 `portfolio_performance.png` 與蒙地卡羅前緣；`02_portfolio` 收集器加入該前緣圖。

### (2) 雷達報酬軸 beta 尺度重校（使用者拍板 β=1.2）
- 新增 `parameters.RADAR_BETA_REF = 1.2`，**與 `PREF_BETA_REF`(=2.0) 解耦**：雷達報酬軸 `0.5+0.5·clip((β−1)/(REF−1))` 改用 RADAR_BETA_REF → β=1.11→0.78（本系統 β 天花板約 1.1~1.2，原 REF=2.0 把軸壓在 0.5~0.56）。
- **只動雷達顯示，win_VT 偏好分數完全不變**（仍 REF=2.0）。使用者問同步改 scoring 的成本評估：correctness 0 支實驗需重跑（REF 不進 optimizer，CAGR/Sharpe/所有結論不動），只 win_VT 數字會上移→只需重跑 `_beta_score_test.py`+更新 REPORT_A/02。**決議：暫不同步、維持解耦**（雷達要鑑別度、scoring 保守不灌水）。

### (3) 集中式 log（使用者要求 log 集中、未來 log 也進去）
- `parameters.LOGS_DIR="logs"`；functions.py logging 設定加 UTF-8 `FileHandler` → 每次執行寫 `logs/run_<時間戳>.log`（固定 INFO 以上、比終端完整；終端 VERBOSE 噤聲行為不變）。best-effort try/except。
- 既有 13 個根目錄 `*.log` 移入 `logs/`；`.gitignore` 加 `logs/`。

### (4) 最終系統瘦身（原地整理；GitHub 只推「最終系統」）
- 依相依性稽核（Explore 全圖）：`git rm --cached` 移除追蹤但保留磁碟檔——生成輸出 `backtest/ png/ report/ sentiment_engine/reports/(1046檔) sentiment_engine/plots/ sentiment_engine/news_sentiment_report.md`、非生產 `version_0/ test_LLM/ demo/ .vscode/`、殘留測試 JSON 3 支。`.gitignore` 同步加入。
- **追蹤檔 1287→94、25MB→8MB**。保留集合 = 核心 .py + `active_preference/` + `sentiment_engine/`(.py+daily cache) + `experiments/` + `system_upgrade_records/` + `literature/` + `json/csv` 設定 + `local_finbert` tokenizer/config + 文件 + requirements + `.env.example`（使用者選擇保留三個佐證夾）。
- 驗證：`import parameters, functions, backtest_engine, pipeline_stages` 全 OK（程式層獨立可跑；資料/.env/FinBERT 權重照常首次擷取/下載）。

### Commits
`5a5403a`(產品化UX) → `900b9b3`(回測10年窗) → `10edd1e`(回測巢狀+四分類+還原前緣) → `3e70178`(雷達β=1.2) → `ac3f1e6`(集中式log) → `293084b`(最終系統瘦身)。

## 2026-06-06：可控的「使用者選擇」旋鈕 ACTIVE_USER_PROFILE（修正 Neutral_user 被寫死為 return_leaning）

狀態：完成 + 多 user 驗證。非 optimizer 改動（只改「系統輸入的偏好權重從哪來」）。

### 問題（使用者指出）
主系統輸出的雷達圖權重（報酬 40%/殖利率 10%/抗波動 14%/抗回撤 6%…）其實 = `USER_PROFILES["return_leaning"]`，並非 neutral。根因：靜態 AHP 模擬 `build_user_simulation(deterministic=True)` 產出的權重固定 ≈ return_leaning，卻掛名 `CASE_NAME="Neutral_user"`，且無法切換使用者。

### 改了什麼
- `parameters.py`：新增單一控制旋鈕 `ACTIVE_USER_PROFILE`（可用環境變數覆寫：`ACTIVE_USER_PROFILE=conservative python main.py`）。設成 `USER_PROFILES` 的 key → 用該原型的 9 維全局權重當系統輸入；None → 沿用原 AHP 模擬（Neutral_user）。打錯 key 直接 `raise ValueError` 列出合法選項（避免靜默跑錯）。`CASE_NAME` 改成隨 `ACTIVE_USER_PROFILE` 變動（有 profile 用 profile 名、否則 Neutral_user）→ 輸出檔名/標題/`user_results/main_{case}_*` 自動分使用者。
- `pipeline_stages.py / stage2_1_static_ahp_preference_extraction`：若 `ACTIVE_USER_PROFILE` 有設 → 直接把該 profile 的 9 維權重寫進 `json/stage2_ahp_global_weights.json` 的 `Global_Weights`（繞過 AHP 成對比較）；否則跑原 AHP 模擬。下游 stage2_2 / stage3 / prompt 回測都讀同一個 JSON，故**系統輸入權重隨選定 user 一起變動**（使用者特別叮囑的點）。
- 之所以可直接套：`USER_PROFILES` 的 key 與 `TwoLevel_AHP_Model.calculate_global_weights` 產出的 `global_weights` key 完全相同（9 維正規化、Σ=1），格式相容。

### 驗證
- `import parameters`：None→CASE_NAME=Neutral_user；`ACTIVE_USER_PROFILE=conservative`→CASE_NAME=conservative；非法值→ValueError ✓。
- 多 user 端到端跑（cached stage0）：權重/雷達/輸出夾名隨 profile 改變。
- 用途：接續的「7 使用者最終呈現」只要對 7 個 profile 各跑一次（設 env 或旋鈕），`user_results/` 即得 7 份各自獨立、權重正確的結果。

## 2026-06-06：七使用者展示固定化 + 主系統輸出改 new_user_{n}（永不覆寫）

狀態：完成。非 optimizer 改動（輸出命名/整理）。

### 改了什麼
- **七使用者展示固定夾**：`user_results/showcase_7_profiles/`（7 個 `main_<profile>_*`，各含主系統 + 巢狀季度回測四分類）+ `對照分析報告.md`（七份關鍵數字對照表 + 分析）。當成固定展示，主系統不再生成到此。
- **主系統每次執行改名 `new_user_{n}`**（`functions.py` 收集器）：`n = 現有 user_results/new_user_* 的最大編號 + 1`（用 `re.fullmatch(r"new_user_(\d+)")` 掃描，max+1，**永不覆寫**前一位使用者；刪掉中間編號也安全）。固定展示夾名稱不符 `new_user_\d+` → 不被計入或覆寫。取代原本的 `main_{case}_{timestamp}`。`stage3b` 巢狀回測仍透過 `LAST_MAIN_USER_DIR` 進到 `new_user_{n}/backtest_*/`。
- `pipeline_stages._stage3_output_hint` 文案同步改 `new_user_<n>`。

### 七使用者 OOS 季度回測對照（2019-06~2026，VT：CAGR 14.32% / Sharpe 0.606）
| profile | core | CAGR% | Sharpe | 贏VT報酬 | win_VT |
|---|--|--:|--:|:--:|--:|
| aggressive_growth | beta | 17.58 | 0.675 | ✅ | 75.0 |
| return_leaning | beta | 16.40 | 0.668 | ✅ | 25.0 |
| cost_liquidity | market | 14.12 | 0.630 | ✗ | 92.9 |
| diversified_quality | market | 12.67 | 0.564 | ✗ | 57.1 |
| balanced | market | 12.71 | 0.563 | ✗ | 67.9 |
| income | minvar | 11.94 | 0.545 | ✗ | 100 |
| conservative | minvar | 9.70 | 0.447 | ✗ | 75.0 |
- 結論與設計論述一致：**只有 beta 核心贏 VT 絕對報酬**（承擔更高波動）;market/minvar 贏在風險效率與偏好滿足;全員對 EW/MaxSharpe 偏好勝率 93–100%。誠實張力：return_leaning win_VT 低（偏好自我矛盾）、部分防禦型 MaxDD 比 VT 深（壓波動≠控回撤）。
- 過程備忘：balanced 首跑撞 OneDrive 暫時鎖檔（Permission denied on 價格快取）→ 基準對齊失敗 → market 退回 minvar;重跑後正常。**OneDrive 同步是隨機鎖檔風險，大量連跑前宜暫停同步或移出 OneDrive 夾。**

## 2026-06-06：回測圖標題加 {user}_ 前綴（用既有資料重繪）+ 縮短回測夾名（修 Windows 260 路徑上限）

狀態：完成。非 optimizer 改動（純繪圖/命名）。

- **回測繪圖函式全部加 `title_prefix: str = ""` 參數**（預設空字串→生產行為不變）：`_plot_backtest_outputs / _plot_backtest_performance_report / _plot_annual_returns / _plot_weight_evolution / _plot_dea_distribution_backtest / _plot_preference_predictive_scatter(V-1) / _plot_preference_score_timeseries(V-6)`，前綴接在各圖主標題前。`_plot_distribution_grid` 本就吃 title 參數（直接傳完整標題）。
- **七使用者回測圖以「已跑出的 CSV」重繪**（不重跑回測），標題改成 `{profile}_{原標題}`（如 `aggressive_growth_Rolling Robo-Advisor Backtest NAV`）。臨時 driver 讀 `04_data_csv/*.csv` → 呼叫上述函式重畫到各自 `02_eda_dea_figures/`、`03_performance_figures/`，跑完刪除。已目視確認標題正確。
- **縮短回測彙整夾名稱**：`_mirror_run_figures_to_upgrade` 的 `backtest_{run_id}_arm{arm}_{stamp}`（run_id 很長→`backtest_backtest_q_lookback-3y_minhist-8y_dca-0_armC2_...`）改成 `{prefix}_arm{arm}_{stamp}`（=`backtest_q_armC2_...`）。原因：巢狀進 `showcase_7_profiles/main_*/` 後完整路徑超過 Windows 260 字元上限導致 savefig FileNotFound。既有 7 夾一併改名為 `backtest_q_armC2`。

## 2026-06-06：接上 preference_engine（投資理念 + 逐輪問答 → 9 維偏好權重）

狀態：完成（程式接好 + import/格式驗證）。非 optimizer 改動（新的偏好來源）。

### 接點（極窄、無需維度映射）
- 使用者把自製引擎放進 `preference_engine/`（`phase3_system/` 引擎 + `assets/` 模型 12MB + `integrate_example.py`）。其 `extract_preferences(philosophy, answer_fn)` 回傳的 `Ew` 是 **9 維、總和=1、鍵與本系統完全相同**（`DIM_LABELS` = Return_CAGR…FinBERT_score）→ 直接當 `Global_Weights`。
- 編碼器 BGE-M3（~2.2GB）首次 `Phase3Engine()` 自動下載（或放 `encoder_model/` 離線）；**載入在 instantiation，import 安全**。

### 改了什麼
- `pipeline_stages.py`：`PreferenceMode` 加 `"preference_engine"`；新增 `stage2_1_preference_engine_elicitation()`（把 `preference_engine/` 加進 sys.path → 呼叫 `extract_preferences` → 終端逐題互動取答，或傳入 `philosophy_text`/`answers` 非互動 → 9 維權重正規化後寫 `json/stage2_ahp_global_weights.json`，格式同 AHP 路徑：`{CR, Global_Weights, Source, Sigma_alpha, ci_note}`）；router 加分支。相依缺失/載入失敗 → 退回既有 fallback 權重、管線不中斷。
- `requirements.txt`：加 `sentence-transformers>=2.2.0`（BGE-M3；torch/scipy/numpy 已有）。
- `.gitignore`：排除 `preference_engine/encoder_model/`（2.2GB）與 `__pycache__`；`assets/`(12MB) 追蹤。
- `main.py`：preference_mode 註解加 `preference_engine`。
- 驗證：`import phase3_system` / `integrate_example.extract_preferences` OK；router 路由正確；24 檔將被追蹤（不含 encoder/pycache）。**未實跑完整誘出（需 2.2GB BGE-M3 下載）**——引擎本身使用者已在他處測過，adapter 僅照 README 介面呼叫。
- 用法：`preference_mode="preference_engine"` 跑 `main.py` → 終端輸入投資理念 + 逐題回答 → 9 維權重進入既有 stage2_2/stage3/回測。與 `ACTIVE_USER_PROFILE`（靜態原型）獨立。

### ★修正：不要早停（使用者指出）★
- **問題**：初版 adapter 用引擎附的 `extract_preferences`，它**一遇 `should_stop` 就 break**。實測引擎在第 **3 題**（Σα≥τ、約掌握 top-1/2）就提議停 → 只覆蓋 3 維、其餘 6 維留在**先驗** → 結果被開場理念/prior 主導（出現 Return_CAGR 0.87 之類的偏頗）。引擎 `snapshot()` 自身的 `ci_note` 也警告「早停 CI 不可信（未問維仍為先驗；需完整 9 題）」。
- **修法**：adapter 改成**直接驅動 `Phase3Engine`**，預設**答完整 9 題**（loop 到 `next_question()` 回 None，含 T3 重問），不再自動早停；互動模式下引擎首次提議早停時**詢問一次**（直接 Enter = 繼續答完）。payload 增記 `n_covered` / `ci_trustworthy`。
- **驗證**：答完整 9 題 → `n_covered=9`、`ci_trustworthy=True`、`ci_note=完整9題CI可信`；by-dim 作答得到合理分布（Return_CAGR 0.35 / Div_Score 0.28 / Cost 0.18，貼合「成長+分散+低費用」理念），不再被 prior 壓成單一維獨大。

## 2026-06-06：回測新增「績效對照長條圖」(各策略 vs VT，取代看 CSV)

狀態：完成。非 optimizer 改動（新增一張圖）。

- 新增 `backtest_engine._plot_backtest_metrics_comparison(summary_df, output_path, title_prefix)`：把回測 Performance Summary 的關鍵數據畫成 5 個子圖（累積總報酬 % / 年化報酬率 % / 年化波動率 % / 夏普 / 最大回撤 %），每圖各策略長條，**偏好組合(紅)、VT(藍)highlight、其餘對照組(灰)**，長條上標數值。
- 接進 `_write_unified_backtest_report`（檔名 `{prefix}_metrics_comparison.png`）→ **未來每次回測自動產生**，並落在 `03_performance_figures/`（分類 by 檔名）。output inventory 同步加列。
- 已用既有 summary CSV 為 showcase 七位使用者各補生成一張（標題 `{profile}_回測績效對照…`），目視確認正確。

## 2026-06-06：接上「網頁版」偏好誘出 `etf_preference_bundle`（取代 `preference_engine`）

狀態：完成（程式接好 + 兩段橋接實測通過）。非 optimizer 改動（新的偏好來源/交付方式）。

### 背景
- 使用者上傳 `etf_preference_bundle/`（= 舊 `preference_engine` 的超集：同一套 `phase3_system/` 引擎 + `assets/`，外加 **Flask 網頁層** `web/`、`run_web.py`、`recommender_hook.py` 交付接點）。接好後使用者會**刪除舊的 `preference_engine/`**。
- 網頁與主系統是**兩個行程**，故採**檔案交付**橋接（非 in-process）。

### 兩段橋接（web → 主系統）
1. **`etf_preference_bundle/recommender_hook.deliver_weights(weights, snapshot)`**（已改寫）：問答完成時（網頁 `web/app.py._finish` 或函式庫 `integrate_example.run` 都會呼叫此唯一接點），把 9 維權重**正規化（補齊9維、總和=1）後直寫主系統 `json/stage2_ahp_global_weights.json`**（canonical `{CR, Global_Weights, Source, Sigma_alpha, n_covered, ci_trustworthy, ci_note}`，格式同 AHP 路徑）。路徑用 `Path(__file__).parent.parent/"json"/...`（bundle 在專案根底下）。
2. **`pipeline_stages.stage2_1_web_preference_ingest()`**（新增）：`main.py` 端讀取網頁最近一次結果。來源優先序 `etf_preference_bundle/web/last_result.json`（含完整快照）⇒ 既有 `json/stage2_ahp_global_weights.json`（hook 直寫檔）。正規化 9 維後寫 canonical payload。**找不到 → fallback 等權重 + 提示先跑網頁**，管線不中斷。

### 改了什麼
- `etf_preference_bundle/recommender_hook.py`：實作上述直寫主系統 json（原本只 `return weights`）。
- `pipeline_stages.py`：`PreferenceMode` 加 `"web_preference"`；新增 `stage2_1_web_preference_ingest()`；router 加分支；`stage2_1_preference_engine_elicitation()` 的 `_eng_dir` **由 `preference_engine` 改指 `etf_preference_bundle`**（終端模式刪舊資料夾後仍可用，引擎/assets 解析自 bundle）；Source 字串改 `etf_preference_bundle …`。
- `main.py`：`preference_mode` 改 `"web_preference"`（兩步流程：先 `python etf_preference_bundle/run_web.py` 瀏覽器完成問答 → 再 `python main.py` 讀取），註解列出 4 種模式。
- `.gitignore`：忽略 `etf_preference_bundle/encoder_model/`（BGE-M3 ~2.2GB）、`etf_preference_bundle/**/__pycache__/`、`etf_preference_bundle/web/last_result.json`（暫存結果）；舊 `preference_engine/` 規則保留以防殘留。
- `requirements.txt`：加 `flask>=3.0`（網頁後端；torch/sentence-transformers/scipy/numpy 已有）。

### 驗證
- 段①：`deliver_weights(未正規化9維, snap)` → 主 json 正確產生，`Global_Weights` 9 維 sum=1、Source/快照欄位齊全。✓
- 段②：放一份模擬 `web/last_result.json` → `stage2_1_web_preference_ingest()` 讀到、正規化 sum=1、`n_covered=9`/`ci_trustworthy=True` 帶入、Source 標來源檔。✓
- 終端模式 import 路徑改 bundle 後仍可載入 `phase3_system`（引擎/assets 在 bundle 內解析正常）。
- 註：`from functions import log` 在 cp950 終端會印出既有 emoji 編碼警告（與本次無關，功能不受影響）。

### 用法
- **網頁版**：`python etf_preference_bundle/run_web.py` → http://127.0.0.1:8000 完成問答（自動交付）→ `python main.py`（`web_preference`）續跑 stage2_2/3/回測。
- **終端版**：`preference_mode="preference_engine"` 跑 `main.py`（在終端逐題作答，沿用 bundle 引擎）。
- 與 `ACTIVE_USER_PROFILE`（靜態原型）獨立。**待使用者刪除舊 `preference_engine/`。**

## 2026-06-06：main.py 單一開關（一鍵終端問答）+ 新增 ETF 網頁版接口 `etf_web/`

狀態：完成（接口骨架 + import/路由/plumbing 實測通過；內容版面待後續細定）。非 optimizer 改動。

### main.py 開關（不依賴已移除的 preference_engine）
- 頂部單一 `RUN_MODE`：`"terminal"`（一鍵終端問答→`preference_engine` 模式，引擎在 bundle）/ `"web"`（啟動 `etf_web`）/ `"profile"`（靜態原型/AHP，不問答）。`main()` 依此分派；web 模式呼叫 `etf_web.run_web.main()` 後 return。

### 回測重構（為了非互動共用，不動 backtest_engine 最佳化邏輯）
- `pipeline_stages.py` 抽出 `run_preference_backtest_core(rebalance_freq, preference_file, emit=print)`：原 `stage3b` 的回測核心（7+3≤10 年動態起點、退階、巢狀 user dir）。`stage3b_optional_preference_backtest` 改為「prompt 詢問 y/N + 頻率 → 呼叫 core」。`emit` 可換成把訊息送進網頁進度緩衝。

### 新增 `etf_web/`（ETF 網頁版，模仿語意萃取網頁）
- `app.py`（Flask 後端，port 8050）：
  - **① 偏好問答**：重用 `etf_preference_bundle` 的 `Phase3Engine`（與語意萃取網頁同一套，含 T1/T2 早停/重問提議流程）；完成時 `recommender_hook.deliver_weights()` 把 9 維權重寫進 `json/stage2_ahp_global_weights.json`。端點 `/api/pref/{start,answer,choose,weights}`。
  - **② 執行分析**：`POST /api/run` 開背景執行緒跑 `run_full_pipeline(preference_mode="web_preference", backtest_prompt=False)` + `run_preference_backtest_core`；`_Tee` 把 stdout/stderr 同時導進記憶體緩衝（write 包 try/except，比終端更耐 cp950 emoji）。`GET /api/status` 輪詢進度/狀態。
  - **③ 結果呈現**：`GET /api/results` 走訪 `functions.LAST_MAIN_USER_DIR`，列出 png（依子夾分組）與 txt/md 報表內文；`GET /results-file/<relpath>` 提供 user_results 底下檔（有路徑穿越防護）。
- `run_web.py`（啟動器，自動開瀏覽器）、`templates/index.html`（三步驟版面：問答／執行／結果）、`static/{app.js,style.css}`（前端，深色主題，沿用信念面板樣式）、`__init__.py`。
- **與語意萃取網頁的差異**：bundle 的 `web/` 只做偏好誘出→交付；`etf_web/` 把「偏好→跑 pipeline→看結果」整條包進同一個瀏覽器流程（main 選 web 即全程網頁）。

### 驗證
- import：`pipeline_stages`（含 `run_preference_backtest_core`/`stage2_1_web_preference_ingest`、`PreferenceMode` 含 `web_preference`）、`etf_web.app`（10 條路由全註冊）皆 OK。flask 3.1.3 已裝。
- test client：`GET /`→200、`/api/status`→idle、`/api/results`→空、static 200、路徑穿越→404。
- py_compile：main/run_web/app/pipeline_stages 全過。
- **尚未做完整 live run**（偏好問答需載 BGE-M3 ~2.2GB；跑 pipeline 需數分鐘）——plumbing 已驗，內容/版面待使用者細定。

### 用法
- 終端一鍵：`RUN_MODE="terminal"` → `python main.py`（終端問答→pipeline→問是否回測）。
- 網頁：`RUN_MODE="web"` → `python main.py`（或 `python etf_web/run_web.py`）→ http://127.0.0.1:8050 全程在瀏覽器。

## 2026-06-06：ETF 網頁版 UX 修正 + 修「VT 偏好分數退化滿分」評分瑕疵

狀態：完成（前端 4 項 + V-6 評分修正）。**最佳化器邏輯未動**（見下「一致性」）。

### A. etf_web 前端 UX（純前端）
1. **主視覺放大 + 整頁不出現視窗滾輪**：`style.css` 改為全視窗 flex（`html,body{height:100%}`、`body{overflow:hidden;display:flex;column}`），header/stepbar 固定高、`main` 吃滿剩餘高度，可見 `.stage` 撐滿（~85%），捲動只發生在內部面板（conv / run-log / results view，皆 `min-height:0;overflow:auto`）。`.stage[hidden]{display:none}` 確保隱藏。
2. **跑程式視窗自動 tail**：`pollStatus` 每次更新 `run-log.scrollTop=scrollHeight`（自動跳到最後一行）；run-log 在新版面為 flex 子項 `flex:1;min-height:0`，自身內捲。
3. **上方步驟列可點回看**（重點）：`app.js` 加 `reached={pref,run,results}` 進度旗標 + stepbar onclick → `showStage`；偏好問答永遠可回看（含**已跑完的 9 維權重**仍顯示在信念面板）；執行/結果到達過即可回看。`showStage` 改用 `reached` 標記 done。

### B. ★修正：單一標的基準（VT）在抗跌維度被退化評分給滿分 1.0★
- **使用者回報**：網頁版跑出「System 偏好分數贏 VT 僅 21%」，測試時幾乎沒出現過。
- **查核（逐維平均，System vs VT）**：System 在 9 維有 **7 維贏或平**（股息 +0.172、成交量 +0.189、波動 +0.069、分散 +0.039、費用 +0.021、報酬β +0.002…），**只輸「抗跌 Risk_MaxDD」一項：System 0.506 vs VT 1.000（−0.494）**，而抗跌正是此網頁使用者的**最高權重 0.257** → 一項翻盤總分（System 0.692 vs VT 0.789）。
- **根因**：`calculate_portfolio_utility` 算 true-MaxDD 分數時，用「**本投組自身持有標的**」建分數尺度（`calculate_individual_maxdd_bounds(returns)`）。單一標的基準（VT/VOO）只有一個值 → 上界=下界退化 → `calculate_true_maxdd_score` 回 **1.0**，不論 VT 實際回撤多深（VT 2020 實際 ~−34%）。多檔的 System 則得到正常相對分 ~0.5。對抗跌權重高的使用者，VT 幾乎必勝。
- **修法（評分尺度，外科）**：`calculate_portfolio_utility` 新增可選參數 `maxdd_bounds`；V-6 評分呼叫端改傳「**同一個跨截面共同尺度**」——forward/benchmark/equal/maxsharpe 用評估截面（含 VT）全體個股 MaxDD 分布建尺（`eval_maxdd_bounds`）、ex-ante 用候選池 lookback 截面建尺、`build_period_dimension_row` 同步。各投組『自身』實際回撤計算不變，只把**比較尺度**統一，VT 不再免費滿分。
- **驗證（合成資料單元測試）**：VT-like 單檔深回撤 → 舊：單檔尺度 (0.4772,0.4772) 退化 → MaxDD 分 **1.0**；新：共同尺度 (0.216,0.456) → VT 分 **0.0**（最深者）。退化消除、各策略同尺比較。實務上 VT 非最深 → 會得中等分；**預期 win-rate 大幅回升**（總差 0.097 幾乎全來自抗跌 0.257×0.494≈0.127；修後 System 應在多數期間領先）。實際新數字待重跑回測（web 重跑即更新）。

### 一致性（重要）
- **未動最佳化器**：`optimize_preference_portfolio`（line ~1175）仍以候選池 `calculate_individual_maxdd_bounds(returns)` 運作，與主系統一致；`calculate_true_maxdd_score` / `calculate_individual_maxdd_bounds` 函式本體未改（只在 `calculate_portfolio_utility` 加可選參數 + 改評分呼叫端）。投組權重、NAV、夏普、最大回撤績效圖**完全不變**；只有 V-6 偏好分數比較（診斷層）變公平。

## 2026-06-06：MaxDD 評分修正後 — 重跑 7 使用者、更新 §3.6 + showcase（win_VT 修正）

狀態：完成。延續上一則「修 VT 抗跌退化滿分」評分修正，重生受污染的偏好分數輸出。

### 查核結論（回應使用者三問）
1. **最佳化器未受污染**（已逐行確認）：生產 C2 臂（functions.py 與 backtest_engine.py）偏好傾斜用 `User_Pref_Score`＝各維 `Norm_*`（含 `Norm_Risk_MaxDD = robust_scale(候選池全體)`，跨截面多檔），**不用**會退化的單檔 MaxDD 上下界。`calculate_individual_maxdd_bounds` 在最佳化器內傳入的恆是多檔選股池（≥5 檔），且 C2/B/BL 目標函式根本未引用該 bounds。退化僅發生在 `calculate_portfolio_utility` 對**單一標的基準**評分（診斷層）。→ 權重/NAV/Sharpe/回撤全部不受影響。
2. **受污染需重生**：V-6（win_VT 時序）、V-1（ex-ante vs forward）、`*_preference_scores.csv`、REPORT_A 的 win_VT 數字、showcase §4/§5 勝率。**乾淨**：NAV/績效/回撤圖、`_metrics_comparison`（原始維度）、雷達（β 基礎）、權重、前緣、REPORT_A 的 CAGR/Sharpe 勝率。
3. 範圍（使用者選）：**只修 7 使用者 + §3.6 + showcase**；§3.2/3.3/3.4 的 A/B 方法學實驗暫不重跑、不加註。

### 做法
- 一次性腳本重跑 7 個 `USER_PROFILES` 的季度回測（start 2019-06-01、lookback 3、freq Q、arm C2、fetch=max），用修正後評分；以 `run_rolling_backtest` 回傳的 `preference_scores` 重算 win_VT/win_Eq/win_MS，並以 `title_prefix={profile}_` 重畫 V-6/V-1 覆寫回 `showcase_7_profiles/main_<profile>_*/backtest_q_armC2/`，同步覆寫 `preference_scores.csv`。腳本與暫存檔（`_regen_*`、`json/_regen_pref_*`）跑完即刪。
- **Sharpe 與原表一致（0.44–0.68）→ 證明投組完全相同，只有偏好分數變公平。**

### win_VT 修正（舊 → 新；28 期）
| profile | 舊 | 新 |
|---|--:|--:|
| aggressive_growth | 75.0 | **100** |
| return_leaning | 25.0 | **89.3** |
| cost_liquidity | 92.9 | **100** |
| balanced | 67.9 | **100** |
| diversified_quality | 57.1 | **100** |
| income | 100 | **100** |
| conservative | 75.0 | **96.4** |

- 對 EqualWeight 93–100%、對 MaxSharpe 89–100%。整體：移除 VT 在抗跌的免費滿分後，**全員偏好分數穩定贏 VT（89–100%）**，結論不變但更乾淨、更有利系統。
- 已更新：`REPORT_A §3.6`（表 win_VT 欄 + 敘述 + 評分修正註）、`showcase/對照分析報告.md`（§4 勝率表、§5 win_VT% 欄、§6/§7 敘述「全員 89–100%」、return_leaning 改「最低但仍 89%」+ 修正註）。

### 全結論對齊（使用者要求「修正所有的結論」）
- 因使用者選擇不重跑 §3.2/3.3/3.4 的 A/B 方法學實驗，改以**誠實註記 + 結論對齊**處理全報告：
  - `REPORT_A`：§0 一句話成果與 §6 結論補上「7 原型 win_VT 89–100%、對等權/最大夏普全面領先」；§3.2/3.3/3.4 前加總註——那些 win_VT 為**修正前舊尺度、未重跑**，但**方向性結論不變**且另有未受污染證據（V-1 過去 CAGR r≈0；BL/品質差異源自投組權重行為），生產級數字以 §3.6 為準。
  - `REPORT_B`：第七幕後加同義註（13.6%→67.8%、統一 BL「win_VT 崩」為修正前尺度；方向性結論不變）。
- 仍未重跑 §3.2/3.3/3.4 的實際 A/B 數字（使用者明確不要）；其餘所有對外結論已與修正後尺度一致。

## 2026-06-06：ETF 網頁視覺化（明亮動態背景 / 對話 UX）+ 新增回測偏好雷達 vs VT

狀態：完成（前端 3 項 + 回測新增一張雷達圖）。非 optimizer 改動。

- **明亮 + 動態背景**：`etf_web/static/style.css` 全面改亮色主題（白卡片 + 柔和陰影），背景為**緩慢動態漸層**（只動 `background-position`、GPU 友善；`@media (prefers-reduced-motion)` 自動關閉，避免影響順暢）。
- **對話自動捲到底**：`app.js` 新增 `scrollConv()`（雙 rAF，待輸入框/回饋訊息長高後再捲），於 `renderAction` 末尾呼叫 → 每次答完都看得到最新題目。
- **換行置左**：對話泡泡 `text-align:left` + `white-space:pre-wrap`，泡泡本身可靠右（使用者訊息）但**內文一律置左**，多行不再右對齊。
- **★新增 `_plot_backtest_preference_radar`★**（backtest_engine，診斷層、不碰最佳化）：9 維事後偏好子分數的回測期間平均，**系統(紅) vs VT(藍)** 雷達；用修正後共同 MaxDD 尺度，故各維公平。已接進 `_write_unified_backtest_report`（檔名 `{prefix}_preference_radar_vs_benchmark.png`，落 03_performance_figures）→ 未來每次回測自動產生；並用既有 7 showcase 的 preference_scores.csv 補生成 7 張。
- 註：`結果頁版面（results presentation）`待與使用者討論後再改；本次只加圖、未動結果頁佈局。

## 2026-06-06：ETF 網頁結果頁改為「敘事式儀表板」（使用者選定方向）

狀態：完成（後端結構化資料 + 前端儀表板）。非 optimizer 改動。

- **後端 `etf_web/app.py`**：`/api/results` 新增 `dashboard` 結構化資料 —— 由本次 `user_dir` 解析：
  - `metrics`：系統(Preference_Driven) vs VT 的 CAGR/波動/Sharpe/MaxDD（讀 `backtest_q_summary.csv`）+ `win_vt`（讀 `backtest_q_preference_scores.csv` 算 Portfolio>Benchmark 期數%）。
  - `weights`：9 維偏好權重（讀本次全域 `json/stage2_ahp_global_weights.json`）。
  - `holdings`：推薦投組持股（讀 `02_portfolio/{case}_weights.csv` 的「偏好組合 Weight (%)」）。
  - `figures_map`：依檔名挑出關鍵圖（nav / metrics_comparison / preference_radar_vs_benchmark / V-6 / 主系統雷達 / 前緣 / 回撤）；明細區 `figures[]` 自動排除已上版的關鍵圖避免重複。
  - 修：`app.py` 原本未 `import json`（`json_loads_safe` 會 NameError 被吞→權重全 0）→ 已補 `import json` / `import csv`。
- **前端**：結果頁改為由上而下 —— ① 摘要大數字卡（win_VT hero + CAGR/波動/Sharpe/MaxDD，系統值大、VT 小字、優於 VT 綠/劣紅）② 你的偏好（9 維長條 + 主系統雷達）③ 推薦投組（持股權重長條）④ 回測 vs VT（NAV + 對照長條 + 偏好雷達 + V-6）⑤ 完整圖表/報表（收合 `<details>`）。移除舊 tab。
- 驗證：test client 對 showcase income 夾 → metrics（CAGR 11.94 vs VT 14.32、win_VT 100）、weights sum=1、holdings（JEPI 40/SCHY 37.5/SCHD 22.5）、8 張關鍵圖全中、明細 13 圖 3 報表；GET / 200、JS/CSS 括號平衡。

## 2026-06-06：接上使用者更新後的 etf_preference_bundle（warmup / lock / trace）

狀態：完成。使用者更新了 bundle（engine.py 內部 `semC_gated` 證據更新 + `self.history` trace；web/app.py 背景預熱 + engine lock + last_result 帶 trace；integrate_example 回傳 trace）。**公開引擎 API 不變**（start_session/next_question/submit_answer/snapshot），故 `etf_web` 仍相容。
- 已把三項改動接進 `etf_web/app.py`：① `_ENGINE_LOCK` 雙重檢查鎖 ② 模組載入即啟動 `_warmup()` daemon 執行緒（伺服器一開就預載 BGE-M3，首問不空等）③ `_finish` 擷取 `engine.history` 存 `_S["last_trace"]`，`/api/pref/weights` 回傳 `trace`（供學術留存/前端日後呈現）。
- 驗證：app.py 編譯 OK；引擎含 `self.history`。

## 2026-06-06：回測雷達改「實現特徵雷達」（修抗跌口徑矛盾，使用者確認）

狀態：完成。**問題**：原雷達抗跌軸用「每期 forward 子分數平均」（income System 0.911 > VT 0.787，96% 期勝），但摘要/績效圖的抗跌是「**全期最大回撤**」（income System −38.45% 比 VT −33.72% 深）→ 雷達說系統贏、頭條說系統輸，口徑矛盾。
- **修法（使用者選「實現特徵雷達」）**：`_plot_backtest_preference_radar` 改吃 `dimension_comparison_df`，9 軸全用投組**實際實現特徵**：CAGR_%、Avg_Raw_Dividend_Yield_%、Annualized_Volatility_%(反向)、**Max_Drawdown_%(全期)**、Avg_Raw_Expense_Ratio_%(反向)、Avg_Raw_Liquidity_Volume_M、Avg_Raw_Liquidity_AUM_B、Avg_Raw_Sector_HHI(反向)、Avg_Raw_FinBERT_Score；跨所有策略 min-max 正規化（下限 0.04），畫 System(紅) vs VT(藍)。標題改「實現特徵雷達…抗跌＝全期最大回撤」。
- 結果：income 雷達抗跌 VT 在外（系統較深、輸）→ 與頭條/§5 一致；殖利率/低波動/分散 系統明顯在外（income 強項）。各 profile 重生 7 張。
- 接點不變：仍輸出 `{prefix}_preference_radar_vs_benchmark.png`，dashboard `figures_map` 照抓；前端 caption 改「實現特徵雷達…」。win_VT（偏好分數）仍由 V-6 與摘要卡呈現，與本雷達各司其職。

## 6. 改動紀錄模板

## 7. 下一個聊天室交接注意事項

### 7.1 絕對重要原則

後續所有演算法升級都必須同時檢查並修改兩套邏輯：

1. 主程式：`functions.py`
2. 回測引擎：`backtest_engine.py`

原因：

1. 主程式 Stage 3 與回測引擎不是共用同一個最佳化函式。
2. 回測引擎有自己獨立的 `optimize_preference_portfolio()` 與 `calculate_portfolio_utility()`。
3. 如果只改 `functions.py`，主程式結果會改變，但 rolling backtest 仍然用舊演算法。
4. 如果只改 `backtest_engine.py`，回測結果會改變，但主程式推薦投組仍然是舊演算法。
5. 因此任何效用函數、風險分數、候選池、DEA 後處理、權重限制、相關性分群等改動，都必須同步檢查主程式與回測。

### 7.2 目前已完成的演算法級改動

已完成：

1. 主程式與回測引擎的 `Risk_MaxDD` 效用分數改為 true portfolio MaxDD score。
2. true MaxDD 使用投組 buy-and-hold NAV 路徑計算，而不是單檔 ETF MaxDD 分數線性加權。
3. 舊版 MaxDD proxy 保留為 fallback。
4. 開關位置在 `functions.py`：

```python
USE_TRUE_MDD_OPTIMIZATION = True
TRUE_MDD_TIME_WARNING_SECONDS = 30.0
```

5. 若 true MaxDD 最佳化在測試中多次超過 30 秒，可以暫時將 `USE_TRUE_MDD_OPTIMIZATION` 改成 `False`，切回舊 proxy。

### 7.3 目前系統仍然存在的演算法問題

1. 報酬導向使用者的結果仍未明顯拉開大盤或 Max Sharpe。
2. DEA 第一階段可能過早排除高報酬但高風險 ETF。
3. 目前風險仍主要是效用加分項，而不是使用者風險預算。
4. 40% 單檔權重上限可能限制報酬導向使用者。
5. 相關性分群可能過早刪除高成長 ETF 的替代品。
6. 成本、流動性、分散、情緒等輔助維度可能稀釋報酬導向主目標。
7. 回測 final-period frontier 中仍有歷史遺留的蒙地卡羅函式，可之後清理，但不屬於演算法核心。

### 7.4 建議下一步開發方向

優先順序建議如下：

1. **Preference-aware rescue list**
   - 在 DEA 後保留通過 DEA 的 ETF。
   - 額外救回使用者最重視維度的前 N 名 ETF。
   - 對目前報酬導向使用者，應救回 `Return_CAGR` 前 N 名或 return composite 前 N 名。
   - 目的：避免 DEA 作為客觀門檻時過早殺掉高報酬 ETF。

2. **風險預算取代低風險加分**
   - 對報酬導向使用者，不應只獎勵低波動。
   - 可改為：

```text
maximize return / preference utility
subject to volatility <= user risk budget
subject to max drawdown score or max drawdown <= user drawdown budget
```

3. **權重上限依使用者風格調整**
   - 保守型可維持 30%-40%。
   - 報酬導向可測試 50%-60%。
   - 但需同時控制持股數與風險上限。

4. **延後 correlation clustering**
   - 不要太早在 Stage 2_2 刪除高度相關 ETF。
   - 可改為讓 optimizer 看到完整候選池，再用相關性懲罰或持股數限制處理。

5. **主目標與輔助品質拆分**
   - 報酬導向使用者的主要目標應是資本利得或總報酬。
   - 成本、流動性、分散、情緒應作為品質篩選或懲罰，而不是和報酬完全平等加總。

### 7.5 開發流程建議

每次改動前：

1. 先寫清楚數學設計。
2. 再確認要改 `functions.py` 哪一段。
3. 同步確認 `backtest_engine.py` 是否有對應邏輯。
4. 更新本文件。
5. 跑 `py_compile`。
6. 至少跑一次 Stage 3。
7. 若改到回測邏輯，至少跑一次小型或完整 rolling backtest。
8. 比較改動前後：
   - 權重
   - CAGR
   - volatility
   - MaxDD
   - Sharpe
   - preference score
   - benchmark 比較

### YYYY-MM-DD：改動名稱

### YYYY-MM-DD：改動名稱

狀態：待填  
是否已批准：待填  

#### 目標

待填。

#### 改動前問題

待填。

#### 核准設計

待填。

#### 修改檔案

待填。

#### 驗證方式

待填。

#### 結果

待填。

#### 對主程式與回測一致性的影響

待填。
