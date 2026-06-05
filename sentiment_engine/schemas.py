"""Column schemas for sentiment cache files."""


NEWS_EVENT_COLUMNS = [
    "ticker",
    "published_at",
    "source",
    "title",
    "summary",
    "url",
    "finbert_score",
    "finbert_label",
    "finbert_confidence",
    "fetched_at",
]

DAILY_SENTIMENT_COLUMNS = [
    "date",
    "ticker",
    "sentiment_score",
    "news_count",
    "weighted_news_count",
    "lookback_days",
    "half_life_days",
]
