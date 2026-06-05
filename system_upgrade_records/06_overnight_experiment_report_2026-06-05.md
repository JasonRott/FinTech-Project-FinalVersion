# 隔夜實驗報告（2026-06-05 夜）— U-C2 實作與驗證

給早上的你：這份是自主跑完的完整成果。讀這份即可，細節散在 `02`(流水帳)、`03`(設計)。  
一句話：**U-C2 做完並驗證了。報酬導向使用者現在真的能用風險換到超過 VT 的報酬；而且我們發現「資本利得排名」一直在扯後腿，拿掉它連最小變異/市場核心都能贏 VT。**

---

## 0. 這一輪做了什麼（程式碼）

| 項目 | 內容 | 狀態 |
|---|---|---|
| 升級 A：`g(w)` 偏好→參數映射 | `derive_params_from_weights()`：用權重向量算 core_mode/τ/risk_fraction。core 由「資本利得渴望 T_growth」決定（修正 income 誤分）。functions.py 為單一真理來源，backtest import。 | ✅ |
| 升級 B：U-C2 三核心（Arm "C2"） | minvar / market（對 VT 報酬流追蹤誤差 `½wᵀΣw−wᵀc`）/ beta（`max wᵀβ`）。只需每日報酬、不需成分權重。兩檔同步。 | ✅ |
| vol_budget 改「相對可行範圍」 | 你指出絕對值會無解/脫離池子。改成 `v_min + risk_fraction·(v_max−v_min)`，恆可行。 | ✅ |
| v_max 穩健化 | 你問「最高變異怎麼算」→ 發現用 SLSQP 最大化凸函數會卡局部、低估 v_max。改成「貪婪填滿最高變異到 cap + 多起點」取最大。 | ✅ |
| `TILT_INCLUDE_CAGR` 預設改 False | s-sweep 證實含 CAGR 排名有害（見下）。 | ✅ |

> 所有實驗跑完已還原：`OPTIMIZATION_ARM="A"`、權重 JSON 還原、`RISK_FRACTION_OVERRIDE=None`。

---

## 1. 實驗一：s_full vs s_noCAGR（傾斜要不要含資本利得排名）

**結論：拿掉資本利得排名（noCAGR）完勝。** 12 格全部 noCAGR Sharpe 較高；高 τ 時差距爆炸。

| profile | τ | full Sharpe/CAGR | noCAGR Sharpe/CAGR | 贏家 |
|---|---:|---|---|---|
| conservative | 0.1 | 0.560 / 10.00 | **0.624 / 10.91** | noCAGR |
| conservative | 0.3 | 0.601 / 10.83 | **0.670 / 11.81** | noCAGR |
| balanced | 0.1 | 0.691 / 12.23 | **0.756 / 13.02** | noCAGR |
| balanced | 0.3 | 0.711 / 12.93 | **0.782 / 13.84** ✓贏VT | noCAGR（壓倒性）|
| return_leaning | 0.1 | 0.666 / 12.07 | 0.685 / 11.87 | 平手偏 noCAGR |
| return_leaning | 0.3 | 0.558 / 11.35 | **0.841 / 14.50** ✓贏VT | noCAGR（壓倒性）|

VT 參考：CAGR 13.51%、Sharpe 0.645、Vol 15.30%。

**機制**：資本利得排名 = 追過去贏家（會均值回歸），不預測未來報酬。在強傾斜(τ=0.3)下，含它會把錢推向「過去漲多、未來回吐」的標的 → return_leaning τ=0.3 從 0.841 崩到 0.558。拿掉後，傾斜改載在較持久的訊號（股息/品質/低成本/低風險）。

**重大更正**：先前多 profile sweep 說「沒有 profile 贏過 VT」——那是用了 s_full 的假象。noCAGR 下 balanced 與 return_leaning 在 τ=0.3 都贏過 VT（且波動更低、回撤更淺、Sharpe 更高）。

---

## 2. 實驗二 Part 1：多 profile C2 vs Arm C vs VT

每個 profile 取 C2(noCAGR) 與 Arm C(τ=0.1) 對照。VT：CAGR 13.51 / Sharpe 0.645 / Vol 15.30。

| profile | g(w) 核心 | C2 Sharpe/CAGR/Vol/MaxDD | Arm C Sharpe/CAGR | 對 VT |
|---|---|---|---|---|
| aggressive_growth | beta | 0.573 / **13.80** / 18.65 / -25.3 | 0.373 / 8.85 | **CAGR 贏 VT**，Sharpe 輸 |
| return_leaning | beta | 0.638 / **14.12** / 16.64 / -25.2 | 0.666 / 12.07 | **CAGR 贏 VT**，Sharpe≈VT |
| income | minvar | **0.858 / 14.27** / 11.71 / -18.0 | 0.773 / 13.21 | **全面贏 VT**（win_VT 100%）|
| cost_liquidity | market | 0.740 / **14.15** / 13.79 / -22.1 | 0.725 / 12.82 | **CAGR+Sharpe 贏 VT** |
| balanced | market | 0.715 / 13.19 / 12.93 / -20.2 | 0.691 / 12.23 | Sharpe 贏、CAGR 近 |
| diversified_quality | market | 0.669 / 12.60 / 13.08 / -20.9 | 0.617 / 11.41 | Sharpe 贏、CAGR 輸 |
| conservative | minvar | 0.666 / 10.94 / 10.44 / -15.9 | 0.560 / 10.00 | 防禦（本應低於 VT）|

