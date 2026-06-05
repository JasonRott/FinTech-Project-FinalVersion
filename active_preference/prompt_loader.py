"""讀取 Gemini prompt 文字檔的小工具。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


DEFAULT_PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "gemini_interview_prompts.txt"


@dataclass(frozen=True)
class GeminiPromptConfig:
    """Gemini 訪談需要的兩種 prompt。"""

    system_instruction: str
    start_prompt: str
    evidence_decoder_system: str
    evidence_decoder_template: str


def load_gemini_prompt_config(prompt_path: str | Path = DEFAULT_PROMPT_PATH) -> GeminiPromptConfig:
    """從文字檔讀取 Gemini prompt 設定。

    文字檔使用簡單 section 格式：
    [SYSTEM_INSTRUCTION]
    ...

    [START_PROMPT]
    ...
    """
    sections = _read_prompt_sections(Path(prompt_path))
    return GeminiPromptConfig(
        system_instruction=sections["SYSTEM_INSTRUCTION"],
        start_prompt=sections["START_PROMPT"],
        evidence_decoder_system=sections["EVIDENCE_DECODER_SYSTEM"],
        evidence_decoder_template=sections["EVIDENCE_DECODER_TEMPLATE"],
    )


def _read_prompt_sections(path: Path) -> dict[str, str]:
    """把 prompt 檔依照 [SECTION] 切成字典。"""
    if not path.exists():
        raise FileNotFoundError(f"找不到 Gemini prompt 檔案：{path}")

    sections: dict[str, list[str]] = {}
    current_section: str | None = None

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()

        # 允許在 prompt 檔中使用 # 寫註解。
        if not stripped or stripped.startswith("#"):
            continue

        if stripped.startswith("[") and stripped.endswith("]"):
            current_section = stripped[1:-1].strip()
            sections.setdefault(current_section, [])
            continue

        if current_section is None:
            raise ValueError(f"prompt 檔案中有未放入 section 的文字：{line}")

        sections[current_section].append(line)

    parsed = {name: "\n".join(lines).strip() for name, lines in sections.items()}
    required_sections = (
        "SYSTEM_INSTRUCTION",
        "START_PROMPT",
        "EVIDENCE_DECODER_SYSTEM",
        "EVIDENCE_DECODER_TEMPLATE",
    )
    missing = [name for name in required_sections if not parsed.get(name)]
    if missing:
        raise ValueError(f"Gemini prompt 檔案缺少必要 section：{missing}")

    return parsed
