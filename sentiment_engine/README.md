# Sentiment Engine

這個資料夾專門處理新聞擷取、FinBERT 推論、每日 sentiment cache，以及不同 sentiment 算法測試。主系統與回測系統之後只需要從這裡讀取指定日期以前的 sentiment 分數，避免把新聞處理邏輯塞回主程式。

## 資料檔案

1. `data/news_events_cache.csv`
   - 每一列是一篇新聞。
   - 每篇新聞只做一次 FinBERT 推論，之後直接讀取快取。
   - 主要欄位：`ticker`, `published_at`, `source`, `title`, `summary`, `url`, `finbert_score`, `finbert_label`, `finbert_confidence`, `fetched_at`。

2. `data/sentiment_daily_cache.csv`
   - 每一列是一個 `ticker` 在某個 `date` 的 as-of sentiment。
   - 由 `news_events_cache.csv` 轉換而來。
   - 沒有可用新聞時，分數為 `0.0`，代表中性。

## 計算邏輯

目前 daily sentiment 採用「每日先平均，再跨日衰減」：

```text
daily_score_d = mean(finbert_score of all news on day d)
weight_d = exp(-ln(2) * age_days_d / half_life_days)
sentiment(date) = sum(daily_score_d * weight_d) / sum(weight_d)
```

這樣設計是為了避免某一天新聞量暴增時，該日自動取得過大的權重。新聞篇數仍會保留在 `news_count`，方便檢查資料覆蓋率。

預設參數：

```text
lookback_days = 180
half_life_days = 60
neutral_score = 0.0
```

## 接入方式

主系統 Stage 0 可用：

```python
from sentiment_engine.store import get_sentiment_map_asof

sentiment_map = get_sentiment_map_asof(tickers, as_of_date)
```

回測系統在每個 rebalance date 可用：

```python
sentiment_map = get_sentiment_map_asof(tickers, rebalance_date)
```

## 常用指令

只用既有新聞快取重建每日 sentiment：

```powershell
python -m sentiment_engine.daily_builder --start-date 2016-05-20 --end-date 2026-05-22
```

比較 VOO 的 30D、90D、180D blend 30D 算法：

```powershell
python -m sentiment_engine.compare_algorithms --ticker VOO
```
