"""Phase 8 — Safe verification (Tier 1 only in PR #3).

Tier 1 is required and read-only. It produces a `VerificationResult` per
check, recording whether each path / link / command claim in the updated
docs actually resolves.

Tier 2 (command execution behind the refuse-list) lands in PR #5 together
with the safety-invariant integration tests — keeping it out of PR #3
preserves the contract that PR #3 has no external side-effects.

Checks performed:
  - `path_exists`     — every doc-file path is present on disk.
  - `internal_link_resolves` — every internal `.md` link target exists.
  - `command_declared` — every command quoted in docs is present in
    `code_first_map.declared_commands` (Phase 2 oracle).

These checks overlap with Phase 3's drift audit on purpose: Phase 3 turns
each broken thing into a *finding with classification*; Phase 8 records
each thing checked, broken or not, so the PR body can quote a verification
table. Same input, different output shape.
"""

from __future__ import annotations

import re
from pathlib import Path

from repo_doc_governance.models import DocFile, DocKind, VerificationResult
from repo_doc_governance.state import RunState


_MD_LINK_RE = re.compile(r"\[(?P<text>[^\]]*)\]\((?P<target>[^)\s]+)\)")

_COMMAND_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"`(npm (?:run )?[A-Za-z0-9:_-]+)`"),
    re.compile(r"`(pnpm (?:run )?[A-Za-z0-9:_-]+)`"),
    re.compile(r"`(yarn (?:run )?[A-Za-z0-9:_-]+)`"),
    re.compile(r"`(make [A-Za-z0-9_/-]+)`"),
)


def run(state: RunState) -> RunState:
    if state.inventory is None:
        return state

    repo = state.target_repo
    results: list[VerificationResult] = []

    # 1) Every doc-file path exists. (It does — we found them via the
    #    file list — but the doc may have moved on disk between inventory
    #    capture and verification on a busy file system; re-check here.)
    for df in (
        *state.inventory.doc_files,
        *state.inventory.agent_files,
        *state.inventory.handoff_files,
    ):
        abs_path = repo / df.path
        results.append(
            VerificationResult(
                check="path_exists",
                target=df.path,
                ok=abs_path.exists(),
                detail="" if abs_path.exists() else "File missing on disk at verification time.",
            )
        )

    # 2) Internal links resolve.
    docs_to_scan: list[DocFile] = (
        list(state.inventory.doc_files)
        + list(state.inventory.agent_files)
        + list(state.inventory.handoff_files)
    )
    for doc in docs_to_scan:
        results.extend(_check_internal_links(repo, doc))

    # 3) Commands quoted in docs are declared somewhere.
    declared = _all_declared_commands(state)
    for doc in docs_to_scan:
        results.extend(_check_commands(repo, doc, declared))

    state.verification_results.extend(results)
    return state


def _check_internal_links(repo: Path, doc: DocFile) -> list[VerificationResult]:
    abs_path = repo / doc.path
    try:
        text = abs_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    out: list[VerificationResult] = []
    doc_dir = abs_path.parent
    for match in _MD_LINK_RE.finditer(text):
        target = match.group("target").strip()
        if not target:
            continue
        if target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        link_path = target.split("#", 1)[0].split("?", 1)[0]
        if not link_path or not link_path.endswith(".md"):
            continue
        resolved = (doc_dir / link_path).resolve()
        out.append(
            VerificationResult(
                check="internal_link_resolves",
                target=f"{doc.path} -> {target}",
                ok=resolved.exists(),
                detail="" if resolved.exists() else "Target does not exist on disk.",
            )
        )
    return out


def _check_commands(
    repo: Path, doc: DocFile, declared: set[str]
) -> list[VerificationResult]:
    abs_path = repo / doc.path
    try:
        text = abs_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    out: list[VerificationResult] = []
    for pattern in _COMMAND_PATTERNS:
        for match in pattern.finditer(text):
            cmd = match.group(1).strip()
            ok = cmd in declared or _command_is_declared(cmd, declared)
            out.append(
                VerificationResult(
                    check="command_declared",
                    target=f"{doc.path}: {cmd}",
                    ok=ok,
                    detail="" if ok else "Command is not declared in any manifest.",
                )
            )
    return out


def _command_is_declared(cmd: str, declared: set[str]) -> bool:
    if cmd in declared:
        return True
    if cmd.startswith("npm run "):
        bare = "npm " + cmd[len("npm run "):]
        if bare in declared:
            return True
    if cmd.startswith(("npm test", "npm start")):
        run_form = "npm run " + cmd.split(" ", 1)[1]
        if run_form in declared:
            return True
    return False


def _all_declared_commands(state: RunState) -> set[str]:
    declared: set[str] = set()
    if state.inventory is not None:
        for m in state.inventory.manifests:
            declared.update(m.declared_commands)
    if state.code_first_map is not None:
        for cmds in state.code_first_map.declared_commands.values():
            declared.update(cmds)
    return declared
