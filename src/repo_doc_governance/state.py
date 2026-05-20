"""RunState — the per-run Pydantic model that carries data across phases.

State is in-process; serialization for checkpoint-and-resume lands later
via `agent_tool_llm_utils.save_checkpoint`.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

from repo_doc_governance.models import (
    CodeFirstMap,
    DriftFinding,
    Inventory,
    StaleCandidate,
    VerificationResult,
)
from repo_doc_governance.phases import Phase, Task


class PhaseFailure(BaseModel):
    """Recorded when a phase raises an exception during execution."""

    phase: Phase
    error_type: str
    message: str


class RunState(BaseModel):
    """Per-run state passed through the phase pipeline.

    Phase implementations mutate this object in place to accumulate
    inventory, findings, classifications, and the eventual PR body.
    """

    # --- Inputs (set at construction; immutable during run) ----------------

    target_repo: Path
    """Path to the repo being analyzed. Must be a git working tree for
    Phase 1's `git ls-files` step to populate `tracked_files`."""

    task: Task
    """Which task type drove this run; determines `phases_to_run`."""

    phases_to_run: list[Phase]
    """Ordered phase list derived from `task` via `phases_for_task()`."""

    # --- Outputs (populated phase-by-phase) --------------------------------

    inventory: Inventory | None = None
    """Phase 1 output."""

    code_first_map: CodeFirstMap | None = None
    """Phase 2 output."""

    drift_findings: list[DriftFinding] = Field(default_factory=list)
    """Phase 3 output."""

    stale_artifact_candidates: list[StaleCandidate] = Field(default_factory=list)
    """Phase 7 output."""

    verification_results: list[VerificationResult] = Field(default_factory=list)
    """Phase 8 Tier-1 output. Tier-2 (command execution) lands in PR #5."""

    readme_diff: str = ""
    """Phase 4 output — unified diff for README.md."""

    agent_files_diff: str = ""
    """Phase 5 output — unified diff for the agent-instruction files."""

    handoff_diff: str = ""
    """Phase 6 output — unified diff for HANDOFF.md / TODO.md / ROADMAP.md."""

    pr_body_draft: str = ""
    """Phase 9 output — the final PR body markdown that gets sent to `gh pr create`."""

    canonical_agent_file: str | None = None
    """Phase 5 decision — which agent-instruction file is canonical
    (default `AGENTS.md`; `CLAUDE.md` for Claude-first repos)."""

    # --- Execution metadata -----------------------------------------------

    phases_completed: list[Phase] = Field(default_factory=list)
    phases_failed: list[PhaseFailure] = Field(default_factory=list)
    started_at: datetime | None = None
    completed_at: datetime | None = None

    model_config = {
        "arbitrary_types_allowed": True,
    }
