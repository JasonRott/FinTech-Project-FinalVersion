"""End-to-end builder for sentiment news events, FinBERT scores, daily cache, and plots."""

from __future__ import annotations

import argparse
import os
import time
from datetime import datetime
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from .config import (
    DAILY_SENTIMENT_CACHE,
    DATA_DIR,
    DEFAULT_HALF_LIFE_DAYS,
    DEFAULT_LOOKBACK_DAYS,
    NEWS_EVENTS_CACHE,
)
from .daily_builder import build_daily_sentiment
from .finbert_scoring import score_news_events
from .finnhub_fetcher import fetch_company_news, normalize_finnhub_articles
from .store import load_news_events, save_daily_sentiment, save_news_events


PLOTS_DIR = Path(__file__).resolve().parent / "plots"


def _load_finnhub_key(cli_key: str | None = None) -> str:
    """優先使用 CLI/env key；若沒有，再嘗試讀取專案原本 parameters.py 的 Finnhub key。"""
    if cli_key:
        return cli_key

    env_key = os.getenv("FINNHUB_API_KEY")
    if env_key:
        return env_key

    try:
        import parameters

        key = getattr(parameters, "FINNHUB_API_KEY", "")
        if key and "請填入" not in key and "Finnhub_API_Key" not in key:
            return key
    except Exception:
        pass

    raise ValueError("Cannot find Finnhub API key. Pass --api-key or set FINNHUB_API_KEY.")


def _date_chunks(start_date: str, end_date: str, chunk_days: int) -> list[tuple[str, str]]:
    """把長區間切成多個 API 查詢區間，降低單次請求失敗風險。"""
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


def fetch_news_events_for_tickers(
    tickers: list[str],
    start_date: str,
    end_date: str,
    api_key: str,
    chunk_days: int,
    sleep_seconds: float,
) -> pd.DataFrame:
    """抓取多個 ticker 的新聞事件，回傳符合 news_events_cache schema 的表格。"""
    all_parts = []
    chunks = _date_chunks(start_date, end_date, chunk_days)

    for ticker in tickers:
        for chunk_start, chunk_end in chunks:
            print(f"[FETCH] {ticker} {chunk_start} -> {chunk_end}")
            try:
                articles = fetch_company_news(ticker, chunk_start, chunk_end, api_key)
                if articles:
                    all_parts.append(normalize_finnhub_articles(ticker, articles))
                    print(f"        articles={len(articles)}")
                    if len(articles) >= 240:
                        print(
                            "        warning: article count is close to Finnhub response cap; "
                            "use a smaller --chunk-days to avoid truncation."
                        )
                else:
                    print("        articles=0")
            except Exception as exc:
                print(f"        failed: {exc}")
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)

    if not all_parts:
        return pd.DataFrame()
    return pd.concat(all_parts, ignore_index=True)


