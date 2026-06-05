"""執行 Gemini ETF 偏好訪談。

這支程式只負責讓 Gemini 控制訪談流程，並把每一輪
「Gemini 問題 -> 使用者回答 -> Gemini 下一題」保存成 JSONL。
偏好萃取改由 run_gemini_preference_extraction.py 在訪談結束後處理。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from active_preference.conversation_recorder import (
    DEFAULT_TURN_RECORD_PATH,
    ConversationDataRecorder,
)
from active_preference.interview_rules import is_interview_done, validate_gemini_reply
from active_preference.llm_clients import GeminiApiError, GeminiRestChatClient
from active_preference.paths import REAL_INTERVIEW_TRANSCRIPT_PATH
from active_preference.prompt_loader import DEFAULT_PROMPT_PATH, load_gemini_prompt_config


def print_progress(message: str) -> None:
    """把 Gemini API 狀態印到終端機，方便確認目前是否在等待回覆。"""
    print(f"[status] {message}", flush=True)


def write_json(path: Path, payload: dict[str, Any]) -> Path:
    """保存完整 transcript，供日後除錯或重新萃取偏好。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def build_transcript_payload(
    client: GeminiRestChatClient,
    created_at: str,
    updated_at: str,
    args: argparse.Namespace,
) -> dict[str, Any]:
    """整理訪談 metadata 與 Gemini transcript。"""
    return {
        "created_at": created_at,
        "updated_at": updated_at,
        "api_key_env": args.gemini_api_key_env,
        "key_source": args.gemini_key_source,
        "model_name": args.gemini_model,
        "fallback_model_names": args.gemini_fallback_model,
        "turn_record_path": args.turn_record_output,
        "transcript": client.transcript.to_dict(),
    }


def annotate_latest_turn(client: GeminiRestChatClient, model_text: str) -> list[str]:
    """檢查 Gemini 是否違反訪談規則，並把警告寫回 transcript。"""
    warnings = validate_gemini_reply(model_text)
    if client.transcript.turns:
        client.transcript.turns[-1]["reply_rule_warnings"] = warnings
    if warnings:
        print(f"[rule-warning] {', '.join(warnings)}", flush=True)
    return warnings


def run_interview(args: argparse.Namespace) -> None:
    """啟動互動式訪談。"""
    prompt_config = load_gemini_prompt_config(args.gemini_prompt_file)
    created_at = datetime.now(timezone.utc).isoformat()

    advisor_client = GeminiRestChatClient(
        model_name=args.gemini_model,
        fallback_model_names=tuple(args.gemini_fallback_model),
        api_key_env=args.gemini_api_key_env,
        key_source=args.gemini_key_source,
        system_instruction=prompt_config.system_instruction,
        progress_callback=print_progress,
    )
    turn_recorder = ConversationDataRecorder(args.turn_record_output)
    transcript_path = Path(args.transcript_output)

    print("\nGemini ETF 偏好訪談。輸入 exit 或 quit 可結束。\n")
    print("[status] Asking Gemini advisor to start the interview...", flush=True)

    try:
        start_result = advisor_client.send(prompt_config.start_prompt, user_visible=False)
        annotate_latest_turn(advisor_client, start_result["model_text"])
        print("\nGemini:")
        print(start_result["model_text"])
        print()
    except GeminiApiError as exc:
        print(f"Gemini API error: {exc.message}")
        return

    pending_advisor_question = start_result["model_text"]
    write_json(
        transcript_path,
        build_transcript_payload(
            advisor_client,
            created_at,
            datetime.now(timezone.utc).isoformat(),
            args,
        ),
    )

    while True:
        user_text = input("You: ").strip()
        if not user_text or user_text.lower() in {"exit", "quit"}:
            break

        print("[status] Sending your answer to Gemini advisor...", flush=True)
        try:
            advisor_result = advisor_client.send(user_text)
            warnings = annotate_latest_turn(advisor_client, advisor_result["model_text"])
        except GeminiApiError as exc:
            print(f"Gemini API error: {exc.message}")
            continue

        print("\nGemini:")
        print(advisor_result["model_text"])
        print()

        done = is_interview_done(advisor_result["model_text"])
        latest_turn = advisor_client.transcript.turns[-1]
        turn_path = turn_recorder.append_interview_exchange(
            turn=latest_turn,
            advisor_question=pending_advisor_question,
            interview_done=done,
        )
        if turn_path:
            print(f"[status] Turn record saved: {turn_path}", flush=True)

        write_json(
            transcript_path,
            build_transcript_payload(
                advisor_client,
                created_at,
                datetime.now(timezone.utc).isoformat(),
                args,
            ),
        )

        if warnings:
            print("[status] Advisor reply has rule warnings; record kept for review.", flush=True)
        if done:
            print("[status] Interview completed. Run preference extraction next.", flush=True)
            break

        pending_advisor_question = advisor_result["model_text"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a real Gemini ETF preference interview.")
    parser.add_argument("--gemini-model", default="gemini-2.5-flash-lite")
    parser.add_argument("--gemini-fallback-model", action="append", default=["gemini-2.5-flash"])
    parser.add_argument("--gemini-api-key-env", default="GEMINI_API_KEY")
    parser.add_argument("--gemini-key-source", choices=("auto", "env", "env_file"), default="auto")
    parser.add_argument("--gemini-prompt-file", default=str(DEFAULT_PROMPT_PATH))
    parser.add_argument("--transcript-output", default=str(REAL_INTERVIEW_TRANSCRIPT_PATH))
    parser.add_argument("--turn-record-output", default=str(DEFAULT_TURN_RECORD_PATH))
    return parser.parse_args()


if __name__ == "__main__":
    run_interview(parse_args())
