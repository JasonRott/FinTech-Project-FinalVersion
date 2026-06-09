# 偏好驅動之智能 ETF 資產配置系統
**Preference-Driven Smart ETF Portfolio Optimization**

> 結合作業研究（OR）與金融科技（FinTech）：以 DEA 效率篩選、AHP / LLM 偏好提取、以及一套**有 Black-Litterman / CAPM 理論地基的 profile-dependent 投組最佳化**，為投資人量身打造客製化 ETF 投資組合。
> -Hugging Face 網頁: https://huggingface.co/spaces/JasonRott/FinTech-FinalProject-Group7

---

## ★ 最新演算法與成果（2026-06 重大升級）★

Stage 3 已從早期「線性加權偏好分數 / Markowitz」演進為 **U-C2 三核心 + Black-Litterman 理論地基**：

- **g(w) 偏好映射**：使用者偏好權重 → 連續決定「核心類型 / 風險水準 / 偏好傾斜」。
- **三核心**（由偏好自動選）：最小變異（保守）/ 市場追蹤 VT（平衡）/ **beta 曝險（報酬導向）**——三者正是 Black-Litterman 效率前緣上不同風險趨避的點（市場隱含報酬 Π ∝ β = CAPM）。
- **beta 化偏好評分**：報酬維度用「系統性風險曝險」而非不持續的過去報酬 → 各類使用者的偏好都能在樣本外被驗證地滿足。
- **跨規制 walk-forward 驗證**：報酬導向使用者穩健取得 >VT 的絕對報酬；其他 profile 贏在風險效率與偏好滿足。

📄 **完整說明見兩份報告**：
- [`REPORT_A_results_and_math.md`](REPORT_A_results_and_math.md) — 數學細節 + 關鍵回測佐證 + 假設與限制。
- [`REPORT_B_design_story.md`](REPORT_B_design_story.md) — 設計歷程與每個決策的理由。
- 開發全程的逐步記錄見 [`system_upgrade_records/`](system_upgrade_records/)（`00` 為入口快照）。

> ⚠️ **誠實定位**：這是一套理論紮實、偏好驅動、且對自身限制誠實量化的**決策支援框架**，非保證打敗市場的產品（詳見報告「假設與限制」）。

---

## 目錄

