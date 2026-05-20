"""Tests for Phase 4 — README update."""

from __future__ import annotations

from pathlib import Path

import pytest

from repo_doc_governance import llm_runtime
from repo_doc_governance.llm_runtime import StubLLMRunner
from repo_doc_governance.orchestrator import make_run_state
from repo_doc_governance.phase_impls import code_first, readme, survey
from repo_doc_governance.phases import Task

from conftest import build_clean_repo, build_drifted_repo


@pytest.fixture(autouse=True)
def _reset_runner():
    """Each test starts with the runner reset; tearDown restores default."""
    llm_runtime.set_runner(None)
    yield
    llm_runtime.set_runner(None)


def _through_phase3(repo: Path):
    state = make_run_state(repo, Task.FULL_PASS)
    survey.run(state)
    code_first.run(state)
    return state


def test_readme_phase_invokes_runner_with_inventory(tmp_path: Path):
    repo = build_clean_repo(tmp_path)
    state = _through_phase3(repo)

    stub = StubLLMRunner(text="# clean-fixture\n\nUpdated body.\n")
    llm_runtime.set_runner(stub)

    readme.run(state)

    assert len(stub.calls) == 1
    call = stub.calls[0]
    assert "package.json" in call["user_prompt"]
    assert "npm test" in call["user_prompt"]
    assert call["repo_path"] == str(repo)


def test_readme_phase_writes_diff_into_state(tmp_path: Path):
    repo = build_clean_repo(tmp_path)
    state = _through_phase3(repo)

    proposed = "# clean-fixture\n\nA brand-new body.\n\n## Quick start\n\nnew steps.\n"
    llm_runtime.set_runner(StubLLMRunner(text=proposed))
    readme.run(state)

    assert state.readme_diff != ""
    assert "a/README.md" in state.readme_diff
    assert "b/README.md" in state.readme_diff
    assert "A brand-new body." in state.readme_diff


def test_readme_phase_empty_response_leaves_diff_empty(tmp_path: Path):
    repo = build_clean_repo(tmp_path)
    state = _through_phase3(repo)
    llm_runtime.set_runner(StubLLMRunner(text=""))
    readme.run(state)
    assert state.readme_diff == ""


def test_readme_phase_passes_drift_findings(tmp_path: Path):
    """Drifted-repo's README has a dead command finding. The phase must
    include that finding in the user prompt so the LLM knows to remove it."""
    repo = build_drifted_repo(tmp_path)
    state = make_run_state(repo, Task.FULL_PASS)
    survey.run(state)
    code_first.run(state)
    from repo_doc_governance.phase_impls import drift_audit
    drift_audit.run(state)

    stub = StubLLMRunner(text="# drifted\n\nClean body.\n")
    llm_runtime.set_runner(stub)
    readme.run(state)

    call = stub.calls[0]
    assert "dead_command" in call["user_prompt"]
    assert "npm run deploy" in call["user_prompt"]
