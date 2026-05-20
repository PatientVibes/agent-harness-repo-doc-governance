"""Phase 5 — Agent instruction consolidation.

Two-step:

1) **Deterministically pick the canonical file.** Per `prompts/decisions.md`
   "Canonical agent file rationale": default `AGENTS.md` unless the repo
   shows Claude-first signals (`.claude/**` infrastructure) — in which
   case `CLAUDE.md` is canonical. The decision is recorded in
   `state.canonical_agent_file` so the PR body (Phase 9) can quote it.

2) **Generate canonical content via LLM**, then **template-fill wrappers
   deterministically** for the non-canonical agent files. The thin-wrapper
   shape is fixed (see `prompts/templates.md`) — no LLM call needed.

The phase computes one diff per touched agent file and concatenates them
into `state.agent_files_diff` with a `--- file ---` separator so Phase 9
can split and present them per-file in the PR body.
"""

from __future__ import annotations

from pathlib import Path

from repo_doc_governance import llm_runtime
from repo_doc_governance.models import DocFile, DocKind
from repo_doc_governance.phase_impls._diff import unified_diff
from repo_doc_governance.phase_impls._prompts import load_prompt
from repo_doc_governance.state import RunState


SYSTEM_PROMPT = (
    "You are the agent-instruction-consolidation phase of the "
    "repo-documentation-governance harness. Your sole output is the "
    "proposed new content of the CANONICAL agent-instruction file as raw "
    "markdown. Do not wrap the output in code fences. The harness will "
    "diff your output against the current file and open a PR.\n\n"
    "Workflow rules (vendored from prompts/phases.md Phase 5):\n\n"
    "{phases_section}\n\n"
    "Template for the canonical file:\n\n"
    "{template_section}\n\n"
    "Hard rules:\n"
    "- Consolidate without losing any commands or safety constraints that "
    "appear in ANY of the source files. If two files disagree, surface the "
    "conflict in a 'Conflicts to resolve' subsection rather than silently "
    "picking one.\n"
    "- Do not invent commands. Use only commands declared in the manifests "
    "provided.\n"
    "- Output raw markdown only."
)


_CLAUDE_FIRST_HINTS = (".claude/",)


def run(state: RunState) -> RunState:
    if state.inventory is None:
        return state

    repo = state.target_repo
    agent_files = [
        df
        for df in state.inventory.agent_files
        if df.kind in (DocKind.AGENT_INSTRUCTIONS, DocKind.COPILOT_INSTRUCTIONS)
        and "/" not in df.path
    ]

    canonical_path = _choose_canonical(repo, agent_files, state)
    state.canonical_agent_file = canonical_path

    if not agent_files:
        # No existing agent files. Generate AGENTS.md from scratch (the
        # template-driven "no existing docs" case in decisions.md).
        canonical_text = _generate_canonical(state, canonical_path, agent_files)
        if canonical_text:
            state.agent_files_diff = _format_multifile_diff(
                {canonical_path: unified_diff(repo, canonical_path, canonical_text + "\n")}
            )
        return state

    canonical_text = _generate_canonical(state, canonical_path, agent_files)
    if not canonical_text:
        return state

    diffs: dict[str, str] = {}
    diffs[canonical_path] = unified_diff(repo, canonical_path, canonical_text + "\n")

    wrapper_text = _build_wrapper(canonical_path)
    for df in agent_files:
        if df.path == canonical_path:
            continue
        # Only generate wrappers for files that aren't already the canonical.
        diffs[df.path] = unified_diff(repo, df.path, wrapper_text)

    state.agent_files_diff = _format_multifile_diff(diffs)
    return state


def _choose_canonical(
    repo: Path, agent_files: list[DocFile], state: RunState
) -> str:
    """Per `prompts/decisions.md`: default AGENTS.md; use CLAUDE.md when
    the repo is Claude-first (heavy `.claude/**` infrastructure)."""
    claude_first = (repo / ".claude").is_dir()
    if not claude_first and state.inventory is not None:
        # Check the file list too — `.claude/` may not exist as a literal
        # directory if everything is inlined.
        for df in state.inventory.agent_files:
            if df.path.startswith(_CLAUDE_FIRST_HINTS):
                claude_first = True
                break
    if claude_first:
        return "CLAUDE.md"
    return "AGENTS.md"