- [專案簡介](#專案簡介)
- [系統架構](#系統架構)
- [核心技術棧](#核心技術棧)
- [資料流與輸入輸出](#資料流與輸入輸出)
- [安裝與環境設定](#安裝與環境設定)
- [使用方式](#使用方式)
- [主要模組說明](#主要模組說明)
- [回測模組](#回測模組)
- [情緒分析引擎](#情緒分析引擎)
- [專案目錄結構](#專案目錄結構)
- [設計取捨與決策說明](#設計取捨與決策說明)
- [改進空間分析](#改進空間分析)

---

## 專案簡介

本系統目標是解決傳統 Robo-Advisor 的兩個核心缺陷：

1. **效率盲點**：市場上的 ETF 超過 3,000 檔，多數評分方法為線性單指標排序，忽略成本-報酬-流動性的多維度相對效率。
2. **偏好黑盒**：傳統問卷只能擷取靜態偏好，無法處理自然語言回答或偏好不確定性。

本系統的解決方案：

- **Stage 1**：以 Data Envelopment Analysis (DEA) 做多輸入輸出相對效率篩選，剔除 Pareto 劣勢標的。
- **Stage 2_1-A**：Analytic Hierarchy Process (AHP) 靜態問卷，轉換多準則偏好為可計算權重（baseline）。
- **Stage 2_1-B**：Gemini LLM 主動訪談 + 結構化萃取，將自然語言偏好對應至九個財務維度（研究主線）。
- **Stage 2_1-C**：`preference_engine`（Phase 3 BNN 偏好誘出）——輸入「投資理念 + 逐輪自然語言問答」，以 BGE-M3 編碼 + 9 個 1D 貝氏神經網路，直接誘出九維偏好權重（與下游維度完全一致）。
- **Stage 3**：U-C2 三核心 + BL 理論地基的偏好驅動最佳化（SLSQP），輸出偏好組合 vs. Max Sharpe / VT / 等權 的完整比較；跑完可選擇「針對你的偏好」做歷史回測。

---

## 系統架構

```
┌─────────────────────────────────────────────────────────────┐
│                     main.py (Entry Point)                    │
│              pipeline_stages.py (Stage Router)               │
└───────────────────────────┬─────────────────────────────────┘
                            │
        ┌───────────────────▼───────────────────┐
        │           Stage 0: Market Data         │
        │  YahooQuery / AlphaVantage / Finnhub   │
        │  FinBERT 新聞情緒 → 時間衰減加權分數   │
        │  EDA + 特徵合併 + DEA 前正規化         │
        └───────────────────┬───────────────────┘
                            │ csv/stage0_final_matrix.csv
        ┌───────────────────▼───────────────────┐
        │           Stage 1: DEA Screening       │
        │  Standard DEA + Super-Efficiency DEA   │
        │  Cross-Efficiency DEA (peer-appraisal) │
        └───────────────────┬───────────────────┘
                            │ csv/stage1_final_candidates.csv
        ┌───────────────────▼───────────────────┐
        │     Stage 2_1: Preference Extraction   │
        │  ┌─────────────┐  ┌─────────────────┐ │
        │  │  (A) Static │  │  (B) Active LLM │ │
        │  │     AHP     │  │ Gemini Interview │ │
        │  └──────┬──────┘  └────────┬────────┘ │
        │         └────────┬─────────┘          │
        └──────────────────┬────────────────────┘
                           │ json/stage2_ahp_global_weights.json
        ┌──────────────────▼────────────────────┐
        │   Stage 2_2: Preference Cluster Select │
        │  相關性分群 → 偏好排序 → 去重複       │
        └──────────────────┬────────────────────┘
                           │ csv/stage2_final_user_universe.csv
        ┌──────────────────▼────────────────────┐
        │   Stage 3: Portfolio Optimization      │
        │  U-C2 三核心 + BL 地基（SLSQP）        │
        │  HHI 產業分散度約束                   │
        │  vs. Max Sharpe 比較                  │
        └──────────────────┬────────────────────┘
                           │
             report/ + png/ (分析報告與視覺化)
```

---

## 核心技術棧

| 領域 | 技術 / 方法 |
|------|------------|
| 市場資料 | YahooQuery、Alpha Vantage API、Finnhub API |
| 情緒分析 | FinBERT（本地端）、時間衰減加權 |
| LLM 偏好訪談 | Google Gemini API（結構化 JSON 輸出） |
| 效率篩選 | DEA（標準、超級效率、交互效率）|
| 偏好建模 | AHP（Analytic Hierarchy Process）|
| 投資組合最佳化 | SLSQP（`scipy.optimize`）、U-C2 三核心、Black-Litterman / CAPM、Ledoit-Wolf 共變異收縮 |
| 資料處理 | pandas、numpy |
| 視覺化 | matplotlib、seaborn |
| 回測 | 自建滾動再平衡回測引擎（`backtest_engine.py`）|

---

## 資料流與輸入輸出

### 輸入

| 來源 | 內容 |
|------|------|
| YahooQuery | 財務比率、報酬率、AUM、Expense Ratio |
| Alpha Vantage | ETF 持股分散度、產業配置 |
| Finnhub | 財經新聞（用於 FinBERT 情緒分析）|
| 使用者問卷 / 訪談 | AHP 成對比較矩陣 or Gemini 自然語言回答 |

### 中間產物

| 檔案 | 說明 |
|------|------|
| `csv/stage0_final_matrix.csv` | ETF 多維度原始特徵矩陣 |
| `csv/stage0_dea_ready_matrix.csv` | DEA 前置正規化矩陣 |
| `csv/stage1_dea_results.csv` | 標準 DEA 效率分數 |
| `csv/stage1_super_efficiency_results.csv` | 超級效率 DEA 結果 |
| `csv/stage1_final_candidates.csv` | 篩選後的候選 ETF 池 |
| `json/stage2_ahp_global_weights.json` | 使用者偏好全域權重（共用介面）|
| `csv/stage2_final_user_universe.csv` | 最終 ETF 投資宇宙 |

### 最終輸出

| 檔案 | 說明 |
|------|------|
| `report/*_summary.txt` | 投資組合文字分析報告 |
| `report/*_weights.csv` | 各 ETF 配置權重 |
| `report/*_analytics.csv` | 績效、風險指標深度分析 |
| `png/*_portfolio_performance.png` | 累積報酬走勢圖 |
| `png/*_mpt_efficient_frontier.png` | MPT 效率前緣圖 |
| `png/*_radar_chart.png` | 九維度偏好雷達圖 |

---

## 安裝與環境設定

**需求**：Python 3.8 以上

### 1. Clone 專案

```bash
git clone https://github.com/JasonRott/FinTech-Project.git
cd FinTech-Project
```

### 2. 安裝主架構套件

```bash
pip install -r requirements.txt
```

### 3. 安裝 Active Preference 套件（選用）

```bash
pip install -r requirements-active_preference.txt
```

### 4. 設定 API Key

在專案根目錄建立 `.env` 檔案（此檔已被 `.gitignore` 排除）：

```env
AV_API_KEY=你的_Alpha_Vantage_API_Key
FINNHUB_API_KEY=你的_Finnhub_API_Key
GEMINI_API_KEY=你的_Gemini_API_Key
```

> **注意**：目前 API Key 暫時存放在 `parameters.py` 中，上傳 GitHub 前請先移除或改為從環境變數讀取。詳見[改進空間分析](#改進空間分析)。

### 5. 下載 FinBERT 模型

`local_finbert/model.safetensors` 因超過 GitHub 大小限制不包含在 repo 中，請手動下載：

```bash
# 方法一：使用 huggingface_hub
python -c "from huggingface_hub import snapshot_download; snapshot_download('ProsusAI/finbert', local_dir='local_finbert')"

# 方法二：從 Hugging Face 官網下載
# https://huggingface.co/ProsusAI/finbert
```

---

## 使用方式

### 執行完整流程

```bash
python main.py
```

### 切換偏好模式

在 `main.py` 中設定 `preference_mode`：

```python
# 靜態 AHP 問卷（傳統方法 / baseline）
preference_mode="static_ahp"

# preference_engine：投資理念 + 逐輪問答 → BNN 偏好誘出（純終端互動）
preference_mode="preference_engine"

# Active LLM 訪談（Gemini 主線）
preference_mode="active_bayesian"
```

> **`preference_engine` 用法**：跑 `python main.py` 後，終端會請你輸入一段「投資理念」，
> 再逐題以自然語言回答。引擎**預設會問完整 9 題**（每維一題）讓信賴區間可信；當它已大致掌握
> 你的前幾名偏好時會詢問一次是否提早結束（直接 Enter 即繼續答完）。完成後輸出九維權重，
> 與 AHP 路徑寫入同一個 `json/stage2_ahp_global_weights.json` 介面，後段 Stage 2_2/3 與回測無需改寫。
> 首次執行會自動下載文字編碼器 BGE-M3（約 2.2 GB，需聯網一次；之後可離線）。
> 相關設定見 `preference_engine/README.md`。靜態原型旋鈕 `parameters.ACTIVE_USER_PROFILE` 僅作用於 `static_ahp`，與本模式獨立。

### 執行部分 Stage

```python
from pipeline_stages import PipelineConfig, run_full_pipeline

run_full_pipeline(
    PipelineConfig(
        run_stage0_fetch=False,            # 略過資料擷取（使用現有快取）
        run_stage0_feature_processing=False,
        run_stage1_dea=False,
        run_stage2_1_preference=True,     # 只重跑偏好提取
        run_stage2_2_cluster_selection=True,
        run_stage3_optimization=True,
        preference_mode="active_bayesian",
    )
)
```

### Active Preference 訪談流程

```bash
# 1. 執行 Gemini 訪談
python active_preference/run_real_interview.py

# 2. 萃取偏好權重
python active_preference/run_gemini_preference_extraction.py

# 3. 執行 benchmark 評估
python active_preference/run_gemini_extraction_benchmark.py
```

### 回測

```bash
# 使用預設參數（每月再平衡）
python backtest_engine.py

# 指定參數
python backtest_engine.py --freq Q --start-date 2021-01-01 --lookback 3
```

---

## 主要模組說明

### `main.py`
專案入口，設定 `PipelineConfig` 並呼叫 `run_full_pipeline()`。

### `pipeline_stages.py`
統一管理 Stage 0 ~ Stage 3 的函式入口。每個 stage 開始與結束時輸出進度提示。三條偏好路線（AHP / preference_engine / Active Bayesian）都輸出至同一個 `json/stage2_ahp_global_weights.json` 介面，確保 Stage 3 無需改寫。

### `functions.py`
所有核心計算函式的彙整：
- 資料擷取（YQ、AV、Finnhub）
- FinBERT 情緒打分
- EDA 與正規化
- DEA 線性規劃求解
- AHP 成對矩陣計算
- SLSQP 偏好最佳化
- MPT 效率前緣繪製
- 雷達圖視覺化

### `parameters.py`
全域參數設定：API Key、ETF 數量上限、權重上限、AHP 確定性輸入、VERBOSE 模式等。

### `active_preference/`
Gemini 主動偏好訪談完整模組：
- `run_real_interview.py`：執行 Gemini 訪談對話
- `gemini_preference_extractor.py`：將訪談記錄萃取為九維度 JSON
- `conversation_recorder.py`：儲存逐輪對話紀錄
- `dimensions.py`：定義九個偏好維度與語意映射
- `llm_clients.py`：Gemini API 客戶端封裝

### `sentiment_engine/`
FinBERT 情緒分析子系統：
- `finnhub_fetcher.py`：抓取財經新聞
- `finbert_scoring.py`：本地 FinBERT 模型推論
- `daily_builder.py`：建立每日情緒時間序列
- `store.py`：快取管理，提供 `get_sentiment_map_asof()` 介面

### `AHP_weights_setting_script.py`
開發輔助工具：給定目標偏好權重，反推 AHP 成對比較矩陣，用於調校 `DETERMINISTIC_USER_INPUTS`。

---

## 回測模組

`backtest_engine.py` 是獨立於主 Pipeline 的滾動回測系統。

**特性：**
- 支援月 / 季 / 半年 / 年再平衡頻率
- 嚴格使用歷史截點前的資料，避免未來資料洩漏
- 支援定期定額（DCA）模式
- 與 VOO、VT 等基準指數比較
- 輸出 NAV 曲線、年化報酬、Sharpe、最大回撤等績效指標

**回測結果存放：**
- `backtest/`：各參數組合的原始資料
- `backtest_report/`：對應的報告與視覺化

---

## 情緒分析引擎

`sentiment_engine/` 提供一套獨立的新聞情緒快取與查詢介面：

- 以 Finnhub 抓取各 ETF ticker 的新聞事件
- 透過本地 FinBERT 打分，避免每次重複推論
- 支援 `get_sentiment_map_asof(date)` 精確查詢某日截點前的情緒分數
- 情緒分數以時間衰減加權整合，對近期新聞給予較高權重

---

## 專案目錄結構

```
Fintech project/
├── main.py                          # 主程式入口
├── pipeline_stages.py               # Stage 路由與進度管理
├── functions.py                     # 核心計算函式庫
├── parameters.py                    # 全域參數與 API Key
├── backtest_engine.py               # 滾動回測引擎
├── AHP_weights_setting_script.py    # AHP 反推工具
├── requirements.txt                 # 主架構套件
├── requirements-active_preference.txt
├── README.md
├── ARCHITECTURE.md                  # 詳細架構說明
├── .gitignore
│
├── active_preference/               # Gemini LLM 偏好訪談模組
│   ├── run_real_interview.py
│   ├── run_gemini_preference_extraction.py
│   ├── run_gemini_extraction_benchmark.py
│   ├── run_gemini_benchmark_reextract.py
│   ├── gemini_preference_extractor.py
│   ├── conversation_recorder.py
│   ├── dimensions.py
│   ├── llm_clients.py
│   ├── interview_rules.py
│   ├── prompt_loader.py
│   ├── paths.py
│   ├── prompts/                     # Gemini 提示詞模板
│   └── results/                    # 訪談記錄與萃取結果
│
├── preference_engine/               # Stage 2_1-C：投資理念+問答 → 9 維權重（Phase 3 BNN）
│   ├── phase3_system/               # 引擎（engine / core / encoder / cli）
│   ├── assets/                      # 模型與設定（9 個 1D BNN、PhilHead、gate、題庫、校準）
│   ├── integrate_example.py         # 整合範例
│   └── README.md                    # 用法（BGE-M3 線上/離線、輸出 Ew 格式）
│
├── sentiment_engine/                # FinBERT 情緒分析子系統
│   ├── finnhub_fetcher.py
│   ├── finbert_scoring.py
│   ├── daily_builder.py
│   ├── store.py
│   ├── schemas.py
│   ├── config.py
│   ├── build_cache.py
│   ├── batch_collect_reports.py
│   ├── compare_algorithms.py
│   ├── data/                       # 情緒快取 CSV
│   ├── plots/                      # 情緒走勢圖
│   └── reports/                    # 各 ticker 情緒報告
│
├── csv/                             # Pipeline 各階段輸出矩陣
├── json/                            # 設定檔、偏好權重、ETF 資料庫
├── png/                             # EDA、DEA、MPT、雷達圖
├── report/                          # 最終投資組合分析報告
├── backtest/                        # 回測原始結果
├── backtest_report/                 # 回測報告與圖表
│
├── demo/                            # 示範 Notebook 與 Demo 腳本
│   ├── active_preference_demo.py
│   ├── demo_AHP.ipynb
│   ├── demo_sentiment_analysis.ipynb
│   └── demo_similarity_analysis.ipynb
│
├── local_finbert/                   # 本地 FinBERT 模型（model.safetensors 不含於 repo）
│   ├── config.json
│   ├── tokenizer.json
│   └── tokenizer_config.json
│
├── literature/                      # 參考文獻、方法說明文件、開發筆記
├── version_0/                       # 原始開發版本（Jupyter Notebooks）
├── system_upgrade_records/          # 演算法升版紀錄
└── test_LLM/                        # LLM 測試實驗（Gemini、Llama3、OLMo）
```

---

## 設計取捨與決策說明

| 決策 | 說明 |
|------|------|
| AHP 保留為 baseline | 作為傳統方法對照組，可在沒有 API Key 的環境下執行完整流程 |
| 三條偏好路線共用介面 | `json/stage2_ahp_global_weights.json` 為唯一輸出點，Stage 3 無需知道上游路線（AHP / preference_engine / Gemini）|
| FinBERT 本地部署 | 避免每次呼叫外部 API，降低延遲與成本；情緒分數計算可離線執行 |
| DEA 交互效率 | 相較單純的 Super-Efficiency DEA，交互效率可避免自評偏誤，排名更具客觀性 |
| Stage 3 不直接依賴偏好來源 | 確保求解器介面穩定，未來可插拔更多偏好方法 |
| Alpha Vantage API 降級處理 | 觸發每日限制時，自動使用 `json/etf_database.json` 既有資料繼續後續流程 |
| 回測與主流程分離 | `backtest_engine.py` 獨立執行，不污染 Stage 0~3 的輸出資料夾 |

---

## 改進空間分析

以下列出本專案目前的主要改進方向，依優先程度排列：

### 1. 安全性：API Key 管理

**現況**：三組 API Key（Alpha Vantage、Finnhub、Gemini）直接硬編碼在 `parameters.py` 中，若上傳至公開 GitHub 將立即洩漏。

**建議**：
```python
# 改為從 .env 讀取
import os
from dotenv import load_dotenv
load_dotenv()
AV_API_KEY = os.getenv("AV_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY")
```
新增 `.env.example` 範本供使用者參考。**上傳前請務必先處理此問題。**

---

### 2. 大型檔案管理：FinBERT 模型

**現況**：`local_finbert/model.safetensors` 約 440MB，遠超 GitHub 單檔 100MB 限制。

**建議**：
- 已將 `model.safetensors` 加入 `.gitignore`
- 在 README 加入 Hugging Face 自動下載指令（已完成）
- 或使用 Git LFS 管理

---

### 3. 單元測試缺失

**現況**：專案無任何測試檔案（`tests/` 目錄不存在），核心函式如 DEA 求解器、AHP 計算、組合最佳化等無法被自動驗證。

**建議**：
```
tests/
├── test_dea.py          # DEA 求解器正確性
├── test_ahp.py          # AHP 一致性比率計算
├── test_optimizer.py    # SLSQP 結果合法性（權重總和=1）
└── test_sentiment.py    # FinBERT 分數範圍驗證
```

---

### 4. 日誌系統

**現況**：使用 `VERBOSE = True/False` 旗標控制輸出，`print()` 分散於 `functions.py` 各處。

**建議**：改用 Python 標準 `logging` 模組，統一格式並支援寫入日誌檔：
```python
import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)
```

---

### 5. 互動式前端

**現況**：所有輸出為靜態 PNG 圖檔與 CSV/TXT 文字報告，缺乏互動介面。

**建議**：以 Streamlit 建立 Web UI，讓使用者可以：
- 線上回答 AHP 問卷或 Gemini 訪談
- 即時調整 Stage 3 的風險限制與資產上限
- 互動式查看雷達圖、效率前緣、組合績效

---

### 6. Pipeline 斷點續跑與快取

**現況**：Pipeline 各 Stage 之間以 CSV / JSON 銜接，但無法精確判斷哪個 Stage 的輸入已過期，必須手動設定 `run_stage*=False`。

**建議**：
- 為每個 Stage 輸出加上 hash 或 timestamp metadata
- Stage 入口自動比對上游輸入是否有更新，按需重跑

---

### 7. CI/CD 自動化

**現況**：無 GitHub Actions 工作流，PR 合入後無自動驗證。

**建議**：加入 `.github/workflows/ci.yml`，在每次 push 時自動：
- 執行 `pytest`（或 lint + type check）
- 驗證 `requirements.txt` 可成功安裝

---

### 8. API 重試機制

**現況**：若 Finnhub 或 Alpha Vantage API 回傳錯誤，系統可能直接中斷或靜默略過。

**建議**：使用 `tenacity` 或手動指數退避（exponential backoff）包裝 API 呼叫：
```python
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def fetch_news(ticker: str) -> list[dict]: ...
```

---

### 9. 型別標注（Type Hints）

**現況**：`functions.py` 中大多數函式缺少型別標注，`mypy` 無法靜態驗證。

**建議**：逐步補充型別標注，提升程式碼可讀性與 IDE 支援：
```python
def run_stage1_normalized_dea(
    df: pd.DataFrame,
    inputs: list[str],
    outputs: list[str],
) -> pd.DataFrame: ...
```

---

### 10. Docker 容器化

**現況**：複製環境需要手動安裝 Python、FinBERT 模型、各套件，且 torch 版本與 CUDA 依賴複雜。

**建議**：提供 `Dockerfile` 與 `docker-compose.yml`，讓任何人可以一行指令複製整個執行環境：
```bash
docker compose up --build
```

---

### 11. 結果資料版本控制

**現況**：`csv/`、`json/`、`backtest/` 下的輸出檔案會被下一次執行覆蓋，無法追蹤不同參數組合的歷史結果。

**建議**：
- Stage 輸出加上 timestamp 後綴（如 `stage1_final_candidates_20260601.csv`）
- 或考慮引入 DVC（Data Version Control）管理大型資料檔案的版本

---

### 12. 情緒分數整合驗證

**現況**：FinBERT 情緒分數在 `BASELINE_WEIGHTS` 中被設為 `0.0`，目前尚未納入正式偏好權重計算。

**建議**：
- 補充情緒分數與 ETF 報酬率的相關性分析
- 若相關性顯著，重新評估其在 AHP / SLSQP 中的加權比重
