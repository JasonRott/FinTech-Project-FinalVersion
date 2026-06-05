"""Finnhub news fetching helpers for sentiment cache construction."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import requests

from .schemas import NEWS_EVENT_COLUMNS


def fetch_company_news(ticker: str, start_date: str, end_date: str, api_key: str, timeout: int = 10) -> list[dict]:
    """從 Finnhub 抓取單一 ticker 的 company news。"""
    url = "https://finnhub.io/api/v1/company-news"
    params = {"symbol": ticker, "from": start_date, "to": end_date, "token": api_key}
    response = requests.get(url, params=params, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, list) else []


def normalize_finnhub_articles(ticker: str, articles: list[dict], fetched_at: str | None = None) -> pd.DataFrame:
    """把 Finnhub 原始新聞轉成 news_events_cache schema。"""
    fetched_at = fetched_at or datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    for article in articles:
        published_ts = article.get("datetime")
        published_at = pd.to_datetime(published_ts, unit="s", errors="coerce") if published_ts else pd.NaT
        rows.append(
            {
                "ticker": ticker,
                "published_at": published_at,
                "source": article.get("source", ""),
                "title": article.get("headline", ""),
                "summary": article.get("summary", ""),
                "url": article.get("url", ""),
                "finbert_score": pd.NA,
                "finbert_label": pd.NA,
                "finbert_confidence": pd.NA,
                "fetched_at": fetched_at,
            }
        )
    return pd.DataFrame(rows, columns=NEWS_EVENT_COLUMNS)