**結論**：
1. **C2 在 Sharpe 與 CAGR 上 6/7 profile 勝過 Arm C**（return_leaning 例外：C2 報酬高但 Arm C 風險調整更好）。
2. **U-C2 的核心目的達成**：aggressive_growth 從 Arm C 的災難性 8.85% CAGR → C2 beta 核心 **13.80%（贏過 VT）**，代價是 vol 18.65%、Sharpe 0.573（< VT）。完全符合「報酬導向成功=風險上限內最大化絕對報酬，允許 Sharpe<VT」(05 §4.9)。
3. **C2(noCAGR) 有 4 個 profile CAGR 贏過 VT**：aggressive 13.80、return_leaning 14.12、income 14.27、cost_liquidity 14.15。
4. **income 是最大驚喜**：minvar 核心 + 最強股息傾斜(τ=0.103) → Sharpe 0.858、CAGR 14.27、vol 11.71、win_VT 100%，全面碾壓 VT。收入型找到了天然歸宿。

**⚠️ 一個必須跟你討論的張力**：beta 核心雖然拿到報酬，但**偏好分數勝率(win_VT)很低**（aggressive 42%、return_leaning 11%），因為 beta 核心幾乎不理偏好傾斜、只買市場風險。也就是說**報酬導向使用者用 beta 核心 = 放棄了「偏好分數」這個專案招牌**。相對地，minvar/market 核心（income 100%、balanced 64%）保住了招牌。這是「要報酬還是要偏好招牌」的取捨，值得你定調。

---

## 3. 實驗二 Part 2：risk_fraction 行為地圖 — 「能不能用風險換報酬？」

你最關心的問題。beta 核心 profile 掃 risk_fraction 0→1：

### aggressive_growth（beta 核心）
| rf | Vol% | CAGR% | Sharpe | MaxDD% |
|---:|---:|---:|---:|---:|
| 0.0 | 9.20 | 13.47 | **0.987** | -11.25 |
| 0.3 | 12.68 | 13.22 | 0.729 | -21.29 |
| 0.5 | 14.99 | 13.74 | 0.668 | -24.68 |
| 0.7 | 17.03 | 14.47 | 0.645 | -25.05 |
| 1.0 | 19.79 | **15.54** | 0.628 | -24.98 |

### return_leaning（beta 核心）：同形，rf=1.0 → Vol 19.76 / CAGR 14.97 / Sharpe 0.603
### balanced（market 核心）：rf≥0.5 後**飽和**（Vol 12.93/CAGR 13.23 不再變）——市場追蹤的天然波動低於預算上限，預算不再綁定（符合設計）。

**結論（直接回答你）：**
1. **能。** beta 核心的 rf 掃描呈現乾淨的「**風險↑ → 報酬↑**」單調關係：aggressive 從 9.2%vol/13.47%CAGR 一路爬到 19.8%vol/15.54%CAGR。**風險預算確實被用來買 beta、換到更高絕對報酬，rf=1.0 時 CAGR 15.54% 明顯超過 VT 13.51%。**
2. **但這個交換是「Sharpe 遞減」的**：每加一分風險，Sharpe 就掉（0.99→0.63）。印證低波動異常(05 §4.9)——可以用更多風險買到更多絕對報酬，但風險調整後報酬變差。
3. **意外但重要**：rf=0（=最小變異端，因為預算=v_min）這一端 **Sharpe 最高(0.99)且 CAGR 已達 13.47%（近 VT），vol 只有 9.2%**。也就是這段期間「防禦端」在風險調整上最強。→ 對報酬導向使用者，「衝報酬」要犧牲很多 Sharpe；「待在低風險端」反而 CP 值最高。這強烈受 2021–26 防禦/低波動因子表現影響（期間運氣），**務必 walk-forward 驗證**。

---

## 4. 綜合：對整個專案的意義