def plot_ticker_sentiment(
    daily_df: pd.DataFrame,
    ticker: str,
    output_dir: Path = PLOTS_DIR,
    output_name: str | None = None,
) -> Path:
    """畫出單一 ticker 的每日 sentiment 變化，用來檢查 cache 是否合理。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    ticker_df = daily_df[daily_df["ticker"] == ticker].copy()
    if ticker_df.empty:
        raise ValueError(f"No daily sentiment rows for ticker: {ticker}")

    ticker_df["date"] = pd.to_datetime(ticker_df["date"], errors="coerce")
    ticker_df["sentiment_score"] = pd.to_numeric(ticker_df["sentiment_score"], errors="coerce")
    ticker_df["news_count"] = pd.to_numeric(ticker_df["news_count"], errors="coerce").fillna(0)
    ticker_df = ticker_df.dropna(subset=["date", "sentiment_score"]).sort_values("date")

    fig, ax = plt.subplots(figsize=(13, 6))
    ax.plot(
        ticker_df["date"],
        ticker_df["sentiment_score"],
        color="#2563EB",
        linewidth=1.8,
        label="Daily Decayed Sentiment",
    )
    ax.axhline(0, color="#111827", linewidth=1, linestyle="--", alpha=0.7)
    ax.fill_between(
        ticker_df["date"],
        ticker_df["sentiment_score"],
        0,
        where=ticker_df["sentiment_score"] >= 0,
        color="#22C55E",
        alpha=0.18,
        interpolate=True,
    )
    ax.fill_between(
        ticker_df["date"],
        ticker_df["sentiment_score"],
        0,
        where=ticker_df["sentiment_score"] < 0,
        color="#EF4444",
        alpha=0.18,
        interpolate=True,
    )
    ax.set_title(f"{ticker} Market Sentiment (FinBERT, 180-day Exponential Decay)", fontsize=14, fontweight="bold")
    ax.set_xlabel("Date")
    ax.set_ylabel("Sentiment Score")
    ax.set_ylim(-1.05, 1.05)
    ax.grid(True, alpha=0.25)

    ax_news = ax.twinx()
    ax_news.bar(
        ticker_df["date"],
        ticker_df["news_count"],
        color="#94A3B8",
        alpha=0.22,
        label="News Count",
        width=3,
    )
    ax_news.set_ylabel("News Count in 180-day Window")

    lines, labels = ax.get_legend_handles_labels()
    bars, bar_labels = ax_news.get_legend_handles_labels()
    ax.legend(lines + bars, labels + bar_labels, loc="upper left")
    fig.tight_layout()

    output_path = output_dir / (output_name or f"{ticker}_sentiment.png")
    fig.savefig(output_path, dpi=300)
    plt.close(fig)
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch, score, build, and plot sentiment cache.")
    parser.add_argument("--tickers", default="VOO", help="Comma-separated tickers, e.g. VOO,VT.")
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", default=datetime.today().strftime("%Y-%m-%d"))
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--chunk-days", type=int, default=7)
    parser.add_argument("--sleep-seconds", type=float, default=1.0)
    parser.add_argument("--lookback-days", type=int, default=DEFAULT_LOOKBACK_DAYS)
    parser.add_argument("--half-life-days", type=int, default=DEFAULT_HALF_LIFE_DAYS)
    parser.add_argument("--plot-ticker", default="VOO")
    parser.add_argument("--skip-fetch", action="store_true")
    parser.add_argument("--skip-score", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    tickers = [ticker.strip().upper() for ticker in args.tickers.split(",") if ticker.strip()]
    existing_events = load_news_events(NEWS_EVENTS_CACHE)

    if args.skip_fetch:
        merged_events = existing_events
    else:
        api_key = _load_finnhub_key(args.api_key)
        fetched_events = fetch_news_events_for_tickers(
            tickers,
            args.start_date,
            args.end_date,
            api_key,
            args.chunk_days,
            args.sleep_seconds,
        )
        if existing_events.empty:
            merged_events = fetched_events
        elif fetched_events.empty:
            merged_events = existing_events
        else:
            merged_events = pd.concat([existing_events, fetched_events], ignore_index=True)
        save_news_events(merged_events, NEWS_EVENTS_CACHE)
        merged_events = load_news_events(NEWS_EVENTS_CACHE)
        print(f"[CACHE] news_events rows={len(merged_events)} path={NEWS_EVENTS_CACHE}")

    if not args.skip_score:
        scored_events = score_news_events(merged_events)
        save_news_events(scored_events, NEWS_EVENTS_CACHE)
        merged_events = load_news_events(NEWS_EVENTS_CACHE)
        scored_count = pd.to_numeric(merged_events["finbert_score"], errors="coerce").notna().sum()
        print(f"[SCORE] scored rows={scored_count}/{len(merged_events)}")

    daily = build_daily_sentiment(
        merged_events,
        tickers=tickers,
        start_date=args.start_date,
        end_date=args.end_date,
        lookback_days=args.lookback_days,
        half_life_days=args.half_life_days,
    )
    save_daily_sentiment(daily, DAILY_SENTIMENT_CACHE)
    print(f"[DAILY] rows={len(daily)} path={DAILY_SENTIMENT_CACHE}")

    if args.plot_ticker:
        output_path = plot_ticker_sentiment(daily, args.plot_ticker.upper())
        print(f"[PLOT] {output_path}")
        plot_ticker = args.plot_ticker.upper()
        plot_df = daily[daily["ticker"] == plot_ticker].copy()
        plot_df["news_count"] = pd.to_numeric(plot_df["news_count"], errors="coerce").fillna(0)
        plot_df["date"] = pd.to_datetime(plot_df["date"], errors="coerce")
        nonzero = plot_df[plot_df["news_count"] > 0]
        if not nonzero.empty:
            zoom_start = (nonzero["date"].min() - pd.Timedelta(days=30)).strftime("%Y-%m-%d")
            zoom_df = plot_df[plot_df["date"] >= zoom_start]
            zoom_output = plot_ticker_sentiment(
                zoom_df,
                plot_ticker,
                PLOTS_DIR,
                output_name=f"{plot_ticker}_sentiment_zoom.png",
            )
            print(f"[PLOT] {zoom_output}")


if __name__ == "__main__":
    main()
