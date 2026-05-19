"""Sequential phase runner.

Iterates `state.phases_to_run` in order and invokes each phase's function
via `PHASE_DISPATCH`. Per-phase failures are caught, recorded into
`state.phases_failed`, and the run continues to the next phase (the spec
calls this the "defensive" behavior — one phase failing doesn't abort
the whole governance pass; the eventual PR body notes which phases were
skipped or failed).

Real LangGraph orchestration is intentionally NOT used here. Per the
design spec, the workflow shape is a sequential pipeline with
conditional phase-skip (a list filter from `task`), not real graph
routing — matches the `agent-harness-card-extractor` precedent.
LangGraph's `create_react_agent` is reserved for the in-phase LLM
loops that land in PR #4.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from repo_doc_governance.phases import (
    PHASE_DISPATCH,
    Phase,
    Task,
    phases_for_task,
)
from repo_doc_governance.state import PhaseFailure, RunState


def make_run_state(target_repo: Path | str, task: Task | str) -> RunState:
    """Build a fresh RunState for a target repo and task type.

    Resolves `task` from its string value if a Task enum isn't passed.
    Resolves `target_repo` to an absolute Path.
    """
    if isinstance(task, str):
        task = Task(task)
    target_repo = Path(target_repo).resolve()
    return RunState(
        target_repo=target_repo,
        task=task,
        phases_to_run=phases_for_task(task),
    )


def run(state: RunState) -> RunState:
    """Execute the configured phases in order.

    Mutates and returns `state`. Per-phase failures are recorded as
    `PhaseFailure` entries on `state.phases_failed`; execution continues
    to the next phase rather than aborting.
    """
    state.started_at = datetime.now(timezone.utc)

    for phase in state.phases_to_run:
        phase_fn = PHASE_DISPATCH[phase]
        try:
            state = phase_fn(state)
            state.phases_completed.append(phase)
        except NotImplementedError as exc:
            # PR #2 expected behavior — phase stubs raise NotImplementedError.
            # Recorded as failure so the orchestrator's error-handling path is
            # exercised by tests. PRs #3-#5 replace stubs with real impls.
            state.phases_failed.append(
                PhaseFailure(
                    phase=phase,
                    error_type="NotImplementedError",
                    message=str(exc),
                )
            )
        except Exception as exc:  # noqa: BLE001 — defensive per spec
            state.phases_failed.append(
                PhaseFailure(
                    phase=phase,
                    error_type=type(exc).__name__,
                    message=str(exc),
                )
            )

    state.completed_at = datetime.now(timezone.utc)
    return state


def summary(state: RunState) -> dict[str, Any]:
    """Return a small dict suitable for logging or `--json` CLI output."""
    return {
        "target_repo": str(state.target_repo),
        "task": state.task.value,
        "phases_to_run": [p.name for p in state.phases_to_run],
        "phases_completed": [p.name for p in state.phases_completed],
        "phases_failed": [
            {"phase": f.phase.name, "error_type": f.error_type, "message": f.message}
            for f in state.phases_failed
        ],
        "started_at": state.started_at.isoformat() if state.started_at else None,
        "completed_at": state.completed_at.isoformat() if state.completed_at else None,
    }
