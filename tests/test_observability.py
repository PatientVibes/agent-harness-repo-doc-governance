"""Tests for token-tracker + pipeline-trace wiring."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from repo_doc_governance import llm_runtime
from repo_doc_governance.llm_runtime import LLMRunResult, StubLLMRunner
from repo_doc_governance.orchestrator import make_run_state, run, summary
from repo_doc_governance.phase_impls import (
    code_first,
    drift_audit,
    handoff,
    readme,
    survey,
)
from repo_doc_governance.phases import Task


def _init_repo(repo: Path, files: dict[str, str]) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=str(repo), check=True)
    for rel, content in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(repo), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=str(repo), check=True)


class _AccountingRunner:
    """A stub that returns a canned text but populates the per-call
    token / latency / model metadata the way the real runner does."""

    def __init__(
        self,
        *,
        text: str,
        model: str = "stub-model",
        input_tokens: int = 100,
        output_tokens: int = 50,
        latency_s: float = 0.42,
    ) -> None:
        self.text = text
        self.model = model
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.latency_s = latency_s

    def run(self, *, system_prompt, user_prompt, repo_path):
        return LLMRunResult(
            text=self.text,
            model=self.model,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            latency_s=self.latency_s,
        )


@pytest.fixture(autouse=True)
def _reset_runner():
    llm_runtime.set_runner(None)
    yield
    llm_runtime.set_runner(None)


def test_token_tracker_records_readme_phase(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(
        repo,
        {"README.md": "# r\n", "package.json": '{"scripts": {"test": "echo ok"}}'},
    )
    llm_runtime.set_runner(_AccountingRunner(text="# r\n\nupdated\n"))

    state = make_run_state(repo, Task.FULL_PASS)
    survey.run(state)
    code_first.run(state)
    readme.run(state)

    totals = state.token_tracker.totals()
    assert "phase4_readme" in totals
    assert totals["phase4_readme"]["input_tokens"] == 100
    assert totals["phase4_readme"]["output_tokens"] == 50
    assert totals["phase4_readme"]["calls"] == 1


def test_token_tracker_aggregates_across_llm_phases(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(
        repo,
        {
            "README.md": "# r\n",
            "AGENTS.md": "# Agent\n",
            "docs/HANDOFF.md": "# Handoff\n",
            "package.json": '{"scripts": {"test": "echo ok"}}',
        },
    )
    llm_runtime.set_runner(_AccountingRunner(text="# generated\n"))

    state = make_run_state(repo, Task.FULL_PASS)
    result = run(state)

    totals = result.token_tracker.totals()
    # All three LLM phases recorded calls with distinct sources.
    assert "phase4_readme" in totals
    assert "phase5_agent_instructions" in totals
    assert "phase6_handoff" in totals


def test_pipeline_trace_emits_phase_events(tmp_path: Path):
    """When `state.trace_path` is set, the orchestrator must emit
    `pipeline_start`, per-phase `phase_start`/`phase_end`, and a final
    `pipeline_end` JSONL event.
    """
    repo = tmp_path / "r"
    _init_repo(
        repo,
        {"README.md": "# r\n", "package.json": '{"scripts": {}}'},
    )
    trace_path = tmp_path / "trace.jsonl"

    state = make_run_state(repo, Task.DRIFT_SWEEP)
    state.trace_path = trace_path
    run(state)

    events = [json.loads(line) for line in trace_path.read_text().splitlines() if line]
    types = [e["event_type"] for e in events]
    assert types[0] == "pipeline_start"
    assert types[-1] == "pipeline_end"
    assert "phase_start" in types
    assert "phase_end" in types


def test_pipeline_trace_emits_llm_call_event(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(
        repo,
        {"README.md": "# r\n", "package.json": '{"scripts": {"test": "echo ok"}}'},
    )
    trace_path = tmp_path / "trace.jsonl"
    llm_runtime.set_runner(_AccountingRunner(text="# updated\n"))

    state = make_run_state(repo, Task.README_ONLY)
    state.trace_path = trace_path
    run(state)

    events = [json.loads(line) for line in trace_path.read_text().splitlines() if line]
    llm_events = [e for e in events if e["event_type"] == "llm_call"]
    assert len(llm_events) == 1
    ev = llm_events[0]
    assert ev["source"] == "phase4_readme"
    assert ev["model"] == "stub-model"
    assert ev["input_tokens"] == 100
    assert ev["output_tokens"] == 50


def test_pipeline_trace_off_by_default(tmp_path: Path):
    """Without `state.trace_path`, no trace file is created."""
    repo = tmp_path / "r"
    _init_repo(
        repo,
        {"README.md": "# r\n", "package.json": '{"scripts": {}}'},
    )
    state = make_run_state(repo, Task.DRIFT_SWEEP)
    # trace_path stays None.
    run(state)
    # Verify no JSONL files in the tmp_path tree (outside the repo).
    assert not any(p.suffix == ".jsonl" for p in tmp_path.rglob("*"))


def test_summary_includes_token_usage(tmp_path: Path):
    repo = tmp_path / "r"
    _init_repo(
        repo,
        {"README.md": "# r\n", "package.json": '{"scripts": {"test": "echo ok"}}'},
    )
    llm_runtime.set_runner(_AccountingRunner(text="# updated\n"))
    state = make_run_state(repo, Task.README_ONLY)
    result = run(state)

    s = summary(result)
    assert "token_usage" in s
    assert "phase4_readme" in s["token_usage"]
