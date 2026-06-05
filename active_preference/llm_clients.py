"""Gemini REST client used by interview and preference extraction scripts."""

from __future__ import annotations

import json
import os
import random
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from collections.abc import Callable
from typing import Any
from urllib import error, request

ApiKeySource = str

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_PATHS = (
    PROJECT_ROOT / ".env",
    PROJECT_ROOT / "active_preference" / ".env",
)
KEY_ASSIGNMENT_PATTERN = re.compile(
    r"(?:GEMINI_API_KEY|GEMINI_KEY|GOOGLE_API_KEY)\s*[:=]\s*[\"']?([A-Za-z0-9_\-]{20,})",
    re.IGNORECASE,
)
RAW_GEMINI_KEY_PATTERN = re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b")
RETRY_DELAY_PATTERN = re.compile(r"retry in ([0-9.]+)s", re.IGNORECASE)
VISIBLE_RESPONSE_PATTERN = re.compile(
    r"(謝謝您|謝謝|感謝|很高興|收到|了解|好的|您好|那麼|請問|談到|為了|訪談到此結束|今天的 ETF 偏好訪談到此結束)"
)


def redact_secret(text: str) -> str:
    """Hide Gemini-like API keys in diagnostics."""
    text = RAW_GEMINI_KEY_PATTERN.sub("<REDACTED_API_KEY>", text)
    return KEY_ASSIGNMENT_PATTERN.sub("GEMINI_API_KEY=<REDACTED_API_KEY>", text)


def load_gemini_api_key_from_env_file(paths: tuple[Path, ...] = DEFAULT_ENV_PATHS) -> str | None:
    """從專案的環境變數檔案讀取 Gemini API key。

    支援常見 .env 寫法：
        GEMINI_API_KEY=...
        GEMINI_KEY: ...
        GOOGLE_API_KEY = "..."

    這個函式只回傳 key，不會把 key 印到 terminal 或 transcript。
    """
    for path in paths:
        if not path.exists():
            continue
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.lower().startswith("export "):
                line = line[7:].strip()

            assignment_match = KEY_ASSIGNMENT_PATTERN.search(line)
            if assignment_match:
                return assignment_match.group(1).strip().strip("\"'")

            # 允許 .env 檔只有一行裸 key，但不再掃 README，避免文件洩漏金鑰。
            raw_match = RAW_GEMINI_KEY_PATTERN.fullmatch(line.strip("\"'"))
            if raw_match:
                return raw_match.group(0).strip()

    return None


def load_gemini_api_key_from_readme(paths: tuple[Path, ...] | None = None) -> str | None:
    """Deprecated compatibility wrapper.

    舊程式曾經從 README 讀 key；現在為了避免明文文件洩漏，只改讀 .env。
    保留這個函式名稱，是為了不讓舊 import 立刻壞掉。
    """
    _ = paths
    return load_gemini_api_key_from_env_file()


def load_gemini_api_key_from_environment(api_key_env: str = "GEMINI_API_KEY") -> tuple[str, str] | None:
    """先讀真正的系統環境變數，再讀專案 .env 檔。"""
    env_value = os.getenv(api_key_env)
    if env_value:
        return env_value.strip(), f"env:{api_key_env}"

    env_file_value = load_gemini_api_key_from_env_file()
    if env_file_value:
        return env_file_value, "env_file:.env"
    return None


class GeminiApiKeyResolver:
    """Resolve the Gemini API key without exposing it in logs or transcripts."""

    def __init__(
        self,
        explicit_api_key: str | None = None,
        api_key_env: str = "GEMINI_API_KEY",
        key_source: ApiKeySource = "auto",
    ) -> None:
        self.explicit_api_key = explicit_api_key
        self.api_key_env = api_key_env
        self.key_source = key_source

    def resolve(self) -> tuple[str, str]:
        if self.explicit_api_key:
            return self.explicit_api_key, "explicit"

        if self.key_source not in {"auto", "env", "env_file", "readme"}:
            raise ValueError(f"Unsupported Gemini key source: {self.key_source}")

        if self.key_source in {"auto", "env"}:
            env_value = os.getenv(self.api_key_env)
            if env_value:
                return env_value.strip(), f"env:{self.api_key_env}"

        if self.key_source in {"auto", "env_file", "readme"}:
            env_file_value = load_gemini_api_key_from_env_file()
            if env_file_value:
                source = "env_file:.env"
                if self.key_source == "readme":
                    source = "env_file:.env(deprecated_readme_source)"
                return env_file_value, source

        raise RuntimeError(
            "Missing Gemini API key. Set GEMINI_API_KEY in your shell or add "
            "GEMINI_API_KEY=<key> to the project .env file."
        )


