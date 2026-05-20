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


# ---- Aspirational-doc (plan / spec) exemption ------------------------------


def test_plan_doc_dead_command_is_needs_verification_not_update(tmp_path: Path):
    """A plan doc that references `npm run dev` against a repo without
    `package.json` describes future state — demote to
    `Needs verification`, not `Update`."""
    import json
    import subprocess

    repo = tmp_path / "ad"
    repo.mkdir()
    (repo / "README.md").write_text("# ad\n", encoding="utf-8")
    (repo / "package.json").write_text(
        json.dumps({"name": "ad", "version": "0.0.1", "scripts": {"test": "echo ok"}}),
        encoding="utf-8",
    )
    plan_dir = repo / "docs" / "superpowers" / "plans"
    plan_dir.mkdir(parents=True)
    (plan_dir / "2026-05-19-frontend.md").write_text(
        "# Frontend plan\n\nWhen the frontend lands, run `npm run dev` to start it.\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=str(repo), check=True)
    subprocess.run(["git", "add", "."], cwd=str(repo), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "i"], cwd=str(repo), check=True)

    state = _run_through_phase3(repo)

    findings = [
        f for f in state.drift_findings if "npm run dev" in f.detail
    ]
    assert len(findings) == 1
    f = findings[0]
    assert f.kind == "dead_command_in_aspirational_doc"
    assert f.classification == Classification.NEEDS_VERIFICATION
    # Severity is Low, not High — aspirational doc is less load-bearing.
    from repo_doc_governance.models import Severity
    assert f.severity == Severity.LOW


def test_regular_doc_dead_command_stays_high_update(tmp_path: Path):
    """Compare baseline — a dead command outside a plan/spec dir is
    still HIGH + Update."""
    repo = build_drifted_repo(tmp_path)  # README references `npm run deploy`
    state = _run_through_phase3(repo)
    dead = [f for f in state.drift_findings if f.kind == "dead_command"]
    assert dead, "expected at least one dead_command finding"
    f = dead[0]
    assert f.classification == Classification.UPDATE
    from repo_doc_governance.models import Severity
    assert f.severity == Severity.HIGH


def test_is_aspirational_doc_matches_plan_dirs():
    """Spec-level test of the path classifier itself."""
    assert drift_audit.is_aspirational_doc("docs/superpowers/plans/x.md")
    assert drift_audit.is_aspirational_doc("docs/superpowers/specs/x.md")
    assert drift_audit.is_aspirational_doc("docs/plans/2026-foo.md")
    assert drift_audit.is_aspirational_doc("docs/specs/foo.md")
    assert drift_audit.is_aspirational_doc("docs/design/arch.md")
    assert drift_audit.is_aspirational_doc("docs/proposals/foo.md")
    assert drift_audit.is_aspirational_doc("docs/rfcs/0001.md")
    # Non-aspirational
    assert not drift_audit.is_aspirational_doc("README.md")
    assert not drift_audit.is_aspirational_doc("docs/HANDOFF.md")
    assert not drift_audit.is_aspirational_doc("docs/ARCHITECTURE.md")
    assert not drift_audit.is_aspirational_doc("AGENTS.md")
