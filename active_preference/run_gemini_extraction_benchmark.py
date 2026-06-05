"""20 筆 Gemini 偏好萃取 benchmark。

流程：
1. 本地產生 20 組格狀 target weights。
2. Gemini 顧問一次產生 10 題 ETF 偏好題。
3. Gemini 模擬使用者依照每組 target weights 回答全部題目。
4. Gemini 萃取者閱讀完整 Q/A，輸出九維偏好權重。
5. 本地比較推論權重與 target weights，輸出 Spearman、L1、MAE、Top1/Top2。
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from active_preference.dimensions import (
    DIMENSION_LABELS_ZH,
    SOLVER_DIMENSION_KEYS,
    dimension_descriptions_for_prompt,
    normalize_weights,
)
from active_preference.gemini_preference_extractor import (
    build_extraction_user_prompt,
    parse_gemini_json,
    validate_and_normalize_profile,
)
from active_preference.llm_clients import GeminiApiError, GeminiRestChatClient
from active_preference.paths import PREFERENCE_RESULTS_DIR, REPORTS_DIR


DEFAULT_EXTRACTION_PROMPT_PATH = (
    Path(__file__).resolve().parent / "prompts" / "gemini_preference_extraction_prompt.txt"
)


def print_progress(message: str) -> None:
    """顯示 Gemini API 呼叫狀態。"""
    print(f"[status] {message}", flush=True)


def make_client(
    args: argparse.Namespace,
    *,
    system_instruction: str,
    temperature: float,
    max_output_tokens: int,
    response_mime_type: str | None = "application/json",
) -> GeminiRestChatClient:
    """建立一次性 Gemini client；不同角色分開建，避免聊天歷史互相干擾。"""
    return GeminiRestChatClient(
        model_name=args.gemini_model,
        fallback_model_names=tuple(args.gemini_fallback_model),
        api_key_env=args.gemini_api_key_env,
        key_source=args.gemini_key_source,
        system_instruction=system_instruction,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        response_mime_type=response_mime_type,
        progress_callback=print_progress,
        max_retries=args.max_retries,
        max_retry_delay_seconds=args.max_retry_delay_seconds,
    )


def generate_grid_weights(count: int = 20) -> list[dict[str, Any]]:
    """產生 20 組 deterministic grid 權重，涵蓋單一主導、雙主導與均衡型。"""
    keys = list(SOLVER_DIMENSION_KEYS)
    profiles: list[dict[str, Any]] = []

    for index, key in enumerate(keys):
        raw = {dim: 0.035 + 0.003 * ((i + index) % 5) for i, dim in enumerate(keys)}
        raw[key] = 0.48
        raw[keys[(index + 1) % len(keys)]] += 0.10
        profiles.append(
            {
                "sample_id": f"grid_single_{index + 1:02d}_{key}",
                "profile_type": "single_dominant",
                "target_weights": normalize_weights(raw, SOLVER_DIMENSION_KEYS),
            }
        )

    for index, key in enumerate(keys):
        pair_key = keys[(index + 3) % len(keys)]
        raw = {dim: 0.035 + 0.002 * ((i * 2 + index) % 7) for i, dim in enumerate(keys)}
        raw[key] = 0.33
        raw[pair_key] = 0.28
        profiles.append(
            {
                "sample_id": f"grid_pair_{index + 1:02d}_{key}_{pair_key}",
                "profile_type": "pair_dominant",
                "target_weights": normalize_weights(raw, SOLVER_DIMENSION_KEYS),
            }
        )

    balanced_raw = {key: 0.10 + 0.005 * index for index, key in enumerate(keys)}
    defensive_raw = {
        "Return_CAGR": 0.10,
        "Return_Div": 0.13,
        "Risk_Vol": 0.18,
        "Risk_MaxDD": 0.20,
        "Cost_ExpRatio": 0.13,
        "Liq_Volume": 0.08,
        "Liq_AUM": 0.07,
        "Div_Score": 0.08,
        "FinBERT_score": 0.03,
    }
    profiles.extend(
        [
            {
                "sample_id": "grid_balanced_19",
                "profile_type": "balanced",
                "target_weights": normalize_weights(balanced_raw, SOLVER_DIMENSION_KEYS),
            },
            {
                "sample_id": "grid_defensive_income_20",
                "profile_type": "defensive_income",
                "target_weights": normalize_weights(defensive_raw, SOLVER_DIMENSION_KEYS),
            },
        ]
    )
    return profiles[:count]


def generate_advisor_questions(args: argparse.Namespace) -> list[str]:
    """請 Gemini 顧問一次產生 10 題，不讓它看到任何 target weights。"""
    system_instruction = (
        "你是 ETF 偏好訪談顧問。請設計能辨識 ETF 投資偏好的問題。"
        "輸出嚴格 JSON，不要 Markdown。"
    )
    user_prompt = (
        "請一次產生 10 題繁體中文 ETF 偏好訪談問題。"
        "問題要覆蓋報酬、風險、成本、流動性、分散度、新聞情緒等面向。"
        "不要提到任何內部維度 key，也不要要求使用者直接填數字權重。\n\n"
        f"內部維度參考：\n{dimension_descriptions_for_prompt()}\n\n"
        '輸出格式：{"questions":["問題1", "..."]}'
    )
    client = make_client(
        args,
        system_instruction=system_instruction,
        temperature=0.3,
        max_output_tokens=1800,
    )
    result = client.send(user_prompt, user_visible=False)
    payload = parse_gemini_json(result["model_text"])
    questions = payload.get("questions", [])
    if not isinstance(questions, list) or len(questions) != 10:
        raise ValueError("advisor must return exactly 10 questions")
    return [str(question).strip() for question in questions]


def simulate_user_answers(
    args: argparse.Namespace,
    *,
    questions: list[str],
    target_weights: dict[str, float],
    sample_id: str,
) -> list[dict[str, Any]]:
    """讓 Gemini 依照隱藏 target weights 扮演使用者回答 10 題。"""
    weight_lines = "\n".join(
        f"- {key} ({DIMENSION_LABELS_ZH[key]}): {target_weights[key]:.4f}"
        for key in SOLVER_DIMENSION_KEYS
    )
    question_lines = "\n".join(f"{index + 1}. {question}" for index, question in enumerate(questions))
    system_instruction = (
        "你是 ETF 投資偏好測試中的模擬使用者。"
        "你會收到隱藏的真實偏好權重，請用自然、前後一致的繁體中文回答問題。"
        "不要直接暴露數字權重或維度 key，但回答內容要反映這些偏好。"
        "輸出嚴格 JSON，不要 Markdown。"
    )
    user_prompt = (
        f"sample_id: {sample_id}\n\n"
        f"隱藏真實偏好權重：\n{weight_lines}\n\n"
        f"請依序回答以下 10 題：\n{question_lines}\n\n"
        '輸出格式：{"answers":[{"question_index":1,"answer":"..."}, ...]}'
    )
    client = make_client(
        args,
        system_instruction=system_instruction,
        temperature=0.55,
        max_output_tokens=2800,
    )
    result = client.send(user_prompt, user_visible=False)
    payload = parse_gemini_json(result["model_text"])
    answers = payload.get("answers", [])
    if not isinstance(answers, list) or len(answers) != len(questions):
        raise ValueError(f"simulated user must return {len(questions)} answers")
    rows: list[dict[str, Any]] = []
    for index, question in enumerate(questions, start=1):
        answer_item = answers[index - 1] if index - 1 < len(answers) else {}
        rows.append(
            {
                "turn": index,
                "advisor_question": question,
                "user_text": str(answer_item.get("answer", "")).strip(),
                "advisor_text": question,
                "next_advisor_text": "",
                "model_name": "gemini_simulated_user",
                "interview_done": index == len(questions),
            }
        )
    return rows


def extract_profile(
    args: argparse.Namespace,
    *,
    rows: list[dict[str, Any]],
) -> tuple[dict[str, Any], str]:
    """讓 Gemini 萃取者閱讀完整訪談並輸出 profile。"""
    system_instruction = Path(args.extraction_prompt_file).read_text(encoding="utf-8")
    user_prompt = build_extraction_user_prompt(rows)
    client = make_client(
        args,
        system_instruction=system_instruction,
        temperature=0.15,
        max_output_tokens=3200,
    )
    last_error = ""
    prompt = user_prompt
    for attempt in range(args.max_parse_retries + 1):
        result = client.send(prompt, user_visible=False)
        raw_text = result["model_text"]
        try:
            profile = validate_and_normalize_profile(parse_gemini_json(raw_text))
            return profile, raw_text
        except Exception as exc:  # noqa: BLE001 - benchmark 要把解析錯誤轉成修復 prompt
            last_error = str(exc)
            if attempt >= args.max_parse_retries:
                raise
            prompt = (
                "上一個回覆不是合法 JSON 或缺少必要欄位。\n"
                f"錯誤：{last_error}\n\n"
                "請只修正成符合 system instruction 的嚴格 JSON，不要輸出其他文字。"
            )
    raise RuntimeError(last_error or "profile extraction failed")


def evaluate_weights(target: dict[str, float], predicted: dict[str, float]) -> dict[str, Any]:
    """計算單筆權重萃取品質。"""
    target_vec = np.asarray([target[key] for key in SOLVER_DIMENSION_KEYS], dtype=float)
    pred_vec = np.asarray([predicted.get(key, 0.0) for key in SOLVER_DIMENSION_KEYS], dtype=float)
    abs_error = np.abs(target_vec - pred_vec)
    target_order = np.argsort(target_vec)[::-1]
    pred_order = np.argsort(pred_vec)[::-1]
    return {
        "spearman": spearman_corr(target_vec, pred_vec),
        "pearson": pearson_corr(target_vec, pred_vec),
        "l1": float(abs_error.sum()),
        "mae": float(abs_error.mean()),
        "rmse": float(np.sqrt(np.mean((target_vec - pred_vec) ** 2))),
        "top1_hit": bool(pred_order[0] == target_order[0]),
        "top2_hit": bool(target_order[0] in set(pred_order[:2])),
        "target_top1": SOLVER_DIMENSION_KEYS[int(target_order[0])],
        "predicted_top1": SOLVER_DIMENSION_KEYS[int(pred_order[0])],
        "top3_jaccard": float(len(set(target_order[:3]) & set(pred_order[:3])) / 3.0),
    }


def spearman_corr(a: np.ndarray, b: np.ndarray) -> float:
    """使用 average ranks 計算 Spearman，避免格狀權重 ties 造成偏差。"""
    return pearson_corr(average_ranks(a), average_ranks(b))


def pearson_corr(a: np.ndarray, b: np.ndarray) -> float:
    """計算 Pearson correlation；若變異為 0 則回傳 0。"""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    if float(a.std()) <= 1e-12 or float(b.std()) <= 1e-12:
        return 0.0
    value = float(np.corrcoef(a, b)[0, 1])
    return 0.0 if math.isnan(value) else value


def average_ranks(values: np.ndarray) -> np.ndarray:
    """回傳 1-based average ranks。"""
    order = np.argsort(values)
    ranks = np.empty(len(values), dtype=float)
    start = 0
    while start < len(values):
        end = start
        while end + 1 < len(values) and values[order[end + 1]] == values[order[start]]:
            end += 1
        rank = (start + end + 2) / 2.0
        ranks[order[start : end + 1]] = rank
        start = end + 1
    return ranks


def summarize_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    """彙總 20 筆 benchmark 指標。"""
    metrics = [record["metrics"] for record in records if record.get("status") == "ok"]
    if not metrics:
        return {"completed": 0}
    numeric_keys = ["spearman", "pearson", "l1", "mae", "rmse", "top3_jaccard"]
    summary = {
        "completed": len(metrics),
        "failed": len(records) - len(metrics),
        "top1_accuracy": float(np.mean([item["top1_hit"] for item in metrics])),
        "top2_accuracy": float(np.mean([item["top2_hit"] for item in metrics])),
    }
    for key in numeric_keys:
        values = [float(item[key]) for item in metrics]
        summary[f"{key}_mean"] = float(np.mean(values))
        summary[f"{key}_median"] = float(np.median(values))
    return summary


def write_markdown_report(payload: dict[str, Any], path: Path) -> None:
    """輸出人類可讀的 benchmark 報告。"""
    summary = payload["summary"]
    lines = [
        "# Gemini Extraction Benchmark",
        "",
        f"- run_id: `{payload['run_id']}`",
        f"- completed: {summary.get('completed', 0)}",
        f"- failed: {summary.get('failed', 0)}",
        f"- Spearman mean: {summary.get('spearman_mean', 0):.4f}",
        f"- Pearson mean: {summary.get('pearson_mean', 0):.4f}",
        f"- L1 mean: {summary.get('l1_mean', 0):.4f}",
        f"- MAE mean: {summary.get('mae_mean', 0):.4f}",
        f"- Top1 accuracy: {summary.get('top1_accuracy', 0):.4f}",
        f"- Top2 accuracy: {summary.get('top2_accuracy', 0):.4f}",
        "",
        "## Per Sample",
        "",
        "| sample_id | type | Spearman | L1 | MAE | Top1 hit | target top1 | predicted top1 |",
        "|---|---|---:|---:|---:|---:|---|---|",
    ]
    for record in payload["records"]:
        if record.get("status") != "ok":
            lines.append(f"| {record['sample_id']} | {record['profile_type']} | error | error | error | 0 | - | - |")
            continue
        metrics = record["metrics"]
        lines.append(
            "| "
            f"{record['sample_id']} | {record['profile_type']} | "
            f"{metrics['spearman']:.4f} | {metrics['l1']:.4f} | {metrics['mae']:.4f} | "
            f"{int(metrics['top1_hit'])} | {metrics['target_top1']} | {metrics['predicted_top1']} |"
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def run(args: argparse.Namespace) -> None:
    """執行完整 benchmark。"""
    run_id = args.run_id or datetime.now().strftime("%Y%m%dT%H%M%S")
    output_json = PREFERENCE_RESULTS_DIR / f"gemini_extraction_benchmark_{run_id}.json"
    output_jsonl = PREFERENCE_RESULTS_DIR / f"gemini_extraction_benchmark_records_{run_id}.jsonl"
    output_md = REPORTS_DIR / f"gemini_extraction_benchmark_{run_id}.md"
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)

    profiles = generate_grid_weights(args.count)
    questions = generate_advisor_questions(args)
    records: list[dict[str, Any]] = []

    with output_jsonl.open("w", encoding="utf-8") as file:
        for index, profile_item in enumerate(profiles, start=1):
            sample_id = profile_item["sample_id"]
            print(f"[status] Benchmark sample {index}/{len(profiles)}: {sample_id}", flush=True)
            try:
                rows = simulate_user_answers(
                    args,
                    questions=questions,
                    target_weights=profile_item["target_weights"],
                    sample_id=sample_id,
                )
                extracted_profile, raw_extraction_text = extract_profile(args, rows=rows)
                predicted_weights = extracted_profile["dimension_weights"]
                metrics = evaluate_weights(profile_item["target_weights"], predicted_weights)
                record = {
                    **profile_item,
                    "status": "ok",
                    "questions": questions,
                    "interview_rows": rows,
                    "extracted_profile": extracted_profile,
                    "raw_extraction_text": raw_extraction_text,
                    "metrics": metrics,
                }
            except Exception as exc:  # noqa: BLE001 - benchmark 需要保留失敗樣本並繼續
                record = {
                    **profile_item,
                    "status": "failed",
                    "error": str(exc),
                    "questions": questions,
                }
            records.append(record)
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
            file.flush()

    payload = {
        "run_id": run_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "count": len(profiles),
        "questions": questions,
        "summary": summarize_metrics(records),
        "records": records,
    }
    output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown_report(payload, output_md)

    print(f"[status] Benchmark JSON saved: {output_json}", flush=True)
    print(f"[status] Benchmark JSONL saved: {output_jsonl}", flush=True)
    print(f"[status] Benchmark report saved: {output_md}", flush=True)
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a 20-sample Gemini preference extraction benchmark.")
    parser.add_argument("--count", type=int, default=20)
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
