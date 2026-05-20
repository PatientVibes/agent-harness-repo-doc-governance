"""Abstracted PR-creator backends.

v1 ships only `GhPRCreator` (shells out to `gh pr create`). Adding
`GitLabPRCreator` / `BitbucketPRCreator` is a contributor-friendly
follow-up that doesn't touch Phase 9's orchestration code — only the
backend class.

`NullPRCreator` is the test double: it records the would-be call and
returns a fake URL. Tests use it to verify Phase 9 reaches the PR-create
step (or doesn't, when a safety gate fired earlier).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class PRCreator(Protocol):
    """Creates a pull request from `branch` against `base` with the given
    title and body. Returns the PR URL on success."""

    def create(
        self,
        *,
        repo: Path,
        branch: str,
        base: str,
        title: str,
        body: str,
    ) -> str: ...


class GhPRCreator:
    """Default — shells out to the `gh` CLI."""

    def create(
        self, *, repo: Path, branch: str, base: str, title: str, body: str
    ) -> str:
        result = subprocess.run(
            [
                "gh", "pr", "create",
                "--base", base,
                "--head", branch,
                "--title", title,
                "--body", body,
            ],
            cwd=str(repo),
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        # `gh pr create` prints the URL as its last line.
        return result.stdout.strip().splitlines()[-1]


class NullPRCreator:
    """Test double. Records every call; returns a stable fake URL."""

    def __init__(self, fake_url: str = "https://example.invalid/pr/1") -> None:
        self.fake_url = fake_url
        self.calls: list[dict] = []

    def create(
        self, *, repo: Path, branch: str, base: str, title: str, body: str
    ) -> str:
        self.calls.append(
            {
                "repo": str(repo),
                "branch": branch,
                "base": base,
                "title": title,
                "body": body,
            }
        )
        return self.fake_url