def _generate_canonical(
    state: RunState, canonical_path: str, agent_files: list[DocFile]
) -> str:
    user_prompt = _build_user_prompt(state, canonical_path, agent_files)
    runner = llm_runtime.get_runner()
    template_key = (
        "## CLAUDE.md (canonical, Claude-first repos) template"
        if canonical_path == "CLAUDE.md"
        else "## AGENTS.md (canonical) template"
    )
    result = runner.run(
        system_prompt=SYSTEM_PROMPT.format(
            phases_section=load_prompt(
                "phases.md", section="## Phase 5 — Agent instruction consolidation"
            ),
            template_section=load_prompt("templates.md", section=template_key),
        ),
        user_prompt=user_prompt,
        repo_path=state.target_repo,
    )
    return result.text.strip()


def _build_user_prompt(
    state: RunState, canonical_path: str, agent_files: list[DocFile]
) -> str:
    assert state.inventory is not None
    inv = state.inventory

    parts: list[str] = []
    parts.append(f"Target repo: {state.target_repo}")
    parts.append(f"Canonical file (already chosen): {canonical_path}")
    parts.append(f"Primary languages: {', '.join(inv.primary_languages) or '(unknown)'}")

    parts.append("\n## Existing agent-instruction files")
    if agent_files:
        for df in agent_files:
            parts.append(f"- `{df.path}` ({df.kind.value}, {df.size_bytes} bytes)")
        parts.append(
            "\nUse the `read_file` tool to inspect any of the existing "
            "agent files whose contents you need to preserve. Consolidate "
            "shared rules and call out contradictions."
        )
    else:
        parts.append(
            "(none — create canonical agent instructions from scratch "
            "using the template.)"
        )

    parts.append("\n## Manifests (the only commands you may reference)")
    for m in inv.manifests:
        cmds = ", ".join(m.declared_commands) if m.declared_commands else "(no commands)"
        parts.append(f"- `{m.path}` → {cmds}")

    related = [
        f
        for f in state.drift_findings
        if f.kind == "conflicting_agent_instructions"
        or any(df.path == f.path for df in agent_files)
    ]
    if related:
        parts.append("\n## Drift findings on agent files")
        for f in related:
            parts.append(f"- [{f.severity.value}] {f.path}: {f.detail}")

    parts.append(f"\nProduce the new {canonical_path} body now. Raw markdown only.")
    return "\n".join(parts)


def _build_wrapper(canonical_path: str) -> str:
    """Generate the thin-wrapper body from the fixed template in
    `prompts/templates.md`. Phase 5's contract: wrappers are
    deterministic — only the canonical content uses the LLM."""
    if canonical_path == "AGENTS.md":
        return (
            "# Claude Instructions\n\n"
            "Use `AGENTS.md` as the canonical repository instruction file. "
            "Everything in `AGENTS.md` applies to Claude Code.\n\n"
            "Claude-specific notes:\n\n"
            "- Follow the repository's documented verification commands before "
            "final handoff.\n"
        )
    # Claude-first wrapper
    return (
        "# Agent Instructions\n\n"
        "Use `CLAUDE.md` as the canonical repository instruction file. "
        "Everything in `CLAUDE.md` applies to all agents.\n\n"
        "This repository is intentionally Claude-first, but the operating "
        "rules, build commands, and constraints in `CLAUDE.md` apply equally "
        "to Codex, Gemini CLI, Cursor, Aider, OpenCode, and any other agent "
        "runtime.\n"
    )


def _format_multifile_diff(diffs: dict[str, str]) -> str:
    """Concatenate per-file diffs with a separator the Phase 9 PR builder
    can split on later."""
    parts: list[str] = []
    for path, diff in diffs.items():
        if not diff:
            continue
        parts.append(f"--- file: {path} ---")
        parts.append(diff)
    return "\n".join(parts).rstrip()
