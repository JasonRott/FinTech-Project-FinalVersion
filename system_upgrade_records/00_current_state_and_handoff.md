# 現況快照與交接（START HERE）

最後更新：2026-06-06  
用途：對話壓縮/換新聊天室後的單一入口。本檔自包含，讀完即可接續工作。  
其他檔：`01` 舊基準、`02` 改動流水帳、`03` 待辦/設計、`04` 文獻+程式稽核、`05` 設計理由與成敗脈絡。

---

## ★★ 最新狀態 + 待辦（2026-06-06，壓縮前快照）★★

### 已上 GitHub（公開 repo，乾淨）
- **Repo**：https://github.com/JasonRott/FinTech-Project-FinalVersion ，分支 `main`，最新 commit ≈ `a3a5abf`。
- HTTPS remote 已設、憑證已快取（Git Credential Manager），`git push origin main` 可直接推。`gh` CLI 未安裝。
- 安全：`.env` 未追蹤、無硬編金鑰（全 `os.getenv`）。

### ★ 已完成：網頁版 preference 已接上（`etf_preference_bundle`，舊 `preference_engine` 已刪）★
- 使用者上傳 `etf_preference_bundle/`（舊 `preference_engine` 的超集：同 `phase3_system/`+`assets/`，外加 Flask 網頁層 `web/`、`run_web.py`、`recommender_hook.py`）。**舊 `preference_engine/` 已從 repo 與磁碟移除**（共用引擎/assets 以 rename 形式保留）。
- **接點極窄**：後段（stage2_2→stage3→回測）只認 `json/stage2_ahp_global_weights.json` 的 `Global_Weights`（9 維、總和=1）。
- **網頁→主系統兩段橋接（檔案交付，跨行程）**：
  1. `etf_preference_bundle/recommender_hook.deliver_weights(weights, snapshot)`：問答完成時（web 或 library 都呼叫此唯一接點）→ 正規化 9 維 → **直寫主系統 `json/stage2_ahp_global_weights.json`**（canonical payload）。
  2. `pipeline_stages.stage2_1_web_preference_ingest()`（`preference_mode="web_preference"`）：讀網頁最近結果（優先 `etf_preference_bundle/web/last_result.json` ⇒ 退而求其次讀 hook 直寫 json）→ 正規化 → 續跑下游。找不到 → fallback + 提示先跑網頁。
- **使用流程**：`python etf_preference_bundle/run_web.py`（http://127.0.0.1:8000 完成問答，自動交付）→ `python main.py`（`web_preference`）。
- 終端版仍可用：`preference_mode="preference_engine"`（`stage2_1_preference_engine_elicitation`，引擎路徑已改指 `etf_preference_bundle`，預設答完 9 題）。
- BGE-M3 首次自動下載 ~2.2GB（或放 `etf_preference_bundle/encoder_model/` 離線）。網頁後端需 `flask>=3.0`（已加 requirements）。

### ★ main.py 單一開關 RUN_MODE（一鍵切換執行方式）★
- `main.py` 頂部 `RUN_MODE`：
  - `"terminal"`：一鍵終端問答（→ `preference_mode="preference_engine"`，引擎在 bundle），跑完整 pipeline + 問是否回測，全程終端。**目前預設。**
  - `"web"`：啟動 ETF 網頁 `etf_web/`（port 8050），偏好問答→執行分析→結果呈現全部在瀏覽器。
  - `"profile"`：不問答，用 `parameters.ACTIVE_USER_PROFILE`（靜態原型/AHP）跑 pipeline。
- 底層 `PreferenceMode`（4 種，輸出同一 JSON）：`web_preference` / `preference_engine` / `static_ahp` / `active_bayesian`。

### ★ ETF 網頁版 `etf_web/`（與「語意萃取網頁」分開的整合網頁）★
- `etf_web/app.py`（Flask，port 8050）：① 偏好問答（重用 `etf_preference_bundle` 的 `Phase3Engine`，完成時 `recommender_hook` 寫權重 json）② `/api/run` 背景跑 `run_full_pipeline(web_preference)`+`run_preference_backtest_core`、`/api/status` 輪詢 ③ `/api/results`+`/results-file/<rel>` 讀 `LAST_MAIN_USER_DIR` 的圖與報表。`run_web.py` 啟動器、`templates/index.html`、`static/{app.js,style.css}`。
- `pipeline_stages.run_preference_backtest_core(freq, preference_file, emit)`：非互動回測核心（終端 `stage3b` 與網頁共用；不動 backtest_engine 最佳化邏輯）。
- 需 `flask>=3.0`。**內容/版面待細定；plumbing 已驗（路由/test client/py_compile），尚未做含模型的 live 全跑。**

