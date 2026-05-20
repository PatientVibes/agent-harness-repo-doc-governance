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


def test_phase5_strips_llm_preamble(tmp_path: Path):
    """Surfaced in v0.1.3 dogfood (#27): Sonnet 4.6 emits chain-of-thought
    prose above the first H1 of the canonical agent file. The phase must
    defensively strip the preamble.
    """
    repo = build_agents_and_claude_repo(tmp_path)
    state = make_run_state(repo, Task.FULL_PASS)
    survey.run(state)

    leaked = (
        "Now I have a thorough understanding of the repo. The manifests "
        "declare no runnable commands directly...\n\n"
        "# Agent instructions\n\nConsolidated body.\n"
    )
    llm_runtime.set_runner(StubLLMRunner(text=leaked))
    agent_instructions.run(state)

    canonical_body = state.agent_files_proposed.get("AGENTS.md", "")
    assert canonical_body.startswith("# Agent instructions"), (
        f"Phase 5 did not strip the preamble. Body starts with: "
        f"{canonical_body[:120]!r}"
    )
    assert "Now I have a thorough" not in canonical_body


def test_phase5_includes_current_agent_file_content(tmp_path: Path):
    """Load-bearing — the LLM must see the EXISTING agent file content so
    it can honor the preserve-existing-content rule. Without this, the LLM
    falls back to writing from the template skeleton (the "rewriting for
    tone only" anti-pattern Phase 4 had pre-v0.1.2).
    """
    repo = build_agents_and_claude_repo(tmp_path)
    state = make_run_state(repo, Task.FULL_PASS)
    survey.run(state)

    stub = StubLLMRunner(text="# Agent instructions\n\nConsolidated body.\n")
    llm_runtime.set_runner(stub)
    agent_instructions.run(state)

    user_prompt = stub.calls[0]["user_prompt"]
    assert "CURRENT AGENT-INSTRUCTION FILES" in user_prompt
    # The fixture's AGENTS.md body — must survive verbatim into the prompt.
    assert "Do not commit to main" in user_prompt
    # The fixture's CLAUDE.md body — must survive verbatim into the prompt.
    assert "Always run tests" in user_prompt
    # And the explicit "preserve all content unless flagged" instruction.
    assert "preserve" in user_prompt.lower()


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
