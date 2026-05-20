"""Tests for Phase 7 — Stale artifact cleanup (candidate identification)."""

from __future__ import annotations

from pathlib import Path

from repo_doc_governance.models import Classification
from repo_doc_governance.orchestrator import make_run_state
from repo_doc_governance.phase_impls import stale_artifacts, survey
from repo_doc_governance.phases import Task

from conftest import build_clean_repo, build_stale_artifacts_repo


def _run_through_phase7(repo: Path):
    state = make_run_state(repo, Task.FULL_PASS)
    survey.run(state)
    stale_artifacts.run(state)
    return state


def test_clean_repo_has_no_stale_candidates(tmp_path: Path):
    repo = build_clean_repo(tmp_path)
    state = _run_through_phase7(repo)
    assert state.stale_artifact_candidates == []


def test_stale_repo_flags_bak_file(tmp_path: Path):
    repo = build_stale_artifacts_repo(tmp_path)
    state = _run_through_phase7(repo)

    candidates = state.stale_artifact_candidates
    by_path = {c.path: c for c in candidates}

    assert "src/main.py.bak" in by_path
    bak = by_path["src/main.py.bak"]
    assert bak.tracked_by_git is True
    assert bak.classification == Classification.DELETE


def test_stale_repo_flags_scratch_md_as_archive(tmp_path: Path):
    repo = build_stale_artifacts_repo(tmp_path)
    state = _run_through_phase7(repo)

    by_path = {c.path: c for c in state.stale_artifact_candidates}
    assert "scratch.md" in by_path
    scratch = by_path["scratch.md"]
    assert scratch.tracked_by_git is True
    assert scratch.classification == Classification.ARCHIVE


def test_stale_repo_flags_handoff_final_final(tmp_path: Path):
    repo = build_stale_artifacts_repo(tmp_path)
    state = _run_through_phase7(repo)

    by_path = {c.path: c for c in state.stale_artifact_candidates}
    assert "handoff-final-final.md" in by_path
    h = by_path["handoff-final-final.md"]
    assert h.kind == "duplicate_handoff"
    assert h.classification == Classification.ARCHIVE


def test_stale_repo_flags_ds_store_as_delete(tmp_path: Path):
    repo = build_stale_artifacts_repo(tmp_path)
    state = _run_through_phase7(repo)

    by_path = {c.path: c for c in state.stale_artifact_candidates}
    assert ".DS_Store" in by_path
    assert by_path[".DS_Store"].classification == Classification.DELETE


def test_untracked_bak_file_is_classified_needs_verification(tmp_path: Path):
    repo = build_clean_repo(tmp_path)
    # Add an untracked .bak file AFTER the initial commit.
    (repo / "untracked.bak").write_text("scratch\n", encoding="utf-8")

    state = make_run_state(repo, Task.FULL_PASS)
    survey.run(state)
    stale_artifacts.run(state)

    by_path = {c.path: c for c in state.stale_artifact_candidates}
    assert "untracked.bak" in by_path
    c = by_path["untracked.bak"]
    assert c.tracked_by_git is False
    assert c.classification == Classification.NEEDS_VERIFICATION


def test_referenced_stale_file_is_classified_needs_verification(tmp_path: Path):
    """A `.bak` file that is mentioned by name from another doc must
    not be auto-Delete. See `prompts/decisions.md`.
    """
    repo = tmp_path / "ref"
    repo.mkdir()
    (repo / "README.md").write_text(
        "# referenced\n\nLegacy backup: see src/legacy.py.bak.\n", encoding="utf-8"
    )
    (repo / "src").mkdir()
    (repo / "src" / "legacy.py.bak").write_text("legacy\n", encoding="utf-8")
    (repo / "package.json").write_text('{"name":"r","version":"0.0.1","scripts":{}}\n', encoding="utf-8")
    import subprocess
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=str(repo), check=True)
    subprocess.run(["git", "add", "."], cwd=str(repo), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "i"], cwd=str(repo), check=True)

    state = make_run_state(repo, Task.FULL_PASS)
    survey.run(state)
    stale_artifacts.run(state)

    by_path = {c.path: c for c in state.stale_artifact_candidates}
    assert "src/legacy.py.bak" in by_path
    c = by_path["src/legacy.py.bak"]
    assert c.referenced_count > 0
    assert c.classification == Classification.NEEDS_VERIFICATION
