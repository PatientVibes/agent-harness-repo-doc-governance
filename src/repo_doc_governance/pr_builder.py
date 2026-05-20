"""Phase-9 PR composition.

Two pieces:
  1. `build_pr_plan(state)` — pure function that assembles a `PRPlan`
     from `RunState`. The plan describes the branch name, the proposed
     file writes / deletes / moves, the inspected/run/not-run command
     list, and the PR body.
  2. `PRPlan` — the dataclass that Phase 9 consumes; safe to pass
     around between tests and the real executor.

The PR body template is the one in `prompts/templates.md`. Each section
gets populated from `RunState`; anything we can't fill from data falls
through to a "Needs verification" entry rather than getting silently
omitted.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field

from repo_doc_governance.models import Classification, DocKind
from repo_doc_governance.state import RunState


@dataclass
class PRPlan:
    branch_name: str
    base_branch: str
    pr_title: str
    pr_body: str
    files_to_write: dict[str, str] = field(default_factory=dict)
    """Repo-relative path → new content (full file body, not a diff)."""

    files_to_delete: list[str] = field(default_factory=list)
    """Repo-relative paths to `git rm`."""

    files_to_move: list[tuple[str, str]] = field(default_factory=list)
    """List of (from, to) repo-relative paths to `git mv`."""

    needs_verification: list[str] = field(default_factory=list)
    """Items the human reviewer must confirm."""


def build_pr_plan(state: RunState) -> PRPlan:
    """Compose a PRPlan from a fully-populated RunState (post Phase 6)."""
    branch_name = _branch_name(state)
    title = _title(state)

    files_to_write: dict[str, str] = {}
    if state.readme_proposed:
        files_to_write[_find_readme_path(state)] = state.readme_proposed
    for path, body in state.agent_files_proposed.items():
        files_to_write[path] = body
    if state.handoff_proposed:
        files_to_write[state.handoff_path or _handoff_path(state)] = state.handoff_proposed

    files_to_delete = [
        c.path
        for c in state.stale_artifact_candidates
        if c.classification == Classification.DELETE and c.tracked_by_git
    ]
    files_to_move = [
        (c.path, _archive_destination(c.path))
        for c in state.stale_artifact_candidates
        if c.classification == Classification.ARCHIVE and c.tracked_by_git
    ]

    needs_verification = _collect_needs_verification(state)

    pr_body = render_pr_body(
        state=state,
        files_written=list(files_to_write.keys()),
        files_deleted=files_to_delete,
        files_moved=files_to_move,
        needs_verification=needs_verification,
    )

    return PRPlan(
        branch_name=branch_name,
        base_branch=state.base_branch,
        pr_title=title,
        pr_body=pr_body,
        files_to_write=files_to_write,
        files_to_delete=files_to_delete,
        files_to_move=files_to_move,
        needs_verification=needs_verification,
    )


# ---------------------------------------------------------------------------
# Body renderer
# ---------------------------------------------------------------------------


def render_pr_body(
    *,
    state: RunState,
    files_written: list[str],
    files_deleted: list[str],
    files_moved: list[tuple[str, str]],
    needs_verification: list[str],
) -> str:
    """Render the PR body markdown from RunState + the resolved file lists.

    Follows the template in `prompts/templates.md` "PR description template".
    """
    lines: list[str] = []
    lines.append("# Summary")
    lines.append("")
    lines.append(
        "Automated repo documentation cleanup via "
        "`agent-harness-repo-doc-governance`. "
        f"Task: `{state.task.value}`. Canonical agent file: "
        f"`{state.canonical_agent_file or 'unchanged'}`."
    )
    lines.append("")

    lines.append("# Changes")
    if files_written:
        lines.append("")
        lines.append("## Updated / Added")
        for path in files_written:
            lines.append(f"- `{path}`")
    if files_moved:
        lines.append("")
        lines.append("## Moved / archived")
        for src, dst in files_moved:
            lines.append(f"- `{src}` → `{dst}`")
    if files_deleted:
        lines.append("")
        lines.append("## Removed")
        for path in files_deleted:
            lines.append(f"- `{path}`")
    if not (files_written or files_moved or files_deleted):
        lines.append("")
        lines.append("_No file changes — audit-only run._")
    lines.append("")

    lines.append("# Source of truth")
    lines.append("")
    lines.append(
        f"- Agent instructions: `{state.canonical_agent_file or 'AGENTS.md (default)'}` "
        "(canonical) — other agent files are thin wrappers."
    )
    if state.inventory is not None:
        readmes = [
            df.path for df in state.inventory.agent_files if df.kind == DocKind.README
        ]
        if readmes:
            lines.append(f"- Human onboarding: `{readmes[0]}`")
    lines.append("")

    lines.append("# Verification")
    lines.append("")
    lines.append("## Commands inspected before execution")
    inspected = sorted(
        {
            vr.target.split(":", 1)[0].strip()
            for vr in state.verification_results
            if vr.check == "command_declared"
        }
    )
    if inspected:
        for path in inspected:
            lines.append(f"- `{path}`")
    else:
        lines.append("_None — no commands were quoted in the docs._")
    lines.append("")

    lines.append("## Commands run")
    ran = [
        vr for vr in state.verification_results if vr.check == "command_execution" and vr.ok
    ]
    if ran:
        for vr in ran:
            lines.append(f"- `{vr.target}` — {vr.detail}")
    else:
        lines.append("_None — Tier-2 execution was off (default)._")
    lines.append("")

    lines.append("## Tier-1 results")
    tier1 = [
        vr
        for vr in state.verification_results
        if vr.check in ("path_exists", "internal_link_resolves", "command_declared")
    ]
    if tier1:
        passed = sum(1 for vr in tier1 if vr.ok)
        failed = sum(1 for vr in tier1 if not vr.ok)
        lines.append(f"- {passed} passed, {failed} failed (read-only checks).")
    else:
        lines.append("_No Tier-1 checks recorded._")
    lines.append("")

    not_run = [
        vr
        for vr in state.verification_results
        if vr.check == "command_execution" and not vr.ok
    ]
    if not_run:
        lines.append("# Not run")
        lines.append("")
        for vr in not_run:
            lines.append(f"- `{vr.target}` — {vr.detail}")
        lines.append("")

    if needs_verification:
        lines.append("# Needs verification")
        lines.append("")
        for item in needs_verification:
            lines.append(f"- {item}")
        lines.append("")

    lines.append("# Governance note")
    lines.append("")
    lines.append(
        "This PR requires human review. An AI agent must not self-approve, "
        "self-merge, or bypass branch protection."
    )
    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _branch_name(state: RunState) -> str:
    today = _dt.date.today().strftime("%Y%m%d")
    return f"{state.branch_prefix}/{today}-{state.task.value}"


def _title(state: RunState) -> str:
    return f"docs: governance sweep ({state.task.value})"


def _find_readme_path(state: RunState) -> str:
    if state.inventory is None:
        return "README.md"
    for df in state.inventory.agent_files:
        if df.kind == DocKind.README and "/" not in df.path:
            return df.path
    return "README.md"


def _handoff_path(state: RunState) -> str:
    if state.inventory is None:
        return "docs/HANDOFF.md"
    for df in state.inventory.handoff_files:
        if df.kind == DocKind.HANDOFF and df.path == "docs/HANDOFF.md":
            return df.path
    for df in state.inventory.handoff_files:
        if df.kind == DocKind.HANDOFF and df.path == "HANDOFF.md":
            return df.path
    return "docs/HANDOFF.md"


def _archive_destination(rel_path: str) -> str:
    base = rel_path.rsplit("/", 1)[-1]
    return f"docs/archive/{base}"


def _collect_needs_verification(state: RunState) -> list[str]:
    items: list[str] = []
    for f in state.drift_findings:
        if f.classification == Classification.NEEDS_VERIFICATION:
            items.append(f"`{f.path}`: {f.detail}")
    for c in state.stale_artifact_candidates:
        if c.classification == Classification.NEEDS_VERIFICATION:
            items.append(f"`{c.path}`: {c.reason}")
    return items
