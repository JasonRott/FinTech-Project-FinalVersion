# 舊演算法系統報告：智能 ETF 投資組合主系統

建立日期：2026-05-25  
狀態：演算法升級前基準版  
範圍：只記錄智能 ETF 投資組合主系統與回測系統。`active_preference` 屬於偏好取得的另一條實驗功能，不列為本文件的主系統演算法核心。

---

## ⚠️ 勘誤（2026-06-04，讀完程式碼後補充）

本文件部分描述在閱讀真正的 `functions.py` 之前撰寫，有兩處需更正，詳見 `04_literature_review_and_code_audit.md`：

1. **風險不是天真加權。** 第 3.5 與第 8 節給人「低風險只是效用加分」的印象。實際上 `functions.py:2529` 用真實共變異數投組波動率 `√(wᵀΣw)`，MaxDD 用真實 buy-and-hold NAV 路徑（`calculate_true_maxdd_score`），HHI 用真實 `1−Σexposure²`。**風險量測本身是正確的。**
2. **真正的根因在報酬側。** `functions.py:2501` 的報酬項是個別 ETF CAGR 的 `[0,1]` 排名分數線性加權（`np.dot(w, vec_cagr)`），不是真實報酬。風險側給最佳化器真實的凸性好處、報酬側只給排名分數，這個**不對稱**才是報酬導向使用者拉不高 CAGR 的主因。

升級重心因此調整為：修報酬側（用真實報酬）+ 把風險改成約束。詳見 `03_planned_upgrade_items.md` 的 U-1 / U-2。

## 1. 系統目標

本系統目標是根據使用者偏好，從大型 ETF universe 中篩選出候選 ETF，並產生符合偏好的投資組合。核心流程是：

1. 收集 ETF 財務、價格、流動性、成本、產業分散與情緒資料。
2. 使用 DEA 作為第一階段客觀效率篩選。
3. 使用 AHP 權重描述使用者偏好。
4. 在候選 ETF 中進行偏好分數排序、相關性去重與投資組合最佳化。
5. 產出權重、績效健檢、雷達圖、數學 MPT 效率前緣圖。
6. 使用回測引擎檢驗「每期依系統推薦買入並持有到下一次再平衡」的結果。

## 2. 主程式 Pipeline 現況

目前 `main.py` 啟動 `PipelineConfig`，所有主系統 stage 都開啟：

| Stage | 是否執行 | 內容 |
|---|---:|---|
| Stage 0 fetch | True | 抓取 ETF 清單、財務特徵、價格資料、產業資料、情緒資料 |
| Stage 0 feature processing | True | EDA、標準化、DEA ready matrix |
| Stage 1 DEA | True | Normalized DEA、super-efficiency、cross-efficiency |
| Stage 2_1 preference | True | static AHP 權重產生 |
| Stage 2_2 cluster selection | True | 高相關 ETF 分群去重 |
| Stage 3 optimization | True | 偏好投組最佳化、Max Sharpe 對照、圖表與報表 |

目前偏好模式：

```text
preference_mode = static_ahp
preference_output_path = json/stage2_ahp_global_weights.json
```

## 3. 舊演算法核心結構

### 3.1 Stage 0：資料與特徵

主要輸入與輸出：

| 類別 | 檔案 |
|---|---|
| ETF universe | `csv/all_etfs.csv` |
| YahooQuery 特徵 | `csv/stage0_yq_features.csv` |
| Alpha Vantage / 產業資料 | `json/etf_database.json` |
| Stage 0 最終特徵矩陣 | `csv/stage0_final_matrix.csv` |
| DEA ready matrix | `csv/stage0_dea_ready_matrix.csv` |
| 歷史 raw close 價格 | `csv/historical_close_price_db.csv` |

Stage 0 特徵包含：

