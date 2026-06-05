"""把每一輪 Gemini 訪談整理成後續模型可讀的資料列。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .paths import REAL_INTERVIEW_TURN_RECORD_PATH

DEFAULT_TURN_RECORD_PATH = REAL_INTERVIEW_TURN_RECORD_PATH


@dataclass
class ConversationTurnRecord:
    """單輪使用者與顧問對話的乾淨資料格式。"""

    turn: int
    user_text: str
    advisor_text: str
    model_name: str
    recorded_at: str
    model_thought_summary: str = ""
    reply_rule_warnings: list[str] = field(default_factory=list)
    interview_done: bool = False
    advisor_question: str = ""
    next_advisor_text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ConversationDataRecorder:
    """把完成的一輪對話 append 到 JSONL 檔案。

    目前這個 recorder 只是把資料寫檔；下一步的 Bayesian updater 可以把
    這個類別換成「直接呼叫語意萃取模型」或「送進 belief tracker」。
    """

    def __init__(self, output_path: str | Path = DEFAULT_TURN_RECORD_PATH) -> None:
        self.output_path = Path(output_path)
        self.output_path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, record: ConversationTurnRecord) -> Path:
        """新增一輪資料到 JSONL。"""
        with self.output_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
        return self.output_path

    def append_gemini_turn(
        self,
        turn: dict[str, Any],
        interview_done: bool,
    ) -> Path | None:
        """從 Gemini transcript turn 取出後續模型需要的欄位。"""
        if not turn.get("user_visible", True):
            return None

        record = ConversationTurnRecord(
            turn=int(turn.get("turn", 0)),
            user_text=str(turn.get("user_input", "")),
            advisor_text=str(turn.get("model_response", "")),
            model_name=str(turn.get("used_model_name") or turn.get("primary_model_name") or ""),
            model_thought_summary=str(turn.get("model_thought_summary", "")),
            reply_rule_warnings=list(turn.get("reply_rule_warnings", [])),
            interview_done=interview_done,
            recorded_at=datetime.now(timezone.utc).isoformat(),
            metadata={
                "finish_reason": turn.get("finish_reason"),
                "usage_metadata": turn.get("usage_metadata", {}),
            },
        )
        return self.append(record)

    def build_interview_exchange_record(
        self,
        turn: dict[str, Any],
        advisor_question: str,
        interview_done: bool,
    ) -> ConversationTurnRecord | None:
        """建立「顧問問題 -> 使用者回答 -> 顧問下一句」的資料列。

        Gemini transcript 的一個 turn 會把「使用者本輪輸入」和「Gemini 本輪回覆」
        放在一起。但在訪談中，使用者本輪輸入其實是在回答上一個 Gemini 問題。
        因此 decoder 應該讀到上一個問題，而不是回答後才出現的下一個問題。
        """
        if not turn.get("user_visible", True):
            return None

        next_advisor_text = str(turn.get("model_response", ""))
        return ConversationTurnRecord(
            turn=int(turn.get("turn", 0)),
            user_text=str(turn.get("user_input", "")),
            advisor_text=advisor_question,
            model_name=str(turn.get("used_model_name") or turn.get("primary_model_name") or ""),
            model_thought_summary=str(turn.get("model_thought_summary", "")),
            reply_rule_warnings=list(turn.get("reply_rule_warnings", [])),
            interview_done=interview_done,
            advisor_question=advisor_question,
            next_advisor_text=next_advisor_text,
            recorded_at=datetime.now(timezone.utc).isoformat(),
            metadata={
                "finish_reason": turn.get("finish_reason"),
                "usage_metadata": turn.get("usage_metadata", {}),
            },
        )

    def append_interview_exchange(
        self,
        turn: dict[str, Any],
        advisor_question: str,
        interview_done: bool,
    ) -> Path | None:
        """寫入已對齊的訪談交換資料列。"""
        record = self.build_interview_exchange_record(
            turn=turn,
            advisor_question=advisor_question,
            interview_done=interview_done,
        )
        if record is None:
            return None
        return self.append(record)
