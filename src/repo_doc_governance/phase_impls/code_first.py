"""Phase 2 — Code-first source-of-truth detection.

Builds the `CodeFirstMap` from manifests + CI + entry points. The trust
hierarchy (`prompts/decisions.md`) puts these above docs, so Phase 3
compares docs against this map rather than the other way round.

Deterministic. No LLM.

Depends on Phase 1's inventory for the manifest list. If Phase 1 hasn't
run (e.g. `readme-only` task skips it), falls back to a thin in-phase
scan via the same `_utils.classify_manifest` helper.
"""

from __future__ import annotations

from pathlib import Path

from repo_doc_governance.models import CodeFirstMap, ManifestKind
from repo_doc_governance.phase_impls import _utils
from repo_doc_governance.state import RunState


_ENTRY_POINT_NAMES: tuple[str, ...] = (
    "main.py", "main.go", "main.rs", "main.ts", "main.js",
    "app.py", "server.py", "index.js", "index.ts",
)

_ENV_EXAMPLE_NAMES: tuple[str, ...] = (
    ".env.example", ".env.sample", "env.example", ".env.template",
)


def run(state: RunState) -> RunState:
    repo = state.target_repo
    cfm = CodeFirstMap()

    # Use Phase 1's inventory if available; otherwise scan in-phase.
    manifests = []
    files: list[str] = []
    if state.inventory is not None:
        manifests = list(state.inventory.manifests)
        # We still need a file list for entry-point / env-example scan.
        if state.inventory.is_git_repo:
            try:
                files = _utils.git_ls_files(repo)
            except Exception:  # noqa: BLE001
                files = []
        else:
            files = list(_utils.walk_repo(repo))
    else:
        # Fallback path — `readme-only` skips Phase 1.
        if _utils.is_git_repo(repo):
            try:
                files = _utils.git_ls_files(repo)
            except Exception:  # noqa: BLE001
                files = []
        else:
            files = list(_utils.walk_repo(repo))
        for rel in files:
            kind = _utils.classify_manifest(rel)
            if kind is None:
                continue
            from repo_doc_governance.models import ManifestEntry  # local to avoid cycle at top

            manifests.append(
                ManifestEntry(
                    path=rel,
                    kind=kind,
                    declared_commands=_utils.extract_commands(repo, rel, kind),
                )
            )

    for m in manifests:
        if m.kind == ManifestKind.CI_WORKFLOW:
            cfm.ci_workflows.append(m.path)
            continue
        if m.declared_commands:
            cfm.declared_commands[m.path] = list(m.declared_commands)

    # Entry points + env examples
    files_set = set(files)
    for rel in files_set:
        base = rel.rsplit("/", 1)[-1]
        if base in _ENTRY_POINT_NAMES:
            cfm.entry_points.append(rel)
        if base in _ENV_EXAMPLE_NAMES:
            cfm.env_examples.append(rel)

    state.code_first_map = cfm
    return state