class GeminiApiError(RuntimeError):
    """Gemini API error with structured fields for CLI-friendly handling."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        status: str | None = None,
        retry_delay_seconds: float | None = None,
        attempts: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.status = status
        self.retry_delay_seconds = retry_delay_seconds
        self.attempts = attempts or []

    def to_dict(self) -> dict[str, Any]:
        return {
            "message": self.message,
            "status_code": self.status_code,
            "status": self.status,
            "retry_delay_seconds": self.retry_delay_seconds,
            "attempts": self.attempts,
        }


@dataclass
class GeminiChatTranscript:
    """In-memory chat transcript that can be serialized by the test script."""

    model_name: str
    system_instruction: str | None = None
    turns: list[dict[str, Any]] = field(default_factory=list)

    @property
    def user_inputs(self) -> list[str]:
        return [
            turn["user_input"]
            for turn in self.turns
            if turn.get("user_visible", True)
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_name": self.model_name,
            "system_instruction": self.system_instruction,
            "user_inputs": self.user_inputs,
            "turns": self.turns,
        }


class GeminiRestChatClient:
    """Minimal Gemini REST chat client.

    This client keeps conversation history locally and sends the full history on
    every turn. It is intended for development tests before the preference
    extractor is replaced with a structured LLM extractor.
    """

    def __init__(
        self,
        model_name: str = "gemini-2.5-flash-lite",
        fallback_model_names: tuple[str, ...] = ("gemini-2.5-flash",),
        api_key: str | None = None,
        api_key_env: str = "GEMINI_API_KEY",
        key_source: ApiKeySource = "auto",
        endpoint_base: str = "https://generativelanguage.googleapis.com/v1beta",
        system_instruction: str | None = None,
        timeout_seconds: int = 60,
        temperature: float = 0.4,
        max_output_tokens: int = 800,
        response_mime_type: str | None = None,
        max_retries: int = 2,
        retry_backoff_seconds: float = 1.5,
        max_retry_delay_seconds: float = 8.0,
        retry_jitter_seconds: float = 0.5,
        progress_callback: Callable[[str], None] | None = None,
    ) -> None:
        self.model_name = model_name
        self.fallback_model_names = tuple(
            model for model in fallback_model_names if model and model != model_name
        )
        self.api_key_resolver = GeminiApiKeyResolver(
            explicit_api_key=api_key,
            api_key_env=api_key_env,
            key_source=key_source,
        )
        self.endpoint_base = endpoint_base.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        self.response_mime_type = response_mime_type
        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds
        self.max_retry_delay_seconds = max_retry_delay_seconds
        self.retry_jitter_seconds = retry_jitter_seconds
        self.progress_callback = progress_callback
        self.transcript = GeminiChatTranscript(
            model_name=model_name,
            system_instruction=system_instruction,
        )
        self._contents: list[dict[str, Any]] = []

    def send(self, user_text: str, user_visible: bool = True) -> dict[str, Any]:
        api_key, resolved_key_source = self.api_key_resolver.resolve()
        pending_contents = [*self._contents, self._content("user", user_text)]
        model_names = (self.model_name, *self.fallback_model_names)
        attempts: list[dict[str, Any]] = []

        raw_response: dict[str, Any] | None = None
        used_model_name: str | None = None
        last_api_error: GeminiApiError | None = None

        for model_name in model_names:
            for attempt_index in range(1, self.max_retries + 2):
                self._progress(
                    f"Sending request to Gemini model={model_name}, attempt={attempt_index}..."
                )
                try:
                    raw_response = self._request_generate_content(
                        api_key=api_key,
                        model_name=model_name,
                        contents=pending_contents,
                    )
                    used_model_name = model_name
                    attempts.append(
                        {
                            "model_name": model_name,
                            "attempt": attempt_index,
                            "status": "success",
                        }
                    )
                    self._progress(f"Gemini response received from model={model_name}.")
                    break
                except error.HTTPError as exc:
                    body = exc.read().decode("utf-8", errors="replace")
                    last_api_error = self._api_error_from_http(
                        status_code=exc.code,
                        body=body,
                        attempts=attempts,
                    )
                    attempts.append(
                        {
                            "model_name": model_name,
                            "attempt": attempt_index,
                            "status": "failed",
                            "error": last_api_error.message,
                            "status_code": exc.code,
                            "api_status": last_api_error.status,
                            "retry_delay_seconds": last_api_error.retry_delay_seconds,
                        }
                    )
                    if not self._should_retry_http(exc.code, attempt_index, last_api_error):
                        break
                    sleep_seconds = self._retry_sleep_seconds(attempt_index, last_api_error)
                    self._progress(
                        f"Gemini returned HTTP {exc.code}; retrying in {sleep_seconds:.1f}s..."
                    )
                    time.sleep(sleep_seconds)
                except error.URLError as exc:
                    last_api_error = GeminiApiError(
                        message=f"Gemini API request failed: {exc.reason}",
                        attempts=attempts,
                    )
                    attempts.append(
                        {
                            "model_name": model_name,
                            "attempt": attempt_index,
                            "status": "failed",
                            "error": last_api_error.message,
                        }
                    )
                    if attempt_index > self.max_retries:
                        break
                    sleep_seconds = self._retry_sleep_seconds(attempt_index, last_api_error)
                    self._progress(
                        f"Gemini network request failed; retrying in {sleep_seconds:.1f}s..."
                    )
                    time.sleep(sleep_seconds)

            if raw_response is not None:
                break

        if raw_response is None or used_model_name is None:
            message = "Gemini API request failed after retries and fallback models."
            if last_api_error:
                message = f"{message} Last error: {last_api_error.message}"
            raise GeminiApiError(
                message=message,
                status_code=last_api_error.status_code if last_api_error else None,
                status=last_api_error.status if last_api_error else None,
                retry_delay_seconds=last_api_error.retry_delay_seconds if last_api_error else None,
                attempts=attempts,
            )

        response_texts = self._extract_response_texts(raw_response)
        model_text = response_texts["answer_text"]
        self._contents = [*pending_contents, self._content("model", model_text)]

        turn = {
            "turn": len(self.transcript.turns) + 1,
            "user_input": user_text,
            "user_visible": user_visible,
            "model_response": model_text,
            "model_thought_summary": response_texts["thought_text"],
            "primary_model_name": self.model_name,
            "used_model_name": used_model_name,
            "key_source": resolved_key_source,
            "attempts": attempts,
            "usage_metadata": raw_response.get("usageMetadata", {}),
            "finish_reason": self._extract_finish_reason(raw_response),
        }
        self.transcript.turns.append(turn)
        return {
            "model_text": model_text,
            "turn": turn,
            "raw_response": raw_response,
            "transcript": self.transcript.to_dict(),
        }

    def _request_generate_content(
        self,
        api_key: str,
        model_name: str,
        contents: list[dict[str, Any]],
    ) -> dict[str, Any]:
        payload = self._build_payload(contents, model_name)
        url = f"{self.endpoint_base}/models/{model_name}:generateContent"
        request_obj = request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": api_key,
            },
            method="POST",
        )

        with request.urlopen(request_obj, timeout=self.timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))

    def _build_payload(self, contents: list[dict[str, Any]], model_name: str) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": self.temperature,
                "maxOutputTokens": self.max_output_tokens,
            },
        }
        if self.response_mime_type:
            payload["generationConfig"]["responseMimeType"] = self.response_mime_type
        if "2.5" in model_name:
            payload["generationConfig"]["thinkingConfig"] = {
                "includeThoughts": False,
                "thinkingBudget": 0,
            }
        if self.transcript.system_instruction:
            payload["systemInstruction"] = {
                "parts": [{"text": self.transcript.system_instruction}]
        }
        return payload

    def _should_retry_http(
        self,
        status_code: int,
        attempt_index: int,
        api_error: GeminiApiError,
    ) -> bool:
        transient_status_codes = {408, 429, 500, 502, 503, 504}
        if status_code not in transient_status_codes or attempt_index > self.max_retries:
            return False
        if api_error.retry_delay_seconds and api_error.retry_delay_seconds > self.max_retry_delay_seconds:
            return False
        return True

    def _retry_sleep_seconds(self, attempt_index: int, api_error: GeminiApiError) -> float:
        if api_error.retry_delay_seconds is not None:
            return min(api_error.retry_delay_seconds, self.max_retry_delay_seconds)
        # 大量生成時遇到 429/暫時性網路錯誤，用指數退避避免立刻再次撞到配額限制。
        backoff = self.retry_backoff_seconds * (2 ** max(0, attempt_index - 1))
        jitter = random.uniform(0.0, self.retry_jitter_seconds) if self.retry_jitter_seconds > 0 else 0.0
        return min(backoff + jitter, self.max_retry_delay_seconds)

    def _api_error_from_http(
        self,
        status_code: int,
        body: str,
        attempts: list[dict[str, Any]],
    ) -> GeminiApiError:
        redacted_body = redact_secret(body)
        api_status = None
        api_message = redacted_body
        retry_delay = self._extract_retry_delay(redacted_body)

        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            parsed = {}

        error_payload = parsed.get("error", {}) if isinstance(parsed, dict) else {}
        if error_payload:
            api_status = error_payload.get("status")
            api_message = redact_secret(error_payload.get("message", redacted_body))
            retry_delay = self._extract_retry_delay_from_error(error_payload) or retry_delay

        return GeminiApiError(
            message=f"HTTP {status_code}: {api_message}",
            status_code=status_code,
            status=api_status,
            retry_delay_seconds=retry_delay,
            attempts=attempts,
        )

    @staticmethod
    def _extract_retry_delay(text: str) -> float | None:
        match = RETRY_DELAY_PATTERN.search(text)
        if not match:
            return None
        return float(match.group(1))

    @staticmethod
    def _extract_retry_delay_from_error(error_payload: dict[str, Any]) -> float | None:
        for detail in error_payload.get("details", []):
            retry_delay = detail.get("retryDelay")
            if isinstance(retry_delay, str) and retry_delay.endswith("s"):
                try:
                    return float(retry_delay[:-1])
                except ValueError:
                    return None
        return None

    def _progress(self, message: str) -> None:
        if self.progress_callback:
            self.progress_callback(message)

    @staticmethod
    def _content(role: str, text: str) -> dict[str, Any]:
        return {
            "role": role,
            "parts": [{"text": text}],
        }

    @staticmethod
    def _extract_response_texts(raw_response: dict[str, Any]) -> dict[str, str]:
        candidates = raw_response.get("candidates") or []
        if not candidates:
            return {"answer_text": "", "thought_text": ""}
        parts = candidates[0].get("content", {}).get("parts", [])
        answer_parts = []
        thought_parts = []

        for part in parts:
            text = part.get("text", "")
            if not text:
                continue
            if part.get("thought"):
                thought_parts.append(text)
            else:
                answer_parts.append(text)

        answer_text = "\n".join(answer_parts).strip()
        thought_text = "\n".join(thought_parts).strip()
        answer_text, leaked_thought = GeminiRestChatClient._strip_literal_thought_prefix(answer_text)
        if leaked_thought:
            thought_text = "\n\n".join(text for text in (thought_text, leaked_thought) if text)

        return {
            "answer_text": answer_text,
            "thought_text": thought_text,
        }

    @staticmethod
    def _strip_literal_thought_prefix(text: str) -> tuple[str, str]:
        stripped = text.lstrip()
        if not stripped.upper().startswith("THOUGHT"):
            return text, ""

        matches = [match.start() for match in VISIBLE_RESPONSE_PATTERN.finditer(stripped) if match.start() > 0]
        if not matches:
            fallback_answer = (
                "我已收到您的回答，這輪回覆中包含不應顯示的內部分析文字，"
                "已在畫面中隱藏並保留到紀錄檔。"
            )
            return fallback_answer, stripped

        split_at = min(matches)
        thought_text = stripped[:split_at].strip()
        answer_text = stripped[split_at:].strip()
        return answer_text, thought_text

    @staticmethod
    def _extract_finish_reason(raw_response: dict[str, Any]) -> str | None:
        candidates = raw_response.get("candidates") or []
        if not candidates:
            return None
        return candidates[0].get("finishReason")

