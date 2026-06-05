# ETF News Sentiment Coverage Report

- Period: 2025-09-12 to 2026-05-22
- Target ETF Count: 522
- Completed ETF Reports: 522
- ETFs With At Least One News Article: 503
- Average Business-Day Coverage: 36.045%
- Average Latest Sentiment: 0.065441

## Method
每篇新聞只用 FinBERT 推論一次並寫入 `data/news_events_cache.csv`。每日 sentiment 採用「同日新聞先平均，再對每日分數做時間衰減加權」，避免單日新聞量直接放大權重。沒有新聞時分數為 0.0，代表中性。

## Top Source Pattern
- SeekingAlpha: 435 ETF(s) as top source
- Benzinga: 36 ETF(s) as top source
- Yahoo: 32 ETF(s) as top source

## Lowest Coverage ETFs
- JPEF: 0.0% coverage, 0 articles
- DUHP: 0.0% coverage, 0 articles
- EEMV: 0.0% coverage, 0 articles
- BGIG: 0.0% coverage, 0 articles
- MSLC: 0.0% coverage, 0 articles
- ILOW: 0.0% coverage, 0 articles
- CGXU: 0.0% coverage, 0 articles
- BAFE: 0.0% coverage, 0 articles
- DFUV: 0.0% coverage, 0 articles
- APUE: 0.0% coverage, 0 articles
- DFEM: 0.0% coverage, 0 articles
- DFSU: 0.0% coverage, 0 articles
- USCL: 0.0% coverage, 0 articles
- FELV: 0.0% coverage, 0 articles
- CGGE: 0.0% coverage, 0 articles

## Output Files
- Per-ETF markdown reports: `C:\Users\lojas\OneDrive\Desktop\我的大四下\Fintech\Fintech project\sentiment_engine\reports\per_ticker`
- Per-ETF CSV summaries: `C:\Users\lojas\OneDrive\Desktop\我的大四下\Fintech\Fintech project\sentiment_engine\reports\per_ticker_csv`
- Global CSV summary: `C:\Users\lojas\OneDrive\Desktop\我的大四下\Fintech\Fintech project\sentiment_engine\reports\all_ticker_sentiment_summary.csv`
- Progress file: `C:\Users\lojas\OneDrive\Desktop\我的大四下\Fintech\Fintech project\sentiment_engine\reports\ticker_progress.csv`

## Interpretation Boundary
本報告用來檢查新聞情緒資料是否足以支援學術報告中的使用者偏好維度，不把 sentiment 當成獨立的報酬預測模型。
