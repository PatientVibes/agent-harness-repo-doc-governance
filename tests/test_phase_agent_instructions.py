"""Tests for Phase 5 — Agent instruction consolidation."""

from __future__ import annotations

from pathlib import Path

import pytest

from repo_doc_governance import llm_runtime
from repo_doc_governance.llm_runtime import StubLLMRunner
from repo_doc_governance.orchestrator import make_run_state
from repo_doc_governance.phase_impls import agent_instructions, survey
from repo_doc_governance.phases import Task

from conftest import build_agents_and_claude_repo, build_clean_repo


@pytest.fixture(autouse=True)
def _reset_runner():
    llm_runtime.set_runner(None)
    yield
    llm_runtime.set_runner(None)


def test_default_canonical_is_agents_md(tmp_path: Path):
    repo = build_agents_and_claude_repo(tmp_path)
    state = make_run_state(repo, Task.FULL_PASS)
    survey.run(state)
    llm_runtime.set_runner(StubLLMRunner(text="# Agent Instructions\n\nCanonical body.\n"))
    agent_instructions.run(state)

    assert state.canonical_agent_file == "AGENTS.md"


def test_claude_first_repo_picks_claude_md(tmp_path: Path):
    repo = build_clean_repo(tmp_path)
    # Make it Claude-first.
    (repo / ".claude").mkdir()
    (repo / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
    (repo / "CLAUDE.md").write_text("# Claude\n", encoding="utf-8")
    import subprocess
    subprocess.run(["git", "add", "."], cwd=str(repo), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "claude"], cwd=str(repo), check=True)

    state = make_run_state(repo, Task.FULL_PASS)
    survey.run(state)
    llm_runtime.set_runner(StubLLMRunner(text="# Claude Instructions\n\nBody.\n"))
    agent_instructions.run(state)

    assert state.canonical_agent_file == "CLAUDE.md"


def test_phase5_generates_diffs_for_canonical_and_wrappers(tmp_path: Path):
    repo = build_agents_and_claude_repo(tmp_path)
    state = make_run_state(repo, Task.FULL_PASS)
    survey.run(state)

    llm_runtime.set_runner(
        StubLLMRunner(text="# Agent Instructions\n\nConsolidated body.\n")
    )
    agent_instructions.run(state)

    assert "--- file: AGENTS.md ---" in state.agent_files_diff
    assert "--- file: CLAUDE.md ---" in state.agent_files_diff
    # The wrapper should point at the canonical file.
    assert "AGENTS.md" in state.agent_files_diff


def test_phase5_wrapper_template_is_deterministic(tmp_path: Path):
    """Two runs with the same canonical decision must produce the same
    wrapper body — the wrapper is deterministic per the spec.
    """
    repo = build_agents_and_claude_repo(tmp_path)
    state1 = make_run_state(repo, Task.FULL_PASS)
    state2 = make_run_state(repo, Task.FULL_PASS)
    survey.run(state1)
    survey.run(state2)

    llm_runtime.set_runner(StubLLMRunner(text="# Agent Instructions\n\nA\n"))
    agent_instructions.run(state1)
    llm_runtime.set_runner(StubLLMRunner(text="# Agent Instructions\n\nA\n"))
    agent_instructions.run(state2)

    # The CLAUDE.md wrapper portion should be byte-identical.
    def _wrapper_part(diff: str) -> str:
        marker = "--- file: CLAUDE.md ---"
        idx = diff.find(marker)
        return diff[idx:] if idx != -1 else ""

    assert _wrapper_part(state1.agent_files_diff) == _wrapper_part(
        state2.agent_files_diff
    )


def test_phase5_no_agent_files_creates_canonical_from_scratch(tmp_path: Path):
    repo = build_clean_repo(tmp_path)
    # Remove README so agent_files is effectively empty for the agent
    # instructions check (README is in agent_files but not the AGENT_INSTRUCTIONS kind).
    state = make_run_state(repo, Task.FULL_PASS)
    survey.run(state)

    llm_runtime.set_runner(
        StubLLMRunner(text="# Agent Instructions\n\nFresh canonical.\n")
    )
    agent_instructions.run(state)

    assert state.canonical_agent_file == "AGENTS.md"
    assert "--- file: AGENTS.md ---" in state.agent_files_diff
    assert "Fresh canonical." in state.agent_files_diff
