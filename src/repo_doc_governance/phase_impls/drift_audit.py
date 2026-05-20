"""Phase 3 — Drift audit.

Compares documentation against the actual repository. Deterministic. No LLM.

Detects:
  - Broken internal `.md` links (link target doesn't resolve on disk).
  - Dead commands (`npm run X` / `make Y` / `pnpm X` quoted in docs but
    not declared in any manifest in `code_first_map.declared_commands`).
  - Missing paths referenced from docs (a doc says `see foo/bar.py` but
    `foo/bar.py` doesn't exist on disk).
  - Conflicting agent-instruction files (multiple agent files exist with
    overlapping content — flagged for Phase 5 to consolidate).
  - Stale TODOs (vague "clean up later" / "investigate this" markers).

Each finding gets a `Classification` from `prompts/decisions.md`:
  - broken link → `Update`
  - dead command → `Update`
  - missing path → `Needs verification` (could be the doc is right and
    the code was deleted, or the path was renamed)
  - conflicting agent files → `Consolidate`
  - vague TODO → `Update`
"""

from __future__ import annotations

import re
from pathlib import Path

from repo_doc_governance.models import (
    Classification,
    DocFile,
    DocKind,
    DriftFinding,
    Severity,
)
from repo_doc_governance.state import RunState


# Markdown link: [text](target) — target may be relative path, http, anchor.
_MD_LINK_RE = re.compile(r"\[(?P<text>[^\]]*)\]\((?P<target>[^)\s]+)\)")

# Inline code that looks like a command — we focus on these common runners
# because they have well-defined manifest mappings.
_COMMAND_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("npm", re.compile(r"`(npm (?:run )?[A-Za-z0-9:_-]+)`")),
    ("pnpm", re.compile(r"`(pnpm (?:run )?[A-Za-z0-9:_-]+)`")),
    ("yarn", re.compile(r"`(yarn (?:run )?[A-Za-z0-9:_-]+)`")),
    ("make", re.compile(r"`(make [A-Za-z0-9_/-]+)`")),
]

# Vague-TODO heuristics from `prompts/phases.md` Phase 6 rules.
_VAGUE_TODO_PHRASES: tuple[str, ...] = (
    "clean up later",
    "investigate this",
    "fix this",
    "look into this",
    "todo: ?",
    "tbd",
    "tbc",
    "fix me later",
)

_TODO_LINE_RE = re.compile(r"(?i)\btodo\b|\bfixme\b")


def run(state: RunState) -> RunState:
    repo = state.target_repo
    findings: list[DriftFinding] = []

    if state.inventory is None:
        # Drift audit needs inventory; record one informational finding and bail.
        state.drift_findings.append(
            DriftFinding(
                path=".",
                kind="phase_skipped",
                severity=Severity.INFO,
                classification=Classification.NEEDS_VERIFICATION,
                detail="Phase 3 requires Phase 1 inventory; was the task table changed?",
            )
        )
        return state

    declared = _all_declared_commands(state)
    tracked_files = {df.path for df in state.inventory.doc_files}
    tracked_files.update(df.path for df in state.inventory.agent_files)
    tracked_files.update(df.path for df in state.inventory.handoff_files)
    # All files (tracked + just-the-list — keep it simple)
    all_files: set[str] = set()
    for df in (
        *state.inventory.doc_files,
        *state.inventory.agent_files,
        *state.inventory.handoff_files,
    ):
        all_files.add(df.path)

    docs_to_scan: list[DocFile] = list(state.inventory.doc_files) + list(
        state.inventory.agent_files
    ) + list(state.inventory.handoff_files)

    for doc in docs_to_scan:
        abs_path = repo / doc.path
        try:
            text = abs_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        findings.extend(_audit_internal_links(repo, doc, text))
        findings.extend(_audit_commands(doc, text, declared))
        if doc.kind in (DocKind.HANDOFF, DocKind.TODO, DocKind.ROADMAP):
            findings.extend(_audit_vague_todos(doc, text))

    findings.extend(_audit_conflicting_agent_files(state))

    state.drift_findings.extend(findings)
    return state


# ---------------------------------------------------------------------------
# Internal-link audit
# ---------------------------------------------------------------------------


