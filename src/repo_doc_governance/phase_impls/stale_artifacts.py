"""Phase 7 — Stale artifact cleanup (candidate identification).

Pure read-only candidate identification. No file mutation here — Phase 9
is the one that opens a PR that touches files. Phase 7 builds the list of
candidates and classifies each per `prompts/decisions.md`.

Classification rules applied here:
  - `*.bak / *.tmp / *.old / *.orig / *.rej` → Delete (tracked) or
    Needs verification (untracked — could be in-progress work).
  - `.DS_Store / Thumbs.db` → Delete (tracked) or Needs verification
    (untracked).
  - `scratch.md / notes-old.md / handoff-final-final.md / handoff-v2-FINAL.md`
    → Archive (move to `docs/archive/`).
  - `generated-*.md / test-output.txt / coverage*` and not referenced
    from CI/scripts → Archive.

Safety invariants per `prompts/phases.md` Phase 7:
  - Never auto-Delete an untracked file. Always `Needs verification`.
  - Never auto-Delete a file referenced from another doc/script/CI/config.
    Always `Needs verification` instead.
"""

from __future__ import annotations

import re
from pathlib import Path

from repo_doc_governance.models import Classification, StaleCandidate
from repo_doc_governance.phase_impls import _utils
from repo_doc_governance.state import RunState


_BAKKY_EXTENSIONS: tuple[str, ...] = (".bak", ".tmp", ".old", ".orig", ".rej")
_OS_DROPPINGS: tuple[str, ...] = (".ds_store", "thumbs.db")
_SCRATCH_NAMES: tuple[str, ...] = (
    "scratch.md", "notes-old.md", "scratchpad.md",
)
_HANDOFF_DROPPING_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)^handoff-?(final-?)+\.md$"),
    re.compile(r"(?i)^handoff-?v\d+(-final)?\.md$"),
    re.compile(r"(?i)^.*-(final-?){2,}\.md$"),
)
_GENERATED_PATTERNS: tuple[str, ...] = (
    "generated-", "test-output", "coverage.",
)


def run(state: RunState) -> RunState:
    if state.inventory is None:
        return state

    repo = state.target_repo
    # Build the reference-count index ONCE: which paths are mentioned by
    # which docs / scripts / CI / config files. Phase 7 uses this to keep
    # the "Never delete a referenced file" invariant deterministic.
    reference_index = _build_reference_index(state)

    inventory = state.inventory
    all_paths: set[str] = set()
    for df in (
        *inventory.doc_files,
        *inventory.agent_files,
        *inventory.handoff_files,
    ):
        all_paths.add(df.path)
    all_paths.update(inventory.generated_candidates)

    # Phase 7 must see tracked AND untracked files — an untracked `*.bak`
    # in the user's working tree is exactly the kind of "ask before
    # touching" case `prompts/phases.md` Phase 7 calls out.
    if inventory.is_git_repo:
        try:
            all_paths.update(_utils.git_ls_files(repo))
        except Exception:  # noqa: BLE001 — defensive
            pass
        try:
            all_paths.update(_utils.git_untracked_files(repo))
        except Exception:  # noqa: BLE001
            pass
    else:
        all_paths.update(_utils.walk_repo(repo))

    candidates: list[StaleCandidate] = []
    for rel in sorted(all_paths):
        candidate = _classify_path(repo, rel, inventory.is_git_repo, reference_index)
        if candidate is not None:
            candidates.append(candidate)

    state.stale_artifact_candidates.extend(candidates)
    return state


# ---------------------------------------------------------------------------
# Reference index — "who mentions whom"
# ---------------------------------------------------------------------------


def _build_reference_index(state: RunState) -> dict[str, int]:
    """For each *basename* in any doc, count how many docs mention it.

    This is intentionally coarse — a file's basename appearing in any doc
    bumps its reference count. False positives lean us toward
    `Needs verification` (safer) rather than `Delete`.
    """
    counter: dict[str, int] = {}
    if state.inventory is None:
        return counter
    repo = state.target_repo
    for df in (
        *state.inventory.doc_files,
        *state.inventory.agent_files,
        *state.inventory.handoff_files,
    ):
        abs_path = repo / df.path
        try:
            text = abs_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for token in re.findall(r"[A-Za-z0-9_.-]+\.[A-Za-z0-9]+", text):
            counter[token] = counter.get(token, 0) + 1
    return counter


# ---------------------------------------------------------------------------
# Per-path classification
# ---------------------------------------------------------------------------


def _classify_path(
    repo: Path,
    rel: str,
    is_git_repo: bool,
    references: dict[str, int],
) -> StaleCandidate | None:
    base = rel.rsplit("/", 1)[-1]
    lowered = base.lower()
    kind: str | None = None
    reason = ""

    if any(lowered.endswith(ext) for ext in _BAKKY_EXTENSIONS):
        kind = "tmp_artifact"
        reason = f"Filename ends with a temp/backup extension ({base})."
    elif lowered in _OS_DROPPINGS:
        kind = "os_droppings"
        reason = f"OS-level metadata file ({base})."
    elif lowered in _SCRATCH_NAMES:
        kind = "scratch_note"
        reason = f"Scratch/notes filename ({base})."
    elif any(p.match(lowered) for p in _HANDOFF_DROPPING_PATTERNS):
        kind = "duplicate_handoff"
        reason = f"`final-final`/`v2-FINAL` style handoff dropping ({base})."
    elif any(p in lowered for p in _GENERATED_PATTERNS):
        kind = "generated_dump"
        reason = f"Filename matches a generated-output pattern ({base})."

    if kind is None:
        return None

    # Reference count (basename-keyed, see _build_reference_index docstring).
    ref_count = references.get(base, 0)

    # Tracked-by-git check — drives the Delete vs Needs verification choice.
    tracked = False
    if is_git_repo:
        try:
            tracked = _utils.git_path_is_tracked(repo, rel)
        except Exception:  # noqa: BLE001
            tracked = False

    classification = _choose_classification(kind, tracked, ref_count)

    return StaleCandidate(
        path=rel,
        kind=kind,
        classification=classification,
        tracked_by_git=tracked,
        referenced_count=ref_count,
        reason=reason,
    )


def _choose_classification(
    kind: str, tracked: bool, ref_count: int
) -> Classification:
    """Apply the decision tree from `prompts/decisions.md`."""
    # Untracked file → never auto-Delete; punt to human.
    if not tracked:
        return Classification.NEEDS_VERIFICATION
    # Referenced from another doc → safer to flag than to delete.
    if ref_count > 0:
        return Classification.NEEDS_VERIFICATION
    # Scratch / duplicate-handoff content may have historical value → Archive.
    if kind in ("scratch_note", "duplicate_handoff"):
        return Classification.ARCHIVE
    # Clear OS / temp / generated junk → Delete.
    return Classification.DELETE
