# 品質約束系統化重設計（設計文件）

建立：2026-06-05　**狀態：已實作 + OAT 驗證完畢 → 結論「硬品質約束無益，預設全關」**　範圍：C2（及 Arm C）

> ## ★最終結論（2026-06-05，OAT 驗證後）★
> 框架已實作（helper 全套 + 兩檔同步），並用 OAT off/on 對照驗證：
> - **OAT-1 成本**：咬到就有害（扭曲投組、跟主偏好打架）。
> - **OAT-2 HHI**：多餘（投組本來就夠分散，不綁定）。
> - **OAT-3 流動性**：完全 inert（每格 off==on 相同）。
> - **OAT-4 情緒**：跳過（同為逐檔線性、資料不穩）。
> **→ 硬品質約束對本系統無價值。品質由「軟傾斜(User_Pref_Score 含 9 維) + DEA 篩選 + 核心(分散自然湧現)」處理已足夠。**
> **決議：所有 `QC_ENABLE_*=False`（框架保留備用、預設全關）。** 詳見 `02` 2026-06-05 OAT 收尾。
> 以下為原始設計（保留供參考/未來若候選池/核心改變需重新評估時使用）。

---

## 0. 問題

現況品質約束是手拍的魔術數字、無系統性、與偏好無關、不保證可行：
- `COST_BUDGET_QUANTILE = 0.75`（成本 ≤ 候選池費用率第 75 百分位）
- `HHI_CEILING = 0.50`（投組產業 HHI ≤ 0.50；池子集中時可能無解）

目標：用**一條原則**統一所有品質約束，使其偏好驅動、池子相對、恆可行。

---

## 1. 核心原則（把 vol_budget 的「相對可行範圍」推廣到所有品質維度）

> **每個品質約束的門檻 = 放在「該維度在當期候選池的可行範圍 [v_min, v_max]」之內，
> 位置由「使用者對該維度的偏好權重」決定。**

`v_min / v_max` = 在約束集（`Σw=1, 0≤wᵢ≤cap`）下，該維度投組值可達到的最小/最大。
→ 門檻恆落在可行範圍內 → **永不無解**；隨候選池浮動 → **池子相對**；位置由偏好決定 → **偏好驅動**。

這與 `compute_feasible_vol_budget`（風險預算）完全同一套哲學，整個求解器的「預算/門檻」邏輯一致。

---

## 2. 偏好強度 tightness（中性點 = 該使用者品質維度的平均權重）★已定案 §7-1★

使用者選擇：用「品質維度平均」當中性點（而非全域 1/9），讓約束更容易綁定。
- 品質 5 個 slot：`Cost_ExpRatio, Div_Score, Liq_Volume, Liq_AUM, FinBERT_score`。
- `neutral = mean(這 5 個 slot 權重)`（per-user）。
- 各約束維度與中性點比較（**per-slot 公平**：流動性是 2 個 slot，故除以 2 再比）：

```
ratio_cost = w_cost / neutral
ratio_hhi  = w_div  / neutral
ratio_sent = w_finbert / neutral
ratio_liq  = (w_liq_vol + w_liq_aum) / (2·neutral)        # 2-slot → per-slot 比較
tightness_q = clip( (ratio_q − 1) / (FULL_RATIO − 1), 0, 1 )      # 預設 FULL_RATIO = 2.0
```
- `ratio_q = 1`（剛好等於品質平均）→ tightness 0（不綁定）；`ratio_q = FULL_RATIO` → 1（最緊）。
- 低於品質平均 → 自動關閉（不需開關）。

### 各 profile 的 tightness 試算（FULL_RATIO=2；neutral=該 profile 品質 5-slot 平均）

| profile | neutral | 成本 ts | HHI(Div) ts | 流動性 ts | 情緒 ts |
|---|---|---|---|---|---|
| aggressive_growth | 0.070 | 0 | **0.43** | 0 | **0.43** |
| return_leaning | 0.060 | **0.67** | 0.17 | 0 | 0 |
| balanced | 0.076 | **0.32** | **0.71** | 0 | 0 |
| conservative | 0.060 | **0.67** | **0.33** | 0 | 0 |
| income | 0.056 | **0.79** | **0.43** | 0 | 0 |
| cost_liquidity | 0.104 | **1.00** | 0 | 0.06 | 0 |
| diversified_quality | 0.106 | 0 | **0.89** | 0 | **0.42** |

（實際 `quality_tightness_map` 計算值；成本約束 5/7 profile 觸發、HHI 6/7、情緒 2/7、流動性僅 cost_liquidity 輕微。）

→ **比 1/9 版本明顯更多約束被綁定**（達成使用者意圖）。各維度仍只在「該使用者相對更重視它」時收緊。
（cost_liquidity 的流動性只 0.06：因其 cost 0.22 拉高了自身品質平均，per-slot 看它更重視成本 > 流動性 → 誠實反映權重。）

DEA 篩選仍負責「基線品質」；本層是「偏好強調層」(在基線之上依偏好加緊)。

---

## 3. 各維度規格

