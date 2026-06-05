"""Gemini 訪談回覆的本地規則檢查。"""

from __future__ import annotations


INTERVIEW_DONE_MARKERS = (
    "訪談到此結束",
    "完成這次的 ETF 偏好訪談",
    "完成這次 ETF 偏好訪談",
    "感謝您的參與",
    "謝謝您完成",
)

MAX_VISIBLE_REPLY_CHARS = 180


def is_interview_done(model_text: str) -> bool:
    """判斷 Gemini 是否已經用固定語意結束訪談。"""
    normalized = model_text.replace(" ", "")
    return any(marker.replace(" ", "") in normalized for marker in INTERVIEW_DONE_MARKERS)


def validate_gemini_reply(model_text: str) -> list[str]:
    """檢查 Gemini 回覆是否違反我們的訪談規則。"""
    warnings = []
    normalized = model_text.strip()
    question_count = normalized.count("?") + normalized.count("？")
    done = is_interview_done(normalized)

    if "THOUGHT" in normalized.upper():
        warnings.append("reply_contains_thought_marker")
    if len(normalized) > MAX_VISIBLE_REPLY_CHARS:
        warnings.append(f"reply_too_long:{len(normalized)}>{MAX_VISIBLE_REPLY_CHARS}")
    if not done and question_count == 0:
        warnings.append("reply_has_no_question_before_completion")
    if not done and question_count > 1:
        warnings.append(f"reply_has_multiple_questions:{question_count}")
    if done and question_count > 0:
        warnings.append("completion_reply_should_not_ask_question")

    return warnings