- **U-C2 是成功的**：補上了 Arm C 對報酬導向使用者「坐在前緣左下、拉不高報酬」的結構缺口。現在有了 profile-dependent 核心 + 相對風險預算，報酬導向使用者能沿前緣往右上移動、用風險換報酬。
- **最大的免費午餐其實是 noCAGR**：不必動核心，光是把資本利得排名從傾斜拿掉，就讓多個 profile 贏過 VT。這是這輪最乾淨、最可推廣的發現。
- **兩個未解的張力（需要你定調）**：
  1. beta 核心 vs 偏好招牌：報酬導向使用者要不要為了報酬放棄高 win_VT？或設計「beta 核心 + 較強偏好傾斜」的折衷？
  2. 「衝報酬」Sharpe 遞減：要不要對報酬導向使用者預設較低 rf（待在高 Sharpe 區），還是尊重其偏好給高 rf？

## 5. 必要的保留（誠實）

- **全部是單一歷史路徑（2021–26 附近）**，數字僅指示性。尤其「最小變異端 Sharpe 0.99」「多個 profile 贏 VT」高度依賴此期間的防禦/股息/低波動因子表現。**下一步必須 walk-forward（多 lookback × 多 time window）驗證跨期穩健性。**
- beta/共變異 helper 已穩健化，但 v_max 仍是啟發式（貪婪+多起點），極端情況可能略低估。

## 6. 建議下一步（待你早上定調）

1. **先 walk-forward 驗證**現有 C2 + noCAGR 設定（多視窗），確認「贏 VT」不是單期運氣 —— 我認為這是最該先做的。
2. 定調上述兩個張力（beta vs 招牌、rf 高低）。
3. 之後再逐一加品質約束（OAT）與考慮 Black-Litterman。

## 6.5 Walk-forward 穩健性驗證結果（2026-06-05，★重要更正★）

跑了 7 profile × 6 個滾動時間窗(lb=2y) + 4 個 lookback(窗 2021-26)。資料 cache 2016-2026。
輸出：`upgrade_figures/walkforward/{wf_timewindow,wf_lookback}.csv`。

### Axis A：跨時間窗（VT 的 CAGR 隨窗 12.2%→21.6%，後兩窗 2022-25/2023-26 是極強多頭）
| profile | 核心 | 贏 VT CAGR | 贏 VT Sharpe | win_VT |
|---|---|---|---|---|
| aggressive_growth | beta | **4/6** | 4/6 | 6-47% |
| return_leaning | beta | **5/6** | 1/6 | 6-47% |
| cost_liquidity | market | 1/6 | **6/6** | 75-100% |
| balanced | market | 0/6 | 4/6 | 39-77% |
| income | minvar | 0/6 | 4/6 | **100%(全窗)** |
| diversified_quality | market | 0/6 | 2/6 | 14-81% |
| conservative | minvar | 0/6 | 2/6 | 36-81% |

### ★重要更正（誠實）★
- **單一路徑(2021-26)的「4 個 profile 贏 VT CAGR」大部分是那一個幸運窗。** 跨 6 窗後：
  - **只有 beta 核心 profile（aggressive 4/6、return_leaning 5/6）穩健地贏過 VT 絕對 CAGR。**（U-C2 核心目的跨規制成立。）
  - minvar/market profile（income/balanced/cost_liquidity/diversified_quality/conservative）**贏 VT 在 Sharpe/回撤/偏好分數，不是絕對報酬**（0-1/6 贏 CAGR）。
- **風險換報酬的取捨跨規制一致**：beta 核心贏 CAGR 但很少贏 Sharpe；market/minvar 核心贏 Sharpe 但不贏 CAGR。**從不兩者兼得**（低波動異常的穩健證據）。
- **強多頭窗(2022-26，VT 20%+)誰都贏不過 VT**（高 beta 在多頭≈市場本身）。
- income 全窗 win_VT 100%（偏好招牌穩固）；但 COVID 窗 MaxDD 深達 -38%（高股息在 2020/03 重挫）。

### Axis B：lookback 敏感度（窗 2021-06~2026-05，VT CAGR 12.17）
- 中度敏感、無不穩定：**lb=2~3 為甜蜜區**；lb=1 較雜訊。
- beta profile 的「贏 VT」對 lookback 有點脆弱（aggressive 只在 lb=2 贏）→ 報酬贏 VT 為真但非鐵板一塊。

### 結論
walk-forward **大幅修正了單期樂觀、但確認了核心論點**：報酬導向(beta)使用者跨規制穩健地拿到 >VT 的絕對報酬；其他 profile 的價值在風險效率與偏好滿足，而非絕對報酬。這比「人人贏 VT」更誠實也更站得住腳。建議對外論述就用這個版本。

## 6.6 排隊實驗結果（2026-06-05）：noCAGR 穩健性 / risk_fraction 跨區 / DCA

輸出：`upgrade_figures/queued/{exp3_nocagr_robustness, exp4_riskfraction_regime, exp5_dca}.csv`。

