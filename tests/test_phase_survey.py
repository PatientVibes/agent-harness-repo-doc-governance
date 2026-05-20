"""Tests for Phase 1 — Survey."""

from __future__ import annotations

from pathlib import Path

from repo_doc_governance.models import DocKind, ManifestKind
from repo_doc_governance.orchestrator import make_run_state
from repo_doc_governance.phase_impls import survey
from repo_doc_governance.phases import Task

from conftest import (
    build_agents_and_claude_repo,
    build_clean_repo,
    build_drifted_repo,
    build_monorepo,
)


def test_survey_clean_repo_finds_readme_and_package_json(tmp_path: Path):
    repo = build_clean_repo(tmp_path)
    state = make_run_state(repo, Task.FULL_PASS)
    survey.run(state)

    assert state.inventory is not None
    inv = state.inventory
    assert inv.is_git_repo is True
    assert inv.tracked_files >= 4
    assert inv.branch == "main"
    assert inv.is_clean is True

    readmes = [df for df in inv.agent_files if df.kind == DocKind.README]
    assert any(df.path == "README.md" for df in readmes)

    pkg_jsons = [m for m in inv.manifests if m.kind == ManifestKind.NODE_PACKAGE]
    assert len(pkg_jsons) == 1
    declared = pkg_jsons[0].declared_commands
    assert "npm test" in declared
    assert "npm run test" in declared
    assert "npm run build" in declared


def test_survey_detects_javascript_language(tmp_path: Path):
    repo = build_clean_repo(tmp_path)
    state = make_run_state(repo, Task.FULL_PASS)
    survey.run(state)
    assert state.inventory is not None
    assert "javascript" in state.inventory.primary_languages


def test_survey_records_handoff_files(tmp_path: Path):
    repo = build_drifted_repo(tmp_path)
    state = make_run_state(repo, Task.FULL_PASS)
    survey.run(state)
    assert state.inventory is not None
    handoff_paths = [df.path for df in state.inventory.handoff_files]
    assert "docs/HANDOFF.md" in handoff_paths


def test_survey_distinguishes_agents_and_claude(tmp_path: Path):
    repo = build_agents_and_claude_repo(tmp_path)
    state = make_run_state(repo, Task.FULL_PASS)
    survey.run(state)
    assert state.inventory is not None
    paths = {df.path for df in state.inventory.agent_files}
    assert "AGENTS.md" in paths
    assert "CLAUDE.md" in paths
    assert "README.md" in paths


def test_survey_monorepo_finds_nested_manifests(tmp_path: Path):
    repo = build_monorepo(tmp_path)
    state = make_run_state(repo, Task.FULL_PASS)
    survey.run(state)
    assert state.inventory is not None
    manifest_paths = {m.path for m in state.inventory.manifests}
    assert "package.json" in manifest_paths
    assert "packages/api/package.json" in manifest_paths
    assert "packages/web/package.json" in manifest_paths


def test_survey_handles_non_git_directory(tmp_path: Path):
    """When the target is not a git working tree, Phase 1 falls back to
    `walk_repo()` and records `is_git_repo=False`."""
    (tmp_path / "README.md").write_text("# bare\n", encoding="utf-8")
    state = make_run_state(tmp_path, Task.FULL_PASS)
    survey.run(state)
    assert state.inventory is not None
    assert state.inventory.is_git_repo is False
    paths = [df.path for df in state.inventory.agent_files]
    assert "README.md" in paths
