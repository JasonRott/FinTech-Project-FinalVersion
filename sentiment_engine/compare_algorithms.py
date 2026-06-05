"""Compare alternative sentiment algorithms for a single ticker."""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .config import DEFAULT_NEUTRAL_SENTIMENT, NEWS_EVENTS_CACHE
from .store import load_news_events


PLOTS_DIR = Path(__file__).resolve().parent / "plots"
COMPARISON_DIR = PLOTS_DIR / "algorithm_comparison"


def _build_daily_news_scores(ticker_news: pd.DataFrame) -> pd.DataFrame:
    """把逐篇新聞整理成每日平均分數，讓演算法測試與正式 daily cache 保持一致。"""
    if ticker_news.empty:
        return pd.DataFrame(columns=["news_date", "daily_score", "news_count"])

    daily_news = ticker_news.copy()
    daily_news["news_date"] = daily_news["published_at"].dt.normalize()
    return (
        daily_news.groupby("news_date", as_index=False)
        .agg(daily_score=("finbert_score", "mean"), news_count=("finbert_score", "size"))
        .sort_values("news_date")
    )


def _decayed_sentiment_for_date(
    ticker_news: pd.DataFrame,
    date: pd.Timestamp,
    lookback_days: int,
    half_life_days: int,
    neutral_score: float = DEFAULT_NEUTRAL_SENTIMENT,
) -> tuple[float, int, float]:
    """計算單日 as-of sentiment。

    採用「每日先平均，再跨日衰減」：同一天新聞很多時，只會先形成一個 daily_score，
    不會因為篇數多就自動取得更大的 sentiment 權重。
    """
    day_end = date.normalize() + pd.Timedelta(days=1)
    window_start = day_end - pd.Timedelta(days=lookback_days)
    daily_news = _build_daily_news_scores(ticker_news)
    usable = daily_news[
        (daily_news["news_date"] < day_end)
        & (daily_news["news_date"] >= window_start.normalize())
    ]
    if usable.empty:
        return float(neutral_score), 0, 0.0

    decay_lambda = np.log(2.0) / float(half_life_days)
    age_days = (day_end - (usable["news_date"] + pd.Timedelta(days=1))).dt.total_seconds() / 86400.0
    weights = np.exp(-decay_lambda * np.maximum(age_days, 0.0))
    score = float(np.dot(usable["daily_score"].values, weights) / weights.sum())
    return float(max(-1.0, min(1.0, score))), int(usable["news_count"].sum()), float(weights.sum())


def build_algorithm_series(
    news_events: pd.DataFrame,
    ticker: str,
    start_date: str | pd.Timestamp,
    end_date: str | pd.Timestamp,
    algorithm: str,
    business_days_only: bool = True,
) -> pd.DataFrame:
    """建立單一 ticker 在指定算法下的 sentiment series。"""
    ticker = ticker.upper()
    df = news_events[news_events["ticker"] == ticker].copy()
    df["published_at"] = pd.to_datetime(df["published_at"], errors="coerce")
    df["finbert_score"] = pd.to_numeric(df["finbert_score"], errors="coerce")
    df = df.dropna(subset=["published_at", "finbert_score"]).sort_values("published_at")

    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    date_index = pd.bdate_range(start, end) if business_days_only else pd.date_range(start, end, freq="D")
    rows = []

    for date in date_index:
        if algorithm == "30D":
            score, count, weighted_count = _decayed_sentiment_for_date(df, date, 30, 15)
            components = {"score_30d": score, "score_90d": np.nan, "score_180d": np.nan}
        elif algorithm == "90D":
            score, count, weighted_count = _decayed_sentiment_for_date(df, date, 90, 30)
            components = {"score_30d": np.nan, "score_90d": score, "score_180d": np.nan}
        elif algorithm == "BLEND_180D_30D":
            score_30d, count_30d, weighted_30d = _decayed_sentiment_for_date(df, date, 30, 15)
            score_180d, count_180d, weighted_180d = _decayed_sentiment_for_date(df, date, 180, 60)
            # 50/50 blend 保留長期敘事，也讓最近 30 天有明確影響。
            score = 0.5 * score_30d + 0.5 * score_180d
            count = count_180d
            weighted_count = weighted_180d
            components = {"score_30d": score_30d, "score_90d": np.nan, "score_180d": score_180d}
        else:
            raise ValueError(f"Unsupported algorithm: {algorithm}")

        rows.append(
            {
                "date": date.strftime("%Y-%m-%d"),
                "ticker": ticker,
                "algorithm": algorithm,
                "sentiment_score": round(float(score), 6),
                "news_count": count,
                "weighted_news_count": round(float(weighted_count), 6),
                **components,
            }
        )

    return pd.DataFrame(rows)


