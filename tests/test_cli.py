"""Tests for the `repo-doc-gov` CLI subcommands."""

from __future__ import annotations

import json
import subprocess
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest

from repo_doc_governance import llm_runtime
from repo_doc_governance.cli import main
from repo_doc_governance.llm_runtime import StubLLMRunner


def _init_repo(repo: Path, files: dict[str, str], *, branch: str = "main") -> None:
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", branch], cwd=str(repo), check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.invalid"],
        cwd=str(repo), check=True,
    )
    subprocess.run(["git", "config", "user.name", "test"], cwd=str(repo), check=True)
    for rel, content in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(repo), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=str(repo), check=True)


@pytest.fixture(autouse=True)
def _reset_runner():
    llm_runtime.set_runner(None)
    yield
    llm_runtime.set_runner(None)


def test_cli_version_flag(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "repo-doc-gov" in out


def test_cli_no_command_prints_help(capsys):
    rc = main([])
    assert rc == 0
    assert "Manual / active-development mode" in capsys.readouterr().out


def test_cli_run_dry_run_returns_zero(tmp_path: Path, capsys):
    repo = tmp_path / "r"
    _init_repo(
        repo,
        {
            "README.md": "# r\n",
            "package.json": '{"name":"r","version":"0.0.1","scripts":{"test":"echo ok"}}',
        },
    )
    llm_runtime.set_runner(StubLLMRunner(text="# r\n\nbody\n"))

    rc = main(["run", "--repo", str(repo), "--task", "full-pass"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "phases_completed" in out
    assert "---- PR body draft ----" in out


def test_cli_run_json_emits_summary(tmp_path: Path, capsys):
    repo = tmp_path / "r"
    _init_repo(
        repo,
        {"README.md": "# r\n", "package.json": '{"scripts": {}}'},
    )
    llm_runtime.set_runner(StubLLMRunner(text="# r\n"))
    rc = main(["run", "--repo", str(repo), "--task", "drift-sweep", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == 1
    assert "phases_completed" in payload
    assert "pr_body_draft" in payload


def test_cli_audit_emits_json_and_zero_when_clean(tmp_path: Path, capsys):
    """A clean repo audits to zero findings and exits 0 with --fail-on=any."""
    repo = tmp_path / "r"
    _init_repo(
        repo,
        {
            "README.md": (
                "# r\n\n## Quick start\n\n```\nnpm install\nnpm test\n```\n"
            ),
            "package.json": '{"scripts": {"test": "echo ok"}}',
        },
    )
    rc = main(["audit", "--repo", str(repo), "--fail-on", "any"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == 1
    assert payload["summary"]["drift_findings"] == 0
    assert rc == 0


def test_cli_audit_returns_nonzero_when_drifted(tmp_path: Path, capsys):
    repo = tmp_path / "r"
    _init_repo(
        repo,
        {
            "README.md": (
                "# r\n\nRun `npm run deploy` (not declared).\n"
                "See [missing](docs/missing.md).\n"
            ),
            "package.json": '{"scripts": {"build": "echo build"}}',
        },
    )
    rc = main(["audit", "--repo", str(repo), "--fail-on", "any"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"]["drift_findings"] > 0
    assert rc != 0


def test_cli_audit_never_calls_llm(tmp_path: Path, capsys):
    """Audit mode must NEVER reach Phase 4/5/6. Set the runner to a stub
    that records calls; assert it stays empty."""
    repo = tmp_path / "r"
    _init_repo(
        repo,
        {"README.md": "# r\n", "package.json": '{"scripts": {}}'},
    )
    stub = StubLLMRunner(text="# nope\n")
    llm_runtime.set_runner(stub)
    rc = main(["audit", "--repo", str(repo), "--fail-on", "never"])
    assert rc == 0
    assert stub.calls == []  # no LLM call


def test_cli_batch_runs_each_repo(tmp_path: Path, capsys):
    repo1 = tmp_path / "r1"
    repo2 = tmp_path / "r2"
    for r in (repo1, repo2):
        _init_repo(r, {"README.md": "# x\n", "package.json": '{"scripts": {}}'})

    config = tmp_path / "batch.yaml"
    config.write_text(
        f"repos:\n"
        f"  - path: {repo1}\n"
        f"    task: drift-sweep\n"
        f"  - path: {repo2}\n"
        f"    task: drift-sweep\n",
        encoding="utf-8",
    )

    llm_runtime.set_runner(StubLLMRunner(text="# y\n"))
    rc = main(["batch", "--config", str(config), "--concurrency", "2", "--json"])
    assert rc == 0
    out = capsys.readouterr().out
    # On Windows, json.dump escapes the backslashes in the path string,
    # so a literal `str(repo)` substring isn't in `out`. Match on the
    # basename — the repo directory name `r1`/`r2` survives JSON quoting.
    assert "r1" in out
    assert "r2" in out
    assert out.count('"phases_completed":') == 2
