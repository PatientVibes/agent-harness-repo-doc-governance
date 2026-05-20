"""Tests for Phase 3 — Drift audit."""

from __future__ import annotations

from pathlib import Path

from repo_doc_governance.models import Classification
from repo_doc_governance.orchestrator import make_run_state
from repo_doc_governance.phase_impls import code_first, drift_audit, survey
from repo_doc_governance.phases import Task

from conftest import (
    build_agents_and_claude_repo,
    build_broken_links_repo,
    build_clean_repo,
    build_drifted_repo,
)


def _run_through_phase3(repo: Path):
    state = make_run_state(repo, Task.FULL_PASS)
    survey.run(state)
    code_first.run(state)
    drift_audit.run(state)
    return state


def test_clean_repo_has_no_drift_findings(tmp_path: Path):
    repo = build_clean_repo(tmp_path)
    state = _run_through_phase3(repo)
    assert state.drift_findings == []


def test_drifted_repo_flags_dead_npm_command(tmp_path: Path):
    repo = build_drifted_repo(tmp_path)
    state = _run_through_phase3(repo)

    dead = [f for f in state.drift_findings if f.kind == "dead_command"]
    assert len(dead) >= 1
    assert any("npm run deploy" in f.detail for f in dead)
    assert all(f.classification == Classification.UPDATE for f in dead)


def test_drifted_repo_flags_broken_link(tmp_path: Path):
    repo = build_drifted_repo(tmp_path)
    state = _run_through_phase3(repo)

    broken = [f for f in state.drift_findings if f.kind == "broken_internal_link"]
    assert any("docs/MISSING.md" in f.detail for f in broken)


def test_drifted_repo_flags_vague_todo(tmp_path: Path):
    repo = build_drifted_repo(tmp_path)
    state = _run_through_phase3(repo)

    stale_todos = [f for f in state.drift_findings if f.kind == "stale_todo"]
    assert len(stale_todos) >= 1
    assert any(f.path == "docs/HANDOFF.md" for f in stale_todos)


def test_broken_links_repo_flags_each_missing_target(tmp_path: Path):
    repo = build_broken_links_repo(tmp_path)
    state = _run_through_phase3(repo)

    broken = [f for f in state.drift_findings if f.kind == "broken_internal_link"]
    assert len(broken) == 2
    targets = " ".join(f.detail for f in broken)
    assert "missing-1.md" in targets
    assert "missing-2.md" in targets


def test_conflicting_agent_files_are_classified_consolidate(tmp_path: Path):
    repo = build_agents_and_claude_repo(tmp_path)
    state = _run_through_phase3(repo)

    conflicts = [
        f
        for f in state.drift_findings
        if f.kind == "conflicting_agent_instructions"
    ]
    paths = {f.path for f in conflicts}
    assert "AGENTS.md" in paths
    assert "CLAUDE.md" in paths
    assert all(f.classification == Classification.CONSOLIDATE for f in conflicts)


def test_single_agent_file_is_not_a_conflict(tmp_path: Path):
    """One agent file == no consolidation finding."""
    repo = build_clean_repo(tmp_path)
    state = _run_through_phase3(repo)
    conflicts = [
        f
        for f in state.drift_findings
        if f.kind == "conflicting_agent_instructions"
    ]
    assert conflicts == []
