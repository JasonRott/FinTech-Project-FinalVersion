# 偏好驅動 ETF 投資組合最佳化系統 — 成果與數學細節

> 版本 A（成果展示）：從頭到尾的數學細節 + 關鍵回測實驗佐證。
> 另見版本 B（`REPORT_B_design_story.md`）：設計歷程與理由。

---

## 0. 一句話成果

一套**偏好驅動、且有 Black-Litterman / CAPM 理論地基**的 ETF robo-advisor:使用者偏好 → 自動決定投組「核心類型 + 風險水準 + 偏好傾斜」。經跨市場規制的 walk-forward 驗證:**報酬導向使用者穩健取得高於 VT 的絕對報酬;保守/收入型贏在風險效率與偏好滿足。** 系統對自身限制誠實量化。

---

## 1. 系統總覽（5 階段管線）

| 階段 | 名稱 | 產出 |
|---|---|---|
| Stage 0 | 市場資料 + 特徵工程 + FinBERT 情緒 | 9 維特徵矩陣 |
| Stage 1 | DEA 效率篩選（標準 / 超效率 / 交叉效率）| 候選池 |
| Stage 2_1 | 偏好提取（兩層 AHP / Gemini 主動探測）| 9 維全局權重 |
| Stage 2_2 | 相關性分群去重 | 去冗候選池 |
| Stage 3 | 偏好驅動投組最佳化（本系統核心）| 推薦投組 + 對照 |

**主系統 vs 回測一致性**:Stage 3 最佳化器(`functions.py`)與回測引擎(`backtest_engine.py`)的數學核心透過共用函式共享,逐行驗證一致（見 `system_upgrade_records/09`）。主系統用最近 3 年 lookback 算「當前推薦」;回測用同樣 3 年 lookback 滾動前進,評估這套規則的歷史表現。

---

## 2. 逐階段數學

### 2.1 Stage 0 — 特徵與正規化
9 維特徵:`Return_CAGR, Return_Div, Risk_Vol, Risk_MaxDD, Cost_ExpRatio, Liq_Volume, Liq_AUM, Div_Score, FinBERT_score`。
正規化 `robust_scale`（縮尾 min-max）：先夾到 $[p_{\text{low}}, p_{\text{high}}]$ 分位,再線性壓到 $[0,1]$（風險/成本維度取 $1-\text{norm}$,越低越好）:

$$\text{clipped} = \mathrm{clip}\big(x,\ Q_{p_{\text{low}}}(x),\ Q_{p_{\text{high}}}(x)\big), \qquad \text{norm} = \frac{\text{clipped} - \min}{\max - \min}$$

### 2.2 Stage 1 — DEA 效率篩選
CCR 投入導向（scipy `linprog`）：每檔 ETF $o$ 解

$$\max_{u,v}\ \sum_r u_r y_{ro} \quad \text{s.t.}\quad \sum_i v_i x_{io}=1,\quad \sum_r u_r y_{rj}-\sum_i v_i x_{ij}\le 0\ \ \forall j,\quad u,v\ge 0$$
投入 = {風險, 成本};產出 = **{Out_CAGR, Out_Div, Out_Liquidity, Out_Diversity}**（資本利得與股息**分開**,成長股不被股息平均稀釋）。
候選池門檻 = **取 DEA 分數前 25% 百分位**（取代固定 0.80）。另算超效率、交叉效率。

### 2.3 Stage 2_1 — 兩層 AHP
成對比較矩陣 → 特徵向量法求權重 → 一致性比率 CR。兩層(主準則 × 子準則)合成 **9 維全局權重 w**（Σ=1）。

### 2.4 Stage 2_2 — 相關性分群去重
日報酬相關 ≥ 0.99 視為同群(幾乎追同指數),群內取偏好分數最高者,去冗。

### 2.5 Stage 3 — 偏好驅動最佳化（系統核心）

**(a) 偏好 → 參數映射 $g(\mathbf{w})$**（連續函數,非查表）。$T_{\text{growth}}$ 即「資本利得渴望」:

$$T_{\text{growth}} = \frac{w_{\text{CAGR}}}{w_{\text{CAGR}}+w_{\text{Vol}}+w_{\text{MaxDD}}}$$

$$\text{core} = \begin{cases} \text{minvar}, & T_{\text{growth}} < 0.40\\[2pt] \text{market}, & 0.40 \le T_{\text{growth}} < 0.65\\[2pt] \text{beta}, & T_{\text{growth}} \ge 0.65 \end{cases}$$

$$\text{risk\_fraction} = \mathrm{clip}(T_{\text{growth}},\,0.05,\,0.95), \qquad \tau = 0.30\,(1-T_{\text{growth}})\,\hat{R}, \quad \hat{R}=\mathrm{clip}(w_{\text{CAGR}}+w_{\text{Div}},\,0,\,1)$$

**(b) U-C2 三核心**（只需每日報酬;$\Sigma=$ Ledoit-Wolf 收縮共變異;$c_i=\mathrm{Cov}(r_i, r_{VT})$）：

