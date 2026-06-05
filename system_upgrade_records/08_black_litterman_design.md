# Black-Litterman 路 (a) 設計文件（待審）

建立：2026-06-05　狀態：**設計提案,待審後實作+驗證**　範圍：C2 核心的正名與統一
決議：先走路 (a)（市場先驗 Π 當穩定 μ + 偏好管風險姿態）；路 (b)（因子觀點）列為未來展望（因子溢酬非每個市場成立,作為未來比較方案）。

---

## 0. 一句話
**把目前手工的三個核心(minvar/market/beta)正名 + 統一成「以 Black-Litterman 市場均衡報酬 Π 為 μ 的效率前緣最佳化」,偏好用 risk_fraction 在前緣上選點。**

---

## 1. 關鍵發現:三個核心本來就是 BL 路 (a)

BL 先驗 `Π = λ·Σ·w_mkt`,且 `Πᵢ = λ·Cov(資產i, 市場) = λ·cᵢ`，其中 `cᵢ = Cov(rᵢ, r_VT)`（用 VT 報酬流算,**不需成分權重**;我們市場/beta 核心已在用 c）。

- **市場核心 = BL 均值-變異(完全相等)**：`max wᵀΠ − (λ/2)wᵀΣw` 代入 Π=λc、同除 λ → `min ½wᵀΣw − wᵀc`（市場核心目標式,一字不差）。
- **beta 核心 = BL 約束式**：`max wᵀβ`（β∝c∝Π）= `max wᵀΠ`,受 vol 上限。
- **最小變異核心 = BL 極限**（λ→∞ / vol_budget→最小）。

→ 三核心是同一個 BL 目標的三個風險點。路 (a) = 認出並統一。

---

## 2. 統一目標（採約束式,沿用 risk_fraction 可行範圍）

```
最大化   wᵀΠ  +  τ·wᵀs
受限於   Σw=1、0≤wᵢ≤cap、√(wᵀΣw) ≤ vol_budget(risk_fraction)
```
- `Π = c`（cᵢ=Cov(rᵢ,r_VT)）= BL 市場隱含報酬。**約束式下 Π 的正純量 λ_mkt 不影響 argmax,故無需估 λ_mkt**（penalty 式才需要;見 §5）。
- `s` = User_Pref_Score（noCAGR 版,可切換）= 保留專案「偏好驅動」特色的傾斜（dividends/quality 等非報酬偏好仍由此進入）。
- `τ`、`vol_budget` 由 `g(w)` 給（偏好 → 風險姿態）。**risk_fraction 在「可行波動範圍」內滑動 → 恆可行**：
  - 低（保守）→ 前緣低風險端（該風險下報酬最高點,比純最小變異略佳）。
  - 中（平衡）→ 市場附近。
  - 高（報酬導向）→ 高 Π/高 beta 端。
- **此式 = 目前 beta 核心的公式,套用到所有 profile**；`core_mode`（minvar/market/beta 切換）被 risk_fraction 連續涵蓋而**功成身退**。

---

## 3. 這買到什麼 / 沒買到什麼（誠實）

**買到**：① 理論地基（「max beta」正名為 Black-Litterman / CAPM 市場均衡報酬 Π）;② 統一/簡化（三核心+門檻 → 一目標+一旋鈕,過渡平滑）;③ 保守/平衡端可能略佳（效率前緣點 vs 純最小變異,可測）;④ 替路 (b) 鋪路（未來在 Π 上加觀點即 (b)）。

**沒買到**：主要是「鞏固+正名+統一」,**非新 alpha**。三核心本是其特例,OOS 預期相近（beta 端尤其相同）;差異集中在保守/平衡端,需實測。

---

## 4. 實作（兩檔同步）

- functions.py Stage 3 與 backtest `optimize_preference_portfolio`：把 C2 的三分支（minvar/market/beta）收成**單一目標** `max wᵀc + τ·wᵀs s.t. vol≤budget`（即現行 beta 分支,移除 core_mode 切換）。
- `g(w)`：`derive_params_from_weights` 仍輸出 risk_fraction、τ;`core_mode` 標為 deprecated（保留欄位但不再分支）。
- Π 命名/註解：把 `c`/`β` 在註解標明為「BL 市場隱含報酬 Π = λΣw_mkt 的 per-asset 形式」。
- 新增開關 `OPTIMIZATION_ARM="BL"`（或沿用 "C2" 但內部統一）；建議新增 "BL" 以便與三核心 C2 做 A/B。

---

