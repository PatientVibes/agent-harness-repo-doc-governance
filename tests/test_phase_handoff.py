"""Tests for Phase 6 — Handoff / TODO / ROADMAP cleanup."""

from __future__ import annotations

from pathlib import Path

import pytest

from repo_doc_governance import llm_runtime
from repo_doc_governance.llm_runtime import StubLLMRunner
from repo_doc_governance.orchestrator import make_run_state
from repo_doc_governance.phase_impls import drift_audit, handoff, survey
from repo_doc_governance.phases import Task

from conftest import build_clean_repo, build_drifted_repo


@pytest.fixture(autouse=True)
def _reset_runner():
    llm_runtime.set_runner(None)
    yield
    llm_runtime.set_runner(None)


def test_handoff_phase_uses_existing_handoff_file(tmp_path: Path):
    repo = build_drifted_repo(tmp_path)
    state = make_run_state(repo, Task.FULL_PASS)
    survey.run(state)
    drift_audit.run(state)

    stub = StubLLMRunner(text="# Handoff\n\nClean.\n")
    llm_runtime.set_runner(stub)
    handoff.run(state)

    assert "docs/HANDOFF.md" in stub.calls[0]["user_prompt"]
    assert state.handoff_diff != ""
    assert "a/docs/HANDOFF.md" in state.handoff_diff
    assert "b/docs/HANDOFF.md" in state.handoff_diff


def test_handoff_phase_falls_back_to_docs_path(tmp_path: Path):
    repo = build_clean_repo(tmp_path)
    state = make_run_state(repo, Task.FULL_PASS)
    survey.run(state)

    stub = StubLLMRunner(text="# Handoff\n\nNew.\n")
    llm_runtime.set_runner(stub)
    handoff.run(state)

    # No existing HANDOFF — phase should target docs/HANDOFF.md.
    assert "docs/HANDOFF.md" in stub.calls[0]["user_prompt"]


def test_handoff_phase_passes_drift_findings_for_handoff_files(tmp_path: Path):
    repo = build_drifted_repo(tmp_path)
    state = make_run_state(repo, Task.FULL_PASS)
    survey.run(state)
    drift_audit.run(state)

    stub = StubLLMRunner(text="# Handoff\n\nUpdated.\n")
    llm_runtime.set_runner(stub)
    handoff.run(state)

    assert "stale_todo" in stub.calls[0]["user_prompt"]


def test_phase6_strips_llm_preamble(tmp_path: Path):
    """Surfaced in v0.1.3 dogfood (#27): Sonnet 4.6 emits "Now I have a
    thorough understanding..." chain-of-thought prose above the first H1
    of the HANDOFF body. The phase must defensively strip it.
    """
    repo = build_drifted_repo(tmp_path)
    state = make_run_state(repo, Task.FULL_PASS)
    survey.run(state)
    drift_audit.run(state)

    leaked = (
        "Now I have a thorough understanding of the repository. "
        "Let me write the HANDOFF file.\n\n"
        "# Handoff\n\nUpdated body.\n"
    )
    llm_runtime.set_runner(StubLLMRunner(text=leaked))
    handoff.run(state)

    assert state.handoff_proposed.startswith("# Handoff"), (
        f"Phase 6 did not strip the preamble. Output starts with: "
        f"{state.handoff_proposed[:120]!r}"
    )
    assert "Now I have a thorough" not in state.handoff_proposed


def test_phase6_includes_current_handoff_content(tmp_path: Path):
    """Load-bearing — the LLM must see the EXISTING HANDOFF/TODO/ROADMAP
    file content so it can honor the "preserve every TODO" rule. Without
    this, the LLM falls back to writing from the template skeleton (the
    "rewriting for tone only" anti-pattern Phase 4 had pre-v0.1.2).
    """
    repo = build_drifted_repo(tmp_path)
    state = make_run_state(repo, Task.FULL_PASS)
    survey.run(state)
    drift_audit.run(state)

    stub = StubLLMRunner(text="# Handoff\n\nUpdated.\n")
    llm_runtime.set_runner(stub)
    handoff.run(state)

    user_prompt = stub.calls[0]["user_prompt"]
    assert "CURRENT HANDOFF" in user_prompt
    # The drifted fixture's docs/HANDOFF.md body must survive into the prompt.
    assert "clean up later" in user_prompt
    assert "rewrite to TypeScript" in user_prompt
    # And the explicit "every TODO ... explicit decision" instruction.
    assert "explicit decision" in user_prompt.lower() or "preserve" in user_prompt.lower()


def test_handoff_phase_empty_response_leaves_diff_empty(tmp_path: Path):
    repo = build_drifted_repo(tmp_path)
    state = make_run_state(repo, Task.FULL_PASS)
    survey.run(state)

    llm_runtime.set_runner(StubLLMRunner(text=""))
    handoff.run(state)
    assert state.handoff_diff == ""
