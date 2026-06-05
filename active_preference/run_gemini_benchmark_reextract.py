"""用既有 benchmark 訪談資料重跑 Gemini 萃取階段。

用途：當 extraction prompt 改版時，不需要重新產生 10 題或模擬回答，
只重跑「完整訪談 -> 偏好 profile」這一步，降低測試成本並方便公平比較。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from active_preference.paths import PREFERENCE_RESULTS_DIR, REPORTS_DIR
from active_preference.run_gemini_extraction_benchmark import (
    DEFAULT_EXTRACTION_PROMPT_PATH,
    evaluate_weights,
    extract_profile,
    summarize_metrics,
    write_markdown_report,
)


def run(args: argparse.Namespace) -> None:
    """讀取舊 benchmark JSON，重跑每筆 extraction。"""
    source = Path(args.input)
    payload = json.loads(source.read_text(encoding="utf-8"))
    run_id = args.run_id or datetime.now().strftime("%Y%m%dT%H%M%S")
    output_json = PREFERENCE_RESULTS_DIR / f"gemini_extraction_benchmark_reextract_{run_id}.json"
    output_jsonl = PREFERENCE_RESULTS_DIR / f"gemini_extraction_benchmark_reextract_records_{run_id}.jsonl"
    output_md = REPORTS_DIR / f"gemini_extraction_benchmark_reextract_{run_id}.md"
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)

    records = []
    with output_jsonl.open("w", encoding="utf-8") as file:
        for index, old_record in enumerate(payload["records"], start=1):
            sample_id = old_record["sample_id"]
            print(f"[status] Re-extract sample {index}/{len(payload['records'])}: {sample_id}", flush=True)
            try:
                extracted_profile, raw_extraction_text = extract_profile(
                    args,
                    rows=old_record["interview_rows"],
                )
                metrics = evaluate_weights(old_record["target_weights"], extracted_profile["dimension_weights"])
                record = {
                    "sample_id": sample_id,
                    "profile_type": old_record["profile_type"],
                    "target_weights": old_record["target_weights"],
                    "status": "ok",
                    "questions": old_record["questions"],
                    "interview_rows": old_record["interview_rows"],
                    "extracted_profile": extracted_profile,
                    "raw_extraction_text": raw_extraction_text,
                    "metrics": metrics,
                }
            except Exception as exc:  # noqa: BLE001 - benchmark 要保留失敗樣本
                record = {
                    "sample_id": sample_id,
                    "profile_type": old_record["profile_type"],
                    "target_weights": old_record["target_weights"],
                    "status": "failed",
                    "error": str(exc),
                }
            records.append(record)
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
            file.flush()

    new_payload = {
        "run_id": run_id,
        "source_benchmark": str(source),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "count": len(records),
        "questions": payload.get("questions", []),
        "summary": summarize_metrics(records),
        "records": records,
    }
    output_json.write_text(json.dumps(new_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown_report(new_payload, output_md)
    print(f"[status] Re-extract JSON saved: {output_json}", flush=True)
    print(f"[status] Re-extract JSONL saved: {output_jsonl}", flush=True)
    print(f"[status] Re-extract report saved: {output_md}", flush=True)
    print(json.dumps(new_payload["summary"], ensure_ascii=False, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Re-run Gemini extraction on an existing benchmark dataset.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--run-id", default="")
    parser.add_argument("--extraction-prompt-file", default=str(DEFAULT_EXTRACTION_PROMPT_PATH))
    parser.add_argument("--gemini-model", default="gemini-2.5-flash-lite")
    parser.add_argument("--gemini-fallback-model", action="append", default=["gemini-2.5-flash"])
    parser.add_argument("--gemini-api-key-env", default="GEMINI_API_KEY")
    parser.add_argument("--gemini-key-source", choices=("auto", "env", "env_file"), default="auto")
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--max-parse-retries", type=int, default=1)
    parser.add_argument("--max-retry-delay-seconds", type=float, default=30.0)
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
