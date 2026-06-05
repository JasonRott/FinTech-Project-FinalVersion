# 預計升級項目清單（程式碼稽核後重寫版）

建立日期：2026-06-04（取代 2026-06-04 初版）  
狀態：候選清單，皆尚未批准實作  
依據：已完整閱讀 `functions.py` 與 `backtest_engine.py` 最佳化核心後重寫

---

## 0. 重大認知更正（讀完程式碼後）

初版清單寫於閱讀程式碼之前，沿用了 `01_legacy_algorithm_report.md` 的描述，有兩個關鍵誤解，這裡更正：

### 0.1 風險量測本來就是「真實投組層級」，不是天真加權

`functions.py:2529` 與 `backtest_engine.py:1195`：

```python
port_vol = np.sqrt(np.dot(w.T, np.dot(cov_matrix_annual, w)))   # 真實共變異數投組波動率
true_maxdd_score = calculate_true_maxdd_score(...)              # 真實 buy-and-hold NAV 路徑回撤
```

波動率是 `wᵀΣw`，MaxDD 是真實 NAV 路徑算的，HHI 是真實 `1−Σexposure²`。**這三個維度的量測是正確的、不需要改。**

### 0.2 真正的根因是「報酬側」而非「風險側」

`functions.py:2501`：

```python
port_cagr = np.dot(w, vec_cagr)   # vec_cagr 是每檔 ETF CAGR 的 [0,1] 排名分數，不是真實報酬
```

**不對稱問題**：風險側給最佳化器的是真金白銀的凸性數學好處（分散化降低 `wᵀΣw`），報酬側給的只是排名分數的線性加權。最佳化器永遠覺得「壓低風險」比「衝高報酬」划算，因為報酬側根本沒有真實報酬的訊號。這才是「報酬導向使用者拉不高 CAGR」的結構性主因。

→ 升級重心從「改風險」轉為「修報酬側 + 把風險改成約束」。

### 0.3 目標重新定義：樣本外回測成績，而非樣本內偏好分數

主系統只能對「過去一段 lookback 期間」求最佳解，看不到未來，這是所有投資推薦的本質限制。
因此**升級的成敗標準是 `backtest_engine.py` 的樣本外（out-of-sample, OOS）成績**，不是樣本內偏好分數。任何改動都要用 rolling backtest 驗證 OOS 報酬/Sharpe/MaxDD，而不是只看偏好分數有沒有變高。

### 0.4 主系統與回測目前完全同邏輯（必須維持）

已逐行確認：偏好最佳化與 Max Sharpe 對照組在 `functions.py` 與 `backtest_engine.py` 數學完全一致。
**鐵律：任何效用函數、風險、候選池、權重限制的改動，兩個檔案必須同步修改並各自驗證。**

---

## 1. 升級項目（依槓桿排序）

每個項目標註：對應稽核發現（F 編號，見 `04`）、要改的檔案、用什麼 OOS 指標驗證。

> **演算法升級策略決議（2026-06-04，使用者確認）：兩臂賽馬。**
> Arm A = 現有線性加權偏好分數（baseline，保留不刪）；Arm B = U-1+U-2 合成的「受約束均值-變異數 + 風險預算」。
> U-1 與 U-2 不是兩個競爭演算法，而是同一個新目標函數的報酬側與風險側。
> 用 rolling backtest 的 OOS 指標 + V-1/V-6 偏好分數 OOS 勝率當裁判，避免 overfit 單一想法。必要時再加 Arm C。

### U-1 ★最高★：報酬項改用真實期望報酬（修 F1）

問題：效用函數報酬項是排名分數 proxy，與真實報酬脫鉤，且和風險側不對稱。

方向：
- 把 `vec_cagr`（排名分數）換成真實年化報酬向量。`functions.py:2570` 的 `annual_returns_array` 已經算好，回測 `optimize_max_sharpe_portfolio` 也有同樣的 `annual_returns`，可直接重用。
- 為了與其他維度尺度可比，對真實報酬向量做一致的正規化（例如同一把 robust_scale，或改用「報酬 − rf」的線性尺度）。
- 進一步：考慮把報酬項與風險項組成 mean-variance 形式 `E[r] − (λ/2)·Var`，讓 λ 由使用者風格（報酬導向→小 λ）決定。

預期 OOS 效果：報酬導向使用者的回測 CAGR 應該拉開，代價是波動上升（可由 U-2 控制）。

影響檔案：`functions.py`（calc_utility）、`backtest_engine.py`（optimize_preference_portfolio.calc_utility、calculate_portfolio_utility）