### Exp3 — noCAGR vs full 跨區（Arm C τ=0.3）★第二個重要更正★
單一路徑(2021-26)曾顯示 noCAGR 壓倒性勝 full（return_leaning τ=0.3：0.841 vs 0.558）。**跨 6 窗後 → 其實是 regime-dependent、大致打平**：
- conservative：full 贏早窗(2018-22)與 2023-26、noCAGR 贏中段 → 約略平手。
- balanced：full 贏 COVID 窗(2018-22)、noCAGR 贏近窗(2021-26)。
- return_leaning：full 贏 2018-22 與 2021-24（**full 在這兩窗甚至 CAGR 贏 VT**：13.99、13.86），noCAGR 贏 2020-23、2022-26。
- **結論：noCAGR「壓倒 full」也是 2021-26 單窗現象；跨規制無穩健贏家。** → `TILT_INCLUDE_CAGR=False` 的預設翻轉**不被跨區證據支持**，財務上是 wash。
- **決策待定（使用者）**：(a) 維持 noCAGR（原則：CAGR 排名不預測未來報酬 V-1 r≈0）；(b) 改回 full（忠實表達資本利得偏好＝招牌、且與展示層成長獎勵一致、wash 故無財務代價）。注意：C2 對 beta 核心 profile 的 τ 很小，此選擇主要影響 minvar/market（conservative/balanced/income）。

### Exp4 — risk_fraction 跨區穩定性（C2 noCAGR）★強化 U-C2★
beta 核心 3 個規制窗（COVID / 2022 熊 / 近多頭）掃 rf 0→1：
- **「風險↑→報酬↑」跨規制全部成立**（單調）：aggressive rf 0→1，2018-21 CAGR 11.2→17.5、2020-23 14.9→19.6、2023-26 16.6→20.8。
- **「Sharpe 隨 rf 遞減」跨規制全部成立**（低波動異常穩健）。
- **高 rf 在非強多頭窗能贏 VT**（2018-21、2020-23 在 rf≥0.75 贏 VT CAGR）；**強多頭窗(2023-26 VT 21.6%)仍贏不過**。
- market 核心(balanced)：rf≥0.5 後**飽和**（預算不綁定），跨規制一致。
→ **U-C2 的核心機制（用風險預算買 beta 換報酬）跨規制穩健，這是最可靠的發現。**

### Exp5 — DCA 單筆 vs 定期定額
- **時間加權 Sharpe/CAGR 單筆≈DCA**（同持股%，如預期）→ DCA 不改變投組風險屬性。
- **財富倍數(終值/總投入)：單筆 > DCA 每一窗**（2016-26 多頭市場，早投入賺更多）。
- **DCA 降低跨窗財富倍數的離散度**（進場時機風險↓），且**高波動組合(aggressive)的絕對降幅最大** → 弱支持你的直覺（風險軸）；但**同時拉低平均**，變異係數(CV)大致不變 → 非風險調整後的免費午餐。
- ⚠️ 量測限制：財富倍數未調整「投入時點」（DCA 資金在場時間較短，天生吃虧）。要公平驗證進場時機風險，應改用 **IRR(金額加權報酬率)** 或「固定投入排程、掃多個起始點看結果離散度」。列為後續精修。
- 結論：在持續上漲的市場，DCA = 較低風險 + 較低報酬，非全面更好；其價值在「降低單點進場後悔/離散度」，對高成長組合的絕對降幅較明顯。

## 6.7 beta 錨 VT vs VTI 解耦實驗（2026-06-05）

新增 `BETA_ANCHOR_TICKER`（beta/market 核心的市場錨可獨立於報告基準）。測 VT vs VTI(整體美國市場)是否拉開報酬導向 vs 保守的價差。
- 解耦正確（conservative 兩錨數字相同）。
- VTI 效果又小又混：aggressive 近窗微好、2022 熊市窗更差；return_leaning/balanced 略差。價差近窗微增(2.89→3.32%)、熊市窗反縮(5.60→4.51%)。
- 根因：候選池幾乎全美國 ETF → 全球(VT) vs 美國(VTI) beta 排序幾乎不變。
- **結論：錨維持 VT；真正的價差槓桿是 risk_fraction 映射 + 核心類型（非錨）。現有 VT 設定下偏好敘事已成立。** `BETA_ANCHOR_TICKER` 解耦功能保留備用。

## 7. 如何重現 / 檔案

- 設定：`OPTIMIZATION_ARM="C2"`、`TILT_INCLUDE_CAGR=False`（已設為預設）；g(w) 自動給 core/τ/risk_fraction。
- 實驗腳本：`_s_sweep.py`、`_c2_experiment.py`（report/figure 已 no-op 加速）；映射驗收 `_verify_gw_mapping.py`；煙霧測試 `_smoke_c2.py`。
- 數據：`upgrade_figures/s_sweep/s_sweep_summary.csv`、`upgrade_figures/c2_experiment/{c2_multiprofile_summary,c2_riskfraction_map}.csv`。
