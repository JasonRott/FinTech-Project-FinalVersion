"""FinBERT scoring utilities for cached news events."""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def load_finbert_pipeline(model_dir: str | Path = "local_finbert"):
    """載入本地 FinBERT pipeline；transformers 只在需要推論時才載入。"""
    from transformers import pipeline

    return pipeline("sentiment-analysis", model=str(model_dir), tokenizer=str(model_dir))


def score_text(finbert, title: str = "", summary: str = "", max_chars: int = 500) -> tuple[float, str, float]:
    """用 FinBERT 將新聞文字轉成 -1 到 1 的情緒分數。"""
    text = f"{title}. {summary}".strip()[:max_chars]
    if not text or text == ".":
        return 0.0, "neutral", 0.0

    result = finbert(text)[0]
    label = str(result.get("label", "neutral")).lower()
    confidence = float(result.get("score", 0.0))

    if label == "positive":
        return confidence, label, confidence
    if label == "negative":
        return -confidence, label, confidence
    return 0.0, label, confidence


def score_news_events(news_events: pd.DataFrame, finbert=None) -> pd.DataFrame:
    """替缺少 FinBERT 分數的新聞事件補分數。"""
    output = news_events.copy()
    if output.empty:
        return output

    if finbert is None:
        finbert = load_finbert_pipeline()

    for column in ["finbert_score", "finbert_label", "finbert_confidence"]:
        if column not in output.columns:
            output[column] = pd.NA
    output["finbert_score"] = pd.to_numeric(output["finbert_score"], errors="coerce")
    output["finbert_label"] = output["finbert_label"].astype("object")
    output["finbert_confidence"] = pd.to_numeric(output["finbert_confidence"], errors="coerce")

    missing_mask = output["finbert_score"].isna()
    for idx, row in output[missing_mask].iterrows():
        score, label, confidence = score_text(
            finbert,
            title=str(row.get("title", "")),
            summary=str(row.get("summary", "")),
        )
        output.at[idx, "finbert_score"] = score
        output.at[idx, "finbert_label"] = label
        output.at[idx, "finbert_confidence"] = confidence

    return output