驗證：rolling backtest 比較改前/改後的 OOS CAGR、Sharpe、MaxDD；報酬導向 user 應 OOS CAGR↑。

---

### U-2 ★高★：風險改為約束（風險預算），取代低波動加分（修 F5，整合舊 P-02/P-06）

問題：波動以 `1−penalty` 當加分項，floor/cap 8%/30% 對所有使用者一致，持續把報酬導向使用者拉回保守。

方向：
- 報酬導向使用者：把波動/回撤從效用「加分」改成「約束」：
  ```
  maximize  報酬偏好效用
  s.t.      portfolio vol  ≤ user risk budget
            portfolio MaxDD ≤ user drawdown budget
  ```
- 在 SLSQP 加 `ineq` 約束即可（`vol_budget − √(wᵀΣw) ≥ 0`）。
- 保守型使用者：維持現有加分或用更緊的 budget。
- 風險預算數值依使用者風格分層（整合舊 P-06：保守 18% / 平衡 30% / 成長 45%）。

預期 OOS 效果：報酬導向可承擔更高波動換更高報酬，但有明確上限保護。

影響檔案：`functions.py`、`backtest_engine.py`、`parameters.py`（新增 risk budget 參數）

驗證：rolling backtest 確認 OOS 波動落在 budget 內、報酬導向 CAGR 提升。

---

### U-3 ★高、低成本★：DEA 報酬產出不該砍半成長股 + rescue list（修 F3，整合舊 P-01）

問題：
- `Out_Return = (CAGR + Div)/2`（`functions.py:1213`、`backtest:689`）把高成長零配息 ETF 的報酬產出稀釋一半。
- DEA 0.80 門檻可能過早殺掉高報酬高風險 ETF。

方向：
- 重新檢視 `Out_Return` 的 CAGR/Div 混合比例，或依使用者風格調整（報酬導向 → CAGR 權重高）。
- DEA 後保留通過者，額外救回使用者最重視維度（報酬導向 → `Return_CAGR` 或 return composite）前 N 名 ETF 進候選池。

預期 OOS 效果：候選池納入更多高成長標的，給 U-1 更多施展空間。

影響檔案：`functions.py`（build_dea_ready 的 Out_Return、Stage 1 後處理）、`backtest_engine.py`（build_dea_ready_matrix、候選池組裝）

驗證：比較 rescue 前後候選池成長股數量與 OOS CAGR。

---

### U-4 ★中★：延後/軟化相關性分群（整合舊 P-04，與 F6 相關）

問題：Stage 2_2 用 `User_Pref_Score.idxmax()` 每群選一檔，可能丟掉群內高報酬者；`CORR_THRESHOLD=0.99` 太高反而幾乎不觸發。

方向：
- 方案 A：延後分群，讓 optimizer 看到完整候選池，用相關性懲罰或持股數約束處理重複。
- 方案 B：群內挑代表時，對報酬導向使用者改用報酬而非綜合偏好分數。

影響檔案：`functions.py`（run_stage2_5...）、`backtest_engine.py`（select_cluster_representatives）

驗證：OOS 分散度與報酬權衡。

---

### U-5 ★中★：主目標與輔助品質拆分（整合舊 P-05，與 F1/F2 相關）

問題：9 維等權線性加總，且尺度不一致（6 維排名分數 vs 3 維真實投組值），輔助維度稀釋報酬主目標。

方向：
- 報酬（CAGR、Div）為主目標進效用函數。
- 成本、流動性、分散、情緒改為門檻篩選或懲罰，不與報酬等權相加。

影響檔案：`functions.py`、`backtest_engine.py`

驗證：OOS 報酬是否提升而品質維度仍在可接受範圍。

---

### U-6 ★低★：cross/super-efficiency 是否接上管線（釐清 F4）

問題：cross-efficiency 與 super-efficiency 都算了，但候選池實際只用「標準 DEA ≥ 0.80」門檻；cross_score 只排序不篩選。

方向：先決定這兩個 DEA 變體是要（a）純資訊性輸出（現況，標註清楚），還是（b）真的當篩選條件接上下游。主系統與回測要做同樣決定。

影響檔案：`functions.py`、`backtest_engine.py`

---

### U-7 ★低、清理★：穩健性與一致性（F7/F8/F9/F10）

