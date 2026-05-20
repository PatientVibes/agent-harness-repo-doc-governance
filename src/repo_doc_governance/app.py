"""FastAPI HTTP shell for the harness.

Two POST routes — `/run` and `/audit` — mirror the CLI subcommands. The
intent is so a webhook (CI on PR open, scheduled cron job, etc.) can
trigger a documentation governance pass without invoking the CLI directly.

Out of scope here: authentication / authorization. Production deployments
must front this with whatever access control they need; the harness
deliberately doesn't bake in an auth model since the right answer is
platform-specific (Cloudflare Access, GitHub Actions OIDC, mTLS, etc.).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field

from repo_doc_governance import __version__
from repo_doc_governance.cli import _AUDIT_PHASES, _audit_report
from repo_doc_governance.orchestrator import make_run_state, run
from repo_doc_governance.phases import Task


class RunRequest(BaseModel):
    repo: str = Field(description="Absolute path to the target repo on the harness host.")
    task: str = Field(default=Task.FULL_PASS.value)
    base_branch: str = Field(default="main")
    execute: bool = Field(default=False, description="Actually create the PR (default: dry-run).")
    execute_tier2: bool = Field(default=False)


class AuditRequest(BaseModel):
    repo: str


app = FastAPI(
    title="repo-doc-governance",
    version=__version__,
    description=(
        "HTTP shell for the agent-harness-repo-doc-governance harness. "
        "POST /run to run a governance sweep; POST /audit to get a "
        "read-only drift report."
    ),
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@app.post("/run")
def post_run(req: RunRequest) -> dict[str, Any]:
    state = make_run_state(Path(req.repo), req.task)
    state.base_branch = req.base_branch
    state.execute_phase9 = req.execute
    state.execute_tier2 = req.execute_tier2
    result = run(state)
    return {
        "schema_version": 1,
        "pr_url": result.pr_url,
        "pr_branch_name": result.pr_branch_name,
        "pr_body_draft": result.pr_body_draft,
        "canonical_agent_file": result.canonical_agent_file,
        "phases_completed": [p.name for p in result.phases_completed],
        "phases_failed": [
            {"phase": f.phase.name, "error_type": f.error_type, "message": f.message}
            for f in result.phases_failed
        ],
    }


@app.post("/audit")
def post_audit(req: AuditRequest) -> dict[str, Any]:
    state = make_run_state(Path(req.repo), Task.FULL_PASS)
    state.phases_to_run = list(_AUDIT_PHASES)
    state.execute_phase9 = False
    result = run(state)
    return _audit_report(result)
