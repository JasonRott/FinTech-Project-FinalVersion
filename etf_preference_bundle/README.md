# etf_preference_bundle —— 金融偏好誘出(函式庫版 + 網頁版,二合一)

把投資者的「投資理念 + 逐輪問答」轉成 **9 維 ETF 偏好權重**(總和=1),交給你的 ETF 推薦主程式。
本包同時提供兩種使用模式,**共用同一套引擎、模型,以及同一個推薦接點**。

```
etf_preference_bundle/
├─ phase3_system/        引擎(共用)
├─ assets/               模型與設定(共用:9 個 1D BNN、PhilHead、gate、題庫、校準)
├─ recommender_hook.py   ★ 唯一要改的檔:在這裡接你的 ETF 推薦模組
├─ integrate_example.py  函式庫版:在 Python 程式裡跑問答
├─ run_web.py            網頁版:本機啟動(http://127.0.0.1:8000)
├─ run_hf.py             網頁版:雲端/Hugging Face 部署用
├─ web/                  Flask 後端 + 前端(完成時自動交付權重)
│  ├─ app.py
│  ├─ integration.py     (轉接層,指向 recommender_hook.py,不用改)
│  ├─ static/  templates/
├─ requirements.txt
└─ README.md
```

## 安裝
```bash
pip install -r requirements.txt
```

## ★ 第一步:接上你的推薦程式(只改這一個檔)
打開 `recommender_hook.py`,在 `deliver_weights()` 裡 import 你的模組:
```python
def deliver_weights(weights, snapshot=None):
    from your_recommender import recommend     # 你的可 import 模組
    return recommend(weights)                   # weights = 9 維 dict,總和=1
```
**改完這一處,網頁版與函式庫版就都接好了。**

## 兩種使用模式

### A) 網頁版(瀏覽器問答)
```bash
python run_web.py        # 開 http://127.0.0.1:8000
```
使用者在網頁上完成問答後,系統會自動:
1. 呼叫 `recommender_hook.deliver_weights(weights, snapshot)`(in-process 交付)
2. 寫一份 `web/last_result.json`(供外部程式讀取)
3. 你也可以用 `GET /api/result` 取得最近一次結果(`{weights, snapshot, delivered}`)

### B) 函式庫版(程式內問答,不開網頁)
```python
import sys; sys.path.insert(0, "etf_preference_bundle")
from integrate_example import run

weights, snapshot, result = run(投資理念字串, answer_fn=你的取答函式)
# weights 已自動經 recommender_hook 交付給你的推薦程式
```
或只取權重、自己決定後續:
```python
from phase3_system import Phase3Engine
e = Phase3Engine(); e.start_session(理念)
while (q := e.next_question()):
    e.submit_answer(你的回答(q))
    if e.snapshot()["should_stop"]: break
weights = e.snapshot()["Ew"]
```

## 輸出格式(9 維權重)
| dim_key | 意義 |
|---|---|
| `Return_CAGR` | 資本增值 / 長期報酬 |
| `Return_Div` | 股息 / 現金流 |
| `Risk_Vol` | 波動穩健 |
| `Risk_MaxDD` | 抗跌 |
| `Cost_ExpRatio` | 費用率 |
| `Liq_Volume` | 成交量 |
| `Liq_AUM` | 基金規模 |
| `Div_Score` | 分散度 |
| `FinBERT_score` | 市場情緒 |

接推薦邏輯通常就是加權打分:`score(etf) = Σ weights[dim] × etf_feature[dim]`。
(權重已含讀出層 cold-start 處理:早停時未問維顯示先驗值;問滿 9 題則為純後驗。)

## 編碼器(BGE-M3)
- 預設**線上**:本包未附 `encoder_model/` → 首次自動下載 `BAAI/bge-m3`(約 2.2 GB,需聯網一次)。
- **離線**:把原始 `phase3_interview_app/encoder_model/` 整個複製進本資料夾(與 `phase3_system/` 同層)。

## 測試
```bash
python integrate_example.py      # 函式庫版,跟著提示輸入即可
# 或
python run_web.py                # 網頁版
```