## 5. （備記）penalty 式 BL，若未來想用
`max wᵀΠ − (λ_user/2)wᵀΣw`，需 `Π=λ_mkt·c`（λ_mkt 由市場 Sharpe 估：λ_mkt=市場超額報酬/市場變異 ≈ 2~3）+ λ_user 由 g(w)。較正統但可能極端/需校準,且不沿用 risk_fraction 可行範圍。**本次採約束式,penalty 式列備案。**

---

## 6. 驗證計畫（季度,月度最終驗）
A/B：**統一 BL-(a)（"BL"）vs 現行三核心 C2**，7 profile × 2 窗。重點看：
- 保守/平衡 profile 的 CAGR/Sharpe/MaxDD/win_VT 是否變化（預期 beta 端相同、保守/平衡端可能略佳或持平）。
- 確認過渡平滑、無無解。
跑後設 `OPTIMIZATION_ARM` 還原 "A"。

---

## 7. 路 (b) 未來展望（不在本次範圍）
在 Π 上加「真實因子觀點」(value/momentum/低波動/quality 等),偏好權重設信心 Ω,P=由特徵建因子組合,Q=因子溢酬估計。**因子溢酬非每市場成立 → 列為未來可比較方案。**

---

## 8. 定調（使用者 2026-06-05）
1. ✅ 採**約束式**（沿用 risk_fraction、恆可行）。
2. ✅ 新增 `OPTIMIZATION_ARM="BL"` 與三核心 C2 **並存做 A/B**。
3. ✅ **保留傾斜** `τ·wᵀs`。

## ★最終結論（2026-06-05，A/B 驗證後）★

**敘事脈絡（專案論述用）**：
> 以 Black-Litterman 作為理論基礎,我們開發了 BL 的統一最佳化模式（約束式：給定風險預算下最大化市場隱含報酬 Π）。然而我們發現,**對於市場型與保守型使用者而言,給定風險預算會讓求解器在該風險水準下盡可能追求 beta,反而導致他們得到的結果不如預期,偏好分數(win_VT)也大幅下降**。因此我們針對不同使用者給了三種核心(最小變異 / 市場 / beta)來解決這個問題——這三核心恰好是 BL 在不同風險趨避程度下的效率前緣點。

**A/B 實證（統一 BL vs 三核心 C2,季度,7 profile × 2 窗；輸出 `upgrade_figures/bl_ab/`）**：
- **beta 端(aggressive/return_leaning)：C2 == BL 完全相同**（C2 本就對它們用 beta 核心 = BL 約束式）。
- **minvar/market 端：統一 BL 明顯更差** —— 波動↑、回撤深↑、win_VT 常崩到 0：
  - balanced：win_VT 80→0、MaxDD -20.8→-25.8;conservative：win_VT 60→5、MaxDD -14.5→-19.1;income：Sharpe 0.776→0.597;cost_liquidity：win_VT 100→50;diversified_quality：win_VT 80→0。
- 原因：保守型 risk_fraction 雖低,vol_budget 仍 > v_min,BL「在預算內衝 Π(beta)」會把風險預算花掉買 beta,推向市場、失去「低波動+防禦/股息」的贏 VT 優勢。

**決議**：
1. **維持三核心 C2 為運作設計**（統一 BL 對非 beta 端更差,不採用為預設）。
2. **BL = C2 的理論正名**：Π=市場隱含(CAPM)報酬;三核心 = BL 效率前緣上不同風險趨避的點（minvar=高趨避、market=中、beta=低）。給系統嚴謹理論基礎,**不需改動能用的系統**。
3. **BL 臂保留並存**,作為「為何需要 per-profile 選核心」的消融對照。
4. 路 (b) 因子觀點 = 未來展望。

---

## 9. 補記：λ 去哪了 / risk_fraction 沒變
- **兩個 λ 在約束式都合法消失**：(i) λ_mkt 是 Π 前的正常數,不改 argmax → 求解時消掉(故約束式不必估 λ_mkt);(ii) λ_user(懲罰式風險趨避)被 vol_budget 約束取代——均值-變異「懲罰式↔約束式」對偶,每個 λ 對應一個 vol_budget,走同一條效率前緣。
- **risk_fraction 設定完全不變**：g(w) 公式 + `vol_budget=v_min+risk_fraction·(v_max−v_min)` 可行範圍機制原封不動;只有目標函數從三核心改成統一式。
- 實作上 Π 用 `β=c/var_bench`(正規化,scale 與傾斜相稱)= 現行 beta 核心的報酬項；BL 臂 = beta 核心目標套用到所有 profile（移除 core_mode 切換）。