- **保守 minvar**：$\displaystyle \min_{\mathbf{w}}\ \tfrac{1}{2}\mathbf{w}^{\top}\Sigma\mathbf{w} - \tau\,\mathbf{w}^{\top}\mathbf{s}$
- **平衡 market**：$\displaystyle \min_{\mathbf{w}}\ \tfrac{1}{2}\mathbf{w}^{\top}\Sigma\mathbf{w} - \mathbf{w}^{\top}\mathbf{c} - \tau\,\mathbf{w}^{\top}\mathbf{s}$ （= 對 VT 報酬流最小化追蹤誤差）
- **報酬 beta**：$\displaystyle \max_{\mathbf{w}}\ \mathbf{w}^{\top}\boldsymbol{\beta} + \tau\,\mathbf{w}^{\top}\mathbf{s}$,其中 $\boldsymbol{\beta} = \mathbf{c}/\mathrm{Var}(r_{VT})$

共同約束:

$$\sum_i w_i = 1, \quad 0\le w_i \le \text{cap}=0.40, \quad \sqrt{\mathbf{w}^{\top}\Sigma\mathbf{w}}\ \le\ \text{vol\_budget}$$

**(c) 風險預算 = 相對候選池可行範圍**（恆可行）：$v_{\min}=$ 最小變異組合波動,$v_{\max}=$ 最大變異組合波動。

$$\text{vol\_budget} = v_{\min} + \text{risk\_fraction}\cdot(v_{\max} - v_{\min})$$

**(d) 偏好分數的報酬維度 = beta（系統性風險曝險）**：取代「過去 CAGR 排名」(不預測未來)。

$$\text{score}_{\text{return}} = 0.5 + 0.5\,\mathrm{clip}\!\left(\frac{\beta - 1}{\text{REF} - 1},\ 0,\ 1\right)$$

市場 $\beta=1\to 0.5$;$\beta=\text{REF}=2\to 1$;低於市場 floor $0.5$（不懲罰保守型）。其餘 8 維仍為偏好分數構面。**僅影響評估/展示分數,不進求解器目標。**（雷達圖另以 $\text{REF}=1.2$ 顯示,僅視覺鑑別度,不影響 win_VT。）

**(e) Black-Litterman 理論地基**：市場均衡隱含報酬 $\Pi = \lambda\Sigma\mathbf{w}_{\text{mkt}}$,而

$$\Pi_i = \lambda\,\mathrm{Cov}(r_i,\,m) = \lambda\,\beta_i\,\mathrm{Var}(m) \quad\Longrightarrow\quad \Pi \propto \beta$$

即 **CAPM**（$m$ = 市場/VT）。可證 market 核心等價於 BL 均值-變異（代入 $\Pi=\lambda\mathbf{c}$）：

$$\min_{\mathbf{w}}\ \tfrac{1}{2}\mathbf{w}^{\top}\Sigma\mathbf{w} - \mathbf{w}^{\top}\mathbf{c} \quad\equiv\quad \max_{\mathbf{w}}\ \mathbf{w}^{\top}\Pi - \tfrac{\lambda}{2}\mathbf{w}^{\top}\Sigma\mathbf{w}$$

而 beta 核心 $\max_{\mathbf{w}}\mathbf{w}^{\top}\boldsymbol{\beta}$ ≡ BL 約束式;minvar = BL 高風險趨避極限。→ **三核心 = BL 效率前緣上不同風險趨避的點**;$\Pi$ 用 $\mathbf{c}$（對 VT 共變異,不需成分權重）計算。

---

## 3. 關鍵回測佐證

資料 2016–2026（美國掛牌 ETF + VT/VOO 基準）。除特別註明,皆 C2 + beta 評分。

### 3.1 Walk-forward 跨規制（6 個 3 年窗,涵蓋 COVID/2022 熊市/復甦）★最關鍵★
| profile | 核心 | 贏 VT CAGR | 贏 VT Sharpe |
|---|---|---|---|
| aggressive_growth | beta | **4/6** | 4/6 |
| return_leaning | beta | **5/6** | 1/6 |
| market/minvar 各型 | market/minvar | 0–1/6 | 多數窗贏 |

→ **報酬導向(beta)跨規制穩健贏 VT 絕對報酬**;其他 profile 贏在風險效率/偏好滿足,非絕對報酬。強多頭窗(VT 20%+)誰都難贏。

### 3.2 beta 評分讓「每種使用者都容易贏」（win_VT,事後偏好分數勝 VT 期數%）
| profile | 過去 CAGR 評分 | **beta 評分** | vs EqualWeight/MaxSharpe |
|---|---|---|---|
| aggressive_growth | 13.6% | **67.8%** | →~100% |
| conservative | 57.6% | **64.4%**(不降反升)| ~95% |
→ 把報酬維度從不持續的「過去 CAGR」改成持續的「beta」,報酬導向 win_VT 大跳,且無 profile 變差。

### 3.3 Black-Litterman A/B（統一 BL vs 三核心 C2）
- beta 端:BL == C2(相同)。minvar/market 端:**統一 BL 更差**(balanced win_VT 80→0、conservative 60→5)。
- → 維持三核心 C2;BL 作為理論地基 + 消融對照。

