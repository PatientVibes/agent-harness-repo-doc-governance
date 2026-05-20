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


def test_phase6_filters_aspirational_docs_from_prompt(tmp_path: Path):
    """Surfaced in v0.1.3 dogfood (#28): card-extractor's huge plan
    docs under `docs/superpowers/plans/` were inlined into the Phase 6
    prompt, producing 728K input tokens (cost: $2.18 for one phase
    call with Sonnet 4.6). Plan/spec docs describe future / proposed
    state — the inverse of what HANDOFF describes. They must be
    FILTERED OUT of the Phase 6 input.
    """
    import json
    import subprocess

    repo = tmp_path / "asp"
    repo.mkdir()
    (repo / "README.md").write_text("# asp-fixture\n", encoding="utf-8")
    (repo / "package.json").write_text(
        json.dumps({"name": "asp", "version": "0.0.1", "scripts": {"test": "echo ok"}}),
        encoding="utf-8",
    )
    plan_dir = repo / "docs" / "superpowers" / "plans"
    plan_dir.mkdir(parents=True)
    (plan_dir / "2026-05-20-frontend-plan.md").write_text(
        "# Frontend plan\n\nPLAN_BODY_THAT_MUST_NOT_LEAK_INTO_PHASE_6 — "
        "this is aspirational plan content describing future state.\n",
        encoding="utf-8",
    )
    (repo / "docs").mkdir(parents=True, exist_ok=True)
    (repo / "docs" / "HANDOFF.md").write_text(
        "# Handoff\n\n## Next tasks\n\n"
        "- [ ] HANDOFF_BODY_THAT_MUST_APPEAR_IN_PROMPT — real current state.\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=str(repo), check=True)
    subprocess.run(["git", "add", "."], cwd=str(repo), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "i"], cwd=str(repo), check=True)

    state = make_run_state(repo, Task.FULL_PASS)
    survey.run(state)
    drift_audit.run(state)

    stub = StubLLMRunner(text="# Handoff\n\nclean.\n")
    llm_runtime.set_runner(stub)
    handoff.run(state)

    user_prompt = stub.calls[0]["user_prompt"]
    # Real handoff body must be inlined.
    assert "HANDOFF_BODY_THAT_MUST_APPEAR_IN_PROMPT" in user_prompt
    # Plan body must NOT be inlined — that's the cost regression we're
    # gating against.
    assert "PLAN_BODY_THAT_MUST_NOT_LEAK_INTO_PHASE_6" not in user_prompt
    # And the plan-doc path should not appear as a `### docs/superpowers/plans/...`
    # header in the CURRENT HANDOFF section.
    assert "docs/superpowers/plans/2026-05-20-frontend-plan.md" not in user_prompt


def test_handoff_phase_empty_response_leaves_diff_empty(tmp_path: Path):
    repo = build_drifted_repo(tmp_path)
    state = make_run_state(repo, Task.FULL_PASS)
    survey.run(state)

    llm_runtime.set_runner(StubLLMRunner(text=""))
    handoff.run(state)
    assert state.handoff_diff == ""
