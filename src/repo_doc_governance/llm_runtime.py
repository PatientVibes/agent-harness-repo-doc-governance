"""LLM runtime abstraction for Phases 4, 5, 6.

Phases 4/5/6 generate documents (README / consolidated agent-instructions /
HANDOFF) using an LLM. The phase code stays decoupled from the underlying
library via the `LLMRunner` protocol: tests pass a `StubLLMRunner`, real
runs use `ReactLLMRunner` which wraps `langgraph.create_react_agent` with
file-reading tools scoped to the target repo path.

Token accounting and pipeline-trace events live on the result object so
the phase doesn't have to know about the underlying SDK shape.

Module-level `get_runner()` / `set_runner()` are the injection point —
the orchestrator's `PHASE_DISPATCH` calls these via `phases.READMERunner`
helpers so the phase functions remain `Callable[[RunState], RunState]`.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass
class LLMRunResult:
    """One LLM call's outcome. Phase code reads `text`; everything else
    is for trace + token-tracking integration."""

    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_s: float = 0.0
    tool_calls: list[dict] = field(default_factory=list)
    """For ReactLLMRunner — list of `{"name": ..., "args": ...}` records
    for each tool call the agent made. Useful in tests + traces."""


@runtime_checkable
class LLMRunner(Protocol):
    """Abstract LLM call interface.

    `run()` is given a system prompt, a user prompt, and a path to the
    target repo. Implementations must scope any file-touching tools to
    `repo_path` — the LLM must not be able to read or write outside it.
    """

    def run(
        self, *, system_prompt: str, user_prompt: str, repo_path: Path
    ) -> LLMRunResult: ...


# ---------------------------------------------------------------------------
# Stub implementation (tests)
# ---------------------------------------------------------------------------


class StubLLMRunner:
    """Test double. Returns a pre-canned `text`, records every call.

    Tests inject a `StubLLMRunner(text=...)` via `set_runner()` and assert
    on `calls` afterward to check what prompts the phase produced.
    """

    def __init__(self, text: str = "", model: str = "stub") -> None:
        self.text = text
        self.model = model
        self.calls: list[dict] = []

    def run(
        self, *, system_prompt: str, user_prompt: str, repo_path: Path
    ) -> LLMRunResult:
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "repo_path": str(repo_path),
            }
        )
        return LLMRunResult(text=self.text, model=self.model)


# ---------------------------------------------------------------------------
# Default implementation — create_react_agent + repo-scoped file tools
# ---------------------------------------------------------------------------


class ReactLLMRunner:
    """Default runner. Wraps `langgraph.create_react_agent` with read-only
    `read_file` + `glob_files` tools scoped to the target repo.

    Lazy-imports langchain/langgraph so the harness can be imported in
    test environments that don't have the heavy deps installed.
    """

    def __init__(self, model_name: str | None = None) -> None:
        self.model_name = model_name or self._default_model_name()

    @staticmethod
    def _default_model_name() -> str:
        if os.environ.get("OPENROUTER_API_KEY"):
            return "openrouter/google/gemini-2.5-pro"
        if os.environ.get("ANTHROPIC_API_KEY"):
            return "anthropic:claude-sonnet-4-6"
        # Fall back to a string the user gets to override; the first real
        # call will fail loudly with a helpful error rather than silently
        # picking an arbitrary provider.
        return "openrouter/google/gemini-2.5-pro"

    def run(
        self, *, system_prompt: str, user_prompt: str, repo_path: Path
    ) -> LLMRunResult:
        from langchain_core.messages import HumanMessage, SystemMessage
        from langgraph.prebuilt import create_react_agent

        llm = self._make_llm()
        tools = make_repo_scoped_tools(repo_path)
        agent = create_react_agent(llm, tools)

        start = time.perf_counter()
        result = agent.invoke(
            {
                "messages": [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=user_prompt),
                ]
            }
        )
        latency = time.perf_counter() - start

        text = ""
        tool_calls: list[dict] = []
        input_tokens = 0
        output_tokens = 0

        for msg in result.get("messages", []):
            tcs = getattr(msg, "tool_calls", None) or []
            for tc in tcs:
                tool_calls.append({"name": tc.get("name"), "args": tc.get("args")})
            um = getattr(msg, "usage_metadata", None)
            if um:
                input_tokens += um.get("input_tokens", 0) or 0
                output_tokens += um.get("output_tokens", 0) or 0
            if (
                getattr(msg, "type", None) == "ai"
                and getattr(msg, "content", None)
                and not tcs
            ):
                text = msg.content if isinstance(msg.content, str) else str(msg.content)

        return LLMRunResult(
            text=text,
            model=self.model_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_s=latency,
            tool_calls=tool_calls,
        )

    def _make_llm(self):
        from langchain_openai import ChatOpenAI

        if self.model_name.startswith("openrouter/"):
            return ChatOpenAI(
                model=self.model_name.removeprefix("openrouter/"),
                api_key=os.environ.get("OPENROUTER_API_KEY"),
                base_url="https://openrouter.ai/api/v1",
                temperature=0.2,
            )
        if self.model_name.startswith("anthropic:"):
            from langchain_anthropic import ChatAnthropic

            return ChatAnthropic(
                model=self.model_name.removeprefix("anthropic:"), temperature=0.2
            )
        # Bare model name → assume OpenAI-compatible.
        return ChatOpenAI(model=self.model_name, temperature=0.2)


# ---------------------------------------------------------------------------
# Repo-scoped read-only file tools (used by ReactLLMRunner)
# ---------------------------------------------------------------------------


def make_repo_scoped_tools(repo_path: Path) -> list:
    """Build `read_file` + `glob_files` LangChain tools scoped to `repo_path`.

    Returns a list of `StructuredTool`s. Path traversal is rejected — the
    resolved path must be inside `repo_path.resolve()`.
    """
    from langchain_core.tools import tool

    root = repo_path.resolve()

    @tool
    def read_file(path: str) -> str:
        """Read a file inside the target repo. `path` is repo-relative."""
        target = (root / path).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            return f"ERROR: path is outside the target repo: {path}"
        if not target.exists() or not target.is_file():
            return f"ERROR: not a file: {path}"
        try:
            return target.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return f"ERROR: {exc}"

    @tool
    def glob_files(pattern: str) -> list[str]:
        """Glob inside the target repo. Returns repo-relative paths."""
        out: list[str] = []
        for hit in root.glob(pattern):
            try:
                rel = hit.resolve().relative_to(root)
            except ValueError:
                continue
            if hit.is_file():
                out.append(str(rel).replace("\\", "/"))
        return out

    return [read_file, glob_files]


# ---------------------------------------------------------------------------
# Module-level injection point for tests
# ---------------------------------------------------------------------------


_RUNNER: LLMRunner | None = None


def get_runner() -> LLMRunner:
    """Return the active LLM runner; lazily instantiate `ReactLLMRunner`
    on first use."""
    global _RUNNER
    if _RUNNER is None:
        _RUNNER = ReactLLMRunner()
    return _RUNNER


def set_runner(runner: LLMRunner | None) -> None:
    """Inject an LLM runner (or `None` to reset)."""
    global _RUNNER
    _RUNNER = runner


def reset_runner() -> None:
    """Reset to default (next `get_runner()` rebuilds the default)."""
    global _RUNNER
    _RUNNER = None
