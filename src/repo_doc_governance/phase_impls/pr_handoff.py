"""Phase 9 — PR-format handoff.

Builds a `PRPlan` from `RunState`, stores the PR body in
`state.pr_body_draft` (always — that's the audit-mode output), and, when
`state.execute_phase9` is True, executes the plan:
  1. Create a feature branch off `state.base_branch`.
  2. Apply file writes / deletes / moves with safety guards.
  3. Commit on the feature branch (never on base).
  4. Push the branch.
  5. Call the configured `PRCreator` (default: `GhPRCreator`).

Safety invariants enforced here (`safety.py`):
  - never_commit_to_main / never_commit_to_base    `BranchPolicyError`
  - never_edit_outside_repo                        `PathOutsideRepoError`
  - never_delete_untracked                         `UntrackedFileError`
  - never_self_merge                               Phase 9 NEVER calls
    `gh pr merge` — only `gh pr create`. The `test_never_self_merge`
    integration test verifies this by patching the `PRCreator` and
    asserting `merge` is never invoked.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from repo_doc_governance import pr_builder, safety
from repo_doc_governance.phase_impls import _utils
from repo_doc_governance.pr_creator import GhPRCreator, PRCreator
from repo_doc_governance.state import RunState


_PR_CREATOR: PRCreator | None = None


def get_pr_creator() -> PRCreator:
    global _PR_CREATOR
    if _PR_CREATOR is None:
        _PR_CREATOR = GhPRCreator()
    return _PR_CREATOR


def set_pr_creator(creator: PRCreator | None) -> None:
    global _PR_CREATOR
    _PR_CREATOR = creator


def reset_pr_creator() -> None:
    global _PR_CREATOR
    _PR_CREATOR = None


def run(state: RunState) -> RunState:
    plan = pr_builder.build_pr_plan(state)
    state.pr_body_draft = plan.pr_body
    state.pr_branch_name = plan.branch_name

    if not state.execute_phase9:
        # Dry-run / audit-mode — body is built; nothing on disk changes.
        return state

    _execute_plan(state, plan)
    return state


def _execute_plan(state: RunState, plan: pr_builder.PRPlan) -> None:
    repo = state.target_repo

    # 1) Safety gate: refuse if base branch is somehow set to a value that
    #    the feature-branch creation below would collide with.
    if plan.branch_name == plan.base_branch:
        raise safety.BranchPolicyError(
            f"Feature branch name collides with base branch '{plan.base_branch}'."
        )

    # 2) Create feature branch off the current HEAD.
    _git(repo, "checkout", "-b", plan.branch_name)

    # 3) Apply file writes (safety: path-inside-repo).
    for rel_path, body in plan.files_to_write.items():
        target = safety.assert_path_inside_repo(repo, rel_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
        _git(repo, "add", rel_path)

    # 4) Apply moves (safety: both src and dst inside-repo; src tracked).
    for src, dst in plan.files_to_move:
        safety.assert_path_inside_repo(repo, src)
        safety.assert_path_inside_repo(repo, dst)
        safety.assert_tracked_for_delete(repo, src)
        (repo / dst).parent.mkdir(parents=True, exist_ok=True)
        _git(repo, "mv", src, dst)

    # 5) Apply deletes (safety: tracked-by-git, path-inside-repo).
    for rel_path in plan.files_to_delete:
        safety.assert_path_inside_repo(repo, rel_path)
        safety.assert_tracked_for_delete(repo, rel_path)
        _git(repo, "rm", rel_path)

    # 6) Final pre-commit safety: branch is not base / not protected.
    safety.assert_committing_to_feature_branch(repo, base_branch=plan.base_branch)

    # 7) No-change short-circuit. If the LLM phases produced output that
    #    matches the on-disk content (e.g. the README had no drift and
    #    the prompt's "preserve" rule landed an identical body), there's
    #    nothing to commit and `git commit` would exit non-zero. That is
    #    success, not failure — record it and return without opening a PR.
    if _index_is_clean(repo):
        state.pr_url = None
        state.pr_branch_name = plan.branch_name  # branch was created; left in place for inspection
        return

    # 8) Commit. Use a config-scoped author so the commit succeeds even if
    #    the repo has no global git identity (CI environments).
    _git(
        repo,
        "-c", "user.email=harness@repo-doc-governance.invalid",
        "-c", "user.name=repo-doc-gov harness",
        "commit",
        "-m", plan.pr_title,
    )

    # 9) Push (best-effort — caller decides if this is allowed).
    _git(repo, "push", "-u", "origin", plan.branch_name)

    # 10) Open PR. NEVER calls `gh pr merge` — only `gh pr create`.
    pr_url = get_pr_creator().create(
        repo=repo,
        branch=plan.branch_name,
        base=plan.base_branch,
        title=plan.pr_title,
        body=plan.pr_body,
    )
    state.pr_url = pr_url


def _index_is_clean(repo: Path) -> bool:
    """True iff `git diff --cached --quiet` reports no staged changes.

    Lets the no-drift case return success without creating a PR.
    """
    result = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=str(repo),
        capture_output=True,
        text=True,
    )
    # `git diff --quiet` exits 0 iff there are NO differences.
    return result.returncode == 0


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=str(repo),
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
