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
    "markdown. Do not wrap the output in code fences.\n\n"
    "Workflow rules (vendored from prompts/phases.md Phase 6):\n\n"
    "{phases_section}\n\n"
    "Template skeleton:\n\n"
    "{template_section}\n\n"
    "Hard rules:\n"
    "- For each TODO in the existing handoff files, decide one of: keep, "
    "rewrite as specific, mark complete, archive, delete, or 'Needs "
    "verification'. Do not silently leave vague items.\n"
    "- Defer to existing repo conventions for TODO format (Linear IDs, "
    "`TODO(name):` markers, plain task lists). Do not impose checkboxes if "
    "the project uses something else.\n"
    "- Output raw markdown only."
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

    parts.append("\n## Existing handoff / TODO / ROADMAP files")
    if inv.handoff_files:
        for df in inv.handoff_files:
            parts.append(f"- `{df.path}` ({df.kind.value}, {df.size_bytes} bytes)")
        parts.append(
            "\nUse `read_file` to inspect each file before deciding which "
            "items to keep, rewrite, archive, or mark `Needs verification`."
        )
    else:
        parts.append("(none — create from the template using the drift "
                     "findings below.)")

    parts.append("\n## Manifests")
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
