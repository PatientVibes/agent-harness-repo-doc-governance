"""Tests for the FastAPI HTTP shell."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from repo_doc_governance import llm_runtime
from repo_doc_governance.app import app
from repo_doc_governance.llm_runtime import StubLLMRunner


client = TestClient(app)


def _init_repo(repo: Path, files: dict[str, str]) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=str(repo), check=True)
    subprocess.run(
        ["git", "config", "user.email", "t@t"], cwd=str(repo), check=True
    )
    subprocess.run(["git", "config", "user.name", "t"], cwd=str(repo), check=True)
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


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"


def test_run_endpoint_dry_run(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(
        repo,
        {"README.md": "# r\n", "package.json": '{"scripts": {"test": "echo ok"}}'},
    )
    llm_runtime.set_runner(StubLLMRunner(text="# r\n\nbody\n"))
    resp = client.post(
        "/run",
        json={"repo": str(repo), "task": "drift-sweep", "execute": False},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["schema_version"] == 1
    assert body["pr_url"] is None  # dry-run
    assert body["pr_body_draft"].startswith("# Summary")


def test_audit_endpoint(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(
        repo,
        {
            "README.md": "# r\n\nRun `npm run deploy`.\n",
            "package.json": '{"scripts": {"test": "echo ok"}}',
        },
    )
    # Set a recorder stub — audit must NOT call the LLM.
    stub = StubLLMRunner(text="# nope\n")
    llm_runtime.set_runner(stub)
    resp = client.post("/audit", json={"repo": str(repo)})
    assert resp.status_code == 200
    body = resp.json()
    assert body["schema_version"] == 1
    assert body["summary"]["drift_findings"] >= 1  # the dead npm run deploy
    assert stub.calls == []
