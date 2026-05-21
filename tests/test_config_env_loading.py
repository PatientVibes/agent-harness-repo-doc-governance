"""Tests for `cli._load_config_env` — the config-env-loading pattern.

Closes #41: the README originally claimed
`${XDG_CONFIG_HOME:-~/.config}/repo-doc-gov/env` was auto-sourced as a
fallback for `OPENROUTER_API_KEY` / `ANTHROPIC_API_KEY` / `GH_TOKEN`.
PR #39 corrected the doc; this is the implementation work to match the
original intent. Sibling-tool precedent: `agent-tool-llm-proofreader`.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from repo_doc_governance.cli import _load_config_env


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Point the loader at a tmp config dir + scrub the env vars the
    tests touch so a real `~/.config/repo-doc-gov/env` on the dev box
    doesn't leak into the assertions.
    """
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    for k in (
        "OPENROUTER_API_KEY",
        "ANTHROPIC_API_KEY",
        "GH_TOKEN",
        "DOGFOOD_VAR_FOR_TESTS",
    ):
        monkeypatch.delenv(k, raising=False)
    yield


def _write_env(tmp_path: Path, body: str, mode: int = 0o600) -> Path:
    env_dir = tmp_path / "repo-doc-gov"
    env_dir.mkdir(parents=True, exist_ok=True)
    env_file = env_dir / "env"
    env_file.write_text(body, encoding="utf-8")
    if os.name == "posix":
        env_file.chmod(mode)
    return env_file


def test_config_env_loads_when_present(tmp_path: Path):
    _write_env(tmp_path, "OPENROUTER_API_KEY=from-file-abc\n")
    _load_config_env()
    assert os.environ.get("OPENROUTER_API_KEY") == "from-file-abc"


def test_config_env_does_not_override_already_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Caller-set env wins. The file is FALLBACK, not authoritative."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "from-shell-zzz")
    _write_env(tmp_path, "OPENROUTER_API_KEY=from-file-abc\n")
    _load_config_env()
    assert os.environ.get("OPENROUTER_API_KEY") == "from-shell-zzz"


def test_config_env_is_no_op_when_missing(tmp_path: Path):
    # No env file written.
    _load_config_env()
    assert "OPENROUTER_API_KEY" not in os.environ


def test_config_env_warns_on_loose_permissions_posix(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    """POSIX: a world-readable env file should produce a stderr warning
    but still load. The warning steers the operator toward `chmod 600`.
    """
    if os.name != "posix":
        pytest.skip("POSIX-only — Windows file modes don't carry the same semantics")
    _write_env(tmp_path, "DOGFOOD_VAR_FOR_TESTS=loaded-anyway\n", mode=0o644)
    _load_config_env()
    captured = capsys.readouterr()
    assert "recommend 600" in captured.err
    # Still loaded despite the warning.
    assert os.environ.get("DOGFOOD_VAR_FOR_TESTS") == "loaded-anyway"


def test_config_env_loads_multiple_vars(tmp_path: Path):
    _write_env(
        tmp_path,
        "OPENROUTER_API_KEY=k1\nANTHROPIC_API_KEY=k2\nGH_TOKEN=tok\n",
    )
    _load_config_env()
    assert os.environ.get("OPENROUTER_API_KEY") == "k1"
    assert os.environ.get("ANTHROPIC_API_KEY") == "k2"
    assert os.environ.get("GH_TOKEN") == "tok"