| 維度 | 偏好權重 | 方向 | 投組值 f(w) | 可行範圍算法 |
|---|---|---|---|---|
| 成本 | `Cost_ExpRatio` | ≤(越低越好) | `w·cost_vec` | 線性 → 貪婪封閉解 |
| 分散 HHI | `Div_Score` | ≤(越低越好) | `Σ_k (w·S_k)²` | min：解凸 QP；max：貪婪集中 |
| 流動性(合併) | `Liq_Volume+Liq_AUM` | ≥(越高越好) | `w·liq_composite` | 線性 → 貪婪封閉解 |
| 情緒 | `FinBERT_score` | ≥(越高越好) | `w·sent_vec` | 線性 → 貪婪封閉解 |

### 門檻公式（依方向放在可行範圍內）
```
越低越好(成本、HHI):  threshold = v_min + (1 − tightness)·(v_max − v_min)
越高越好(流動性、情緒): threshold = v_max − (1 − tightness)·(v_max − v_min)
約束:  越低越好 → f(w) ≤ threshold ;  越高越好 → f(w) ≥ threshold
```
tightness=0 → 門檻貼最鬆端 → 約束不綁定；tightness=1 → 貼最嚴格可行端。

### 線性維度的可行範圍（封閉解，免求解器）
對 `f(w)=w·x`，在 `Σw=1, 0≤wᵢ≤cap`：
- `v_min` = 把權重貪婪塞到 **x 最小** 的標的（各到 cap）直到加總=1 → 對應加權值。
- `v_max` = 同理塞到 **x 最大** 的標的。
（線性目標最優在頂點，貪婪即為精確解。）

### 流動性合併特徵 `liq_composite`（依使用者 Vol:AUM 權重比例，§7-3 定案）
```
liq_composite_i = (w_vol·Norm_Liq_Volume_i + w_aum·Norm_Liq_AUM_i) / (w_vol + w_aum)   # ∈[0,1]
```
（`w_vol+w_aum=0` 的退化情況退回各 0.5。）tightness 用 §2 的 `ratio_liq`。

### HHI 可行範圍
- `HHI_min`：解「最小 HHI」（沿用既有 `USE_TRUE_HHI_OPTIMIZATION` 機制 / 凸 QP）。
- `HHI_max`：貪婪把權重集中到同一產業（受 cap 限制）的 HHI（近似上端即可，因上端只是「最鬆」參考）。
- 門檻 `HHI ≤ HHI_min + (1−tightness)·(HHI_max−HHI_min)` → 恆 ≥ HHI_min → **永不無解**（修掉現況 0.50 可能無解）。

---

## 4. 移除 / 新增

**移除**：`COST_BUDGET_QUANTILE`、`HHI_CEILING`（魔術數字）。
**新增（parameters.py）**：
- `QUALITY_TIGHTNESS_FULL_RATIO = 2.0`（tightness 在幾倍等權時達最緊）
- `USE_QUALITY_CONSTRAINTS = True`（沿用；總開關）
- 各維度可獨立關閉的小旗標（OAT 用），例如 `QC_ENABLE_COST/HHI/LIQ/SENT`（預設逐一打開）
**新增（functions.py，backtest import → 單一真理來源）**：
- `quality_tightness(w_q, n_dims=9, full_ratio=...)`
- `feasible_linear_range(x_vec, cap)` → (v_min, v_max)
- `quality_threshold(v_min, v_max, tightness, lower_is_better)` 
- HHI 上端 `feasible_hhi_range(sector_matrix, cap)`（min 用既有解、max 貪婪）

---

## 5. 性質

1. **恆可行**：所有門檻落在 [v_min,v_max] 內 → SLSQP 不會因品質約束無解。
2. **偏好驅動**：tightness 由權重決定；越在乎越緊。
3. **池子相對**：每期依當期候選池的可達範圍重算。
4. **低優先自動關閉**：權重 ≤ 等權 → 約束不綁定，無需手動開關。
5. **與風險預算一致**：同一套「可行範圍 + 偏好定位」哲學。
6. **不動報酬/風險核心**：品質仍是約束（03 §1.5 拆分），核心目標函數不變。

---

## 6. 實作與 OAT 上線計畫

兩檔同步（functions.py Stage 3 的 Arm C/C2 分支 + backtest_engine `optimize_preference_portfolio`），helper 放 functions.py 由 backtest import。
**一次只開一個約束、跑回測看 OOS 影響再開下一個**：
1. 框架 helper 實作 + 用新框架**重設成本**（取代 0.75），其餘維度先關。跑多 profile 回測。
2. **重設 HHI**（取代 0.50、修無解）。
3. 開**合併流動性下限**。
4. 開**情緒門檻**。
每步記錄：win_VT / Sharpe / CAGR / MaxDD / 該維度投組值 的變化（對照未開該約束）。

---

## 7. 定調結果（使用者 2026-06-05）

1. ✅ **中性點 = 該使用者品質維度平均**（讓約束更易綁定）。已更新 §2。
2. ✅ **成本不特殊對待**（純偏好驅動，低於品質平均就關；無最小底線）。
3. ✅ **流動性合併依使用者 Vol:AUM 權重比例**加權（非各 0.5）。已更新 §3。
4. ✅ **OAT 順序**：成本 → HHI → 流動性 → 情緒。
5. ⚠️ **情緒(FinBERT)資料不穩定**：效果不一定好。→ 情緒列為最後一步、謹慎評估；若 OOS 無助益或不穩定就保持關閉或輕量。其餘三項先做。