def plot_algorithm_series(df: pd.DataFrame, ticker: str, algorithm: str, output_dir: Path = COMPARISON_DIR) -> Path:
    """輸出演算法 sentiment 走勢圖。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    plot_df = df.copy()
    plot_df["date"] = pd.to_datetime(plot_df["date"], errors="coerce")
    plot_df["sentiment_score"] = pd.to_numeric(plot_df["sentiment_score"], errors="coerce")
    plot_df["news_count"] = pd.to_numeric(plot_df["news_count"], errors="coerce").fillna(0)
    plot_df = plot_df.dropna(subset=["date", "sentiment_score"]).sort_values("date")

    fig, ax = plt.subplots(figsize=(13, 6))
    ax.plot(plot_df["date"], plot_df["sentiment_score"], color="#2563EB", linewidth=1.9, label=algorithm)
    ax.axhline(0, color="#111827", linewidth=1, linestyle="--", alpha=0.7)
    ax.fill_between(
        plot_df["date"],
        plot_df["sentiment_score"],
        0,
        where=plot_df["sentiment_score"] >= 0,
        color="#22C55E",
        alpha=0.18,
        interpolate=True,
    )
    ax.fill_between(
        plot_df["date"],
        plot_df["sentiment_score"],
        0,
        where=plot_df["sentiment_score"] < 0,
        color="#EF4444",
        alpha=0.18,
        interpolate=True,
    )
    ax.set_title(f"{ticker} Sentiment Algorithm Test: {algorithm}", fontsize=14, fontweight="bold")
    ax.set_xlabel("Date")
    ax.set_ylabel("Sentiment Score")
    ax.set_ylim(-1.05, 1.05)
    ax.grid(True, alpha=0.25)

    ax_news = ax.twinx()
    ax_news.bar(plot_df["date"], plot_df["news_count"], color="#94A3B8", alpha=0.22, label="News Count", width=3)
    ax_news.set_ylabel("News Count in Algorithm Window")

    lines, labels = ax.get_legend_handles_labels()
    bars, bar_labels = ax_news.get_legend_handles_labels()
    ax.legend(lines + bars, labels + bar_labels, loc="upper left")
    fig.tight_layout()

    output_path = output_dir / f"{ticker}_{algorithm}.png"
    fig.savefig(output_path, dpi=300)
    plt.close(fig)
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare VOO sentiment algorithms.")
    parser.add_argument("--ticker", default="VOO")
    parser.add_argument("--start-date", default=None)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--output-csv", default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ticker = args.ticker.upper()
    news_events = load_news_events(NEWS_EVENTS_CACHE)
    ticker_news = news_events[news_events["ticker"] == ticker].copy()
    ticker_news["published_at"] = pd.to_datetime(ticker_news["published_at"], errors="coerce")
    ticker_news = ticker_news.dropna(subset=["published_at"])
    if ticker_news.empty:
        raise ValueError(f"No news events found for {ticker}.")

    start_date = args.start_date or ticker_news["published_at"].min().normalize().strftime("%Y-%m-%d")
    end_date = args.end_date or ticker_news["published_at"].max().normalize().strftime("%Y-%m-%d")
    algorithms = ["30D", "90D", "BLEND_180D_30D"]

    all_parts = []
    for algorithm in algorithms:
        series = build_algorithm_series(news_events, ticker, start_date, end_date, algorithm)
        all_parts.append(series)
        output_path = plot_algorithm_series(series, ticker, algorithm)
        print(f"[PLOT] {output_path}")

    combined = pd.concat(all_parts, ignore_index=True)
    output_csv = Path(args.output_csv) if args.output_csv else COMPARISON_DIR / f"{ticker}_algorithm_comparison.csv"
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(output_csv, index=False, encoding="utf-8-sig")
    print(f"[CSV] {output_csv}")


if __name__ == "__main__":
    main()
