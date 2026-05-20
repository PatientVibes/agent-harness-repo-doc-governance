"""Safety primitives enforced *in code* (not just prompts).

Each load-bearing safety invariant from the spec has a guard function
here. Integration tests against real temp git repos exercise each one.

The list (from the design spec § Verification):
  - `assert_committing_to_feature_branch` → `BranchPolicyError`
  - `assert_path_inside_repo`             → `PathOutsideRepoError`
  - `assert_command_safe`                 → `RefusedCommandError`
  - `assert_tracked_for_delete`           → `UntrackedFileError`
"""

from __future__ import annotations

from pathlib import Path

from repo_doc_governance.phase_impls import _utils


class BranchPolicyError(Exception):
    """Raised when the harness would commit/push to a protected branch."""


class PathOutsideRepoError(Exception):
    """Raised when a file operation would touch a path outside the target repo."""


class RefusedCommandError(Exception):
    """Raised when a Tier-2 command matches the refuse-list."""


class UntrackedFileError(Exception):
    """Raised when the harness would delete an untracked file (always
    `Needs verification` instead per `prompts/decisions.md`)."""


_PROTECTED_BRANCHES = frozenset({"main", "master", "trunk", "develop"})


def assert_committing_to_feature_branch(repo: Path, *, base_branch: str) -> None:
    """Verify HEAD is on a branch that is neither protected nor the base
    branch. Called immediately before `git commit` to catch the
    "we forgot to switch off main" failure mode."""
    branch = _utils.git_current_branch(repo)
    if branch is None:
        raise BranchPolicyError(
            "Refusing to commit on a detached HEAD or repo with no branch."
        )
    if branch in _PROTECTED_BRANCHES:
        raise BranchPolicyError(
            f"Refusing to commit to protected branch '{branch}'. "
            "The harness must create a feature branch first."
        )
    if branch == base_branch:
        raise BranchPolicyError(
            f"Refusing to commit to base branch '{base_branch}'. "
            "The harness must create a feature branch first."
        )


def assert_path_inside_repo(repo: Path, candidate: str | Path) -> Path:
    """Resolve `candidate` and assert it lives inside `repo.resolve()`.
    Returns the absolute resolved path on success.
    """
    repo_root = repo.resolve()
    target = (repo_root / candidate).resolve() if not Path(candidate).is_absolute() \
        else Path(candidate).resolve()
    try:
        target.relative_to(repo_root)
    except ValueError as exc:
        raise PathOutsideRepoError(
            f"Refusing to touch path outside target repo: {candidate}"
        ) from exc
    return target


def assert_tracked_for_delete(repo: Path, rel_path: str) -> None:
    """Refuse to delete an untracked file. Phase 7 already classifies
    untracked stale candidates as `Needs verification`; this is the
    last-mile enforcement at the actual delete step."""
    if not _utils.is_git_repo(repo):
        raise UntrackedFileError(
            f"Cannot verify tracking status — target is not a git repo: {repo}"
        )
    if not _utils.git_path_is_tracked(repo, rel_path):
        raise UntrackedFileError(
            f"Refusing to delete untracked file: {rel_path}. "
            "Untracked files are always classified `Needs verification` "
            "for the human reviewer."
        )


# --- Refuse-list (Phase 8 Tier-2) ------------------------------------------


_REFUSE_PATTERNS: tuple[tuple[str, str], ...] = (
    # (substring or regex-anchor, reason)
    ("rm -rf", "destructive filesystem operation (rm -rf)"),
    ("find . -delete", "destructive filesystem operation (find -delete)"),
    ("find -delete", "destructive filesystem operation (find -delete)"),
    ("curl ", "uninspected network call"),
    ("wget ", "uninspected network call"),
    ("| bash", "curl|bash style execution"),
    ("|bash", "curl|bash style execution"),
    ("| sh", "curl|sh style execution"),
    ("|sh", "curl|sh style execution"),
    ("npm publish", "package publishing"),
    ("cargo publish", "package publishing"),
    ("mvn deploy", "package publishing"),
    ("twine upload", "package publishing"),
    ("terraform apply", "deployment command"),
    ("kubectl apply", "deployment command"),
    ("helm install", "deployment command"),
    ("helm upgrade", "deployment command"),
    ("aws s3 sync", "deployment / production data op"),
    ("systemctl ", "host-level service modification"),
    ("service ", "host-level service modification"),
    ("psql -c", "production database operation"),
    ("mysql -u", "production database operation"),
    ("docker run --privileged", "privileged container operation"),
    ("--privileged", "privileged container operation"),
    ("sudo ", "privileged escalation"),
)


def refuse_list_match(text: str) -> tuple[bool, str | None]:
    """If `text` contains a refuse-list pattern, return (True, reason).
    Otherwise (False, None). Used by both the command-string check and
    the manifest-script-body check.
    """
    lowered = text.lower()
    for pattern, reason in _REFUSE_PATTERNS:
        if pattern in lowered:
            return True, reason
    return False, None


def assert_command_safe(cmd: str, script_body: str = "") -> None:
    """Raise `RefusedCommandError` if `cmd` or the script body it would
    invoke matches the refuse-list. Both are checked because a short
    `npm test` command can wrap an unreviewed `curl | bash` line in
    package.json.
    """
    refused, reason = refuse_list_match(cmd)
    if refused:
        raise RefusedCommandError(f"Command refused: {cmd} ({reason})")
    if script_body:
        refused, reason = refuse_list_match(script_body)
        if refused:
            raise RefusedCommandError(
                f"Command refused — manifest script body matched refuse-list: {cmd} ({reason})"
            )