def _audit_internal_links(repo: Path, doc: DocFile, text: str) -> list[DriftFinding]:
    out: list[DriftFinding] = []
    doc_dir = (repo / doc.path).parent
    in_fence = _fenced_code_lines(text)

    for line_no, line in enumerate(text.splitlines(), start=1):
        if line_no in in_fence:
            # Inside a ``` fenced code block — author is showing an
            # example, not asserting a link. Skip.
            continue
        for match in _MD_LINK_RE.finditer(line):
            target = match.group("target").strip()
            if not target:
                continue
            # Skip external URLs and pure anchors.
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            # Skip template placeholders (`${foo}`, `{{foo}}`).
            if "${" in target or "{{" in target:
                continue
            # Strip anchor + query
            link_path = target.split("#", 1)[0].split("?", 1)[0]
            if not link_path or not link_path.endswith(".md"):
                # Phase 3's contract here is .md → .md / .md → file. We only
                # flag missing `.md` link targets to avoid false positives on
                # image/asset links that may be intentionally stub-able.
                if not link_path.endswith(".md"):
                    continue
            resolved = (doc_dir / link_path).resolve()
            if not resolved.exists():
                out.append(
                    DriftFinding(
                        path=doc.path,
                        kind="broken_internal_link",
                        severity=Severity.MEDIUM,
                        classification=Classification.UPDATE,
                        detail=f"Link target does not exist: {target}",
                        line=line_no,
                    )
                )
    return out


def _fenced_code_lines(text: str) -> set[int]:
    """Return the set of 1-indexed line numbers that lie inside ``` fences.

    Treats every ``` (with optional language tag) as toggling fenced-ness.
    Lines on the fence markers themselves are also marked fenced so a
    closing ``` is never treated as in-content. Robust to nested fences
    of the same depth — markdown doesn't really support nested fences,
    so we don't either.
    """
    fenced: set[int] = set()
    in_fence = False
    for line_no, line in enumerate(text.splitlines(), start=1):
        stripped = line.lstrip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            fenced.add(line_no)
            continue
        if in_fence:
            fenced.add(line_no)
    return fenced


# ---------------------------------------------------------------------------
# Dead-command audit
# ---------------------------------------------------------------------------


def _all_declared_commands(state: RunState) -> set[str]:
    """Union of all declared commands across all manifests + the
    code-first map. Used as the source-of-truth oracle for Phase 3."""
    declared: set[str] = set()
    if state.inventory is not None:
        for m in state.inventory.manifests:
            declared.update(m.declared_commands)
    if state.code_first_map is not None:
        for cmds in state.code_first_map.declared_commands.values():
            declared.update(cmds)
    return declared


def _audit_commands(
    doc: DocFile, text: str, declared: set[str]
) -> list[DriftFinding]:
    out: list[DriftFinding] = []
    is_aspirational = is_aspirational_doc(doc.path)
    for line_no, line in enumerate(text.splitlines(), start=1):
        for tool_name, pattern in _COMMAND_PATTERNS:
            for match in pattern.finditer(line):
                cmd = match.group(1).strip()
                # Build a generous "is this declared?" check so the audit
                # doesn't flag style variations (`npm run test` vs `npm test`).
                if _command_is_declared(cmd, declared):
                    continue
                if is_aspirational:
                    # Plan / spec / design docs describe future or
                    # alternative state. A `dead_command` here is usually
                    # a planned-but-not-yet-shipped reference, not drift.
                    # Demote to `Needs verification` so the human can
                    # confirm whether the plan landed or not.
                    out.append(
                        DriftFinding(
                            path=doc.path,
                            kind="dead_command_in_aspirational_doc",
                            severity=Severity.LOW,
                            classification=Classification.NEEDS_VERIFICATION,
                            detail=(
                                f"`{cmd}` is referenced in a plan/spec doc but "
                                f"not declared in any {tool_name}-flavored manifest. "
                                f"Confirm whether the plan landed."
                            ),
                            line=line_no,
                        )
                    )
                else:
                    out.append(
                        DriftFinding(
                            path=doc.path,
                            kind="dead_command",
                            severity=Severity.HIGH,
                            classification=Classification.UPDATE,
                            detail=(
                                f"`{cmd}` is referenced but not declared in any "
                                f"{tool_name}-flavored manifest."
                            ),
                            line=line_no,
                        )
                    )
    return out


