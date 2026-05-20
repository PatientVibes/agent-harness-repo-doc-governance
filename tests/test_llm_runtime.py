"""Tests for the LLM runtime abstraction.

Covers the `StubLLMRunner` and the repo-scoped file tools. The
`ReactLLMRunner` is exercised only via the `-m integration` smoke test
elsewhere — its `invoke()` call hits a real model.
"""

from __future__ import annotations

from pathlib import Path

from repo_doc_governance.llm_runtime import (
    LLMRunResult,
    StubLLMRunner,
    get_runner,
    make_repo_scoped_tools,
    reset_runner,
    set_runner,
)


def test_stub_runner_returns_canned_text(tmp_path: Path):
    stub = StubLLMRunner(text="hi")
    result = stub.run(system_prompt="sys", user_prompt="usr", repo_path=tmp_path)
    assert isinstance(result, LLMRunResult)
    assert result.text == "hi"
    assert stub.calls == [
        {"system_prompt": "sys", "user_prompt": "usr", "repo_path": str(tmp_path)}
    ]


def test_set_runner_and_reset(tmp_path: Path):
    reset_runner()
    s1 = StubLLMRunner(text="one")
    set_runner(s1)
    assert get_runner() is s1
    set_runner(None)
    # After reset, get_runner() will lazily instantiate ReactLLMRunner; we
    # don't want to actually call it (no API key). Just verify identity
    # check: setting to None and re-setting works.
    s2 = StubLLMRunner(text="two")
    set_runner(s2)
    assert get_runner() is s2
    set_runner(None)


def test_read_file_tool_scoped_to_repo(tmp_path: Path):
    repo = tmp_path / "x"
    repo.mkdir()
    (repo / "ok.txt").write_text("inside", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")

    tools = make_repo_scoped_tools(repo)
    read_file = next(t for t in tools if t.name == "read_file")

    assert read_file.invoke({"path": "ok.txt"}) == "inside"
    # Traversal: ../outside.txt resolves outside the repo root → rejected.
    out = read_file.invoke({"path": "../outside.txt"})
    assert "outside" in out and "ERROR" in out


def test_glob_files_tool_returns_repo_relative_paths(tmp_path: Path):
    repo = tmp_path / "g"
    repo.mkdir()
    (repo / "a.md").write_text("a", encoding="utf-8")
    (repo / "sub").mkdir()
    (repo / "sub" / "b.md").write_text("b", encoding="utf-8")

    tools = make_repo_scoped_tools(repo)
    glob_files = next(t for t in tools if t.name == "glob_files")

    out = glob_files.invoke({"pattern": "**/*.md"})
    assert "a.md" in out
    assert "sub/b.md" in out
