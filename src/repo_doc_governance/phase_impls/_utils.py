"""Shared helpers for deterministic phases.

Anything that touches a git working tree, classifies a doc file by name,
or parses a manifest lives here so it can be unit-tested independently.
Phase implementations stay thin and orchestrate these helpers.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Iterable

from repo_doc_governance.models import DocFile, DocKind, ManifestEntry, ManifestKind


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    """Run a `git` command inside `repo` and return stdout.

    Raises `subprocess.CalledProcessError` if the command exits non-zero.
    `git ls-files` against a non-git directory exits non-zero — callers
    that tolerate that should call `is_git_repo` first.
    """
    result = subprocess.run(
        ["git", *args],
        cwd=str(repo),
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.stdout


def is_git_repo(repo: Path) -> bool:
    """True iff `repo` contains a `.git/` directory or file (worktree)."""
    if not repo.exists() or not repo.is_dir():
        return False
    try:
        subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--is-inside-work-tree"],
            check=True,
            capture_output=True,
            text=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def git_ls_files(repo: Path) -> list[str]:
    """All paths tracked by git (repo-relative, forward-slash)."""
    out = _git(repo, "ls-files")
    return [line for line in out.splitlines() if line]


def git_untracked_files(repo: Path) -> list[str]:
    """Untracked files not ignored by `.gitignore` (repo-relative).

    Used by Phase 7 so an untracked `*.bak` in the working tree is
    surfaced as a candidate (classified `Needs verification`, never
    auto-Delete).
    """
    out = _git(repo, "ls-files", "--others", "--exclude-standard")
    return [line for line in out.splitlines() if line]


def git_current_branch(repo: Path) -> str | None:
    """Current branch name, or None if detached / no commits."""
    try:
        out = _git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip()
    except subprocess.CalledProcessError:
        return None
    if out == "HEAD":
        return None
    return out or None


def git_is_clean(repo: Path) -> bool:
    """True iff `git status --porcelain` is empty."""
    out = _git(repo, "status", "--porcelain")
    return out.strip() == ""


def git_path_is_tracked(repo: Path, rel_path: str) -> bool:
    """True iff the path is tracked by git (matches `git ls-files --error-unmatch`)."""
    try:
        subprocess.run(
            ["git", "ls-files", "--error-unmatch", rel_path],
            cwd=str(repo),
            check=True,
            capture_output=True,
            text=True,
        )
        return True
    except subprocess.CalledProcessError:
        return False


# ---------------------------------------------------------------------------
# Doc classification
# ---------------------------------------------------------------------------


_DOC_PATTERNS: list[tuple[re.Pattern[str], DocKind]] = [
    (re.compile(r"(?i)(^|/)readme(\.md|\.rst|\.txt)?$"), DocKind.README),
    (re.compile(r"(?i)(^|/)agents\.md$"), DocKind.AGENT_INSTRUCTIONS),
    (re.compile(r"(?i)(^|/)claude\.md$"), DocKind.AGENT_INSTRUCTIONS),
    (re.compile(r"(?i)(^|/)gemini\.md$"), DocKind.AGENT_INSTRUCTIONS),
    (re.compile(r"(?i)(^|/)\.github/copilot-instructions\.md$"), DocKind.COPILOT_INSTRUCTIONS),
    (re.compile(r"(?i)(^|/)handoff\.md$"), DocKind.HANDOFF),
    (re.compile(r"(?i)/handoff\.md$"), DocKind.HANDOFF),
    (re.compile(r"(?i)(^|/)todo\.md$"), DocKind.TODO),
    (re.compile(r"(?i)(^|/)roadmap\.md$"), DocKind.ROADMAP),
    (re.compile(r"(?i)(^|/)architecture(\.md)?$"), DocKind.ARCHITECTURE),
    (re.compile(r"(?i)(^|/)architecture-[a-z0-9-]+\.md$"), DocKind.ARCHITECTURE),
    (re.compile(r"(?i)(^|/)troubleshooting\.md$"), DocKind.TROUBLESHOOTING),
]


def classify_doc(path: str) -> DocKind | None:
    """Classify a repo-relative path as a doc kind.

    Returns DocKind.OTHER_DOC for any .md under `docs/` that doesn't match
    a more specific pattern; returns None for non-docs (.py, .json, etc.).
    """
    path_fwd = path.replace("\\", "/")
    for pattern, kind in _DOC_PATTERNS:
        if pattern.search(path_fwd):
            return kind
    if path_fwd.endswith(".md") and (path_fwd.startswith("docs/") or "/docs/" in path_fwd):
        return DocKind.OTHER_DOC
    return None


def is_agent_file(kind: DocKind | None) -> bool:
    return kind in (DocKind.AGENT_INSTRUCTIONS, DocKind.COPILOT_INSTRUCTIONS, DocKind.README)


def is_handoff_file(kind: DocKind | None) -> bool:
    return kind in (DocKind.HANDOFF, DocKind.TODO, DocKind.ROADMAP)


def make_doc_file(repo: Path, rel_path: str) -> DocFile | None:
    """Construct a DocFile if `rel_path` classifies as a doc. Else None."""
    kind = classify_doc(rel_path)
    if kind is None:
        return None
    abs_path = repo / rel_path
    try:
        size = abs_path.stat().st_size
    except OSError:
        size = 0
    return DocFile(path=rel_path.replace("\\", "/"), kind=kind, size_bytes=size)


# ---------------------------------------------------------------------------
# Manifest classification + command extraction
# ---------------------------------------------------------------------------


_MANIFEST_BY_NAME: dict[str, ManifestKind] = {
    "package.json": ManifestKind.NODE_PACKAGE,
    "pyproject.toml": ManifestKind.PYTHON_PYPROJECT,
    "requirements.txt": ManifestKind.PYTHON_REQUIREMENTS,
    "cargo.toml": ManifestKind.RUST_CARGO,
    "go.mod": ManifestKind.GO_MOD,
    "pom.xml": ManifestKind.JAVA_MAVEN,
    "build.gradle": ManifestKind.GRADLE,
    "build.gradle.kts": ManifestKind.GRADLE,
    "settings.gradle": ManifestKind.GRADLE,
    "makefile": ManifestKind.MAKEFILE,
    "dockerfile": ManifestKind.DOCKERFILE,
    "docker-compose.yml": ManifestKind.COMPOSE,
    "docker-compose.yaml": ManifestKind.COMPOSE,
    "compose.yml": ManifestKind.COMPOSE,
    "compose.yaml": ManifestKind.COMPOSE,
}


def classify_manifest(rel_path: str) -> ManifestKind | None:
    """Classify a manifest by filename. Returns None for non-manifests."""
    path_fwd = rel_path.replace("\\", "/")
    base = path_fwd.rsplit("/", 1)[-1].lower()
    if base in _MANIFEST_BY_NAME:
        return _MANIFEST_BY_NAME[base]
    if path_fwd.startswith(".github/workflows/") and (
        path_fwd.endswith(".yml") or path_fwd.endswith(".yaml")
    ):
        return ManifestKind.CI_WORKFLOW
    return None


_MAKEFILE_TARGET_RE = re.compile(r"^([A-Za-z0-9_./-]+):\s")


def extract_commands(repo: Path, rel_path: str, kind: ManifestKind) -> list[str]:
    """Best-effort extraction of declared commands from a manifest.

    Returns a list of surface-form commands like `npm test`, `make build`,
    or `python scripts/build.py`. Phase 3 uses these to detect dead
    commands referenced from docs.
    """
    abs_path = repo / rel_path
    try:
        text = abs_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    if kind == ManifestKind.NODE_PACKAGE:
        return _extract_npm_scripts(text)
    if kind == ManifestKind.MAKEFILE:
        return _extract_makefile_targets(text)
    if kind == ManifestKind.PYTHON_PYPROJECT:
        return _extract_pyproject_scripts(text)
    return []


def _extract_npm_scripts(text: str) -> list[str]:
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return []
    scripts = data.get("scripts") if isinstance(data, dict) else None
    if not isinstance(scripts, dict):
        return []
    out: list[str] = []
    for name in scripts.keys():
        if not isinstance(name, str):
            continue
        # `npm test` is the conventional surface form for the `test` script;
        # everything else surfaces as `npm run <name>`.
        if name in ("test", "start"):
            out.append(f"npm {name}")
        out.append(f"npm run {name}")
    return out


def _extract_makefile_targets(text: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for line in text.splitlines():
        if line.startswith("\t") or line.startswith("#"):
            continue
        match = _MAKEFILE_TARGET_RE.match(line)
        if not match:
            continue
        target = match.group(1)
        if target.startswith(".") or "/" in target:
            continue
        if target in seen:
            continue
        seen.add(target)
        out.append(f"make {target}")
    return out


def _extract_pyproject_scripts(text: str) -> list[str]:
    """Extract entry-point script names from `[project.scripts]`.

    Tolerant parser — does not require tomllib (Python 3.11+). Falls back
    cleanly to an empty list if the section is missing or malformed.
    """
    try:
        import tomllib
    except ImportError:  # pragma: no cover — Python < 3.11
        return []
    try:
        data = tomllib.loads(text)
    except (tomllib.TOMLDecodeError, ValueError):
        return []
    project = data.get("project", {}) if isinstance(data, dict) else {}
    scripts = project.get("scripts", {}) if isinstance(project, dict) else {}
    if not isinstance(scripts, dict):
        return []
    return [name for name in scripts.keys() if isinstance(name, str)]


# ---------------------------------------------------------------------------
# File walking when not in a git repo (fallback only)
# ---------------------------------------------------------------------------


_IGNORE_DIRS = {
    ".git", "node_modules", "target", "dist", "build", "__pycache__",
    ".venv", "venv", ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache",
}


def walk_repo(repo: Path, max_depth: int = 3) -> Iterable[str]:
    """Yield repo-relative paths bounded by `max_depth`.

    Fallback inventory source when the target isn't a git working tree.
    Skips obvious noise directories. Used by Phase 1 only when `is_git_repo`
    is False.
    """
    repo = repo.resolve()
    for path in repo.rglob("*"):
        if not path.is_file():
            continue
        try:
            rel = path.relative_to(repo)
        except ValueError:
            continue
        parts = rel.parts
        if any(part in _IGNORE_DIRS for part in parts):
            continue
        if len(parts) > max_depth + 1:
            continue
        yield str(rel).replace("\\", "/")