| 維度 | 欄位 |
|---|---|
| 資本利得報酬 | `Return_CAGR (%)` |
| 殖利率 | `Return_Div (%)` |
| 波動風險 | `Risk_Vol (%)` |
| 最大回撤風險 | `Risk_MaxDD (%)` |
| 費用 | `Cost_ExpRatio (%)` |
| 成交量流動性 | `Liq_Volume (M)` |
| AUM 流動性 / 規模 | `Liq_AUM (B)` |
| 產業分散 | `Div_Score (產出)` |
| 市場情緒 | `FinBERT_score` |

### 3.2 Stage 1：DEA 篩選

舊演算法 DEA 第一階段設計如下：

| DEA 類別 | 欄位 |
|---|---|
| Input | `In_Risk`, `In_Cost` |
| Output | `Out_Return`, `Out_Liquidity`, `Out_Diversity` |
| 不納入 DEA 第一階段 | `Out_Sentiment` |

重要邏輯：

1. `Out_Sentiment` 仍會建立在 DEA ready matrix 中，但目前不放入 Stage 1 DEA 的 `output_cols`。
2. DEA score 小於 `0.80` 的 ETF 被視為劣勢標的。
3. cross-efficiency DEA 從 `DEA_Score >= 0.8` 的 ETF 中進一步評估。
4. 這個設計讓 DEA 成為「客觀效率門檻」，而非直接使用使用者偏好。

### 3.3 Stage 2_1：AHP 偏好權重

目前使用 deterministic static AHP：

```text
DETERMINISTIC_AHP_WEIGHTS = True
CR = 3.733412000018201e-11
```

目前主系統使用者權重：

| 維度 | 權重 |
|---|---:|
| `Return_CAGR` | 40.00% |
| `Return_Div` | 10.00% |
| `Risk_Vol` | 14.00% |
| `Risk_MaxDD` | 6.00% |
| `Cost_ExpRatio` | 10.00% |
| `Liq_Volume` | 4.00% |
| `Liq_AUM` | 4.00% |
| `Div_Score` | 7.00% |
| `FinBERT_score` | 5.00% |

目前 `ALPHA_BASELINE = 0.0`，因此 Stage 3 完全使用使用者 AHP 權重，不混入 baseline 權重。

baseline 權重保留如下，但目前不會影響結果：

| 維度 | baseline 權重 |
|---|---:|
| `Return_CAGR` | 23% |
| `Return_Div` | 10% |
| `Risk_Vol` | 10% |
| `Risk_MaxDD` | 12% |
| `Cost_ExpRatio` | 15% |
| `Liq_Volume` | 5% |
| `Liq_AUM` | 5% |
| `Div_Score` | 15% |
| `FinBERT_score` | 0% |

### 3.4 Stage 2_2：相關性分群去重

目前相關性門檻：

```text
CORR_THRESHOLD = 0.99
```

邏輯：

1. 讀取 Stage 1 候選 ETF。
2. 取歷史報酬矩陣。
3. 對高度相關 ETF 分群。
4. 每群保留偏好分數最高的 ETF。

這會降低高度重複持股，但也可能在高成長 ETF 群中過早刪除替代標的。

### 3.5 Stage 3：偏好投資組合最佳化

目前最佳化目標是最大化偏好效用：

```text
U(P) =
  w_cagr      * score_cagr
+ w_div       * score_div
+ w_liq_vol   * score_liq_vol
+ w_liq_aum   * score_liq_aum
+ w_div_score * score_diversity
+ w_sent      * score_sentiment
+ w_maxdd     * score_maxdd
+ w_cost      * score_cost
+ w_vol_risk  * score_volatility
```

目前限制：

```text
MAX_WEIGHT_LIMIT = 0.40
long-only weights
sum(weights) = 1.0
```

波動率分數固定尺度：

```text
VOL_SCORE_FLOOR = 0.08
VOL_SCORE_CAP   = 0.30
```

目前 Stage 3 已修正成：

1. 投組績效使用 Stage 3 lookback 期間。
2. 在 lookback 第一個交易日依建議權重買入 ETF。
3. 不每日再平衡，直接持有到最後一日。
4. 用同一條 buy-and-hold NAV 計算 `CAGR`, `Annualized Volatility`, `Max Drawdown`, `Sharpe Ratio`。
5. 報表不再使用 Stage 0 單檔 ETF CAGR 的線性加權作為投組 CAGR。
6. 蒙地卡羅 MPT 圖已停用，保留數學解析 MPT 效率前緣圖。