### 3.4 品質約束 OAT（成本/HHI/流動性,off vs on）
- 成本:咬到就傷(income/cost_liquidity 的 Sharpe、win_VT 降);HHI/流動性:**完全 inert**(投組本已夠分散/低成本)。
- → **硬品質約束無益,全關**;品質由軟傾斜 + DEA + 核心處理（奧坎剃刀）。

### 3.5 風險預算 rf 與 DCA（誠實負面結果）
- **rf**:報酬導向高 rf=最大絕對報酬;封頂反而 CAGR↓/回撤更深(vol 約束≠回撤控制)→ 維持高 rf;低 Sharpe 是低波動異常的本質代價。
- **DCA**:用 IRR(金額加權)+ 跨起點離散度公平重測 → DCA 不比單筆差(修正早期假象),但**「DCA 降進場時機風險/高成長更受益」未獲支持**。

---

## 4. 假設與限制（誠實揭露）

### 4.1 資料/特徵層假設
- **情緒分數(FinBERT)有限**:資料不穩、覆蓋有限;OAT 也顯示情緒約束無益 → 系統不倚賴它。
- **產業分布回溯近似**:回測用「現在的產業/分散資料」套到過去期間(無歷史逐期產業快照)→ HHI/分散維度在歷史回測中是近似,含輕微 look-ahead。
- **殖利率以平均殖利率估**,非逐次除息事件;股息不再投入(嚴格 buy-and-hold)。
- **單一市場/期間**:資料 2016–2026、以美國掛牌 ETF 為主 → 結論對其他市場/期間未必成立。

### 4.2 演算法層假設
- **beta(系統性風險)有效、過去報酬無效**:報酬訊號用 beta/市場隱含(CAPM/BL),不用樣本 μ 或過去 CAGR 排名(V-1 證實過去 CAGR 不預測未來 r≈0;且樣本 μ 觸發 1/N 之謎)。
- **低波動異常**:高 beta 能換更高絕對報酬但 Sharpe 遞減 → 報酬導向「成功」定義為「風險上限內最大化絕對報酬,允許 Sharpe<VT」。
- **VT ≈ 市場組合 / BL 先驗**;Π 用對 VT 共變異近似(不需 VT 成分權重)。
- **單一歷史路徑**:雖做了跨 6 窗 walk-forward,仍非完整跨市場;數字為指示性。
- **偏好分數定位**:作為偏好提取 + 樣本外評估(win_VT)指標,**非 alpha 來源**;不宣稱系統性打敗市場風險調整報酬(1/N 之謎)。

---

## 5. 未來展望

已完成範圍與刻意延後的工作如下,作為後續研究的明確路線:

1. **Black-Litterman 路 (b) — 因子觀點**：目前僅用路 (a)（市場隱含報酬 $\Pi=$ CAPM 作為穩定 $\mu$）。未來可加入因子觀點（價值/動能/品質/低波）的 BL 主觀觀點 + 信心矩陣;惟因子溢酬非每個市場/期間皆成立,須市場別校準。
2. **歷史逐期產業快照**：消除目前 HHI/分散維度的 look-ahead（現用「當前產業分布」回溯套用）。改抓各再平衡日的歷史產業歸屬,使分散度在回測中完全 point-in-time。
3. **回撤控制改用 MaxDD 約束**：rf 封頂實驗證實「壓 vol 預算 $\neq$ 控回撤」。正解是直接對投組 MaxDD（或 CVaR）加約束,作為報酬導向使用者真正的回撤旋鈕。
4. **真實除息與股息再投入（DRIP）**：以逐次 ex-dividend 事件取代平均殖利率估計,並支援股息再投入,使總報酬與稅務更貼近真實。
5. **跨市場 / 跨期間驗證**：現以美國掛牌 ETF、2016–2026 為主。擴及他國市場與更長/不同期間,檢驗 $g(\mathbf{w})$、三核心與 beta 評分的外推性。
6. **更穩健的情緒資料**：FinBERT 情緒覆蓋與穩定性有限,目前不倚賴。未來可換更廣、更穩的新聞/情緒來源,並重評其邊際價值。
7. **交易成本 / 周轉感知再平衡**：將周轉與交易成本納入再平衡目標（如周轉懲罰），降低實務摩擦。
8. **主動式偏好探測產品化**：把 Gemini 自然語言訪談（Stage 2_1 主動模式）做成穩定的對話式偏好提取流程。
9. **更乾淨的 DCA 測試**：以固定未來期間 + 細粒度起始點位移,分離「進場時機」與「市場規制」,精確量測定期定額效果。

---

## 6. 結論
本系統的價值在於:**理論地基紮實(BL/CAPM)、偏好驅動、profile-dependent、跨規制驗證、且對限制誠實**。它能讓報酬導向使用者穩健取得 >VT 的絕對報酬,並讓各類使用者的偏好在樣本外可被驗證地滿足;但不應宣稱為穩定 alpha。作為決策支援框架與研究成果,結論站得住腳。
