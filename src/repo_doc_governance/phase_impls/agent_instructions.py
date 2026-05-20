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
from repo_doc_governance.phase_impls._observability import record_llm_call
from repo_doc_governance.phase_impls._prompts import load_prompt
from repo_doc_governance.state import RunState


SYSTEM_PROMPT = (
    "You are the agent-instruction-consolidation phase of the "
    "repo-documentation-governance harness. Your sole output is the "
    "proposed new content of the CANONICAL agent-instruction file as raw "
    "markdown. Do not wrap the output in code fences. Do not add commentary "
    "before or after. The harness will diff your output against the current "
    "file and open a PR.\n\n"
    "Workflow rules to follow (vendored from prompts/phases.md Phase 5 + "
    "prompts/templates.md agent template):\n\n"
    "{phases_section}\n\n"
    "Template for the canonical file — use ONLY as a reference for what "
    "sections *could* exist. NEVER add a section just because it's in the "
    "template skeleton; you must have factual, repo-specific content to "
    "put in it.\n\n"
    "{template_section}\n\n"
    "## Hard rules (load-bearing — violating these is the failure mode "
    "this phase exists to prevent)\n\n"
    "1. **PRESERVE every command, safety constraint, and repo-specific quirk "
    "that appears in ANY of the source agent files unless the drift findings "
    "explicitly flag it.** Two source files that DISAGREE go in a "
    "'Conflicts to resolve' subsection — never silently pick one.\n\n"
    "2. **DO NOT rename the canonical title.** If the current canonical file "
    "already has a first-line H1, keep it verbatim. When creating from "
    "scratch, use `# Agent Instructions` (or `# Claude Instructions` for "
    "Claude-first repos).\n\n"
    "3. **OMIT empty sections.** If you would only be able to write filler "
    "(e.g. 'Needs verification' as a section's body, or template "
    "placeholders), leave the section out entirely. The canonical file is "
    "not a template skeleton — it is a document that contains the facts "
    "that exist.\n\n"
    "4. **Manifest-faithful commands.** The user prompt lists every command "
    "declared in this repo's manifests. Quote those EXACTLY. NEVER substitute "
    "`pip install` when the manifest declares `uv tool install`. NEVER "
    "substitute `npm test` when the manifest declares `pytest`. The repo's "
    "actual convention is the only correct convention to document.\n\n"
    "5. **Cross-repo references and migration notes are content, not "
    "boilerplate.** Sentences like \"Used as a library by `agent-tool-X`\" "
    "or \"Migrated from `path/Y`\" are load-bearing facts. NEVER drop them "
    "silently — they survive into the new canonical file under the "
    "appropriate section.\n\n"
    "6. **`Needs verification` items survive as `Needs verification` items**, "
    "not as deletions. If a drift finding has classification "
    "`Needs verification`, surface it in a clearly-marked section the human "
    "reviewer can act on; do not silently remove the line.\n\n"
    "7. **Output raw markdown only.** No code fences around the whole "
    "document. No prose commentary before or after."
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
            body = canonical_text + "\n"
            state.agent_files_proposed[canonical_path] = body
            state.agent_files_diff = _format_multifile_diff(
                {canonical_path: unified_diff(repo, canonical_path, body)}
            )
        return state

    canonical_text = _generate_canonical(state, canonical_path, agent_files)
    if not canonical_text:
        return state

    diffs: dict[str, str] = {}
    canonical_body = canonical_text + "\n"
    state.agent_files_proposed[canonical_path] = canonical_body
    diffs[canonical_path] = unified_diff(repo, canonical_path, canonical_body)

    wrapper_text = _build_wrapper(canonical_path)
    for df in agent_files:
        if df.path == canonical_path:
            continue
        # Only generate wrappers for files that aren't already the canonical.
        state.agent_files_proposed[df.path] = wrapper_text
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
    record_llm_call(
        state, source="phase5_agent_instructions", ref=canonical_path, result=result
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

    # --- Current agent-instruction file content. Without this, the LLM has
    # no way to honor the "preserve existing content" rule and falls back
    # to writing from the template skeleton (the "rewriting for tone only"
    # anti-pattern). Include EVERY source file the consolidation may touch,
    # including `.github/copilot-instructions.md` and any nested locations
    # — the canonical-choice scope is separate from the read scope.
    all_sources = [
        df
        for df in inv.agent_files
        if df.kind in (DocKind.AGENT_INSTRUCTIONS, DocKind.COPILOT_INSTRUCTIONS)
    ]
    parts.append(
        "\n## CURRENT AGENT-INSTRUCTION FILES "
        "(preserve all content unless flagged as drift)"
    )
    if all_sources:
        for df in all_sources:
            body = _read_file_safely(state.target_repo, df.path)
            parts.append(f"\n### {df.path} ({df.kind.value})")
            parts.append("```markdown")
            parts.append(body if body else "(empty or unreadable)")
            parts.append("```")
    else:
        parts.append(
            "(none — create canonical agent instructions from scratch "
            "using the template skeleton.)"
        )

    parts.append("\n## Manifests (the ONLY commands you may quote)")
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


def _read_file_safely(repo: Path, rel_path: str) -> str:
    try:
        return (repo / rel_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


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