## 4. 情緒分數系統現況

目前情緒系統已獨立到 `sentiment_engine/`。

資料檔：

| 類別 | 檔案 |
|---|---|
| 原始新聞事件 | `sentiment_engine/data/news_events_cache.csv` |
| 每日 ETF 情緒快取 | `sentiment_engine/data/sentiment_daily_cache.csv` |
| 總結報告 | `sentiment_engine/news_sentiment_report.md` |

目前情緒設定：

```text
DEFAULT_LOOKBACK_DAYS = 180
DEFAULT_HALF_LIFE_DAYS = 60
DEFAULT_NEUTRAL_SENTIMENT = 0.0
```

目前方法：

1. 擷取新聞事件。
2. 對新聞標題與摘要做 FinBERT 推論。
3. 先做同日新聞平均。
4. 再用 180 日 lookback 與半衰期 60 日做時間衰減。
5. 主程式 Stage 0 透過每日快取取得 as-of sentiment。
6. 回測在每個再平衡日讀取該日以前可見的 sentiment。
7. 若回測日期早於情緒快取，或 ETF 無新聞資料，情緒分數為 `0.0` 中性。

## 5. 回測系統現況

回測引擎：`backtest_engine.py`

目前預設設定：

| 參數 | 值 |
|---|---:|
| `DEFAULT_BACKTEST_START_DATE` | `2021-01-01` |
| `DEFAULT_BACKTEST_END_DATE` | `None` |
| `DEFAULT_REBALANCE_FREQ` | `M` |
| `DEFAULT_LOOKBACK_YEARS` | `3` |
| `DEFAULT_MIN_HISTORY_YEARS` | `8` |
| `DEFAULT_INITIAL_CAPITAL` | `1,000,000` |
| `DEFAULT_PERIODIC_CONTRIBUTION` | `0` |
| `DEFAULT_BENCHMARK_TICKER` | `VOO` |
| `DEFAULT_COMPARISON_BENCHMARKS` | `VOO`, `VT` |
| `DEFAULT_FETCH_MISSING_DATA` | `False` |
| `DEFAULT_FETCH_PERIOD` | `10y` |
| `corr_threshold` | `0.99` |
| `dea_threshold` | `0.80` |
| `max_weight_limit` | `0.40` |

回測績效邏輯：

1. 每個再平衡日使用當時 lookback 資料建立特徵矩陣。
2. 依照當時可見資料重新跑 DEA、偏好分數、分群與最佳化。
3. 在再平衡日買入系統建議權重。
4. 持有到下一個再平衡日。
5. 下一期再重新最佳化並換倉。
6. 分開記錄資本利得、股息現金與總財富。

## 6. 目前最後一次主程式輸出

目前最後一次 Stage 3 權重：

| ETF | 偏好組合 | Max Sharpe |
|---|---:|---:|
| SCHF | 40.00% | 0.00% |
| SCHG | 40.00% | 0.00% |
| VOO | 20.00% | 38.23% |
| HDV | 0.00% | 40.00% |
| DIVO | 0.00% | 21.77% |

目前最後一次深度健檢：

| 指標 | 偏好組合 | Max Sharpe |
|---|---:|---:|
| Arithmetic Annual Return (%) | 13.56 | 12.37 |
| Capital Gain CAGR (%) | 12.73 | 12.23 |
| Dividend Yield (%) | 1.77 | 2.74 |
| Estimated Total Return, No Reinvestment (%) | 14.50 | 14.97 |
| Expense Ratio (%) | 0.034 | 0.165 |
| Annualized Volatility (%) | 17.77 | 12.89 |
| Maximum Drawdown (%) | -29.63 | -16.75 |
| Liquidity Volume (Millions) | 7.95 | 2.74 |
| Liquidity AUM (Billions) | 241.28 | 374.17 |
| True Portfolio HHI (Real) | 0.1575 | 0.1251 |
| Weighted Sentiment Score | 0.0736 | 0.0579 |
| Sharpe Ratio | 0.538 | 0.649 |

