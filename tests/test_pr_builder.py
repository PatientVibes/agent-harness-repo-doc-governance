"""Tests for `pr_builder.build_pr_plan` + Phase-9 dry-run behavior."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from repo_doc_governance import llm_runtime, pr_builder
from repo_doc_governance.llm_runtime import StubLLMRunner
from repo_doc_governance.models import (
    Classification,
    DriftFinding,
    Severity,
    StaleCandidate,
)
from repo_doc_governance.orchestrator import make_run_state
from repo_doc_governance.phase_impls import (
    code_first,
    drift_audit,
    pr_handoff,
    stale_artifacts,
    survey,
    verification,
)
from repo_doc_governance.phases import Task


@pytest.fixture(autouse=True)
def _reset_runner():
    llm_runtime.set_runner(None)
    yield
    llm_runtime.set_runner(None)


def _init_repo(repo: Path, files: dict[str, str], *, branch: str = "main") -> None:
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", branch], cwd=str(repo), check=True)
    subprocess.run(
        ["git", "config", "user.email", "harness@example.invalid"],
        cwd=str(repo), check=True,
    )
    subprocess.run(["git", "config", "user.name", "harness"], cwd=str(repo), check=True)
    for rel, content in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(repo), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=str(repo), check=True)


def test_pr_plan_branch_name_format(tmp_path: Path):
    state = make_run_state(tmp_path, Task.FULL_PASS)
    plan = pr_builder.build_pr_plan(state)
    assert plan.branch_name.startswith("doc-governance/")
    assert plan.branch_name.endswith("full-pass")


def test_pr_plan_includes_governance_note(tmp_path: Path):
    state = make_run_state(tmp_path, Task.FULL_PASS)
    plan = pr_builder.build_pr_plan(state)
    assert "Governance note" in plan.pr_body
    assert "must not self-approve" in plan.pr_body
    assert "self-merge" in plan.pr_body


def test_pr_plan_files_to_delete_filters_untracked(tmp_path: Path):
    """A StaleCandidate classified Delete but with tracked_by_git=False
    must NOT appear in files_to_delete. The reverse — tracked, Delete —
    is the only auto-delete path."""
    state = make_run_state(tmp_path, Task.FULL_PASS)
    state.stale_artifact_candidates.append(
        StaleCandidate(
            path="ghost.bak",
            kind="tmp_artifact",
            classification=Classification.DELETE,
            tracked_by_git=False,
            referenced_count=0,
            reason="(synthetic untracked)",
        )
    )
    state.stale_artifact_candidates.append(
        StaleCandidate(
            path="real.bak",
            kind="tmp_artifact",
            classification=Classification.DELETE,
            tracked_by_git=True,
            referenced_count=0,
            reason="(synthetic tracked)",
        )
    )
    plan = pr_builder.build_pr_plan(state)
    assert "ghost.bak" not in plan.files_to_delete
    assert "real.bak" in plan.files_to_delete


def test_pr_plan_archive_moves_to_docs_archive(tmp_path: Path):
    state = make_run_state(tmp_path, Task.FULL_PASS)
    state.stale_artifact_candidates.append(
        StaleCandidate(
            path="handoff-final-final.md",
            kind="duplicate_handoff",
            classification=Classification.ARCHIVE,
            tracked_by_git=True,
            referenced_count=0,
            reason="dropping",
        )
    )
    plan = pr_builder.build_pr_plan(state)
    assert ("handoff-final-final.md", "docs/archive/handoff-final-final.md") in plan.files_to_move


def test_pr_plan_needs_verification_aggregates(tmp_path: Path):
    state = make_run_state(tmp_path, Task.FULL_PASS)
    state.drift_findings.append(
        DriftFinding(
            path="README.md",
            kind="missing_path",
            severity=Severity.MEDIUM,
            classification=Classification.NEEDS_VERIFICATION,
            detail="Path src/legacy.py not found.",
        )
    )
    state.stale_artifact_candidates.append(
        StaleCandidate(
            path="docs/maybe.md",
            kind="scratch_note",
            classification=Classification.NEEDS_VERIFICATION,
            tracked_by_git=False,
            referenced_count=0,
            reason="untracked scratch",
        )
    )
    plan = pr_builder.build_pr_plan(state)
    assert any("src/legacy.py" in item for item in plan.needs_verification)
    assert any("docs/maybe.md" in item for item in plan.needs_verification)


def test_phase9_dry_run_does_not_create_branch(tmp_path: Path):
    """With execute_phase9=False (default), Phase 9 must not modify the
    git state at all — no branch, no commit, no working-tree changes."""
    repo = tmp_path / "repo"
    _init_repo(
        repo,
        {
            "README.md": "# x\n",
            "package.json": json.dumps({"scripts": {"test": "echo ok"}}),
        },
        branch="main",
    )

    llm_runtime.set_runner(StubLLMRunner(text="# x\n\nupdated\n"))

    state = make_run_state(repo, Task.FULL_PASS)
    state.base_branch = "main"
    # execute_phase9 stays False (default)

    survey.run(state)
    code_first.run(state)
    drift_audit.run(state)
    pr_handoff.run(state)

    # Branch list should still be just `main`.
    result = subprocess.run(
        ["git", "branch", "--list"],
        cwd=str(repo), capture_output=True, text=True, check=True,
    )
    branches = [
        line.strip().lstrip("* ").strip() for line in result.stdout.splitlines()
    ]
    assert branches == ["main"]
    # PR body should still be built.
    assert state.pr_body_draft != ""
    assert state.pr_branch_name is not None
    assert state.pr_url is None  # not pushed → no URL
