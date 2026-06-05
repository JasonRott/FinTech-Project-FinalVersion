"""Build daily as-of sentiment cache from scored news events."""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from .config import (
    DAILY_SENTIMENT_CACHE,
    DEFAULT_HALF_LIFE_DAYS,
    DEFAULT_LOOKBACK_DAYS,
    DEFAULT_NEUTRAL_SENTIMENT,
    NEWS_EVENTS_CACHE,
)
from .schemas import DAILY_SENTIMENT_COLUMNS
from .store import load_news_events, save_daily_sentiment


def _build_daily_news_scores(ticker_news: pd.DataFrame) -> pd.DataFrame:
    """把逐篇新聞整理成每日平均分數，避免單日新聞量直接放大權重。"""
    if ticker_news.empty:
        return pd.DataFrame(columns=["news_date", "daily_score", "news_count"])

    daily_news = ticker_news.copy()
    daily_news["news_date"] = daily_news["published_at"].dt.normalize()
    return (
        daily_news.groupby("news_date", as_index=False)
        .agg(daily_score=("finbert_score", "mean"), news_count=("finbert_score", "size"))
        .sort_values("news_date")
    )


def build_daily_sentiment(
    news_events: pd.DataFrame,
    tickers: list[str] | None = None,
    start_date: str | pd.Timestamp | None = None,
    end_date: str | pd.Timestamp | None = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    half_life_days: int = DEFAULT_HALF_LIFE_DAYS,
    business_days_only: bool = True,
    neutral_score: float = DEFAULT_NEUTRAL_SENTIMENT,
) -> pd.DataFrame:
    """由逐篇新聞 FinBERT 分數建立每日 as-of sentiment cache。

    計算邏輯：
    1. 同一 ticker、同一天的新聞先平均成 daily_score。
    2. 對 lookback window 內的 daily_score 做時間衰減加權。

    這樣可以保留新聞方向，同時避免某一天新聞量暴增時，單日敘事過度支配整體情緒分數。
    """
    if news_events.empty and not tickers:
        return pd.DataFrame(columns=DAILY_SENTIMENT_COLUMNS)

    df = news_events.copy()
    if df.empty:
        df = pd.DataFrame(columns=["ticker", "published_at", "finbert_score"])
    else:
        df["published_at"] = pd.to_datetime(df["published_at"], errors="coerce")
        df["finbert_score"] = pd.to_numeric(df["finbert_score"], errors="coerce")
        df = df.dropna(subset=["ticker", "published_at", "finbert_score"])

    if df.empty and not tickers:
        return pd.DataFrame(columns=DAILY_SENTIMENT_COLUMNS)

    selected_tickers = sorted(set(tickers or df["ticker"].dropna().astype(str)))
    if not selected_tickers:
        return pd.DataFrame(columns=DAILY_SENTIMENT_COLUMNS)
    if df.empty and (start_date is None or end_date is None):
        raise ValueError("start_date and end_date are required when building neutral sentiment for tickers without news.")

    start = pd.Timestamp(start_date) if start_date else df["published_at"].min().normalize()
    end = pd.Timestamp(end_date) if end_date else pd.Timestamp.today().normalize()
    date_index = pd.bdate_range(start, end) if business_days_only else pd.date_range(start, end, freq="D")

    decay_lambda = np.log(2.0) / float(half_life_days)
    rows = []
    for ticker in selected_tickers:
        ticker_news = df[df["ticker"] == ticker].sort_values("published_at")
        daily_news = _build_daily_news_scores(ticker_news)

        for date in date_index:
            # date 視為「當日收盤後」的 as-of 時點，因此可使用 date 當天已發布的新聞。
            day_end = date.normalize() + pd.Timedelta(days=1)
            window_start = day_end - pd.Timedelta(days=lookback_days)
            usable = daily_news[
                (daily_news["news_date"] < day_end)
                & (daily_news["news_date"] >= window_start.normalize())
            ]

            if usable.empty:
                rows.append(
                    {
                        "date": date.strftime("%Y-%m-%d"),
                        "ticker": ticker,
                        "sentiment_score": neutral_score,
                        "news_count": 0,
                        "weighted_news_count": 0.0,
                        "lookback_days": lookback_days,
                        "half_life_days": half_life_days,
                    }
                )
                continue

            # 同日新聞已先平均；當天 age=0、昨天 age=1，衰減只反映日期遠近，不反映篇數多寡。
            age_days = (day_end - (usable["news_date"] + pd.Timedelta(days=1))).dt.total_seconds() / 86400.0
            weights = np.exp(-decay_lambda * np.maximum(age_days, 0.0))
            weighted_score = float(np.dot(usable["daily_score"].values, weights) / weights.sum())

            rows.append(
                {
                    "date": date.strftime("%Y-%m-%d"),
                    "ticker": ticker,
                    "sentiment_score": round(max(-1.0, min(1.0, weighted_score)), 6),
                    "news_count": int(usable["news_count"].sum()),
                    "weighted_news_count": round(float(weights.sum()), 6),
                    "lookback_days": lookback_days,
                    "half_life_days": half_life_days,
                }
            )

    return pd.DataFrame(rows, columns=DAILY_SENTIMENT_COLUMNS)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build daily sentiment cache from scored news events.")
    parser.add_argument("--news-events", default=str(NEWS_EVENTS_CACHE))
    parser.add_argument("--output", default=str(DAILY_SENTIMENT_CACHE))
    parser.add_argument("--start-date", default=None)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--lookback-days", type=int, default=DEFAULT_LOOKBACK_DAYS)
    parser.add_argument("--half-life-days", type=int, default=DEFAULT_HALF_LIFE_DAYS)
    parser.add_argument("--calendar-days", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    news_events = load_news_events(args.news_events)
    daily = build_daily_sentiment(
        news_events,
        start_date=args.start_date,
        end_date=args.end_date,
        lookback_days=args.lookback_days,
        half_life_days=args.half_life_days,
        business_days_only=not args.calendar_days,
    )
    save_daily_sentiment(daily, args.output)
    print(f"Saved {len(daily)} daily sentiment rows to {args.output}")


if __name__ == "__main__":
    main()