- F7：Max Sharpe 對照組也被 40% cap 約束 → 報表/命名標註清楚這是「受約束 Max Sharpe」。
- F8：AHP 特徵向量加 `abs()` 或強制符號，避免罕見負權重。
- F9：兩套 scaler（`custom_minmax_scaler` [0.1,1] vs `robust_scale` [0,1]）並存 → 文件標註用途，避免未來改錯。
- F10：無風險利率 0.04 移到 `parameters.py`（回測已用 config，主系統仍硬編碼 → 統一來源）。

---

## 1.05 U-C2：profile-dependent 穩健核心（讓報酬導向使用者「往上爬」）— 待實作

狀態：提案，待目前 Arm C 基底與多 profile 驗證完成後實作  
動機：Arm C 的最小變異核心對報酬導向使用者無法「用風險換報酬」（坐在前緣左下角 + 排名傾斜不具預測性）。詳見 `05` §4.9。

### 設計（核心 profile-dependent）
```
保守型:   min wᵀΣw                                   （最小變異）
平衡型:   ≈ 市場組合（beta≈1）
報酬導向: max 市場/因子曝險  s.t. vol ≤ 較高風險預算（目標值，非最小化）
+ 偏好傾斜 τ·(wᵀs)  + 品質約束（沿用 Arm C）
```
- 「市場/因子曝險」用**比 μ 穩定的訊號**：對 VT 回歸的 beta、或規模/價值/動能/品質因子；**不碰個別 μ**。
- 風險預算從「壓低」改為「目標值」：報酬導向設高（15–20%），逼最佳化器用掉風險額度買 beta。
- 報酬導向使用者「成功」定義改為「風險上限內最大化絕對報酬」，**允許 Sharpe 低於 VT**（低波動異常下，高報酬必然犧牲 Sharpe）。

### 待決
- ~~beta/因子曝險的具體估法與資料來源~~ → **已定案（2026-06-05）：第一版用單一 beta vs VT**（對 VT 日報酬時間序列回歸 `βᵢ=Cov(rᵢ,r_VT)/Var(r_VT)`，lookback 視窗內估）。多因子留待單一 beta 證明「買 beta」可行後再加（避免單一路徑 overfit）。
- ~~profile → 核心類型 / 風險預算的映射~~ → **已定案（2026-06-05）：用權重向量函數 g(w)，先做（見下方「鎖定設置」）。**
- 是否與 Black-Litterman 整合（BL 先驗=市場、觀點=因子加碼）。

### 鎖定設置（2026-06-05，使用者確認，依此實作）

**實作順序：先 g(w) → 再 U-C2 核心。**

**升級 A：偏好→參數映射 `g(w)`（前置，先做）**
- 彙總指標（輸入 9 維正規化 global_weights）：
  - `R = w[Return_CAGR] + w[Return_Div]`（報酬總渴望）
  - `T = R / (R + w[Risk_Vol] + w[Risk_MaxDD] + 1e-9)`（報酬 vs 風險相對偏好，對尺度穩健）
- 映射（連續、單調）：
  - 核心類型：`T<0.40`→最小變異；`0.40≤T<0.65`→市場；`T≥0.65`→因子(beta)曝險。
  - `vol_budget = clip(0.10 + 0.40·T, 0.10, 0.45)`。
  - `τ = 0.30·(1−T)·R̂`（R̂ = R 的 min-max 正規化）→ **保守大、報酬導向趨近 0**（編碼 sweep 結論：傾斜對報酬導向有害）。
  - 成本預算分位 0.75、HHI 上限 0.50（暫固定，後續 OAT 調）。
- 落點：`parameters.py` 加 `USE_PREF_PARAM_MAPPING` + 係數常數；`functions.py`、`backtest_engine.py` 各加 `derive_params_from_weights(global_weights)` helper（**兩邊數值完全一致**）。
- 驗收：印出 7 個 profile 的 (R, T, 核心類型, vol_budget, τ)，人工確認映射方向合理（aggressive→因子核心/τ≈0；conservative→最小變異/τ 大）。

