# Project Architecture

本專案目前整理成四個主要 stage，並把使用者偏好提取獨立成 `stage 2_1`，ETF 分群與偏好篩選獨立成 `stage 2_2`。

## 統一 Stage 命名

```text
stage 0   market_data_preparation
stage 1   dea_screening
stage 2_1 preference_extraction
stage 2_2 preference_cluster_selection
stage 3   preference_portfolio_optimization
```

實作入口統一放在：

```text
pipeline_stages.py
```

主程式入口：

```text
main.py
```

## Stage 0: Market Data Preparation

目的：

```text
從網路抓取 ETF 數據，進行特徵處理、EDA、DEA 前正規化。
```

統一入口：

```python
stage0_market_data_preparation()
```

目前沿用的核心函式：

```python
get_all_etfs()
get_target_tickers_from_csv()
fetch_etf_data_yq()
build_etf_database_av()
clean_existing_database()
append_sentiment_to_csv()
merge_final_features()
patch_aum_from_csv()
run_stage0_2_eda()
run_stage0_normalization_and_reduction()
```

主要輸出：

```text
csv/stage0_final_matrix.csv
csv/stage0_dea_ready_matrix.csv
png/eda_*.png
```

## Stage 1: DEA Screening

目的：

```text
執行完整 DEA，包含標準 DEA、超級效率 DEA、交互效率 DEA。
```

統一入口：

```python
stage1_dea_screening()
```

目前沿用的核心函式：

```python
run_stage1_normalized_dea()
plot_dea_distribution()
run_stage1_super_efficiency_normalized()
run_cross_efficiency_dea()
```

主要輸出：

```text
csv/stage1_dea_results.csv
csv/stage1_super_efficiency_results.csv
csv/stage1_final_candidates.csv
png/dea_score_distribution.png
```

## Stage 2_1: Preference Extraction

目的：

```text
提取使用者偏好，最後輸出 Stage 3 求解器可讀的 Global_Weights。
```

這個 stage 保留兩條路線。

### Stage 2_1-A: Static AHP Preference Extraction

定位：

```text
原本的靜態 AHP 問卷形式，保留作為 baseline 與傳統方法對照組。
```

統一入口：

```python
stage2_1_static_ahp_preference_extraction()
```

目前沿用的核心函式：

```python
build_user_simulation()
TwoLevel_AHP_Model.calculate_global_weights()
```

主要輸出：

```text
json/stage2_ahp_global_weights.json
```

### Stage 2_1-B: Active Bayesian Preference Elicitation

定位：

```text
自然語言偏好提取 + 階層式 Bayesian 信念更新，是新的主研究方向。
```

統一入口：

```python
stage2_1_active_bayesian_preference_elicitation()
```

內部循環小 stage：

```text
stage2_1B_0 initialize_hierarchical_belief
stage2_1B_1 select_uncertain_targets
stage2_1B_2 ask_contextual_question
stage2_1B_3 extract_semantic_evidence
stage2_1B_4 update_bayesian_belief
stage2_1B_5 check_convergence_or_continue
stage2_1B_6 export_solver_compatible_weights
```

目前使用的模組：

```text
active_preference/
```

主要輸出：

```text
json/stage2_ahp_global_weights.json
json/stage2_1_active_bayesian_state.json
```

注意：

```text
為了讓既有 Stage 3 不必改寫，兩種偏好提取方法都輸出到同一個 Global_Weights 介面。
```

## Stage 2_2: Preference Cluster Selection

目的：

```text
針對高相關性 ETF 分群，再依照使用者偏好選出每群最佳 ETF。
```

統一入口：

```python
stage2_2_preference_cluster_selection()
```

目前沿用的核心函式：

```python
run_stage2_5_preference_deduplication_yq()
```

命名說明：

```text
原本函式名稱中的 stage2_5 代表舊流程位置。
新架構中它被重新定位為 stage 2_2。
```

主要輸出：

```text
csv/stage2_final_user_universe.csv
csv/stage2_normalized_features.csv
```

## Stage 3: Preference Portfolio Optimization

目的：

```text
將使用者偏好權重放入求解器，求出最佳偏好組合，並與傳統 Max Sharpe 組合比較。
```

統一入口：

```python
stage3_preference_portfolio_optimization()
```

目前沿用的核心函式：

```python
run_stage3_pipeline()
plot_portfolio_analytics_and_mpt()
plot_preference_radar_chart()
```

主要輸出：

```text
report/*_summary.txt
report/*_weights.csv
report/*_analytics.csv
png/*_portfolio_performance.png
png/*_mpt_efficient_frontier.png
png/*_radar_chart.png
```

## 偏好模式切換

在 `main.py` 中切換：

```python
preference_mode="static_ahp"
```

或：

```python
preference_mode="active_bayesian"
```

兩者最後都會輸出：

```text
json/stage2_ahp_global_weights.json
```

因此 Stage 2_2 與 Stage 3 不需要知道前面是 AHP 還是 Active Bayesian。
