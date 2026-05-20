"""Phase 4 — README update.

Builds a prompt from `state.inventory`, `state.code_first_map`, and the
README drift findings, then asks the LLM to produce an updated README body.
The phase computes a unified diff between the current README and the
proposed body and stores it in `state.readme_diff`. It does NOT touch
disk — PR-opening is Phase 9's job.

Prompt content is anchored on `prompts/templates.md` (the README section)
+ `prompts/phases.md` (the Phase-4 rules). Vendored content stays the
single source of truth.
"""

from __future__ import annotations

from pathlib import Path

from repo_doc_governance import llm_runtime
from repo_doc_governance.models import DocKind
from repo_doc_governance.phase_impls._diff import unified_diff
from repo_doc_governance.phase_impls._prompts import load_prompt
from repo_doc_governance.state import RunState


SYSTEM_PROMPT = (
    "You are the README phase of the repo-documentation-governance harness. "
    "Your sole output is the proposed new content of README.md as raw markdown. "
    "Do not wrap the output in code fences. Do not add commentary before or "
    "after. The harness will diff your output against the current README and "
    "open a PR — do not pretend you have already written the file.\n\n"
    "Workflow rules to follow (vendored from prompts/phases.md Phase 4 + "
    "prompts/templates.md README template):\n\n"
    "{phases_section}\n\n"
    "Template skeleton — include only the sections that apply:\n\n"
    "{template_section}\n\n"
    "Hard rules:\n"
    "- Verify every command against the manifests provided. Do not invent commands.\n"
    "- If a fact cannot be confirmed from the data given, write 'Needs verification' explicitly.\n"
    "- Do not duplicate long content from deeper docs — link instead.\n"
    "- Output raw markdown only. No code fences around the whole document."
)


def run(state: RunState) -> RunState:
    if state.inventory is None:
        # Phase 1 must have run for us to have anything useful to say.
        return state

    repo = state.target_repo
    readme_rel = _find_readme_path(state) or "README.md"
    user_prompt = _build_user_prompt(state, readme_rel)
    runner = llm_runtime.get_runner()
    result = runner.run(
        system_prompt=SYSTEM_PROMPT.format(
            phases_section=load_prompt("phases.md", section="## Phase 4 — README update"),
            template_section=load_prompt("templates.md", section="## README.md template"),
        ),
        user_prompt=user_prompt,
        repo_path=repo,
    )

    proposed = result.text.strip()
    if not proposed:
        return state

    proposed_with_newline = proposed + "\n"
    state.readme_proposed = proposed_with_newline
    state.readme_diff = unified_diff(repo, readme_rel, proposed_with_newline)
    return state


def _find_readme_path(state: RunState) -> str | None:
    if state.inventory is None:
        return None
    for df in state.inventory.agent_files:
        if df.kind == DocKind.README and "/" not in df.path:
            return df.path
    return None


def _build_user_prompt(state: RunState, readme_rel: str) -> str:
    inv = state.inventory
    cfm = state.code_first_map
    assert inv is not None  # caller checks

    parts: list[str] = []
    parts.append(f"Target repo: {state.target_repo}")
    parts.append(f"README to update: {readme_rel}")
    parts.append(f"Primary languages: {', '.join(inv.primary_languages) or '(unknown)'}")
    parts.append(f"Branch: {inv.branch or '(detached or none)'}")
    parts.append(f"Working tree clean: {inv.is_clean}")

    parts.append("\n## Manifests")
    for m in inv.manifests:
        cmds = ", ".join(m.declared_commands) if m.declared_commands else "(no commands)"
        parts.append(f"- `{m.path}` ({m.kind.value}) → {cmds}")

    if cfm:
        if cfm.entry_points:
            parts.append("\n## Runtime entry points")
            for ep in cfm.entry_points:
                parts.append(f"- `{ep}`")
        if cfm.env_examples:
            parts.append("\n## Env examples")
            for env in cfm.env_examples:
                parts.append(f"- `{env}`")
        if cfm.ci_workflows:
            parts.append("\n## CI workflows")
            for ci in cfm.ci_workflows:
                parts.append(f"- `{ci}`")

    readme_findings = [
        f for f in state.drift_findings if f.path == readme_rel
    ]
    if readme_findings:
        parts.append("\n## Drift findings on README")
        for f in readme_findings:
            parts.append(f"- [{f.severity.value}] {f.kind}: {f.detail}")

    parts.append("\nProduce the updated README.md body now. Raw markdown only.")
    return "\n".join(parts)
