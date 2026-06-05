"""Read/write helpers and as-of lookup for sentiment cache files."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .config import DAILY_SENTIMENT_CACHE, DEFAULT_NEUTRAL_SENTIMENT, NEWS_EVENTS_CACHE
from .schemas import DAILY_SENTIMENT_COLUMNS, NEWS_EVENT_COLUMNS


def ensure_data_dir(path: Path | str | None = None) -> None:
    """確保 sentiment cache 的資料夾存在。"""
    target = Path(path) if path is not None else DAILY_SENTIMENT_CACHE.parent
    target.mkdir(parents=True, exist_ok=True)


def _empty_frame(columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame(columns=columns)


def load_news_events(path: Path | str = NEWS_EVENTS_CACHE) -> pd.DataFrame:
    """讀取原始新聞事件 cache；若檔案不存在，回傳空表。"""
    cache_path = Path(path)
    if not cache_path.exists():
        return _empty_frame(NEWS_EVENT_COLUMNS)

    df = pd.read_csv(cache_path, low_memory=False)
    for column in NEWS_EVENT_COLUMNS:
        if column not in df.columns:
            df[column] = pd.NA
    df["ticker"] = df["ticker"].astype(str).str.strip().str.upper()
    df["published_at"] = pd.to_datetime(df["published_at"], errors="coerce")
    df["fetched_at"] = pd.to_datetime(df["fetched_at"], errors="coerce")
    return df[NEWS_EVENT_COLUMNS]


def save_news_events(df: pd.DataFrame, path: Path | str = NEWS_EVENTS_CACHE) -> None:
    """儲存原始新聞事件 cache，並用 ticker/url/published_at 去重。"""
    cache_path = Path(path)
    ensure_data_dir(cache_path.parent)

    output = df.copy()
    for column in NEWS_EVENT_COLUMNS:
        if column not in output.columns:
            output[column] = pd.NA
    output = output[NEWS_EVENT_COLUMNS]
    output["ticker"] = output["ticker"].astype(str).str.strip().str.upper()
    output["published_at"] = pd.to_datetime(output["published_at"], errors="coerce")
    output = output.drop_duplicates(subset=["ticker", "url", "published_at"], keep="last")
    output = output.sort_values(["ticker", "published_at"], na_position="last")
    output.to_csv(cache_path, index=False, encoding="utf-8-sig")


def load_daily_sentiment(path: Path | str = DAILY_SENTIMENT_CACHE) -> pd.DataFrame:
    """讀取每日 sentiment cache；若檔案不存在，回傳空表。"""
    cache_path = Path(path)
    if not cache_path.exists():
        return _empty_frame(DAILY_SENTIMENT_COLUMNS)

    df = pd.read_csv(cache_path, low_memory=False)
    for column in DAILY_SENTIMENT_COLUMNS:
        if column not in df.columns:
            df[column] = pd.NA
    df = df[DAILY_SENTIMENT_COLUMNS].copy()
    df["ticker"] = df["ticker"].astype(str).str.strip().str.upper()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["sentiment_score"] = pd.to_numeric(df["sentiment_score"], errors="coerce")
    df["news_count"] = pd.to_numeric(df["news_count"], errors="coerce").fillna(0)
    df["weighted_news_count"] = pd.to_numeric(df["weighted_news_count"], errors="coerce").fillna(0.0)
    return df


def save_daily_sentiment(df: pd.DataFrame, path: Path | str = DAILY_SENTIMENT_CACHE) -> None:
    """儲存每日 sentiment cache。"""
    cache_path = Path(path)
    ensure_data_dir(cache_path.parent)

    output = df.copy()
    for column in DAILY_SENTIMENT_COLUMNS:
        if column not in output.columns:
            output[column] = pd.NA
    output = output[DAILY_SENTIMENT_COLUMNS]
    output["ticker"] = output["ticker"].astype(str).str.strip().str.upper()
    output["date"] = pd.to_datetime(output["date"], errors="coerce")
    output = output.drop_duplicates(subset=["ticker", "date"], keep="last")
    output = output.sort_values(["ticker", "date"])
    output.to_csv(cache_path, index=False, encoding="utf-8-sig")


def _clean_tickers(tickers: list[str] | tuple[str, ...] | pd.Series) -> list[str]:
    """把 ETF 代碼標準化成大寫，避免主程式與 cache 大小寫不一致。"""
    cleaned: list[str] = []
    for ticker in tickers:
        value = str(ticker).strip().upper()
        if value and value != "NAN":
            cleaned.append(value)
    return cleaned


def get_sentiment_frame_asof(
    tickers: list[str] | tuple[str, ...] | pd.Series,
    as_of_date: str | pd.Timestamp,
    daily_df: pd.DataFrame | None = None,
    cache_path: Path | str = DAILY_SENTIMENT_CACHE,
    neutral_score: float = DEFAULT_NEUTRAL_SENTIMENT,
) -> pd.DataFrame:
    """批次取得 as-of sentiment，快取起始日前或缺資料時回傳 0.0 中性分數。"""
    clean_tickers = _clean_tickers(tickers)
    if daily_df is None:
        daily_df = load_daily_sentiment(cache_path)

    # 回測很早期的日期通常早於新聞 cache 起點；這時直接中性化，避免最佳化被缺值干擾。
    neutral_rows = pd.DataFrame(
        {
            "ticker": clean_tickers,
            "sentiment_score": float(neutral_score),
            "sentiment_date": pd.NaT,
            "news_count": 0,
            "weighted_news_count": 0.0,
        }
    )
    if not clean_tickers or daily_df.empty:
        return neutral_rows

    as_of = pd.Timestamp(as_of_date)
    cache = daily_df.copy()
    cache["ticker"] = cache["ticker"].astype(str).str.strip().str.upper()
    cache["date"] = pd.to_datetime(cache["date"], errors="coerce")
    cache = cache[
        cache["ticker"].isin(clean_tickers)
        & cache["date"].notna()
        & (cache["date"] <= as_of)
    ].copy()
    if cache.empty:
        return neutral_rows

    latest = (
        cache.sort_values(["ticker", "date"])
        .drop_duplicates(subset=["ticker"], keep="last")
        .set_index("ticker")
    )
    rows = []
    for ticker in clean_tickers:
        if ticker not in latest.index:
            rows.append(
                {
                    "ticker": ticker,
                    "sentiment_score": float(neutral_score),
                    "sentiment_date": pd.NaT,
                    "news_count": 0,
                    "weighted_news_count": 0.0,
                }
            )
            continue

        row = latest.loc[ticker]
        score = pd.to_numeric(row.get("sentiment_score"), errors="coerce")
        news_count = pd.to_numeric(row.get("news_count", 0), errors="coerce")
        weighted_news_count = pd.to_numeric(row.get("weighted_news_count", 0.0), errors="coerce")
        rows.append(
            {
                "ticker": ticker,
                "sentiment_score": float(score) if pd.notna(score) else float(neutral_score),
                "sentiment_date": row.get("date"),
                "news_count": int(news_count) if pd.notna(news_count) else 0,
                "weighted_news_count": float(weighted_news_count) if pd.notna(weighted_news_count) else 0.0,
            }
        )
    return pd.DataFrame(rows)


def get_sentiment_asof(
    ticker: str,
    as_of_date: str | pd.Timestamp,
    daily_df: pd.DataFrame | None = None,
    cache_path: Path | str = DAILY_SENTIMENT_CACHE,
    neutral_score: float = DEFAULT_NEUTRAL_SENTIMENT,
) -> float:
    """取得單一 ticker 在 as_of_date 當下可見的最近 sentiment。"""
    frame = get_sentiment_frame_asof([ticker], as_of_date, daily_df, cache_path, neutral_score)
    if frame.empty:
        return float(neutral_score)
    return float(frame.iloc[0]["sentiment_score"])


def get_sentiment_map_asof(
    tickers: list[str],
    as_of_date: str | pd.Timestamp,
    daily_df: pd.DataFrame | None = None,
    cache_path: Path | str = DAILY_SENTIMENT_CACHE,
    neutral_score: float = DEFAULT_NEUTRAL_SENTIMENT,
) -> dict[str, float]:
    """批次取得多個 ticker 在同一 as-of date 的 sentiment。"""
    frame = get_sentiment_frame_asof(tickers, as_of_date, daily_df, cache_path, neutral_score)
    return dict(zip(frame["ticker"], frame["sentiment_score"]))
