"""Tests for Phase 2 — Code-first source-of-truth detection."""

from __future__ import annotations

from pathlib import Path

from repo_doc_governance.orchestrator import make_run_state
from repo_doc_governance.phase_impls import code_first, survey
from repo_doc_governance.phases import Task

from conftest import build_clean_repo, build_monorepo


def test_code_first_collects_npm_scripts(tmp_path: Path):
    repo = build_clean_repo(tmp_path)
    state = make_run_state(repo, Task.FULL_PASS)
    survey.run(state)
    code_first.run(state)

    assert state.code_first_map is not None
    cmds_by_manifest = state.code_first_map.declared_commands
    assert "package.json" in cmds_by_manifest
    assert "npm test" in cmds_by_manifest["package.json"]
    assert "npm run build" in cmds_by_manifest["package.json"]


def test_code_first_handles_readme_only_task_without_prior_survey(tmp_path: Path):
    """README_ONLY skips Phase 1 (`SURVEY`). Phase 2 must fall back to
    its own in-phase manifest scan rather than crashing on a None
    inventory."""
    repo = build_clean_repo(tmp_path)
    state = make_run_state(repo, Task.README_ONLY)
    # Intentionally do NOT run Phase 1.
    code_first.run(state)

    assert state.code_first_map is not None
    assert "package.json" in state.code_first_map.declared_commands


def test_code_first_monorepo_collects_per_package_commands(tmp_path: Path):
    repo = build_monorepo(tmp_path)
    state = make_run_state(repo, Task.FULL_PASS)
    survey.run(state)
    code_first.run(state)

    assert state.code_first_map is not None
    assert "packages/api/package.json" in state.code_first_map.declared_commands
    assert "packages/web/package.json" in state.code_first_map.declared_commands
    api_cmds = state.code_first_map.declared_commands["packages/api/package.json"]
    web_cmds = state.code_first_map.declared_commands["packages/web/package.json"]
    assert "npm test" in api_cmds
    assert "npm run build" in web_cmds


def test_code_first_records_entry_points(tmp_path: Path):
    repo = tmp_path / "entry-points"
    repo.mkdir()
    (repo / "main.py").write_text("print('hi')\n", encoding="utf-8")
    (repo / ".env.example").write_text("FOO=bar\n", encoding="utf-8")
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "0.0.1"\n', encoding="utf-8"
    )

    import subprocess
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=str(repo), check=True)
    subprocess.run(["git", "add", "."], cwd=str(repo), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "i"], cwd=str(repo), check=True)

    state = make_run_state(repo, Task.FULL_PASS)
    survey.run(state)
    code_first.run(state)

    assert state.code_first_map is not None
    assert "main.py" in state.code_first_map.entry_points
    assert ".env.example" in state.code_first_map.env_examples
