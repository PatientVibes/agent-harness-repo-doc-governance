"""Phase + Task enums and the task-to-phases routing table.

Phases 1-9 mirror the workflow in `prompts/skill_body.md` (vendored from
the repo-documentation-governance skill). Each task type selects a subset
of phases per the SKILL.md triage table.
"""

from __future__ import annotations

from enum import Enum, IntEnum
from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from repo_doc_governance.state import RunState


class Phase(IntEnum):
    """The nine phases of the repo-documentation-governance workflow."""

    SURVEY = 1
    CODE_FIRST = 2
    DRIFT_AUDIT = 3
    README = 4
    AGENT_INSTRUCTIONS = 5
    HANDOFF = 6
    STALE_ARTIFACTS = 7
    VERIFICATION = 8
    PR_HANDOFF = 9


class Task(str, Enum):
    """Task types from the SKILL.md triage table.

    Each value maps to a subset of phases via `TASK_TO_PHASES`. Phase 9
    (PR-format handoff) runs on every non-empty task.
    """

    README_ONLY = "readme-only"
    TODO_CLEANUP = "todo-cleanup"
    AGENT_CONSOLIDATION = "agent-consolidation"
    DRIFT_SWEEP = "drift-sweep"
    FROM_SCRATCH = "from-scratch"
    FULL_PASS = "full-pass"


# Task → phases mapping. Source of truth:
# `src/repo_doc_governance/prompts/skill_body.md` (vendored), "Triage" table.
TASK_TO_PHASES: dict[Task, list[Phase]] = {
    Task.README_ONLY: [Phase.CODE_FIRST, Phase.README, Phase.PR_HANDOFF],
    Task.TODO_CLEANUP: [Phase.SURVEY, Phase.HANDOFF, Phase.PR_HANDOFF],
    Task.AGENT_CONSOLIDATION: [Phase.SURVEY, Phase.AGENT_INSTRUCTIONS, Phase.PR_HANDOFF],
    Task.DRIFT_SWEEP: [
        Phase.SURVEY,
        Phase.DRIFT_AUDIT,
        Phase.STALE_ARTIFACTS,
        Phase.VERIFICATION,
        Phase.PR_HANDOFF,
    ],
    Task.FROM_SCRATCH: [
        Phase.SURVEY,
        Phase.CODE_FIRST,
        Phase.README,
        Phase.AGENT_INSTRUCTIONS,
        Phase.HANDOFF,
        Phase.PR_HANDOFF,
    ],
    Task.FULL_PASS: [
        Phase.SURVEY,
        Phase.CODE_FIRST,
        Phase.DRIFT_AUDIT,
        Phase.README,
        Phase.AGENT_INSTRUCTIONS,
        Phase.HANDOFF,
        Phase.STALE_ARTIFACTS,
        Phase.VERIFICATION,
        Phase.PR_HANDOFF,
    ],
}


PhaseFn = Callable[["RunState"], "RunState"]


def phases_for_task(task: Task) -> list[Phase]:
    """Return the ordered phase list for a given task type."""
    return list(TASK_TO_PHASES[task])


# --- Phase implementations.
#
# PR #3 lands the deterministic phases (1, 2, 3, 7, 8 Tier-1). The remaining
# phases stay as `NotImplementedError` stubs until their PR lands.

def _phase_not_implemented(phase: Phase) -> PhaseFn:
    """Return a phase function that raises NotImplementedError with a clear message."""

    def _run(state: "RunState") -> "RunState":
        raise NotImplementedError(
            f"{phase.name} (Phase {phase.value}) lands in a later PR. "
            "See the design spec build sequence at "
            "D:/ai-agents/docs/superpowers/specs/2026-05-19-agent-harness-repo-doc-governance-design.md."
        )

    return _run


def _build_dispatch() -> dict[Phase, PhaseFn]:
    # Imported lazily to keep `phases.py` free of state.py / models.py
    # imports at top level (avoids the circular import that would
    # otherwise form once state.py imports from this module).
    from repo_doc_governance.phase_impls import (
        agent_instructions,
        code_first,
        drift_audit,
        handoff,
        readme,
        stale_artifacts,
        survey,
        verification,
    )

    dispatch: dict[Phase, PhaseFn] = {p: _phase_not_implemented(p) for p in Phase}
    dispatch[Phase.SURVEY] = survey.run
    dispatch[Phase.CODE_FIRST] = code_first.run
    dispatch[Phase.DRIFT_AUDIT] = drift_audit.run
    dispatch[Phase.README] = readme.run
    dispatch[Phase.AGENT_INSTRUCTIONS] = agent_instructions.run
    dispatch[Phase.HANDOFF] = handoff.run
    dispatch[Phase.STALE_ARTIFACTS] = stale_artifacts.run
    dispatch[Phase.VERIFICATION] = verification.run
    return dispatch


PHASE_DISPATCH: dict[Phase, PhaseFn] = _build_dispatch()
