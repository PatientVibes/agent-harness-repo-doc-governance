"""Phase 1 — Survey.

Builds the `Inventory` from filesystem + git. Deterministic. No LLM.
Reads:
  - `git ls-files` (or `walk_repo()` fallback if not a git working tree)
  - For each tracked file, classifies as doc/manifest/agent/handoff/etc.
Writes:
  - `state.inventory`
"""

from __future__ import annotations

from collections import Counter

from repo_doc_governance.models import (
    DocKind,
    Inventory,
    ManifestEntry,
)
from repo_doc_governance.phase_impls import _utils
from repo_doc_governance.state import RunState


_LANG_BY_EXT: dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".jsx": "javascript",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".kt": "kotlin",
    ".rb": "ruby",
    ".php": "php",
    ".cs": "csharp",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".c": "c",
    ".h": "c",
    ".swift": "swift",
}


_GENERATED_PATTERNS: tuple[str, ...] = (
    ".bak", ".tmp", ".old", ".orig", ".rej",
    "generated-", "test-output", "coverage.",
)


def _looks_generated(path: str) -> bool:
    base = path.rsplit("/", 1)[-1].lower()
    return any(p in base for p in _GENERATED_PATTERNS)


def run(state: RunState) -> RunState:
    repo = state.target_repo
    is_git = _utils.is_git_repo(repo)

    if is_git:
        files = _utils.git_ls_files(repo)
        branch = _utils.git_current_branch(repo)
        try:
            is_clean = _utils.git_is_clean(repo)
        except Exception:  # noqa: BLE001 — defensive; phase must not crash on a dirty fs error
            is_clean = True
    else:
        files = list(_utils.walk_repo(repo))
        branch = None
        is_clean = True

    inventory = Inventory(
        target_repo=str(repo),
        is_git_repo=is_git,
        tracked_files=len(files),
        branch=branch,
        is_clean=is_clean,
    )

    # Walk files once, building all the sub-lists in a single pass.
    lang_counter: Counter[str] = Counter()

    for rel in files:
        # Manifest?
        manifest_kind = _utils.classify_manifest(rel)
        if manifest_kind is not None:
            inventory.manifests.append(
                ManifestEntry(
                    path=rel,
                    kind=manifest_kind,
                    declared_commands=_utils.extract_commands(repo, rel, manifest_kind),
                )
            )

        # Doc / agent / handoff?
        doc = _utils.make_doc_file(repo, rel)
        if doc is not None:
            if _utils.is_agent_file(doc.kind):
                inventory.agent_files.append(doc)
            elif _utils.is_handoff_file(doc.kind):
                inventory.handoff_files.append(doc)
            elif doc.kind != DocKind.OTHER_DOC:
                # ARCHITECTURE / TROUBLESHOOTING → doc_files
                inventory.doc_files.append(doc)
            else:
                inventory.doc_files.append(doc)

        # Generated-looking?
        if _looks_generated(rel):
            inventory.generated_candidates.append(rel)

        # Primary language tally.
        ext = ""
        if "." in rel.rsplit("/", 1)[-1]:
            ext = "." + rel.rsplit(".", 1)[-1].lower()
        lang = _LANG_BY_EXT.get(ext)
        if lang:
            lang_counter[lang] += 1

    inventory.primary_languages = [lang for lang, _ in lang_counter.most_common(3)]

    state.inventory = inventory
    return state
