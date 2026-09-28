from __future__ import annotations

import re
from pathlib import Path

_PROMPTS_DIR = Path(__file__).resolve().parent
_FRONT_MATTER = re.compile(r"^---\n.*?\n---\n", re.DOTALL)


def load_prompt(name: str) -> str:
    """Load prompt file by stem, e.g. detect_v1 -> detect_v1.md."""
    path = _PROMPTS_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Prompt not found: {path}")
    text = path.read_text(encoding="utf-8")
    return _FRONT_MATTER.sub("", text).strip()
