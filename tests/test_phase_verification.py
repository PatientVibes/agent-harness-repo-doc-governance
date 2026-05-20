"""Tests for Phase 8 Tier-1 — read-only verification."""

from __future__ import annotations

from pathlib import Path

from repo_doc_governance.orchestrator import make_run_state
from repo_doc_governance.phase_impls import code_first, survey, verification
from repo_doc_governance.phases import Task

from conftest import build_broken_links_repo, build_clean_repo, build_drifted_repo


def _run_through_phase8(repo: Path):
    state = make_run_state(repo, Task.FULL_PASS)
    survey.run(state)
    code_first.run(state)
    verification.run(state)
    return state


def test_clean_repo_all_checks_pass(tmp_path: Path):
    repo = build_clean_repo(tmp_path)
    state = _run_through_phase8(repo)

    assert all(r.ok for r in state.verification_results)


def test_broken_links_repo_link_checks_fail(tmp_path: Path):
    repo = build_broken_links_repo(tmp_path)
    state = _run_through_phase8(repo)

    link_checks = [
        r for r in state.verification_results if r.check == "internal_link_resolves"
    ]
    failing = [r for r in link_checks if not r.ok]
    assert len(failing) == 2
    targets = " ".join(r.target for r in failing)
    assert "missing-1.md" in targets
    assert "missing-2.md" in targets


def test_drifted_repo_command_check_fails(tmp_path: Path):
    repo = build_drifted_repo(tmp_path)
    state = _run_through_phase8(repo)

    cmd_checks = [
        r for r in state.verification_results if r.check == "command_declared"
    ]
    failing = [r for r in cmd_checks if not r.ok]
    assert any("npm run deploy" in r.target for r in failing)


def test_every_doc_file_gets_a_path_check(tmp_path: Path):
    repo = build_clean_repo(tmp_path)
    state = _run_through_phase8(repo)
    path_checks = {
        r.target for r in state.verification_results if r.check == "path_exists"
    }
    assert "README.md" in path_checks
    assert "docs/ARCHITECTURE.md" in path_checks
