from __future__ import annotations

import re
from pathlib import Path


def chapter_title_from_final_text(text: str, chapter_number: int) -> str:
    stripped = text.strip()
    first_line = stripped.splitlines()[0].strip() if stripped else ""
    if first_line and any(token in first_line for token in ("第", "章", "Chapter")):
        return first_line.lstrip("# ")
    return f"第{chapter_number}章"


def chapter_body_from_final_text(text: str) -> str:
    stripped = text.strip()
    lines = stripped.splitlines()
    if not lines:
        return ""
    if lines[0].startswith("#"):
        return "\n".join(lines[1:]).strip()
    return stripped


def count_chinese_chars(text: str) -> int:
    return len(re.findall(r"[一-龥]", text))
