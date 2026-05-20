"""Shared fixtures for the deterministic phase tests.

Each `build_*_repo` helper takes a `tmp_path` and returns a `Path` to a
freshly-initialized git working tree with the named drift pattern. The
helpers are exposed as plain functions (not pytest fixtures) so a single
test can build multiple repos when needed for differential checks.

These fixtures are the load-bearing test substrate for PR #3 — the spec
calls out `tests/fixtures/` "clean / drifted / broken-links /
has-AGENTS-and-CLAUDE / monorepo" as the expected set.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Mapping


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=str(repo),
        check=True,
        capture_output=True,
        text=True,
    )


def _git_init_with(repo: Path, files: Mapping[str, str]) -> None:
    """Init a git repo at `repo`, write `files`, stage, and commit."""
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q", "-b", "main")
    # Local identity so the commit succeeds in any CI/dev env.
    _git(repo, "config", "user.email", "harness-test@example.invalid")
    _git(repo, "config", "user.name", "harness-test")
    for rel, content in files.items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "fixture init")


# ---------------------------------------------------------------------------
# Repo factories
# ---------------------------------------------------------------------------


def build_clean_repo(root: Path) -> Path:
    """A small, well-organized Node + Python repo with consistent docs."""
    repo = root / "clean"
    files = {
        "README.md": (
            "# clean-fixture\n\n"
            "## Quick start\n\n"
            "```\n"
            "npm install\n"
            "npm test\n"
            "```\n\n"
            "See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).\n"
        ),
        "package.json": json.dumps(
            {
                "name": "clean-fixture",
                "version": "0.0.1",
                "scripts": {"test": "echo ok", "build": "echo build"},
            },
            indent=2,
        ),
        "docs/ARCHITECTURE.md": "# Architecture\n\nShort overview.\n",
        "src/index.js": "console.log('hi');\n",
    }
    _git_init_with(repo, files)
    return repo


def build_drifted_repo(root: Path) -> Path:
    """Has a dead npm command, a broken link, and a vague TODO."""
    repo = root / "drifted"
    files = {
        "README.md": (
            "# drifted-fixture\n\n"
            "## Quick start\n\n"
            "```\n"
            "npm install\n"
            "```\n\n"
            "Run the deploy step with `npm run deploy` (dead — not in package.json).\n\n"
            "See [docs/MISSING.md](docs/MISSING.md) for details.\n"
        ),
        "package.json": json.dumps(
            {"name": "drifted", "version": "0.0.1", "scripts": {"build": "echo build"}},
            indent=2,
        ),
        "docs/HANDOFF.md": (
            "# Handoff\n\n"
            "## Next tasks\n\n"
            "- [ ] TODO: clean up later\n"
            "- [ ] Update src/index.js: rewrite to TypeScript.\n"
        ),
        "src/index.js": "console.log('drift');\n",
    }
    _git_init_with(repo, files)
    return repo


def build_broken_links_repo(root: Path) -> Path:
    """Multiple broken internal markdown links."""
    repo = root / "broken_links"
    files = {
        "README.md": (
            "# broken-links-fixture\n\n"
            "See [missing-1](docs/missing-1.md) and [missing-2](docs/missing-2.md).\n"
            "Working link: [arch](docs/ARCHITECTURE.md).\n"
        ),
        "docs/ARCHITECTURE.md": "# Architecture\n",
        "package.json": json.dumps({"name": "bl", "version": "0.0.1", "scripts": {}}),
    }
    _git_init_with(repo, files)
    return repo


def build_agents_and_claude_repo(root: Path) -> Path:
    """Has both AGENTS.md and CLAUDE.md at the repo root (conflict)."""
    repo = root / "agents_and_claude"
    files = {
        "README.md": "# agents-claude-fixture\n",
        "AGENTS.md": (
            "# Agent instructions\n\n"
            "## Working rules\n\n"
            "Do not commit to main.\n"
        ),
        "CLAUDE.md": (
            "# Claude instructions\n\n"
            "## Working rules\n\n"
            "Always run tests.\n"
        ),
        "package.json": json.dumps(
            {"name": "ac", "version": "0.0.1", "scripts": {"test": "echo ok"}}
        ),
    }
    _git_init_with(repo, files)
    return repo


def build_monorepo(root: Path) -> Path:
    """Two packages under `packages/`, each with its own README + manifest."""
    repo = root / "monorepo"
    files = {
        "README.md": (
            "# monorepo-fixture\n\n"
            "Packages: [api](packages/api/README.md), [web](packages/web/README.md).\n"
        ),
        "packages/api/README.md": "# api\n",
        "packages/api/package.json": json.dumps(
            {"name": "api", "version": "0.0.1", "scripts": {"test": "echo ok"}}
        ),
        "packages/web/README.md": "# web\n",
        "packages/web/package.json": json.dumps(
            {"name": "web", "version": "0.0.1", "scripts": {"build": "echo ok"}}
        ),
        "package.json": json.dumps(
            {"name": "root", "version": "0.0.1", "private": True, "scripts": {}}
        ),
    }
    _git_init_with(repo, files)
    return repo


def build_stale_artifacts_repo(root: Path) -> Path:
    """Has clear stale-artifact candidates: *.bak / scratch.md /
    handoff-final-final.md / .DS_Store. Plus a tracked file that gets
    referenced from README (should NOT be flagged Delete).
    """
    repo = root / "stale"
    files = {
        "README.md": (
            "# stale-fixture\n\n"
            "Refer to docs/important.md for setup.\n"
        ),
        "docs/important.md": "# Important\n\nReal content.\n",
        "src/main.py.bak": "old content\n",
        "scratch.md": "random scratch notes\n",
        "handoff-final-final.md": "yet another handoff\n",
        ".DS_Store": "binary\n",
        "package.json": json.dumps({"name": "s", "version": "0.0.1", "scripts": {}}),
    }
    _git_init_with(repo, files)
    return repo
