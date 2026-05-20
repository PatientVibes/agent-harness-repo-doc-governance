"""Defensive post-processing for LLM phase outputs.

Phases 4, 5, and 6 all have a "Output raw markdown only. No prose
commentary before or after." hard rule in their system prompts. Some
models honor it (Gemini 2.5 Pro in the v0.1.2 dogfood); some don't
(Sonnet 4.6 in the v0.1.3 dogfood, where all three phases emitted
chain-of-thought prose above the first H1).

When the preamble leaks through, it defeats Phase 9's no-change
short-circuit — the preamble creates a diff against the existing file
and the harness ships a "preamble added" PR. So we always run the
output through `strip_llm_preamble` after `.strip()`.

Defensive only: if the output already starts with `# `, the function
is a no-op.
"""

from __future__ import annotations


def strip_llm_preamble(text: str) -> str:
    """Drop any prose commentary that appears before the first H1.

    Many models emit a reasoning paragraph ("Now I have a thorough
    understanding..." / "No drift was flagged...") above the file
    content even when the system prompt forbids it. This helper finds
    the first line that starts with `# ` and discards everything before
    it. If no H1 is present in the output, the original text is returned
    unchanged so the operator can still inspect it.
    """
    if not text:
        return text
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.lstrip().startswith("# "):
            stripped = "\n".join(lines[i:])
            # Preserve the trailing newline iff the original had one.
            if text.endswith("\n") and not stripped.endswith("\n"):
                stripped += "\n"
            return stripped
    return text
