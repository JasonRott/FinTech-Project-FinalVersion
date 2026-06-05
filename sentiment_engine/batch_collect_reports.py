"""Batch collect ETF news sentiment and generate per-ticker/global reports."""

from __future__ import annotations

import argparse
import os
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

from .config import DAILY_SENTIMENT_CACHE, DEFAULT_HALF_LIFE_DAYS, DEFAULT_LOOKBACK_DAYS, NEWS_EVENTS_CACHE, SENTIMENT_DIR
from .daily_builder import build_daily_sentiment
from .finbert_scoring import load_finbert_pipeline, score_news_events
from .finnhub_fetcher import fetch_company_news, normalize_finnhub_articles
from .store import load_daily_sentiment, load_news_events, save_daily_sentiment, save_news_events


REPORTS_DIR = SENTIMENT_DIR / "reports"
PER_TICKER_REPORT_DIR = REPORTS_DIR / "per_ticker"
PER_TICKER_CSV_DIR = REPORTS_DIR / "per_ticker_csv"
PROGRESS_FILE = REPORTS_DIR / "ticker_progress.csv"
GLOBAL_REPORT_FILE = SENTIMENT_DIR / "news_sentiment_report.md"
GLOBAL_SUMMARY_FILE = REPORTS_DIR / "all_ticker_sentiment_summary.csv"


@dataclass
class TickerResult:
    ticker: str
    status: str
    articles: int
    scored_articles: int
    start_date: str
    end_date: str
    report_path: str
    error: str = ""


def _load_finnhub_key(cli_key: str | None = None) -> str:
    """讀取 Finnhub API key，優先使用 CLI，其次使用環境變數，最後讀 parameters.py。"""
    if cli_key:
        return cli_key

    env_key = os.getenv("FINNHUB_API_KEY")
    if env_key:
        return env_key

    try:
        import parameters

        key = getattr(parameters, "FINNHUB_API_KEY", "")
        if key and "Finnhub_API_Key" not in key:
            return key
    except Exception:
        pass

    raise ValueError("Cannot find Finnhub API key. Pass --api-key or set FINNHUB_API_KEY.")


def _ensure_report_dirs() -> None:
    """建立所有報告輸出資料夾。"""
    for directory in (REPORTS_DIR, PER_TICKER_REPORT_DIR, PER_TICKER_CSV_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def _load_tickers(args: argparse.Namespace) -> list[str]:
    """根據 CLI 指定來源取得 ticker 清單。"""
    if args.tickers:
        tickers = [ticker.strip().upper() for ticker in args.tickers.split(",") if ticker.strip()]
        return list(dict.fromkeys(tickers))

    df = pd.read_csv(args.ticker_source)
    if args.ticker_column not in df.columns:
        raise ValueError(f"Ticker column '{args.ticker_column}' not found in {args.ticker_source}.")

    tickers = df[args.ticker_column].dropna().astype(str).str.strip().str.upper()
    tickers = [ticker for ticker in tickers if ticker]
    if args.max_tickers:
        tickers = tickers[: args.max_tickers]
    return list(dict.fromkeys(tickers))


def _infer_voo_news_range(news_events: pd.DataFrame) -> tuple[str, str]:
    """用 VOO 現有新聞快取推定本次批次蒐集期間。"""
    voo = news_events[news_events["ticker"].astype(str).str.upper().eq("VOO")].copy()
    voo["published_at"] = pd.to_datetime(voo["published_at"], errors="coerce")
    voo = voo.dropna(subset=["published_at"])
    if voo.empty:
        raise ValueError("Cannot infer VOO news range because VOO is not available in news_events_cache.csv.")
    return (
        voo["published_at"].min().normalize().strftime("%Y-%m-%d"),
        voo["published_at"].max().normalize().strftime("%Y-%m-%d"),
    )


def _date_chunks(start_date: str, end_date: str, chunk_days: int) -> list[tuple[str, str]]:
    """將查詢期間切成多個 chunk；若資料量太大，後續會自動細切。"""
    start = pd.Timestamp(start_date).normalize()
    end = pd.Timestamp(end_date).normalize()
    if start > end:
        raise ValueError("start_date must be before end_date.")

    chunks = []
    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + pd.Timedelta(days=chunk_days - 1), end)
        chunks.append((cursor.strftime("%Y-%m-%d"), chunk_end.strftime("%Y-%m-%d")))
        cursor = chunk_end + pd.Timedelta(days=1)
    return chunks


