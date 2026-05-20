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
from repo_doc_governance.phase_impls._observability import record_llm_call
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
    "Template skeleton — use ONLY as a reference for what sections "
    "*could* exist. NEVER add a section just because it's in the template "
    "skeleton; you must have factual, repo-specific content to put in it.\n\n"
    "{template_section}\n\n"
    "## Hard rules (load-bearing — violating these is the failure mode "
    "this phase exists to prevent)\n\n"
    "1. **PRESERVE all existing content that the drift findings did NOT flag.** "
    "If the current README has a section, a sentence, a code example, a "
    "cross-repo reference, a link, or an origin/migration note — and it isn't "
    "in the drift findings list — it MUST appear in your output, byte-faithful "
    "where reasonable. You are updating a document, not writing a new one.\n\n"
    "2. **DO NOT rename the title.** The current README's first-line H1 is the "
    "canonical project name. Keep it verbatim.\n\n"
    "3. **OMIT empty sections.** If you would only be able to write "
    "'Needs verification' as a section's body (or some equivalent filler), "
    "leave the section out entirely. The README is not a template skeleton — "
    "it is a document that contains the facts that exist.\n\n"
    "4. **Manifest-faithful commands.** The user prompt lists every command "
    "declared in this repo's manifests. Quote those EXACTLY. NEVER substitute "
    "`pip install` when the manifest declares `uv tool install`. NEVER "
    "substitute `npm test` when the manifest declares `pytest`. The repo's "
    "actual convention is the only correct convention to document.\n\n"
    "5. **Cross-repo references are content, not boilerplate.** Sentences like "
    "\"Used as a library by `agent-tool-X`\" or \"Migrated from `path/Y`\" are "
    "load-bearing facts. NEVER drop them silently — they survive into the new "
    "README under the appropriate section (Status, Repository structure, "
    "Origin, etc.).\n\n"
    "6. **`Needs verification` items survive as `Needs verification` items**, "
    "not as deletions. If a drift finding has classification "
    "`Needs verification`, surface it in a clearly-marked section the human "
    "reviewer can act on; do not silently remove the line from the README.\n\n"
    "7. **Output raw markdown only.** No code fences around the whole "
    "document. No prose commentary before or after."
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
    record_llm_call(state, source="phase4_readme", ref=readme_rel, result=result)

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

    # --- The current README content. Without this, the LLM has no way to
    # honor the "preserve existing content" rule and falls back to
    # writing from the template skeleton. This is the load-bearing
    # context — it goes first in the prompt body.
    current = _read_current_readme(state.target_repo, readme_rel)
    parts.append("\n## CURRENT README CONTENT (preserve all of this unless flagged as drift)")
    parts.append("")
    parts.append("```markdown")
    parts.append(current if current else "(empty or unreadable; create from scratch using the template skeleton)")
    parts.append("```")

    parts.append("\n## Manifests (the ONLY commands you may quote)")
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
        parts.append("\n## Drift findings on README (these — and ONLY these — should change in the new README)")
        for f in readme_findings:
            parts.append(f"- [{f.severity.value}] {f.kind}: {f.detail}")
    else:
        parts.append("\n## Drift findings on README")
        parts.append(
            "(none — the README has no flagged drift. Your output should be "
            "byte-faithful to the current content unless you have a "
            "specific manifest-grounded fact to add. If there is nothing to "
            "change, output the current README verbatim.)"
        )

    parts.append("\nProduce the updated README.md body now. Raw markdown only.")
    return "\n".join(parts)


def _read_current_readme(repo: Path, rel_path: str) -> str:
    try:
        return (repo / rel_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