## 7. 我們一路以來已完成的工程修正

### 7.1 資料與價格

1. 將主程式價格資料改用 raw close，而不是 adjusted close，以便資本利得與殖利率可以分開表達。
2. 修正價格快取沒有更新到最新可得日期的問題。
3. 補強 `historical_close_price_db.csv` 的近期資料刷新。
4. 修正 historical price cache 缺漏與對齊邏輯。

### 7.2 DEA 與數學健檢

1. 確認 Stage 1 DEA 第一階段不使用 sentiment，讓 sentiment 只進入偏好最佳化階段。
2. 修正 DEA / linprog 因 NaN 或 inf 導致崩潰的問題。
3. 保留 `Out_Sentiment` 欄位但不納入 DEA output columns。

### 7.3 產業分散

1. 修正 sector HHI 對缺少 sector data ETF 的處理。
2. 對 equity ETF 與非 equity ETF 的 sector 資料缺失做更清楚的邏輯區分。
3. 目前對無產業資料的 ETF 仍保留 NaN / fallback 處理，避免錯誤建立假 sector exposure。

### 7.4 情緒分數

1. 建立 `sentiment_engine/` 專門處理新聞情緒資料。
2. 建立新聞事件 cache 與每日 sentiment cache。
3. 改成「同日新聞平均，再做跨日時間衰減」。
4. 主程式 Stage 0 改為從每日 sentiment cache 讀取 as-of sentiment。
5. 回測每個再平衡日使用該日以前可見 sentiment。
6. 快取起始日前或缺新聞 ETF 統一使用 `0.0` 中性分數。

### 7.5 主程式績效與圖表

1. 修正投組 CAGR 不應使用單檔 ETF CAGR 線性加權的問題。
2. 改成用 buy-and-hold NAV path 計算 CAGR、波動、回撤與 Sharpe。
3. 修正投資組合深度健檢報告在 console 中被截斷成兩段的問題。
4. 停用主程式蒙地卡羅 MPT 圖。
5. 保留數學解析 MPT 效率前緣圖。
6. 調整 MPT 圖尺度以凸顯 frontier、偏好位置與 Max Sharpe 位置。

### 7.6 回測系統

1. 新增 rolling backtest 架構。
2. 支援再平衡頻率：月、季、半年、年。
3. 支援 initial capital 與 periodic contribution。
4. 回測輸出依單次 run 分資料夾整理 CSV、PNG、report。
5. 回測中使用 as-of feature matrix，避免未來資料滲漏。
6. 回測中保留資本利得、股息現金、總財富三條線。
7. 回測可比較 `VOO` 與 `VT` benchmark。

## 8. 尚未開始的演算法升級問題

以下是我們已觀察到，但尚未開始修改的演算法問題：

1. 報酬導向使用者的結果沒有明顯拉高 CAGR。
2. 偏好分數贏，但實際投資結果未必更理想。
3. DEA 第一階段可能過早阻擋高報酬但高風險 ETF。
4. 40% 單檔上限可能限制報酬導向使用者的表達。
5. 風險目前是加分項，較像獎勵低風險，而不是風險預算。
6. 相關性分群可能過早移除高成長替代品。
7. 成本、流動性、分散、情緒等輔助維度可能稀釋「報酬導向」主目標。

## 9. 舊演算法基準結論

目前系統已經具備完整 end-to-end pipeline、資料快取、情緒快取、主程式報表、數學 MPT 圖、rolling backtest 與 benchmark 比較。工程邏輯大致可作為演算法升級前基準版。

接下來的工作不應再以修 bug 為主，而應進入演算法設計問題：如何讓系統真的根據使用者風格改變投資行為，尤其是讓報酬導向使用者能合理承擔較高風險以追求更高報酬。
