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

    readme_proposed: str = ""
    """Phase 4 output — the full proposed new README body. Empty when
    Phase 4 didn't run or produced nothing."""

    readme_diff: str = ""
    """Phase 4 derived — unified diff between disk and `readme_proposed`,
    for display in the PR body."""

    agent_files_proposed: dict[str, str] = Field(default_factory=dict)
    """Phase 5 output — `{path: full proposed body}` for the canonical
    agent file + each wrapper file."""

    agent_files_diff: str = ""
    """Phase 5 derived — concatenated per-file unified diffs separated by
    `--- file: <path> ---`, for display in the PR body."""

    handoff_proposed: str = ""
    """Phase 6 output — the full proposed new HANDOFF body."""

    handoff_path: str | None = None
    """Phase 6 output — the path the proposed body targets."""

    handoff_diff: str = ""
    """Phase 6 derived — unified diff for display in the PR body."""

    pr_body_draft: str = ""
    """Phase 9 output — the final PR body markdown that gets sent to `gh pr create`."""

    canonical_agent_file: str | None = None
    """Phase 5 decision — which agent-instruction file is canonical
    (default `AGENTS.md`; `CLAUDE.md` for Claude-first repos)."""

    # --- Phase 9 configuration + outputs ----------------------------------

    base_branch: str = "main"
    """The branch the PR will target. Default `main`. Override per-repo
    via the CLI / HTTP API."""

    branch_prefix: str = "doc-governance"
    """Prefix for the feature branch Phase 9 creates. The resulting branch
    name is `<branch_prefix>/<YYYYMMDD>-<task>`."""

    execute_phase9: bool = False
    """When False (default), Phase 9 is *dry-run* — it composes the PR
    body but does not create a branch, write files, push, or call `gh`.
    When True, Phase 9 executes the plan, subject to the safety gates."""

    execute_tier2: bool = False
    """When True, Phase 8 also executes commands that pass the refuse-list
    check. When False (default), Tier-1 read-only checks are the only
    verification performed. Set explicitly per-invocation; never auto-on."""

    pr_url: str | None = None
    """Set by Phase 9 after `gh pr create` returns. Surfaced in `summary()`
    for `--json` output."""

    pr_branch_name: str | None = None
    """Feature branch Phase 9 used. Recorded for trace + post-mortem."""

    # --- Execution metadata -----------------------------------------------

    phases_completed: list[Phase] = Field(default_factory=list)
    phases_failed: list[PhaseFailure] = Field(default_factory=list)
    started_at: datetime | None = None
    completed_at: datetime | None = None

    model_config = {
        "arbitrary_types_allowed": True,
    }
