"""Phase 6 — Handoff / TODO / ROADMAP cleanup.

Generates an updated `docs/HANDOFF.md` (or `HANDOFF.md` at the repo root,
whichever exists; if neither exists, creates `docs/HANDOFF.md` from the
template). Reads drift findings + the existing HANDOFF/TODO/ROADMAP files
and asks the LLM to produce a refreshed handoff with vague-TODO items
either marked done, rewritten as specific items, or marked
`Needs verification`.

The phase computes a unified diff and stores it in `state.handoff_diff`.
"""

from __future__ import annotations

from pathlib import Path

from repo_doc_governance import llm_runtime
from repo_doc_governance.models import DocKind
from repo_doc_governance.phase_impls._diff import unified_diff
from repo_doc_governance.phase_impls._observability import record_llm_call
from repo_doc_governance.phase_impls._prompts import load_prompt
from repo_doc_governance.state import RunState


SYSTEM_PROMPT = (
    "You are the HANDOFF phase of the repo-documentation-governance harness. "
    "Your sole output is the proposed new content of the HANDOFF file as raw "
    "markdown. Do not wrap the output in code fences. Do not add commentary "
    "before or after. The harness will diff your output against the current "
    "file and open a PR — do not pretend you have already written the file.\n\n"
    "Workflow rules to follow (vendored from prompts/phases.md Phase 6 + "
    "prompts/templates.md HANDOFF template):\n\n"
    "{phases_section}\n\n"
    "Template skeleton — use ONLY as a reference for what sections *could* "
    "exist. NEVER add a section just because it's in the template skeleton; "
    "you must have factual, repo-specific content to put in it.\n\n"
    "{template_section}\n\n"
    "## Hard rules (load-bearing — violating these is the failure mode "
    "this phase exists to prevent)\n\n"
    "1. **PRESERVE every TODO / item / fact** that appears in the source "
    "files. For each TODO, output one of: kept verbatim, rewritten as "
    "specific, marked complete, archived to a `Completed` or `Archive` "
    "section, deleted with a reason, or `Needs verification`. Silently "
    "dropping a TODO is the primary failure mode.\n\n"
    "2. **DO NOT rename the title.** If the current HANDOFF/TODO/ROADMAP "
    "file already has a first-line H1, keep it verbatim. When creating "
    "from scratch, use `# Handoff` as the H1.\n\n"
    "3. **OMIT empty sections.** If a template section has no real content "
    "to fill it, leave it out — do not pad with placeholders or filler. "
    "`Needs verification` is a valid section body only when an explicit "
    "drift finding has that classification.\n\n"
    "4. **Defer to existing repo conventions for TODO format** (Linear/Jira "
    "IDs, `TODO(name):` markers, plain task lists). Do not impose "
    "checkboxes if the project uses something else.\n\n"
    "5. **Manifest-faithful commands.** Any commands you cite must come from "
    "the manifests listed in the user prompt. Do not invent commands.\n\n"
    "6. **Cross-repo references and migration notes are content, not "
    "boilerplate.** Preserve them.\n\n"
    "7. **Output raw markdown only.** No code fences around the whole "
    "document. No prose commentary before or after."
)


def run(state: RunState) -> RunState:
    if state.inventory is None:
        return state

    repo = state.target_repo
    handoff_path = _pick_handoff_target(state)

    user_prompt = _build_user_prompt(state, handoff_path)
    runner = llm_runtime.get_runner()
    result = runner.run(
        system_prompt=SYSTEM_PROMPT.format(
            phases_section=load_prompt(
                "phases.md",
                section="## Phase 6 — Handoff / TODO / ROADMAP cleanup",
            ),
            template_section=load_prompt(
                "templates.md", section="## docs/HANDOFF.md template"
            ),
        ),
        user_prompt=user_prompt,
        repo_path=repo,
    )
    record_llm_call(state, source="phase6_handoff", ref=handoff_path, result=result)

    proposed = result.text.strip()
    if not proposed:
        return state

    body = proposed + "\n"
    state.handoff_proposed = body
    state.handoff_path = handoff_path
    state.handoff_diff = unified_diff(repo, handoff_path, body)
    return state


def _pick_handoff_target(state: RunState) -> str:
    """Pick the path the refreshed HANDOFF should be written to.

    Prefer an existing `docs/HANDOFF.md`, fall back to `HANDOFF.md` at
    the root, fall back to creating `docs/HANDOFF.md` from scratch.
    """
    if state.inventory is None:
        return "docs/HANDOFF.md"
    for df in state.inventory.handoff_files:
        if df.kind == DocKind.HANDOFF and df.path == "docs/HANDOFF.md":
            return df.path
    for df in state.inventory.handoff_files:
        if df.kind == DocKind.HANDOFF and df.path == "HANDOFF.md":
            return df.path
    return "docs/HANDOFF.md"


def _build_user_prompt(state: RunState, handoff_target: str) -> str:
    assert state.inventory is not None
    inv = state.inventory

    parts: list[str] = []
    parts.append(f"Target repo: {state.target_repo}")
    parts.append(f"HANDOFF target file: {handoff_target}")
    parts.append(f"Primary languages: {', '.join(inv.primary_languages) or '(unknown)'}")
    parts.append(f"Branch: {inv.branch or '(detached or none)'}")

    # --- Current HANDOFF / TODO / ROADMAP file content. Without this, the
    # LLM has no way to honor the "preserve every TODO" rule and falls back
    # to writing from the template skeleton (the "rewriting for tone only"
    # anti-pattern that Phase 4 had pre-v0.1.2).
    parts.append(
        "\n## CURRENT HANDOFF / TODO / ROADMAP FILES "
        "(every TODO item below must appear in your output under an "
        "explicit decision — kept / rewritten / completed / archived / "
        "deleted / Needs verification)"
    )
    if inv.handoff_files:
        for df in inv.handoff_files:
            body = _read_file_safely(state.target_repo, df.path)
            parts.append(f"\n### {df.path} ({df.kind.value})")
            parts.append("```markdown")
            parts.append(body if body else "(empty or unreadable)")
            parts.append("```")
    else:
        parts.append(
            "(none — create from the template skeleton using the drift "
            "findings below.)"
        )

    parts.append("\n## Manifests (the ONLY commands you may quote)")
    for m in inv.manifests:
        cmds = ", ".join(m.declared_commands) if m.declared_commands else "(no commands)"
        parts.append(f"- `{m.path}` → {cmds}")

    handoff_findings = [
        f for f in state.drift_findings if any(
            df.path == f.path for df in inv.handoff_files
        )
    ]
    if handoff_findings:
        parts.append("\n## Drift findings on handoff/TODO/ROADMAP")
        for f in handoff_findings:
            parts.append(
                f"- [{f.severity.value}] {f.kind} ({f.path}): {f.detail}"
            )

    parts.append("\nProduce the updated HANDOFF body now. Raw markdown only.")
    return "\n".join(parts)


def _read_file_safely(repo: Path, rel_path: str) -> str:
    try:
        return (repo / rel_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
