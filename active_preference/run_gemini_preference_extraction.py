"""從 Gemini 訪談紀錄萃取 ETF 偏好權重。

使用方式：
python active_preference/run_gemini_preference_extraction.py

預設會讀取 active_preference/results/interviews/gemini_turn_records.jsonl，
並輸出 active_preference/results/preferences/gemini_preference_profile_<timestamp>.json。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from active_preference.conversation_recorder import DEFAULT_TURN_RECORD_PATH
from active_preference.gemini_preference_extractor import (
    build_extraction_user_prompt,
    build_output_payload,
    load_turn_records,
    parse_gemini_json,
    validate_and_normalize_profile,
)
from active_preference.llm_clients import GeminiApiError, GeminiRestChatClient
from active_preference.paths import PREFERENCE_RESULTS_DIR


DEFAULT_EXTRACTION_PROMPT_PATH = (
    Path(__file__).resolve().parent / "prompts" / "gemini_preference_extraction_prompt.txt"
)


def print_progress(message: str) -> None:
    """顯示 Gemini API 進度。"""
    print(f"[status] {message}", flush=True)


def run(args: argparse.Namespace) -> None:
    """執行 Gemini 結構化偏好萃取。"""
    rows = load_turn_records(args.turn_record_input)
    system_instruction = Path(args.extraction_prompt_file).read_text(encoding="utf-8")
    user_prompt = build_extraction_user_prompt(rows)

    client = GeminiRestChatClient(
        model_name=args.gemini_model,
        fallback_model_names=tuple(args.gemini_fallback_model),
        api_key_env=args.gemini_api_key_env,
        key_source=args.gemini_key_source,
        system_instruction=system_instruction,
        temperature=args.temperature,
        max_output_tokens=args.max_output_tokens,
        response_mime_type="application/json",
        progress_callback=print_progress,
    )

    result, profile, parse_errors = request_valid_profile(
        client,
        user_prompt,
        max_parse_retries=args.max_parse_retries,
    )
    raw_text = result["model_text"]
    output_payload = build_output_payload(
        profile=profile,
        raw_model_text=raw_text,
        turn_record_input=args.turn_record_input,
        model_name=result["turn"].get("used_model_name") or args.gemini_model,
    )
    output_payload["parse_errors"] = parse_errors

    output_path = Path(args.output)
    if not args.output:
        run_id = datetime.now().strftime("%Y%m%dT%H%M%S")
        output_path = PREFERENCE_RESULTS_DIR / f"gemini_preference_profile_{run_id}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[status] Preference profile saved: {output_path}", flush=True)
    print(f"summary: {profile.get('summary', '')}")
    print(f"confidence: {profile.get('confidence', 0.0):.3f}")
    print("dimension_weights:")
    for key, value in profile["dimension_weights"].items():
        print(f"  {key}: {value:.4f}")


def request_valid_profile(
    client: GeminiRestChatClient,
    user_prompt: str,
    *,
    max_parse_retries: int,
) -> tuple[dict, dict, list[str]]:
    """要求 Gemini 輸出合法 profile；若 JSON 壞掉，請它修復一次或多次。"""
    parse_errors: list[str] = []
    prompt = user_prompt
    result: dict | None = None
    for attempt in range(max(0, max_parse_retries) + 1):
        try:
            result = client.send(prompt, user_visible=False)
        except GeminiApiError as exc:
            print(f"Gemini API error: {exc.message}")
            raise SystemExit(1) from exc

        raw_text = result["model_text"]
        try:
            parsed = parse_gemini_json(raw_text)
            profile = validate_and_normalize_profile(parsed)
            return result, profile, parse_errors
        except Exception as exc:  # noqa: BLE001 - CLI 需要把解析/驗證錯誤轉成修復 prompt
            parse_errors.append(str(exc))
            if attempt >= max_parse_retries:
                raise
            # 只要求 Gemini 修正格式，不重新解釋整段訪談，避免來回漂移。
            prompt = (
                "上一個回覆無法被本地程式解析或驗證。\n"
                f"錯誤：{exc}\n\n"
                "請只根據你上一輪的內容，修正成符合 system instruction 的嚴格 JSON。"
                "不要輸出 Markdown，不要 code fence，不要額外文字。"
            )

    raise RuntimeError("unreachable Gemini profile extraction state")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract ETF preference weights from Gemini interview records.")
    parser.add_argument("--turn-record-input", default=str(DEFAULT_TURN_RECORD_PATH))
    parser.add_argument("--extraction-prompt-file", default=str(DEFAULT_EXTRACTION_PROMPT_PATH))
    parser.add_argument("--output", default="")
    parser.add_argument("--gemini-model", default="gemini-2.5-flash-lite")
    parser.add_argument("--gemini-fallback-model", action="append", default=["gemini-2.5-flash"])
    parser.add_argument("--gemini-api-key-env", default="GEMINI_API_KEY")
    parser.add_argument("--gemini-key-source", choices=("auto", "env", "env_file"), default="auto")
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--max-output-tokens", type=int, default=3000)
    parser.add_argument("--max-parse-retries", type=int, default=1)
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
