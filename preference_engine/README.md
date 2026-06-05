# preference_engine —— 金融偏好誘出引擎(可嵌入模組)

把投資者的「投資理念 + 逐輪問答」轉成一個 **9 維 ETF 偏好權重向量**(總和=1),
供下游 ETF 推薦/評分程式使用。這是從 Phase 3 互動系統抽出的純引擎,**不含任何網頁/Flask**。

## 內容
```
preference_engine/
├─ phase3_system/      引擎(engine / core / encoder / cli)
├─ assets/             你訓練好的模型與設定(9 個 1D BNN、PhilHead、gate、題庫、校準參數)
├─ requirements.txt    相依套件
├─ integrate_example.py 整合範例(可直接執行)
└─ README.md
```
> ⚠️ `phase3_system/` 與 `assets/` **必須維持在同一層**(引擎以「phase3_system 的上一層」為根去找 assets)。整包搬移即可,不要拆開。

## 安裝
```bash
pip install -r requirements.txt
```

## 編碼器(BGE-M3)兩種模式
引擎需要 BGE-M3 來編碼文字:
- **線上(預設,免設定)**:本資料夾未附 `encoder_model/` → 首次執行自動從 Hugging Face 下載 `BAAI/bge-m3`(約 2.2 GB,需聯網一次)。
- **離線**:把原始 `phase3_interview_app/encoder_model/` 整個複製進 `preference_engine/`(與 `phase3_system/` 同層),即可斷網執行、且啟動更快。

## 最小用法
```python
import sys
sys.path.insert(0, "preference_engine")          # 指到本資料夾
from phase3_system import Phase3Engine

engine = Phase3Engine()                           # 載入模型(首次較慢)
engine.start_session("我偏好長期穩健成長,很怕大跌,重視低費用…")

while True:
    q = engine.next_question()                    # dict: step / dim_label / question
    if q is None:
        break
    ans = 你的UI取得回答(q["question"])
    snap = engine.submit_answer(ans)
    if snap["should_stop"]:                        # 引擎判斷已足夠(或你自訂何時停)
        break

weights = engine.snapshot()["Ew"]                 # ★ 9 維權重 dict,總和=1
```

或直接用範例封好的函式(見 `integrate_example.py`):
```python
from integrate_example import extract_preferences
weights, snap = extract_preferences(理念字串, answer_fn=你的取答函式)
```

## 輸出格式:`Ew`(這就是給推薦程式的接口)
9 維、總和=1 的 dict:

| dim_key | 意義 |
|---|---|
| `Return_CAGR` | 資本增值 / 長期報酬成長 |
| `Return_Div` | 股息 / 穩定現金流 |
| `Risk_Vol` | 價格波動小 / 穩健 |
| `Risk_MaxDD` | 抗跌 / 避免重大虧損 |
| `Cost_ExpRatio` | 費用率 / 管理成本 |
| `Liq_Volume` | 成交量 / 流動性 |
| `Liq_AUM` | 基金規模 / 穩定性 |
| `Div_Score` | 持股 / 產業分散度 |
| `FinBERT_score` | 市場情緒 / 新聞語氣 |

接到推薦邏輯通常就是對每支 ETF 的 9 維特徵做加權打分:
```
score(etf) = Σ  weights[dim] × etf_feature[dim]
```

`snapshot()` 另含:`ranking`(排序 + 每維 90% 信賴區間)、`Sigma_alpha`(整體確定度)、
`should_stop`、`ci_trustworthy` / `ci_note`(早停時 CI 不可信的提醒)。

## 測試
```bash
python preference_engine/integrate_example.py
```
依提示輸入理念並逐題回答,最後會印出 9 維權重長條圖與 dict。