def _fetch_chunk_adaptive(
    ticker: str,
    start_date: str,
    end_date: str,
    api_key: str,
    cap_warning: int,
    sleep_seconds: float,
    max_retries: int,
    retry_backoff_seconds: float,
) -> list[dict]:
    """抓取單一日期區間；若回傳量接近 Finnhub 上限，改用逐日補抓降低截斷風險。"""
    articles = _fetch_company_news_with_retry(
        ticker,
        start_date,
        end_date,
        api_key,
        max_retries=max_retries,
        retry_backoff_seconds=retry_backoff_seconds,
    )
    if len(articles) < cap_warning or start_date == end_date:
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)
        return articles

    all_articles = []
    for day_start, day_end in _date_chunks(start_date, end_date, 1):
        day_articles = _fetch_company_news_with_retry(
            ticker,
            day_start,
            day_end,
            api_key,
            max_retries=max_retries,
            retry_backoff_seconds=retry_backoff_seconds,
        )
        all_articles.extend(day_articles)
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)
    return all_articles


def _fetch_company_news_with_retry(
    ticker: str,
    start_date: str,
    end_date: str,
    api_key: str,
    max_retries: int,
    retry_backoff_seconds: float,
) -> list[dict]:
    """包裝 Finnhub request；遇到暫時錯誤時退避重試，避免長批次被單次錯誤中斷。"""
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return fetch_company_news(ticker, start_date, end_date, api_key)
        except Exception as exc:
            last_error = exc
            if attempt >= max_retries:
                break
            wait_seconds = retry_backoff_seconds * (attempt + 1)
            print(f"        retry {attempt + 1}/{max_retries} after error: {exc}; wait={wait_seconds:.1f}s")
            time.sleep(wait_seconds)
    raise RuntimeError(f"Finnhub fetch failed for {ticker} {start_date}->{end_date}: {last_error}")


def fetch_ticker_events(
    ticker: str,
    start_date: str,
    end_date: str,
    api_key: str,
    chunk_days: int,
    cap_warning: int,
    sleep_seconds: float,
    max_retries: int,
    retry_backoff_seconds: float,
) -> pd.DataFrame:
    """抓取單一 ETF 在指定期間的新聞；只回傳結構化資料，不分析標題或摘要內容。"""
    parts = []
    for chunk_start, chunk_end in _date_chunks(start_date, end_date, chunk_days):
        print(f"[FETCH] {ticker} {chunk_start} -> {chunk_end}")
        articles = _fetch_chunk_adaptive(
            ticker,
            chunk_start,
            chunk_end,
            api_key,
            cap_warning,
            sleep_seconds,
            max_retries,
            retry_backoff_seconds,
        )
        print(f"        articles={len(articles)}")
        if articles:
            parts.append(normalize_finnhub_articles(ticker, articles))

    if not parts:
        return pd.DataFrame()
    return pd.concat(parts, ignore_index=True)


def _merge_ticker_events(all_events: pd.DataFrame, ticker_events: pd.DataFrame) -> pd.DataFrame:
    """將單一 ETF 新資料合併回全域新聞快取，並依 store 規則去重。"""
    if ticker_events.empty:
        return all_events
    if all_events.empty:
        return ticker_events
    return pd.concat([all_events, ticker_events], ignore_index=True)


