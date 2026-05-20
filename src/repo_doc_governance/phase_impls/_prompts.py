"""Helpers to load slices of the vendored prompt files.

Each LLM phase wants a specific section out of `phases.md` /
`decisions.md` / `templates.md` (the README section, the AGENTS.md
section, etc.). Rather than embed those strings directly in code — which
would force a re-vendor every time the upstream skill body shifts — the
prompts are read at runtime from the vendored copies in
`src/repo_doc_governance/prompts/`.

`load_prompt(filename, section=...)` reads the vendored file, strips the
DO-NOT-EDIT header, and returns either the full body or the named
section (matched by exact heading line — `"## Phase 4 — README update"`).
"""

from __future__ import annotations

import re
from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
_DO_NOT_EDIT_RE = re.compile(r"^\s*<!--\s*DO NOT EDIT[^>]*-->\s*$", re.MULTILINE)


def load_prompt(filename: str, *, section: str | None = None) -> str:
    """Read `prompts/<filename>`, drop the DO-NOT-EDIT header, optionally
    return the slice between the named section heading and the next
    heading of the same or shallower depth.
    """
    path = _PROMPTS_DIR / filename
    text = path.read_text(encoding="utf-8")
    text = _DO_NOT_EDIT_RE.sub("", text, count=1).lstrip("\n")
    if section is None:
        return text

    depth = _heading_depth(section)
    if depth == 0:
        return text

    lines = text.splitlines()
    start: int | None = None
    end = len(lines)
    for i, line in enumerate(lines):
        stripped = line.rstrip()
        if start is None and stripped == section:
            start = i + 1
            continue
        if start is not None:
            line_depth = _heading_depth(stripped)
            if 0 < line_depth <= depth:
                end = i
                break
    if start is None:
        return ""
    return "\n".join(lines[start:end]).strip("\n")


def _heading_depth(line: str) -> int:
    """Return the markdown heading depth (1 for `# `, 2 for `## `, ...).
    Zero if the line isn't a heading.
    """
    stripped = line.lstrip()
    if not stripped.startswith("#"):
        return 0
    depth = 0
    for ch in stripped:
        if ch == "#":
            depth += 1
        else:
            break
    if depth > 6:
        return 0
    if not stripped[depth:].startswith(" "):
        return 0
    return depth