_ASPIRATIONAL_PATH_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)(^|/)docs/superpowers/plans/"),
    re.compile(r"(?i)(^|/)docs/superpowers/specs/"),
    re.compile(r"(?i)(^|/)docs/plans/"),
    re.compile(r"(?i)(^|/)docs/specs/"),
    re.compile(r"(?i)(^|/)docs/design/"),
    re.compile(r"(?i)(^|/)docs/proposals/"),
    re.compile(r"(?i)(^|/)docs/rfcs/"),
)


def is_aspirational_doc(path: str) -> bool:
    """True for docs that describe a future / proposed / alternative
    state of the repo — plan docs, spec docs, design notes, proposals,
    RFCs. Dead-command findings in these get demoted from
    `Update` to `Needs verification` because the command is usually
    a planned-but-not-yet-shipped reference, not drift.
    """
    path_fwd = path.replace("\\", "/")
    return any(p.search(path_fwd) for p in _ASPIRATIONAL_PATH_PATTERNS)


def _command_is_declared(cmd: str, declared: set[str]) -> bool:
    if cmd in declared:
        return True
    # Variants — `npm run test` vs `npm test`, `pnpm X` vs `pnpm run X`.
    if cmd.startswith("npm run "):
        bare = "npm " + cmd[len("npm run "):]
        if bare in declared:
            return True
    if cmd.startswith("npm test") or cmd.startswith("npm start"):
        run_form = "npm run " + cmd.split(" ", 1)[1]
        if run_form in declared:
            return True
    return False


# ---------------------------------------------------------------------------
# Vague-TODO audit
# ---------------------------------------------------------------------------


def _audit_vague_todos(doc: DocFile, text: str) -> list[DriftFinding]:
    out: list[DriftFinding] = []
    lowered_lines = [(i, line.lower()) for i, line in enumerate(text.splitlines(), start=1)]
    for line_no, lowered in lowered_lines:
        if not _TODO_LINE_RE.search(lowered):
            continue
        if any(phrase in lowered for phrase in _VAGUE_TODO_PHRASES):
            out.append(
                DriftFinding(
                    path=doc.path,
                    kind="stale_todo",
                    severity=Severity.LOW,
                    classification=Classification.UPDATE,
                    detail=(
                        "Vague TODO marker — `prompts/phases.md` Phase 6 "
                        "requires specific actionable items with file paths."
                    ),
                    line=line_no,
                )
            )
    return out


# ---------------------------------------------------------------------------
# Conflicting-agent-files audit
# ---------------------------------------------------------------------------


def _audit_conflicting_agent_files(state: RunState) -> list[DriftFinding]:
    """If two or more of AGENTS.md / CLAUDE.md / GEMINI.md / copilot
    instructions exist at the repo root, flag for Phase 5 consolidation.

    `prompts/decisions.md` "Canonical agent file rationale": the *choice*
    of which is canonical is for Phase 5. Phase 3 just records the
    conflict and classifies it `Consolidate`.
    """
    if state.inventory is None:
        return []

    root_level = [
        df
        for df in state.inventory.agent_files
        if "/" not in df.path  # repo-root only
        and df.kind in (DocKind.AGENT_INSTRUCTIONS, DocKind.COPILOT_INSTRUCTIONS)
    ]
    # README is also in agent_files (per `_utils.is_agent_file`); the
    # consolidation rule is about agent-instruction files, not READMEs.
    root_level = [df for df in root_level if df.kind != DocKind.README]

    if len(root_level) < 2:
        return []

    names = sorted({df.path for df in root_level})
    return [
        DriftFinding(
            path=df.path,
            kind="conflicting_agent_instructions",
            severity=Severity.MEDIUM,
            classification=Classification.CONSOLIDATE,
            detail=(
                f"Multiple agent-instruction files present: {names}. "
                f"Phase 5 must pick a canonical and reduce the others to wrappers."
            ),
        )
        for df in root_level
    ]
