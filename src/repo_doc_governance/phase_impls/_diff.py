"""Shared diff helpers for LLM phases (4, 5, 6).

Each LLM phase produces a *proposed new body* for one or more files; the
harness computes a unified diff against the on-disk content and stores the
diff string in `RunState`. PR-opening (Phase 9, in PR #5) consumes those
diffs to build the actual PR.

Keeping the diff format consistent (unified, 3 lines of context, repo-
relative paths) lets the PR body template reuse the same blob.
"""

from __future__ import annotations

import difflib
from pathlib import Path


def unified_diff(
    repo: Path, rel_path: str, proposed: str, n_context: int = 3
) -> str:
    """Return a unified diff between the on-disk content and `proposed`.

    `rel_path` is repo-relative; the diff header uses `a/<rel>` and
    `b/<rel>` like `git diff` does so the PR body reads naturally.
    Empty string if `proposed` matches disk byte-for-byte after both
    sides are normalized to LF-ended.
    """
    abs_path = repo / rel_path
    current = ""
    if abs_path.exists() and abs_path.is_file():
        try:
            current = abs_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            current = ""

    current = current.replace("\r\n", "\n")
    proposed = proposed.replace("\r\n", "\n")

    if current == proposed:
        return ""

    lines_current = current.splitlines(keepends=True)
    lines_proposed = proposed.splitlines(keepends=True)
    if lines_current and not lines_current[-1].endswith("\n"):
        lines_current[-1] += "\n"
    if lines_proposed and not lines_proposed[-1].endswith("\n"):
        lines_proposed[-1] += "\n"

    diff_lines = difflib.unified_diff(
        lines_current,
        lines_proposed,
        fromfile=f"a/{rel_path}",
        tofile=f"b/{rel_path}",
        n=n_context,
    )
    return "".join(diff_lines)
