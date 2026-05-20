"""Tests for the PR #2 orchestrator skeleton.

Covers:
- Task → phases routing matches the SKILL.md triage table.
- Phase 9 (PR_HANDOFF) is the last phase of every task.
- Phase ordering inside each task is strictly ascending by phase number.
- RunState construction via `make_run_state`.
- Sequential `run()` exercises per-phase exception handling (every stub
  raises NotImplementedError, so every phase ends up in `phases_failed`
  in PR #2 — and this is the expected behavior until PR #3 implements
  the deterministic phases).
- `summary()` produces a serializable dict with the expected keys.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from repo_doc_governance.orchestrator import make_run_state, run, summary
from repo_doc_governance.phases import (
    PHASE_DISPATCH,
    TASK_TO_PHASES,
    Phase,
    Task,
    phases_for_task,
)
from repo_doc_governance.state import RunState


# ---- TASK_TO_PHASES table conformance --------------------------------------


def test_every_task_ends_with_pr_handoff():
    for task, phases in TASK_TO_PHASES.items():
        assert phases[-1] == Phase.PR_HANDOFF, (
            f"Task {task.value} must end with PR_HANDOFF; got {phases[-1].name}"
        )


def test_phases_are_strictly_ascending_within_each_task():
    for task, phases in TASK_TO_PHASES.items():
        values = [p.value for p in phases]
        assert values == sorted(values), (
            f"Task {task.value} phases must run in ascending order; got {values}"
        )
        assert len(set(values)) == len(values), (
            f"Task {task.value} has duplicate phases: {values}"
        )


def test_readme_only_runs_phases_2_4_9():
    assert phases_for_task(Task.README_ONLY) == [
        Phase.CODE_FIRST,
        Phase.README,
        Phase.PR_HANDOFF,
    ]


def test_full_pass_runs_all_nine_phases():
    assert phases_for_task(Task.FULL_PASS) == list(Phase)


def test_drift_sweep_excludes_llm_phases():
    """Drift sweep is deterministic — never touches Phases 4/5/6 (LLM phases)."""
    phases = phases_for_task(Task.DRIFT_SWEEP)
    llm_phases = {Phase.README, Phase.AGENT_INSTRUCTIONS, Phase.HANDOFF}
    assert llm_phases.isdisjoint(set(phases))


def test_phase_dispatch_covers_every_phase():
    assert set(PHASE_DISPATCH.keys()) == set(Phase)


# ---- RunState construction --------------------------------------------------


def test_make_run_state_resolves_task_string(tmp_path: Path):
    state = make_run_state(tmp_path, "readme-only")
    assert state.task == Task.README_ONLY
    assert state.phases_to_run == phases_for_task(Task.README_ONLY)


def test_make_run_state_accepts_task_enum(tmp_path: Path):
    state = make_run_state(tmp_path, Task.FULL_PASS)
    assert state.task == Task.FULL_PASS


def test_make_run_state_resolves_relative_path(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state = make_run_state(".", Task.FULL_PASS)
    assert state.target_repo.is_absolute()


def test_make_run_state_rejects_invalid_task(tmp_path: Path):
    with pytest.raises(ValueError):
        make_run_state(tmp_path, "not-a-real-task")


def test_run_state_default_collections_are_empty(tmp_path: Path):
    state = make_run_state(tmp_path, Task.FULL_PASS)
    # Typed phase outputs default to None until their phase runs;
    # findings/results lists default empty.
    assert state.inventory is None
    assert state.code_first_map is None
    assert state.drift_findings == []
    assert state.stale_artifact_candidates == []
    assert state.verification_results == []
    assert state.phases_completed == []
    assert state.phases_failed == []
    assert state.pr_body_draft == ""


# ---- run() exception-handling path -----------------------------------------


def test_run_after_pr3_completes_deterministic_phases(tmp_path: Path):
    """PR #3 lands the deterministic phases (1, 2, 3, 7, 8 Tier-1).
    For README_ONLY ([CODE_FIRST, README, PR_HANDOFF]), CODE_FIRST is now
    deterministic and should complete; README and PR_HANDOFF stay stubs
    and end up in `phases_failed`. The orchestrator must continue past
    failures.
    """
    state = make_run_state(tmp_path, Task.README_ONLY)
    result = run(state)

    assert result.phases_completed == [Phase.CODE_FIRST]
    failed_phases = [f.phase for f in result.phases_failed]
    assert failed_phases == [Phase.README, Phase.PR_HANDOFF]
    assert all(f.error_type == "NotImplementedError" for f in result.phases_failed)


def test_drift_sweep_after_pr3_all_deterministic_phases_complete(tmp_path: Path):
    """DRIFT_SWEEP runs SURVEY, DRIFT_AUDIT, STALE_ARTIFACTS, VERIFICATION,
    PR_HANDOFF. The first four are deterministic (PR #3); only PR_HANDOFF
    is still a stub."""
    # Make tmp_path look like an empty git repo so the deterministic
    # phases have something to run against.
    import subprocess
    subprocess.run(["git", "init", "-q"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "--allow-empty", "-m", "init", "-q"],
                   cwd=str(tmp_path), check=True)

    state = make_run_state(tmp_path, Task.DRIFT_SWEEP)
    result = run(state)

    assert Phase.SURVEY in result.phases_completed
    assert Phase.DRIFT_AUDIT in result.phases_completed
    assert Phase.STALE_ARTIFACTS in result.phases_completed
    assert Phase.VERIFICATION in result.phases_completed

    failed_phases = [f.phase for f in result.phases_failed]
    assert failed_phases == [Phase.PR_HANDOFF]


def test_run_records_timestamps(tmp_path: Path):
    state = make_run_state(tmp_path, Task.README_ONLY)
    assert state.started_at is None
    assert state.completed_at is None

    result = run(state)
    assert result.started_at is not None
    assert result.completed_at is not None
    assert result.completed_at >= result.started_at


def test_run_continues_past_first_failure(tmp_path: Path):
    """Specifically the defensive behavior — one phase failing must not
    short-circuit the remaining phases."""
    import subprocess
    subprocess.run(["git", "init", "-q"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "--allow-empty", "-m", "init", "-q"],
                   cwd=str(tmp_path), check=True)

    state = make_run_state(tmp_path, Task.FULL_PASS)
    result = run(state)

    # All 9 phases attempted. PR #3 = 5 deterministic complete, 4 stub fail.
    assert len(result.phases_failed) + len(result.phases_completed) == 9


# ---- summary() --------------------------------------------------------------


def test_summary_includes_expected_keys(tmp_path: Path):
    state = make_run_state(tmp_path, Task.README_ONLY)
    result = run(state)
    s = summary(result)

    expected_keys = {
        "target_repo",
        "task",
        "phases_to_run",
        "phases_completed",
        "phases_failed",
        "started_at",
        "completed_at",
    }
    assert expected_keys <= set(s.keys())
    assert s["task"] == "readme-only"
    assert s["phases_to_run"] == ["CODE_FIRST", "README", "PR_HANDOFF"]


def test_summary_failed_entries_have_error_type(tmp_path: Path):
    state = make_run_state(tmp_path, Task.README_ONLY)
    result = run(state)
    s = summary(result)

    assert all("error_type" in f for f in s["phases_failed"])
    assert all("message" in f for f in s["phases_failed"])


# ---- vendored prompts are present ------------------------------------------


def test_vendored_prompts_exist():
    """Verifies that PR #2 vendoring landed the 4 expected prompt files."""
    prompts_dir = (
        Path(__file__).parent.parent
        / "src"
        / "repo_doc_governance"
        / "prompts"
    )
    expected = {"skill_body.md", "phases.md", "decisions.md", "templates.md"}
    actual = {p.name for p in prompts_dir.glob("*.md")}
    assert expected <= actual, f"Missing vendored prompts: {expected - actual}"


def test_vendored_prompts_carry_do_not_edit_header():
    """Every vendored prompt must lead with the DO NOT EDIT header."""
    prompts_dir = (
        Path(__file__).parent.parent
        / "src"
        / "repo_doc_governance"
        / "prompts"
    )
    for prompt in prompts_dir.glob("*.md"):
        first_line = prompt.read_text(encoding="utf-8").splitlines()[0]
        assert "DO NOT EDIT" in first_line, (
            f"{prompt.name} missing DO NOT EDIT header: {first_line!r}"
        )
        assert "vendored from agent-skills" in first_line