**升級 B：U-C2 profile-dependent 核心（主升級）**
```
保守(T<0.40):     min ½wᵀΣw                    − τ·wᵀs        最小變異核心
平衡(0.40–0.65):  min ½wᵀΣw − wᵀc              − τ·wᵀs        對 VT 報酬流最小化追蹤誤差
報酬導向(T≥0.65): max wᵀβ                       + τ·wᵀs        beta 曝險
                  s.t. √(wᵀΣw) ≤ vol_budget（目標值，逼近非最小化）
共同約束: Σw=1, 0≤wᵢ≤cap, 成本≤分位, HHI≤上限
```
- **三核心只需「每日報酬」即可，不需任何成分權重。** 共用原料：`Σ`=ETF 共變異（Ledoit-Wolf）、`c`=各 ETF 對 VT 的共變異向量 `cᵢ=Cov(rᵢ,r_VT)`。
- 平衡型 `min ½wᵀΣw − wᵀc` 等價於 `min Var(r_p − r_VT)`（對 VT 報酬流的追蹤誤差²，丟常數），用真實 VT 報酬流，非池內等權代理。
- β = `c / σ²_VT`（即對 VT 回歸的 beta，單一 beta 第一版）；主系統 Stage 0 加 `beta_vs_benchmark` 欄或現算，回測直接用價格序列算。
- 報酬導向「成功」= 風險上限內最大化絕對報酬，**允許 Sharpe < VT**（低波動異常下高報酬必犧牲 Sharpe，報表明講）。
- 開關：`parameters.py` `OPTIMIZATION_ARM` 增加 `"C2"`；`functions.py` Stage 3 與 `backtest_engine.py` `optimize_preference_portfolio` 各加三分支（**鐵律：兩邊同步**）。
- 驗收（多 profile rolling backtest）：aggressive_growth 在 C2 下 CAGR 須 > Arm C 的 ~9%、逼近/超過 VT 13.51%（C2 存在的唯一理由）；balanced/conservative 不得低於 Arm C 甜蜜點。

## 1.2 Arm B 結構鎖定進度（2026-06-04 討論決議）

### 已實作
- 目標函數：mean-variance + 風險預算約束，算術 μ。
- μ 報酬組成：資本利得（算術年化）+ **殖利率依偏好比例加權**（`Return_Div/Return_CAGR`，預設 0.25）。
- 求解器報酬一律算術平均（Max Sharpe + Arm B），視覺化/雷達/MPT 同步算術，報表保留兩口徑。
- **DEA 選項 A**：`Out_Return` 拆成 `Out_CAGR` + `Out_Div` 兩個獨立產出（兩邊同步），成長股不再被股息平均稀釋。

### 已決議但未實作
- **#3 下檔風險取代變異數**（報酬導向使用者）：用 CVaR／半變異數／MaxDD 取代 wᵀΣw。已有 true MaxDD 機器，可行且不麻煩。狀態：待實作。
- **#5 相關性 0.99 維持不變**：0.99 幾乎等於追蹤同一指數，去重合理、極少誤刪。決議：不動。
- **交易成本：暫不加入**（演算法本身未穩定前加入只會更差）。
- **超參數搜索清單**：λ、波動預算、單檔上限（#6）、rebalance 頻率、lookback 長度。

### 待討論/待確認
- **DEA 門檻 0.8**：選項 A 後成長股 DEA 分數自然提高，候選池會變化；先看 A 後的池子再決定是否調門檻。
- **Rescue list**：DEA 後額外救回 CAGR 前 N 名，待 A 後評估是否仍需要。
- **DEA 其他構思**：(a) 用 cross-efficiency 當篩選閘門（目前算了沒用，F4）；(b) 百分位門檻取代絕對 0.8；(c) 風險作為 DEA input 的根本問題（Arm B 已有風險預算，DEA 是否該退為品質閘門）。

### V-7 新視覺化（使用者要求，待實作）
偏好分數 vs 使用者最在意（前 1~2 名）維度分數的散佈圖，檢查是否正相關（偏好分數是否真由使用者最重視的維度驅動）。

### 估計品質升級（我的優先建議，待實作）
- **Ledoit-Wolf 共變異數收縮**（高 CP 值，常比調 λ 更能提升 OOS Sharpe）。
- μ 估計改善（樣本平均雜訊大）。
- **Black-Litterman**：可直接 drop-in 取代 μ（求解器結構不變），是偏好整合（#3 映射）的天然框架；待現有架構優化後實作。

## 1.1 Arm C 完整設計（2026-06-05，待實作）

由 μ-free 最小變異實驗演化而來（注意：先前誤把含股息傾斜的 Sharpe 1.07 當成純最小變異；純最小變異 Arm C τ=0 實為 0.655，τ sweep 後 Arm C 穩健區間約 0.65–0.69）。核心：**最小變異穩健核心 + 偏好傾斜 + 偏好約束 + 偏好強度旋鈕**，用排名式偏好分數當傾斜目標以避開噪音 μ。

