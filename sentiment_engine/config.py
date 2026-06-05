"""Sentiment engine path and calculation defaults."""

from pathlib import Path


SENTIMENT_DIR = Path(__file__).resolve().parent
DATA_DIR = SENTIMENT_DIR / "data"

NEWS_EVENTS_CACHE = DATA_DIR / "news_events_cache.csv"
DAILY_SENTIMENT_CACHE = DATA_DIR / "sentiment_daily_cache.csv"

# 目前沿用原系統 180 天新聞窗口，並保留半衰期讓衰減速度可獨立調整。
DEFAULT_LOOKBACK_DAYS = 180
DEFAULT_HALF_LIFE_DAYS = 60
DEFAULT_NEUTRAL_SENTIMENT = 0.0