def _merge_daily_sentiment(all_daily: pd.DataFrame, ticker_daily: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """將單一 ETF daily sentiment 合併回全域 daily cache。"""
    if all_daily.empty:
        return ticker_daily
    remaining = all_daily[all_daily["ticker"].astype(str).str.upper() != ticker.upper()].copy()
    return pd.concat([remaining, ticker_daily], ignore_index=True)


def _coverage_stats(ticker_events: pd.DataFrame, start_date: str, end_date: str) -> dict[str, float | int | str]:
    """產出新聞覆蓋率，不讀取文章內容。"""
    start = pd.Timestamp(start_date).normalize()
    end = pd.Timestamp(end_date).normalize()
    calendar_index = pd.date_range(start, end, freq="D")
    business_index = pd.bdate_range(start, end)

    if ticker_events.empty:
        return {
            "calendar_days": len(calendar_index),
            "calendar_days_with_news": 0,
            "business_days": len(business_index),
            "business_days_with_news": 0,
            "calendar_coverage_pct": 0.0,
            "business_coverage_pct": 0.0,
            "first_news_date": "",
            "last_news_date": "",
        }

    events = ticker_events.copy()
    events["published_at"] = pd.to_datetime(events["published_at"], errors="coerce")
    events = events.dropna(subset=["published_at"])
    event_dates = events["published_at"].dt.normalize()
    calendar_counts = event_dates.value_counts().reindex(calendar_index, fill_value=0)
    business_counts = event_dates.value_counts().reindex(business_index, fill_value=0)
    return {
        "calendar_days": len(calendar_index),
        "calendar_days_with_news": int((calendar_counts > 0).sum()),
        "business_days": len(business_index),
        "business_days_with_news": int((business_counts > 0).sum()),
        "calendar_coverage_pct": round(float((calendar_counts > 0).mean() * 100), 4),
        "business_coverage_pct": round(float((business_counts > 0).mean() * 100), 4),
        "first_news_date": events["published_at"].min().strftime("%Y-%m-%d"),
        "last_news_date": events["published_at"].max().strftime("%Y-%m-%d"),
    }


def _ticker_summary(ticker: str, ticker_events: pd.DataFrame, ticker_daily: pd.DataFrame, start_date: str, end_date: str) -> pd.DataFrame:
    """將單一 ETF 的新聞與 daily sentiment 彙整成一列摘要。"""
    coverage = _coverage_stats(ticker_events, start_date, end_date)
    events = ticker_events.copy()
    daily = ticker_daily.copy()

    label_counts = events["finbert_label"].fillna("missing").value_counts() if not events.empty else pd.Series(dtype=int)
    source_counts = events["source"].fillna("missing").value_counts() if not events.empty else pd.Series(dtype=int)
    daily["sentiment_score"] = pd.to_numeric(daily.get("sentiment_score", pd.Series(dtype=float)), errors="coerce")

    return pd.DataFrame(
        [
            {
                "ticker": ticker,
                "articles": int(len(events)),
                "scored_articles": int(pd.to_numeric(events.get("finbert_score", pd.Series(dtype=float)), errors="coerce").notna().sum()),
                "sources": int(events["source"].nunique()) if not events.empty else 0,
                "top_source": str(source_counts.index[0]) if not source_counts.empty else "",
                "top_source_articles": int(source_counts.iloc[0]) if not source_counts.empty else 0,
                "positive_articles": int(label_counts.get("positive", 0)),
                "neutral_articles": int(label_counts.get("neutral", 0)),
                "negative_articles": int(label_counts.get("negative", 0)),
                "sentiment_mean": round(float(daily["sentiment_score"].mean()), 6) if not daily.empty else 0.0,
                "sentiment_std": round(float(daily["sentiment_score"].std()), 6) if len(daily) > 1 else 0.0,
                "sentiment_min": round(float(daily["sentiment_score"].min()), 6) if not daily.empty else 0.0,
                "sentiment_max": round(float(daily["sentiment_score"].max()), 6) if not daily.empty else 0.0,
                "latest_sentiment": round(float(daily["sentiment_score"].iloc[-1]), 6) if not daily.empty else 0.0,
                **coverage,
            }
        ]
    )


def write_ticker_report(ticker: str, ticker_events: pd.DataFrame, ticker_daily: pd.DataFrame, start_date: str, end_date: str) -> tuple[Path, pd.DataFrame]:
    """寫出單一 ETF 報告；報告只放彙總統計，不閱讀或整理文章標題/摘要。"""
    summary = _ticker_summary(ticker, ticker_events, ticker_daily, start_date, end_date)
    csv_path = PER_TICKER_CSV_DIR / f"{ticker}_sentiment_summary.csv"
    md_path = PER_TICKER_REPORT_DIR / f"{ticker}_sentiment_report.md"
    summary.to_csv(csv_path, index=False, encoding="utf-8-sig")

    events = ticker_events.copy()
    source_counts = events["source"].fillna("missing").value_counts() if not events.empty else pd.Series(dtype=int)
    label_counts = events["finbert_label"].fillna("missing").value_counts() if not events.empty else pd.Series(dtype=int)
    row = summary.iloc[0].to_dict()

    source_lines = "\n".join([f"- {source}: {count}" for source, count in source_counts.items()]) or "- no news"
    label_lines = "\n".join([f"- {label}: {count}" for label, count in label_counts.items()]) or "- no news"

    md_path.write_text(
        "\n".join(
            [
                f"# {ticker} Sentiment Data Report",
                "",
                f"- Period: {start_date} to {end_date}",
                f"- Articles: {row['articles']}",
                f"- Scored Articles: {row['scored_articles']}",
                f"- Business-Day Coverage: {row['business_days_with_news']}/{row['business_days']} ({row['business_coverage_pct']}%)",
                f"- Latest Sentiment: {row['latest_sentiment']}",
                f"- Mean Sentiment: {row['sentiment_mean']}",
                f"- Sentiment Range: {row['sentiment_min']} to {row['sentiment_max']}",
                "",
                "## Source Counts",
                source_lines,
                "",
                "## FinBERT Label Counts",
                label_lines,
                "",
                "## Method Note",
                "本報告只整理新聞數量、來源、FinBERT 標籤與每日情緒分數統計，沒有逐篇閱讀或解釋新聞標題與摘要。",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return md_path, summary


def _load_progress() -> pd.DataFrame:
    """讀取批次進度，支援中斷後續跑。"""
    if not PROGRESS_FILE.exists():
        return pd.DataFrame(columns=["ticker", "status", "articles", "scored_articles", "start_date", "end_date", "report_path", "error", "updated_at"])
    return pd.read_csv(PROGRESS_FILE)


def _save_progress(progress: pd.DataFrame, result: TickerResult) -> None:
    """每完成一檔 ETF 就立即更新進度表。"""
    row = {
        "ticker": result.ticker,
        "status": result.status,
        "articles": result.articles,
        "scored_articles": result.scored_articles,
        "start_date": result.start_date,
        "end_date": result.end_date,
        "report_path": result.report_path,
        "error": result.error,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    progress = progress[progress["ticker"].astype(str).str.upper() != result.ticker.upper()].copy()
    progress = pd.concat([progress, pd.DataFrame([row])], ignore_index=True)
    progress.sort_values("ticker").to_csv(PROGRESS_FILE, index=False, encoding="utf-8-sig")


def write_global_report(tickers: list[str], start_date: str, end_date: str) -> Path:
    """彙整所有單檔報告，產出 sentiment_engine 最上層的總報告。"""
    summaries = []
    for csv_path in sorted(PER_TICKER_CSV_DIR.glob("*_sentiment_summary.csv")):
        df = pd.read_csv(csv_path)
        summaries.append(df)

    if summaries:
        summary_df = pd.concat(summaries, ignore_index=True)
        summary_df = summary_df[summary_df["ticker"].astype(str).str.upper().isin([ticker.upper() for ticker in tickers])]
    else:
        summary_df = pd.DataFrame()

    if not summary_df.empty:
        summary_df.sort_values("ticker").to_csv(GLOBAL_SUMMARY_FILE, index=False, encoding="utf-8-sig")
        completed = len(summary_df)
        with_news = int((summary_df["articles"] > 0).sum())
        avg_business_coverage = round(float(summary_df["business_coverage_pct"].mean()), 4)
        avg_latest_sentiment = round(float(summary_df["latest_sentiment"].mean()), 6)
        top_sources = summary_df["top_source"].replace("", pd.NA).dropna().value_counts().head(10)
        source_lines = "\n".join([f"- {source}: {count} ETF(s) as top source" for source, count in top_sources.items()]) or "- no source data"
        low_coverage = summary_df.sort_values("business_coverage_pct").head(15)
        low_coverage_lines = "\n".join(
            [
                f"- {row.ticker}: {row.business_coverage_pct}% coverage, {row.articles} articles"
                for row in low_coverage.itertuples(index=False)
            ]
        )
    else:
        completed = 0
        with_news = 0
        avg_business_coverage = 0.0
        avg_latest_sentiment = 0.0
        source_lines = "- no source data"
        low_coverage_lines = "- no coverage data"

    GLOBAL_REPORT_FILE.write_text(
        "\n".join(
            [
                "# ETF News Sentiment Coverage Report",
                "",
                f"- Period: {start_date} to {end_date}",
                f"- Target ETF Count: {len(tickers)}",
                f"- Completed ETF Reports: {completed}",
                f"- ETFs With At Least One News Article: {with_news}",
                f"- Average Business-Day Coverage: {avg_business_coverage}%",
                f"- Average Latest Sentiment: {avg_latest_sentiment}",
                "",
                "## Method",
                "每篇新聞只用 FinBERT 推論一次並寫入 `data/news_events_cache.csv`。每日 sentiment 採用「同日新聞先平均，再對每日分數做時間衰減加權」，避免單日新聞量直接放大權重。沒有新聞時分數為 0.0，代表中性。",
                "",
                "## Top Source Pattern",
                source_lines,
                "",
                "## Lowest Coverage ETFs",
                low_coverage_lines,
                "",
                "## Output Files",
                f"- Per-ETF markdown reports: `{PER_TICKER_REPORT_DIR}`",
                f"- Per-ETF CSV summaries: `{PER_TICKER_CSV_DIR}`",
                f"- Global CSV summary: `{GLOBAL_SUMMARY_FILE}`",
                f"- Progress file: `{PROGRESS_FILE}`",
                "",
                "## Interpretation Boundary",
                "本報告用來檢查新聞情緒資料是否足以支援學術報告中的使用者偏好維度，不把 sentiment 當成獨立的報酬預測模型。",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return GLOBAL_REPORT_FILE


def process_ticker(
    ticker: str,
    start_date: str,
    end_date: str,
    api_key: str,
    args: argparse.Namespace,
    all_events: pd.DataFrame,
    all_daily: pd.DataFrame,
    finbert,
) -> tuple[pd.DataFrame, pd.DataFrame, TickerResult]:
    """完成單一 ETF 的抓取、評分、daily cache 與報告。"""
    fetched_events = pd.DataFrame()
    if not args.skip_fetch:
        fetched_events = fetch_ticker_events(
            ticker,
            start_date,
            end_date,
            api_key,
            args.chunk_days,
            args.cap_warning,
            args.sleep_seconds,
            args.max_retries,
            args.retry_backoff_seconds,
        )

    all_events = _merge_ticker_events(all_events, fetched_events)
    save_news_events(all_events, NEWS_EVENTS_CACHE)
    all_events = load_news_events(NEWS_EVENTS_CACHE)

    ticker_events = all_events[all_events["ticker"].astype(str).str.upper().eq(ticker.upper())].copy()
    ticker_events["published_at"] = pd.to_datetime(ticker_events["published_at"], errors="coerce")
    ticker_events = ticker_events[
        (ticker_events["published_at"] >= pd.Timestamp(start_date))
        & (ticker_events["published_at"] < pd.Timestamp(end_date) + pd.Timedelta(days=1))
    ].copy()

    if not ticker_events.empty:
        scored_ticker = score_news_events(ticker_events, finbert=finbert)
        rest = all_events[~all_events.index.isin(ticker_events.index)].copy()
        all_events = pd.concat([rest, scored_ticker], ignore_index=True)
        save_news_events(all_events, NEWS_EVENTS_CACHE)
        all_events = load_news_events(NEWS_EVENTS_CACHE)
        ticker_events = all_events[all_events["ticker"].astype(str).str.upper().eq(ticker.upper())].copy()
        ticker_events["published_at"] = pd.to_datetime(ticker_events["published_at"], errors="coerce")
        ticker_events = ticker_events[
            (ticker_events["published_at"] >= pd.Timestamp(start_date))
            & (ticker_events["published_at"] < pd.Timestamp(end_date) + pd.Timedelta(days=1))
        ].copy()

    ticker_daily = build_daily_sentiment(
        ticker_events,
        tickers=[ticker],
        start_date=start_date,
        end_date=end_date,
        lookback_days=args.lookback_days,
        half_life_days=args.half_life_days,
    )
    all_daily = _merge_daily_sentiment(all_daily, ticker_daily, ticker)
    save_daily_sentiment(all_daily, DAILY_SENTIMENT_CACHE)
    all_daily = load_daily_sentiment(DAILY_SENTIMENT_CACHE)

    report_path, summary = write_ticker_report(ticker, ticker_events, ticker_daily, start_date, end_date)
    row = summary.iloc[0]
    result = TickerResult(
        ticker=ticker,
        status="completed",
        articles=int(row["articles"]),
        scored_articles=int(row["scored_articles"]),
        start_date=start_date,
        end_date=end_date,
        report_path=str(report_path),
    )
    return all_events, all_daily, result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Batch collect ETF news sentiment and generate reports.")
    parser.add_argument("--ticker-source", default="csv/stage0_final_matrix.csv")
    parser.add_argument("--ticker-column", default="ETF")
    parser.add_argument("--tickers", default=None, help="Optional comma-separated tickers for partial runs.")
    parser.add_argument("--max-tickers", type=int, default=None)
    parser.add_argument("--start-date", default=None, help="Default: infer from VOO cache.")
    parser.add_argument("--end-date", default=None, help="Default: infer from VOO cache.")
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--chunk-days", type=int, default=30)
    parser.add_argument("--cap-warning", type=int, default=220)
    parser.add_argument("--sleep-seconds", type=float, default=1.0)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--retry-backoff-seconds", type=float, default=10.0)
    parser.add_argument("--lookback-days", type=int, default=DEFAULT_LOOKBACK_DAYS)
    parser.add_argument("--half-life-days", type=int, default=DEFAULT_HALF_LIFE_DAYS)
    parser.add_argument("--skip-fetch", action="store_true", help="Only rebuild reports/cache from existing news_events_cache.")
    parser.add_argument("--force", action="store_true", help="Reprocess tickers even if progress says completed.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    _ensure_report_dirs()

    all_events = load_news_events(NEWS_EVENTS_CACHE)
    inferred_start, inferred_end = _infer_voo_news_range(all_events)
    start_date = args.start_date or inferred_start
    end_date = args.end_date or inferred_end
    tickers = _load_tickers(args)
    progress = _load_progress()
    completed = set(
        progress.loc[progress["status"].astype(str).eq("completed"), "ticker"].astype(str).str.upper()
    )
    api_key = "" if args.skip_fetch else _load_finnhub_key(args.api_key)
    finbert = load_finbert_pipeline()
    all_daily = load_daily_sentiment(DAILY_SENTIMENT_CACHE)

    print(f"[CONFIG] tickers={len(tickers)} period={start_date} -> {end_date} skip_fetch={args.skip_fetch}")
    for idx, ticker in enumerate(tickers, start=1):
        if not args.force and ticker.upper() in completed:
            print(f"[SKIP] {idx}/{len(tickers)} {ticker} already completed")
            continue

        print(f"[START] {idx}/{len(tickers)} {ticker}")
        try:
            all_events, all_daily, result = process_ticker(
                ticker,
                start_date,
                end_date,
                api_key,
                args,
                all_events,
                all_daily,
                finbert,
            )
        except Exception as exc:
            result = TickerResult(
                ticker=ticker,
                status="failed",
                articles=0,
                scored_articles=0,
                start_date=start_date,
                end_date=end_date,
                report_path="",
                error=str(exc),
            )
            print(f"[FAILED] {ticker}: {exc}")

        progress = _load_progress()
        _save_progress(progress, result)
        print(f"[DONE] {ticker} status={result.status} articles={result.articles} scored={result.scored_articles}")

    report_path = write_global_report(tickers, start_date, end_date)
    print(f"[GLOBAL_REPORT] {report_path}")


if __name__ == "__main__":
    main()