### 使用者結果輸出
- 主系統每次跑 → `user_results/new_user_{n}`（n=現有最大+1，永不覆寫）；回測巢狀其中。`new_user_*` 不入庫。
- **固定展示** `user_results/showcase_7_profiles/`（**已追蹤+上 GitHub**）：7 profile 各含主系統+季度回測；`對照分析報告.md`（含多維度表、熱圖、小倍數長條、`迷你雷達_vs_VT/` 7 張）。
- `upgrade_figures/`（關鍵實驗數據+圖）也已追蹤上 GitHub（供組員簡報）。

### 近期已完成（細節見 02 對應日期）
- 回測自動產 `_metrics_comparison.png`（各策略 vs VT；含**股息**：堆疊資本利得+股息、平均殖利率）。
- **CAGR/累積總報酬含股息**（=資本利得+估計現金股息、未再投入）；報表另拆 Capital_Gain/Dividend_Income。
- FinBERT 載入改檢查「權重檔」存在（fresh clone 缺權重會自動下載 ProsusAI/finbert）。
- 雷達 β 尺度 `RADAR_BETA_REF=1.2`（與 PREF_BETA_REF=2.0 解耦，只動顯示）。
- 集中式 log → `logs/`（每次執行一個時間戳檔）。
- REPORT_A 數學：**區塊用 ```math 圍欄（GitHub 會渲染）、行內改純 Unicode**（行內 `$...$` 在該檢視器不渲染會露原始碼）。

---

## ★ 系統定案 + GitHub 整理（2026-06-06）★
- **生產演算法 = C2**（`OPTIMIZATION_ARM="C2"`）+ beta 評分 + noCAGR + 品質約束全關 + 錨 VT。主系統 Stage 3 與回測**邏輯一致已逐行驗證**（`09`）。
- **主系統跑完會問是否做「針對此偏好」的回測**（選頻率;**資料/視窗固定 ≤10 年**＝OOS 從 7 年前起算 + lookback 3 年,起點動態隨時間滑動,缺資料才補抓;`pipeline_stages.stage3b_optional_preference_backtest`）。
- **視覺化稽核**（`10`）：雷達**報酬軸=beta（標籤與顯示值皆 β,與評分同口徑）、殖利率軸=固定 0~5% 尺度（避免微差放大）**。**主系統的績效圖與效率前緣圖已停用不再輸出**（描述性、非 C2/BL 最佳化所在,易誤導）→ 故先前「前緣標 VT+三核心」的深度重繪已取消（直接移除該圖）。
- **兩份報告**：`REPORT_A_results_and_math.md`、`REPORT_B_design_story.md`（含假設）。
- **GitHub 整理完成（本地）**：無硬編金鑰（.env + os.getenv）;`.env.example` 已建;`.gitignore` 擴充（排除 .env/FinBERT 模型/1.1GB active_preference results/價格庫/50MB新聞快取/生成輸出/日誌）;實驗腳本移到 `experiments/`;README 加最新演算法 banner + 報告連結。已 `git init` + 初始 commit（master,1289 檔/25MB,無敏感檔）。**push 待使用者提供 repo 網址/授權。**
- **輸出重整（2026-06-06）**：新增單一父資料夾 `user_results/`（`parameters.USER_RESULTS_DIR`,已 gitignore）。**主系統每次執行** → `user_results/main_{case}_{時間戳}/`，**分兩子夾**：`01_screening_eda/`（eda_*、*dea* 圖 + `stage1_dea_results.csv`）與 `02_portfolio/`（`{case}_radar_chart.png` + 推薦報表;績效/前緣圖已停用故不收）;在 `run_stage3_pipeline` 末段收集。**回測每次執行** → `user_results/backtest_{run_id}_arm{X}_{時間戳}/`（收齊該次 png_dir+report_dir+csv_dir 全部;改寫自 `_mirror_run_figures_to_upgrade`）。原 `png/`、`report/`、`backtest_report/`、`upgrade_figures/` 仍是工作輸出,user_results 是自包含彙整。
- **最終系統瘦身 + 集中式 log（2026-06-06）**：
  - **集中式 log**：`parameters.LOGS_DIR="logs"`;functions.py 每次執行寫 `logs/run_<ts>.log`（UTF-8 FileHandler,INFO+,終端噤聲不變）;舊根目錄 *.log 已移入;`.gitignore` 加 `logs/`。
  - **回測夾巢狀進主系統夾**：prompt 回測經 `BacktestConfig.user_results_parent`（functions 全域 `LAST_MAIN_USER_DIR`）→ `user_results/main_*/backtest_*/`;回測夾再分 `01_text_reports/02_eda_dea_figures/03_performance_figures/04_data_csv`。主系統**還原輸出數學前緣圖**（績效圖/蒙地卡羅前緣仍停用）。
  - **雷達 β 尺度** `RADAR_BETA_REF=1.2`（與 PREF_BETA_REF=2.0 解耦,只動顯示,win_VT 不變;詳見 02 與 project memory）。
  - **repo 瘦身（原地）**：`git rm --cached` 生成輸出（backtest/png/report/sentiment_engine reports+plots）與非生產（version_0/test_LLM/demo/.vscode/殘留JSON）;**追蹤 1287→94、25MB→8MB**。保留 = 核心 .py + active_preference/ + sentiment_engine/ + experiments/ + system_upgrade_records/ + literature/ + json/csv 設定 + local_finbert tokenizer/config + 文件。核心模組 import 驗證 OK（程式層獨立可跑）。
- **待辦**：(1) 跑 7 個 USER_PROFILES（最終版、印出所有真實流程圖表）→ user_results 得 7 份乾淨結果;(2) push 到 GitHub（需 repo 網址;repo 現為乾淨最終系統包）;(3) 報告請使用者審。
  - 備忘：雷達 β scale 維持解耦,**先不同步 PREF_BETA_REF**（要同步才需重跑 `_beta_score_test` + 更新報告數字）。

## 0. 一句話現況
偏好驅動 ETF 投組最佳化專案。已從 Arm A（線性加權）→ Arm C（最小變異+傾斜）→ **Arm C2（profile-dependent 三核心，已實作並驗證成功，2026-06-05）**。C2 讓報酬導向使用者用 beta 核心換到**超過 VT 的絕對報酬**（aggressive 8.85%→13.80% CAGR）；且發現**拿掉傾斜中的資本利得排名（noCAGR）**就讓多個 profile 贏過 VT。**下一步 = walk-forward 多視窗驗證**（確認非單期運氣）。完整成果見 `06_overnight_experiment_report_2026-06-05.md`。

## 1. 程式現況（三臂，開關在 parameters.py）
- `OPTIMIZATION_ARM`：**目前預設 "A"（安全 baseline）**。"A"=線性加權偏好分數（現況）；"B"=mean-variance（真實 μ，已證實差，因 μ 不可估）；"C"=最小變異核心+偏好傾斜（目前最佳方向）。
- **鐵律：`functions.py`（主系統 Stage 3）與 `backtest_engine.py`（`optimize_preference_portfolio`）是兩套獨立最佳化器，任何改動必須兩邊同步並各自驗證。**
- Arm C 目標：`min ½wᵀΣw − τ·(wᵀs)`，Σ=Ledoit-Wolf 收縮，s=`User_Pref_Score`（排名式 AHP 加權），+ 風險預算約束 + 品質約束（成本上限、HHI 上限）。
- 關鍵參數（parameters.py）：`TILT_STRENGTH(τ)=0.1`、`TILT_INCLUDE_CAGR=True`、`RISK_BUDGET_VOL=0.30`、`USE_QUALITY_CONSTRAINTS=True`、`COST_BUDGET_QUANTILE=0.75`、`HHI_CEILING=0.50`、`USE_LEDOIT_WOLF_COV=True`、`MEAN_SHRINKAGE_INTENSITY=0.5`（僅 Arm B 用）、`DEA_TOP_FRACTION=0.25`、`DEFAULT_BENCHMARK_TICKER="VT"`。
- `USER_PROFILES`（parameters.py）：7 個使用者原型（aggressive_growth / return_leaning / balanced / conservative / income / cost_liquidity / diversified_quality），9 維全局權重，供多 profile 實驗（繞過 AHP）。

## 2. 已完成的演算法/工程改動（重點）
- DEA：`Out_Return` 拆成 `Out_CAGR`+`Out_Div`（選項 A，成長股不被股息稀釋）；候選池門檻改「取前 25%」百分位。
- 視覺化/求解器報酬一律**算術平均**（Max Sharpe + 報表）；報表同時保留幾何 CAGR。
- 共變異數用 **Ledoit-Wolf 收縮**（最佳化器）。
- 殖利率進 μ 用**偏好比例加權**（Return_Div/Return_CAGR），非 1:1。
- 基準改 **VT**（≈市場組合/BL 先驗）；VOO 留作 aspirational 對照。偏好分數欄位改 benchmark-generic 命名。
- 視覺化：回測新增 V-1（偏好分數 vs 未來結果散佈）、V-6（偏好分數時間序列 + OOS 勝率）；雷達圖已停用（函式保留）。`upgrade_figures/` 每次執行開 `{run_id}_arm{X}_{時間戳}/` 並只複製 6 張指定圖。

## 3. 關鍵實證結論（含誠實更正）
- **μ 估計是毒藥**：用樣本 μ 的 mean-variance（Arm B）OOS 最差。**1/N 之謎**：等權打敗所有用 μ 的最佳化（DeMiguel 2009）。
- **「Sharpe 1.07」已更正**：那是「最小變異+強股息傾斜」押中 2021–26 防禦/股息因子（期間運氣），**非純最小變異**。純最小變異（Arm C τ=0）Sharpe=0.655。
- **Arm C τ sweep（return_leaning，VT 基準）**：τ=0→Sharpe0.655/winVT36%；τ=0.05→0.691(峰)/66%；τ=0.1→0.666/89%；τ=0.2→0.569/94%；τ=0.5→0.477/98%。**甜蜜區 τ∈[0.05,0.1]**：Sharpe 贏 VT(0.645)與等權(0.622)、回撤 −14%（VT −24.6%）。
- **但 Arm C 報酬輸 VT**：CAGR 10.9–12.1% < VT 13.51%（所有 τ）。「風險≈VT、報酬>VT」未達成。
- **核心觀念（05 §4.9）**：報酬來自承擔系統性風險（risk premia），不來自預測 μ。要偏好報酬 → 報酬導向使用者錨定在前緣右上（高 beta/目標高波動），用風險預算「買 beta」，傾斜改用 beta/因子（比 μ 穩定）。代價：低波動異常下，高報酬必犧牲 Sharpe → 報酬導向使用者「成功」重新定義為「風險上限內最大化絕對報酬」。

## 4. 進行中 / 下一步
- ✅ **多 profile τ sweep 已完成**（結果見 `02`「2026-06-05：多 profile τ sweep（完成）」）。重大結論：trade-off **強烈** profile 依賴——
  - aggressive_growth：τ 傾斜是災難（加風險、CAGR 反降、Sharpe 崩）→ 強力佐證需要 U-C2。
  - balanced：τ 傾斜雙贏（Sharpe+CAGR 同升）；τ=0.3 是全場最佳全方位點。
  - conservative：τ≈0（純最小變異）已最佳。
  - 沒有 profile 在任何 τ 贏過 VT 的 CAGR。
  → **τ 應 profile 依賴：保守→τ≈0、平衡→τ 中高、報酬導向→改走 U-C2（不用排名傾斜）。**
- ✅ **升級 A（偏好→參數映射 g(w)）已完成**（`02`「2026-06-05：升級 A 完成」）：`derive_params_from_weights()` 在 functions.py，backtest 直接 import（單一真理來源）。`core_mode`/`vol_budget` 由 `T_growth=CAGR/(CAGR+Vol+MaxDD)` 決定（核心=要不要買成長風險，不含股息，修正 income 誤分）；`τ=0.30·(1−T_growth)·R̂`（平滑小量級、只編碼方向，量級交 walk-forward）。預設 `USE_PREF_PARAM_MAPPING=False`，不影響 Arm A/C。7 profile 驗收方向全對。
- ✅ **升級 B（U-C2 三核心，Arm "C2"）已實作 + 多 profile 驗證成功**：minvar / market（`min ½wᵀΣw−wᵀc`）/ beta（`max wᵀβ`，β=c/var_bench）。共用 helper `compute_benchmark_cov_vector`、`compute_feasible_vol_budget`（functions.py，backtest import）。只需每日報酬。兩檔同步、各三層 fallback。
- ✅ **vol_budget 改「相對候選池可行波動範圍」**：g(w) 輸出 `risk_fraction`，求解器算 `v_min + frac·(v_max−v_min)`，恆可行（修正無解風險）。`v_max` 用貪婪+多起點（SLSQP 凸最大化會低估，已修）。
- ✅ **`TILT_INCLUDE_CAGR` 預設改 False**（s-sweep 證實 CAGR 排名有害）。
- ✅ **驗證結論**（`06` 報告）：C2 6/7 profile 勝 Arm C；aggressive 8.85→13.80% CAGR（贏 VT）；4 profile CAGR 贏 VT；risk_fraction 掃描證實「能用風險換報酬但 Sharpe 遞減」。
- ✅ **Walk-forward 已完成（2026-06-05，`06` §6.5）**：跨 6 時間窗後**只有 beta 核心 profile 穩健贏 VT 絕對 CAGR**（aggressive 4/6、return_leaning 5/6）；其餘 profile 贏 VT 在 Sharpe/回撤/偏好分數，非絕對報酬。**單期「4 profile 贏 VT」大半是 2021-26 窗運氣，已修正。** 風險換報酬跨規制一致（beta 贏 CAGR 不贏 Sharpe，反之亦然）。lookback lb=2~3 甜蜜區。
- ✅ **偏好分數結構分析 + 資本利得成長獎勵修正**（展示層）：`PREF_SCORE_CAGR_UPPER_Q=0.999` 放寬上尾 winsorize；最佳化器(noCAGR)代數上不受影響（已驗證）。
- ⏳ **排隊實驗執行中**（noCAGR vs full 跨區、risk_fraction 跨區、DCA 定期定額）→ 結果待分析。
- ✅ **排隊實驗完成**（`06` §6.6）：Exp4 強化 U-C2（風險換報酬跨規制穩健）；Exp3 第二更正（noCAGR vs full 跨區 wash）；Exp5 DCA（不改風險屬性、多頭單筆贏、DCA 降離散度但也降報酬，宜用 IRR 重測）。
- ✅ **TILT_INCLUDE_CAGR 決議**：保留為可切換旗標、不強制預設（跨區 wash），nominal=False。
- ✅ **beta 錨解耦 + VT vs VTI 實驗**（`02`/`06` §6.7）：新增 `BETA_ANCHOR_TICKER`（預設 None=VT）。結論：換 VTI 對「報酬導向 vs 保守」價差是弱槓桿（候選池幾乎全美國，beta 排序幾乎不變；熊市還更糟）→ **錨維持 VT**。真正的價差槓桿是 risk_fraction 映射 + 核心類型，非錨。
- ✅ **偏好分數「報酬維度」改用 beta 評分（已採用為預設）**（`02` 2026-06-05 連續多筆）：`PREF_RETURN_BASIS="beta"`，報酬分數=`0.5+0.5·clip((beta−1)/(REF−1),0,1)`（市場=0.5、低 beta 不懲罰、beta=REF→1.0）。**只動展示/評估分數(win_VT)，求解器完全未動**（backtest `calculate_portfolio_utility` 與主系統 `calc_utility(for_display=True)`；objective 仍 CAGR）。效果：報酬導向 win_VT 大跳（aggressive 13.6→67.8/5.6→47.2、對 EW/MS ~100%），且每個 profile 不降反升（conservative 57.6→64.4）。主系統已同步並驗證(0.7027→0.5907)。CAGR 仍保留供 V-1。
- ✅ **品質約束 OAT 完成 → 硬品質約束無益（`02` 2026-06-05 收尾 / `07`）**：系統化框架(可行範圍+偏好 tightness，中性點=品質維度平均)已實作(`build_quality_constraints` 等，兩檔同步)，但 OAT off/on 證明：成本=有害、HHI=多餘、流動性=inert、情緒=跳過。**決議全關 `QC_ENABLE_*=False`**；品質由軟傾斜(User_Pref_Score)+DEA+核心處理。框架保留備用。系統現況 C2 約束僅 Σw=1+界內+vol_budget。
- ✅ **win_VT 偏低已解**：改用 beta 評分後報酬導向 win_VT 大跳（見前）。
- ✅ **Black-Litterman 路(a) 完成（`08`）**：實作 `OPTIMIZATION_ARM="BL"`（統一目標,與 C2 並存）。A/B 結論：beta 端 BL==C2;**minvar/market 端統一 BL 更差**（給定風險預算下衝 beta → 推向市場、win_VT 崩,balanced 80→0、conservative 60→5）。**決議：維持三核心 C2 為運作設計;BL 當理論正名(Π=CAPM 市場隱含報酬,三核心=BL 不同風險趨避的效率前緣點)+ 消融對照。** 路(b)因子觀點=未來展望。
- **敘事(論述用)**：以 BL 為理論基礎開發統一模式 → 發現市場/保守型在「給定風險預算下追 beta」結果變差、偏好分數大降 → 故用三核心解決（三核心=BL 前緣不同風險趨避點）。
- ✅ **「衝報酬 Sharpe 遞減」張力收尾（`02`）**：試封 rf 上限 0.6 → 驗證反而 CAGR↓/回撤更深/Sharpe 略↓（vol 約束≠回撤控制；先前建議過度套用多頭窗）→ 還原 `RISK_FRACTION_MAX=0.95`。結論：張力是低波動異常本質、無免費修法,報酬導向維持高 rf（最大絕對報酬,低 Sharpe 為誠實代價）。若要控回撤,正解=MaxDD 約束（未來）。
- ✅ **DCA 公平重測完成（`02`）**：用 XIRR(金額加權) + 跨起始點離散度。修正 Exp5 假象(DCA 公平基礎上反略勝,但路徑依賴);**但「DCA 降進場時機風險/高成長更受益」假設未獲支持**(離散度未降、高波動未更受益)。結論:DCA≈路徑依賴平手,可當選項不宣稱系統性效益。
- **演算法線 + 品質約束 + rf + BL + DCA 全部告一段落。** 後續可選:walk-forward 多視窗最終驗證(月度)、MaxDD 約束(若要控報酬導向回撤)、路(b)因子觀點、Gemini 主動偏好。
- 腳本：`_verify_gw_mapping.py`、`_smoke_c2.py`、`_s_sweep.py`、`_c2_experiment.py`、`_walkforward.py`、`_queued_experiments.py`。
- **穩健性**：演算法定案後跑多 lookback × 多 time window walk-forward（目前只有單一路徑，所有數字僅指示性）。
- 方法論：單參數/OAT sweep，**不做大網格**（過擬合）。

## 5. Gotchas
- 跑完任何 ARM=B/C 或改參數的實驗後，**把 `OPTIMIZATION_ARM` 還原成 "A"**。
- Windows cp950 主控台對 log 裡 emoji 會噴 `UnicodeEncodeError`（非致命，被 logging 攔截）；跑指令加 `PYTHONIOENCODING=utf-8`。
- 跑回測前確認快取存在：`csv/backtest_close_price_db.csv` 等、`csv/stage0_final_matrix.csv`、`json/stage2_ahp_global_weights.json`、`sentiment_engine/data/sentiment_daily_cache.csv`（`fetch_missing_data=False` 用快取）。
- 多 profile sweep 會暫時改寫 `json/stage2_ahp_global_weights.json`，腳本結束會還原（注意若中斷需手動還原成 return_leaning 權重）。
- **網頁版 app 跑在埠 8050**（5000 常被 Intel OneApp.IGCC 顯卡服務佔走）；同一埠跨多次 build → 瀏覽器靠網址快取 `static/app.js`，會發生「改了卻看到舊版」。後端其實正常（live `/api/pref/answer` 確有回 `last_turn`）。**臨時解：Ctrl+Shift+R 硬重載 / 關分頁開新分頁 / 無痕。永久解（2026-06-08）：`etf_web/app.py` 加 `asset_v()` context processor + `index.html` 對 style.css/app.js 加 `?v={mtime}` 版本號，檔案一變網址就變、瀏覽器強制重抓。此修正需重建 exe 後對凍結版生效。**
- **BUG 修正（2026-06-08）：範例偏好一鍵帶入時不顯示每題 μ/σ/gate 回饋。** 根因：`etf_web/static/app.js` 的 `runPreset()` 只取回應 `.action`、丟掉 `last_turn`（手動 `submitAnswer` 正常）。修法：抽出共用函式 `renderTurnFeedback(lt)`，手動與範例兩流程共用；`runPreset` 改為接完整回應並每題呼叫之。已熱更新到 `etf_build/dist/.../_internal/etf_web/static/app.js`（Flask static 即時讀磁碟，故現跑的 exe 已生效）。**待辦：重建 exe + 重壓 zip 才能把此修正與 `?v=` 防快取一起帶進可分發版。**
