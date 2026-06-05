"""active_preference 的共用路徑設定。

目前主線已改成 Gemini 訪談與 Gemini 偏好萃取，所以只保留訪談、
偏好輸出與報告相關路徑。所有產出仍統一放在 active_preference/results/。
"""

from __future__ import annotations

from pathlib import Path


PACKAGE_DIR = Path(__file__).resolve().parent
RESULTS_DIR = PACKAGE_DIR / "results"
INTERVIEW_RESULTS_DIR = RESULTS_DIR / "interviews"
PREFERENCE_RESULTS_DIR = RESULTS_DIR / "preferences"
REPORTS_DIR = RESULTS_DIR / "reports"

REAL_INTERVIEW_TRANSCRIPT_PATH = INTERVIEW_RESULTS_DIR / "gemini_real_interview_transcript.json"
REAL_INTERVIEW_TURN_RECORD_PATH = INTERVIEW_RESULTS_DIR / "gemini_turn_records.jsonl"
GEMINI_CHAT_TRANSCRIPT_PATH = INTERVIEW_RESULTS_DIR / "gemini_chat_transcript.json"
GEMINI_PREFERENCE_PROFILE_PATH = PREFERENCE_RESULTS_DIR / "gemini_preference_profile.json"