### 目標函數
```
min_w   (1/2)·wᵀΣw  −  τ·(wᵀs)
```
- Σ = Ledoit-Wolf 收縮共變異數
- s = 每檔 ETF 偏好分數向量（排名式 [0,1]，AHP 加權）
- τ = 偏好強度旋鈕：τ=0 純最小變異（Sharpe≈0.655、偏好低）；τ↑ 越往高偏好傾斜（偏好↑、Sharpe 視 profile 而定）。即「財務效率 ↔ 偏好滿足」Pareto 旋鈕（注意：trade-off 形狀與 profile 有關，見 05）

### 約束
- `Σwᵢ=1`、`0≤wᵢ≤cap`
- 風險預算 `√(wᵀΣw) ≤ vol_budget`
- **(b) 品質約束 v1 只加兩個：成本上限 `w·成本 ≤ 成本預算`、分散上限 `投組HHI ≤ 上限`**
- **最終目標：把全部維度（流動性下限、情緒等）都加成約束**，逐一加入並記錄 OOS 影響

### 凸性
Σ 半正定 → 凸 QP，SLSQP 可解；約束皆線性/簡單。

### 偏好三層進入
1. 篩選層：DEA 取前25% + 分群（已有）
2. 傾斜層：`τ·(wᵀs)`（報酬導向→拉向高報酬排名；保守型→拉向低風險/低成本）
3. 約束層：(b) 品質門檻

### 待 sweep 的旋鈕（先建行為地圖，再設計偏好→參數映射）
τ ∈ {0, 0.01, 0.05, 0.1, 0.5}；vol_budget；cap（#6）；各約束門檻。

### 決議：傾斜目標 s 要不要含資本利得排名（#1 的問題）
- 事實：`User_Pref_Score` 含 `Norm_Return_CAGR`，故資本利得噪音會經 `Σ⁻¹·s` 流進求解器（光有界不能完全免疫）。
- 但比原始 μ 大幅馴服：排名+縮尾（無離群主導）、僅 s 的一部分、τ 控制幅度、Ledoit-Wolf Σ 良態 → 不會重演 v2 災難。
- 深層誠實：資本利得排名不預測未來報酬（V-1 右圖 r≈0），傾斜它=「符合使用者嘴上要的」而非「真能多賺」。
- **決議：sweep 兩版傾斜目標 `s_full`（含 CAGR 排名）vs `s_noCAGR`（去掉 CAGR 排名），用 OOS 決定。**

## 1.5 偏好分數的重新定位（專案特色的保留方式）

決策（2026-06-04）：偏好分數是本專案的核心特色，升級時**保留但重新定位**，分開它的兩個角色：

| 角色 | 現況 | 升級後 |
|---|---|---|
| 當最佳化器目標函數 | 是（F1 數學弱點在此）| 降級 → 改用 mean-variance / 風險預算（U-1/U-2）|
| 當偏好提取 + OOS 評估指標 | 未充分發揮 | 升級 → V-1 / V-6 的主角，論文招牌 |

升級後仍是「偏好驅動」：偏好改去設定最佳化器參數（報酬傾斜、風險預算、λ），符合文獻兩層式架構。偏好分數成為 OOS 驗證指標，賣點從「事前分數較高（同義反覆）」變成「X% 的樣本外期間照系統買，事後偏好分數真的贏過大盤」。

## 2. 視覺化升級項目（充分利用回測引擎）

現況稽核（見 `04` 附錄）：回測其實已輸出約 10 張圖（NAV+回撤、年報酬、權重演化、分布網格、DEA 分布）。
- 2026-06-04：**雷達圖 `_plot_backtest_radar` 已從輸出移除**（函式保留為 dormant，待以偏好分數為核心重新設計後重用）。
- `_plot_final_period_frontiers`（含 8000 次蒙地卡羅）**定義了卻沒被呼叫**，是死碼（V-5）。

真正缺的是「能證明系統 OOS 有效」、且以偏好分數為核心的圖。**好消息：V-1 與 V-6 的資料 `preference_scores_df` 已 100% 算好並存成 `{prefix}_preference_scores.csv`，純畫圖工作，不碰演算法、不影響主系統/回測一致性。**

資料欄位（`backtest_engine.py:2206-2235`，逐再平衡期）：
- `Portfolio_ExAnte_Preference_Score`：用過去 lookback 算的分數（最佳化器看到的，必然較高）
- `Portfolio_Forward_Preference_Score`：同投組用未來實際資料重算（不保證較高）
- `VOO_Forward / EqualWeight_Forward / MaxSharpe_Forward_Preference_Score`
- `Forward_Score_vs_VOO / EqualWeight / MaxSharpe`、各策略 `Forward_Return`

