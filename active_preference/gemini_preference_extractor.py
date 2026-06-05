"""Gemini 偏好萃取的資料整理與驗證工具。

這裡不再訓練 BNN，也不建立 feature vector；流程改成：
訪談紀錄 -> Gemini 結構化 JSON -> 本地驗證/正規化 -> results/preferences。
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .dimensions import SOLVER_DIMENSION_KEYS


JSON_FENCE_PATTERN = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)


def load_turn_records(path: str | Path) -> list[dict[str, Any]]:
    """讀取 run_real_interview.py 產生的 JSONL 訪談紀錄。"""
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"turn record not found: {source}")
    rows: list[dict[str, Any]] = []
    for line in source.read_text(encoding="utf-8-sig").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    if not rows:
        raise ValueError(f"turn record is empty: {source}")
    return rows


def format_turn_records_for_prompt(rows: list[dict[str, Any]]) -> str:
    """把訪談紀錄轉成 Gemini 容易閱讀的純文字格式。"""
    blocks: list[str] = []
    for index, row in enumerate(rows, start=1):
        question = str(row.get("advisor_question") or row.get("advisor_text") or "").strip()
        answer = str(row.get("user_text") or "").strip()
        next_question = str(row.get("next_advisor_text") or "").strip()
        blocks.append(
            "\n".join(
                [
                    f"Turn {index}",
                    f"Gemini question: {question}",
                    f"User answer: {answer}",
                    f"Gemini next message: {next_question}",
                ]
            )
        )
    return "\n\n".join(blocks)


def build_extraction_user_prompt(rows: list[dict[str, Any]]) -> str:
    """建立送給 Gemini 的使用者訊息，system prompt 則放萃取規則。"""
    return (
        "以下是 ETF 偏好訪談紀錄。請依照 system instruction 輸出嚴格 JSON。\n\n"
        f"{format_turn_records_for_prompt(rows)}"
    )


def parse_gemini_json(text: str) -> dict[str, Any]:
    """解析 Gemini JSON 回覆；若模型意外包 code fence，先保守移除。"""
    cleaned = JSON_FENCE_PATTERN.sub("", text.strip()).strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise
        parsed = json.loads(cleaned[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("Gemini extraction response must be a JSON object")
    return parsed


def validate_and_normalize_profile(payload: dict[str, Any]) -> dict[str, Any]:
    """檢查 Gemini 輸出並正規化九維權重，避免下游排序器吃到缺欄或總和錯誤。"""
    weights = payload.get("dimension_weights")
    if not isinstance(weights, dict):
        raise ValueError("missing dimension_weights object")

    cleaned_weights: dict[str, float] = {}
    for key in SOLVER_DIMENSION_KEYS:
        value = weights.get(key, 0.0)
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            numeric = 0.0
        cleaned_weights[key] = max(numeric, 0.0)

    total = sum(cleaned_weights.values())
    if total <= 1e-12:
        equal = 1.0 / len(SOLVER_DIMENSION_KEYS)
        cleaned_weights = {key: equal for key in SOLVER_DIMENSION_KEYS}
    else:
        cleaned_weights = {key: value / total for key, value in cleaned_weights.items()}

    normalized = dict(payload)
    normalized["dimension_weights"] = cleaned_weights
    normalized["dimension_rationales"] = _complete_dimension_rationales(
        normalized.get("dimension_rationales", {})
    )
    normalized["confidence"] = _clip01(normalized.get("confidence", 0.0))
    normalized["validated_at"] = datetime.now(timezone.utc).isoformat()
    normalized["validation_notes"] = [
        "dimension_weights normalized locally to sum to 1",
        "missing dimension rationales filled with empty defaults",
    ]
    return normalized


def build_output_payload(
    *,
    profile: dict[str, Any],
    raw_model_text: str,
    turn_record_input: str | Path,
    model_name: str,
) -> dict[str, Any]:
    """包裝最終輸出，保留原始模型文字方便追蹤。"""
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "method": "gemini_structured_preference_extraction",
        "turn_record_input": str(turn_record_input),
        "model_name": model_name,
        "profile": profile,
        "raw_model_text": raw_model_text,
    }


def _complete_dimension_rationales(value: Any) -> dict[str, dict[str, Any]]:
    """補齊每個維度的 rationale 欄位，讓 JSON schema 穩定。"""
    source = value if isinstance(value, dict) else {}
    completed: dict[str, dict[str, Any]] = {}
    for key in SOLVER_DIMENSION_KEYS:
        item = source.get(key, {})
        if not isinstance(item, dict):
            item = {}
        evidence = item.get("evidence", [])
        completed[key] = {
            "rationale": str(item.get("rationale", "")),
            "evidence": evidence if isinstance(evidence, list) else [str(evidence)],
            "confidence": _clip01(item.get("confidence", 0.0)),
        }
    return completed


def _clip01(value: Any) -> float:
    """把信心分數限制在 0 到 1。"""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = 0.0
    return min(max(numeric, 0.0), 1.0)
