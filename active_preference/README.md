# Active Preference

這個資料夾現在採用簡化後的主線：**Gemini 訪談 + Gemini 結構化偏好萃取**。

先前的 BNN、Deep Ensemble、feature encoder、synthetic training data、AHP/RF/XGBoost/Siamese 等實驗流程已放棄，不再作為後續開發方向。

## 目前流程

1. 使用 Gemini 進行 ETF 偏好訪談。
2. 將訪談逐輪保存到 `active_preference/results/interviews/`。
3. 訪談結束後，再用 Gemini 讀取完整訪談紀錄，輸出九維度偏好權重與理由。
4. 本地程式只做 JSON 解析、欄位補齊、權重正規化與保存，不再訓練模型。

## 主要指令

### 1. 執行訪談

```powershell
python active_preference/run_real_interview.py
```

輸出：

```text
active_preference/results/interviews/gemini_real_interview_transcript.json
active_preference/results/interviews/gemini_turn_records.jsonl
```

### 2. 萃取偏好

```powershell
python active_preference/run_gemini_preference_extraction.py
```

預設輸入：

```text
active_preference/results/interviews/gemini_turn_records.jsonl
```

輸出：

```text
active_preference/results/preferences/gemini_preference_profile_<timestamp>.json
```

### 3. 執行 Gemini 萃取 benchmark

```powershell
python active_preference/run_gemini_extraction_benchmark.py
```

用途：

```text
使用既有 benchmark cases 檢查 Gemini 萃取 prompt 的 Spearman、Top1、Top2、L1 / MAE 等指標。
```

### 4. 重跑既有 benchmark 結果

```powershell
python active_preference/run_gemini_benchmark_reextract.py
```

用途：

```text
在不重新生成訪談資料的前提下，對既有訪談紀錄重新套用目前的 Gemini extraction prompt。
```

## 九個偏好維度

- `Return_CAGR`：長期資本成長
- `Return_Div`：股息現金流
- `Risk_Vol`：低波動穩定度
- `Risk_MaxDD`：抗跌與回撤控制
- `Cost_ExpRatio`：低內扣成本
- `Liq_Volume`：成交流動性
- `Liq_AUM`：基金規模
- `Div_Score`：投資組合分散度
- `FinBERT_score`：市場情緒與新聞品質

## API key

建議在專案根目錄或 `active_preference/.env` 放：

```text
GEMINI_API_KEY=你的 Gemini API key
```

程式也會讀取 shell 環境變數 `GEMINI_API_KEY`。

## 保留的核心檔案

```text
conversation_recorder.py
dimensions.py
gemini_preference_extractor.py
interview_rules.py
llm_clients.py
paths.py
prompt_loader.py
run_real_interview.py
run_gemini_preference_extraction.py
run_gemini_extraction_benchmark.py
run_gemini_benchmark_reextract.py
prompts/gemini_interview_prompts.txt
prompts/gemini_preference_extraction_prompt.txt
```

## 最終整理包

```text
active_preference/results/final_package_20260428/
```

這裡保存過去 BNN / Deep Ensemble 路線的訓練資料、模型 artifacts、超參數摘要、正式失敗報告與 Gemini benchmark 結果。後續若要做 prompt engineering，建議從這個資料夾挑選 regression samples，而不是恢復舊的 BNN pipeline。

## 設計原則

- Gemini 全權控制訪談問題。
- 偏好萃取也直接交給 Gemini，但必須輸出可驗證的 JSON。
- 本地程式不再嘗試用 BNN 或其他傳統模型解碼偏好。
- 本地只負責保存紀錄、解析 JSON、正規化權重與產出結果。