### V-1 ✅ 已實作（2026-06-04）：偏好分數 vs 未來結果 散佈圖（驗證偏好分數的預測力）

實作：`backtest_engine.py:_plot_preference_predictive_scatter`，輸出 `{prefix}_preference_predictive_scatter.png`。依使用者決議做兩個 Y 軸：左圖 Y=事後偏好分數（profile-adaptive）、右圖 Y=未來報酬（報酬導向視角）。


每個再平衡期 = 一個點。X 軸 = 事前偏好分數（`Portfolio_ExAnte_Preference_Score`）；Y 軸 = 該投組未來實際報酬（`Forward_Period_Return`）。加回歸線 + 標 R²/相關係數。
- 點雲右上傾斜（正相關）→ 偏好分數是真有用的 OOS 訊號（特色站得住腳，論文最強證據）。
- 點雲平/亂（無相關）→ 用數據證明需要 U-1（排名分數轉真實報酬）。
資料已算好，只差畫出來。

### V-6 ✅ 已實作（2026-06-04）：隨時間變化的偏好分數圖（使用者要求，保留專案特色）

實作：`backtest_engine.py:_plot_preference_score_timeseries`，輸出 `{prefix}_preference_score_timeseries.png`（含 V-6a/b/c）。

核心訊息：照系統推薦買，事後（OOS）偏好分數真的有比其他組合高嗎？誠實呈現「有時候輸」。

- **V-6a 時間序列折線（主圖）**：X = 評價日期，4 條線 = `Portfolio_Forward` / `VOO_Forward` / `EqualWeight_Forward` / `MaxSharpe_Forward` 的偏好分數。一眼看出每期照系統買的事後偏好分數排名。
- **V-6b 事前 vs 事後落差**：`Portfolio_ExAnte`（必然高）vs `Portfolio_Forward`（不一定高）兩條線，差距 = 偏好分數的樣本外衰減，把「下一段不一定比較高」視覺化、量化。
- **V-6c OOS 勝率（標題數字）**：照系統買的事後偏好分數 > VOO/等權/MaxSharpe 的期間占比。專案特色的誠實版頭條：「X% 樣本外期間，照推薦買實際偏好分數贏過大盤」。

資料（`Portfolio_ExAnte/Forward`、各 benchmark forward、`Forward_Score_vs_*`）全部已存在 CSV，純畫圖工作。

### V-2 ★高★：逐維度 OOS 貢獻分解
`period_dimension_df` 有每個維度的逐期分數。畫成堆疊面積/折線，看哪個維度長期真的帶來 OOS 報酬、哪個只是稀釋。直接支撐 U-5 的拆分決策。

### V-3 ★中★：策略 vs benchmark 的滾動超額報酬 / 滾動 Sharpe
用既有 NAV 算 12 個月滾動超額報酬與滾動 Sharpe，看系統在不同市場環境（多頭/空頭/震盪）的穩定度。

### V-4 ★中★：換手率與成本侵蝕
`_calc_turnover` 已存在但沒畫。畫逐期換手率，並估算交易成本對 OOS 報酬的侵蝕。

### V-5 ★低★：清理 `_plot_final_period_frontiers`
要嘛接上呼叫並移除蒙地卡羅（保留數學解析 frontier），要嘛刪除死碼。主系統與回測的 frontier 邏輯要一致。

---

## 3. 建議啟動順序

1. **U-1 + U-2**（報酬真實化 + 風險預算）—— 打中根因，直接衝 OOS 報酬。
2. **V-1**（偏好分數 vs 未來報酬散佈圖）—— 先建立 OOS 驗證的「儀表板」，這樣 U-1/U-2 改完才有客觀的好壞判準。
3. **U-3**（DEA 報酬不砍半 + rescue list）—— 低成本擴大候選池。
4. 其餘 U-4 ~ U-7、V-2 ~ V-5 視結果排序。

> 注意：每個 U 項目都必須同步改 `functions.py` 與 `backtest_engine.py` 並各自 `py_compile` + 跑驗證。

---

## 已合併/取代

- 舊 P-01 → U-3；舊 P-02 → U-2；舊 P-03（權重上限分層）→ 併入 U-2 風險預算；舊 P-04 → U-4；舊 P-05 → U-5；舊 P-06 → 併入 U-2；舊 P-07（主動偏好學習）→ 本輪暫不延伸，移出本清單。
