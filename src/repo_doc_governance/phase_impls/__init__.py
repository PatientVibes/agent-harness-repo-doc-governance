"""Per-phase implementations.

Imported by `phases.py` to populate `PHASE_DISPATCH`. Each module exposes a
single `run(state: RunState) -> RunState` function.

PR #3 lands the deterministic phases (1, 2, 3, 7, 8 Tier-1). LLM phases
(4, 5, 6), PR-creation (9), and Tier-2 verification land in later PRs.
"""

from repo_doc_governance.phase_impls import (
    agent_instructions,
    code_first,
    drift_audit,
    handoff,
    pr_handoff,
    readme,
    stale_artifacts,
    survey,
    verification,
)

__all__ = [
    "survey",
    "code_first",
    "drift_audit",
    "readme",
    "agent_instructions",
    "handoff",
    "stale_artifacts",
    "verification",
    "pr_handoff",
]
