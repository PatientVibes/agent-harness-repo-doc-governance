"""RunState — the per-run Pydantic model that carries data across phases.

State is in-process; serialization for checkpoint-and-resume lands in PR #3
once `agent_tool_llm_utils.save_checkpoint` is wired up.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from repo_doc_governance.phases import Phase, Task


class PhaseFailure(BaseModel):
    """Recorded when a phase raises an exception during execution."""

    phase: Phase
    error_type: str
    message: str


class RunState(BaseModel):
    """Per-run state passed through the phase pipeline.

    Phase implementations mutate this object (or return a new copy) to
    accumulate inventory, findings, classifications, and the eventual PR
    body. Field shapes will tighten as phases land — they are intentionally
    loose (`dict`, `list[dict]`) in PR #2 so the skeleton can compile and be
    tested without pinning the exact internal schemas.
    """

    # --- Inputs (set at construction; immutable during run) ----------------

    target_repo: Path
    """Path to the repo being analyzed. Must be a git working tree."""

    task: Task
    """Which task type drove this run; determines `phases_to_run`."""

    phases_to_run: list[Phase]
    """Ordered phase list derived from `task` via `phases_for_task()`."""

    # --- Outputs (populated phase-by-phase) --------------------------------

    inventory: dict[str, Any] = Field(default_factory=dict)
    """Phase 1 output — tracked files, directories, package manifests, doc files."""

    code_first_map: dict[str, Any] = Field(default_factory=dict)
    """Phase 2 output — manifests/CI/entry-points → declared commands and paths."""

    drift_findings: list[dict[str, Any]] = Field(default_factory=list)
    """Phase 3 output — each finding has `path`, `kind`, `severity`, `classification`."""

    stale_artifact_candidates: list[dict[str, Any]] = Field(default_factory=list)
    """Phase 7 output — candidate files for deletion or archive."""

    verification_results: list[dict[str, Any]] = Field(default_factory=list)
    """Phase 8 output — read-only checks (Tier 1) + optional execution (Tier 2)."""

    readme_diff: str = ""
    """Phase 4 output — unified diff for README.md (empty if Phase 4 didn't run)."""

    agent_files_diff: str = ""
    """Phase 5 output — unified diff for the agent-instruction files."""

    handoff_diff: str = ""
    """Phase 6 output — unified diff for HANDOFF.md / TODO.md / ROADMAP.md."""

    pr_body_draft: str = ""
    """Phase 9 output — the final PR body markdown that gets sent to `gh pr create`."""

    # --- Execution metadata -----------------------------------------------

    phases_completed: list[Phase] = Field(default_factory=list)
    phases_failed: list[PhaseFailure] = Field(default_factory=list)
    started_at: datetime | None = None
    completed_at: datetime | None = None

    model_config = {
        "arbitrary_types_allowed": True,
    }
