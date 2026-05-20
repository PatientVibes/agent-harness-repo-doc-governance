"""Phase 4 preserve-while-editing — real LLM integration test.

Opt-in. Skipped unless `OPENROUTER_API_KEY` or `ANTHROPIC_API_KEY` is set,
and only collected when the `integration` marker is targeted explicitly
(`uv run pytest -m integration`).

Validates the load-bearing claim of the v0.1.2 fix: when the README has
REAL drift (a dead command + a broken link) but ALSO real content that
must survive (the title, a working code block), the LLM should:

- Remove only the drift-flagged content
- Preserve the title verbatim (no rename)
- Preserve the working code block
- Not invent `Needs verification` filler sections

Cost: < $0.05 per run with Haiku 4.5. Issue #13 (≤ $0.20 budget).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from repo_doc_governance import llm_runtime
from repo_doc_governance.llm_runtime import ReactLLMRunner
from repo_doc_governance.orchestrator import make_run_state
from repo_doc_governance.phase_impls import code_first, drift_audit, readme, survey
from repo_doc_governance.phases import Task

from conftest import build_drifted_repo


def _resolve_route() -> tuple[bool, str | None, str]:
    """Pick the cheapest viable LLM route given what's actually available
    in the environment.

    Prefer OpenRouter (works with `langchain_openai`, already a hard dep).
    Fall back to direct Anthropic only when `langchain_anthropic` is
    importable. Returns `(viable, model_name, skip_reason)`.
    """
    if os.environ.get("OPENROUTER_API_KEY"):
        return True, "openrouter/anthropic/claude-haiku-4.5", ""
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            import langchain_anthropic  # noqa: F401
        except ImportError:
            return False, None, (
                "ANTHROPIC_API_KEY is set but `langchain_anthropic` is not "
                "installed. Either `uv pip install langchain-anthropic` or "
                "set OPENROUTER_API_KEY for a deps-free route."
            )
        return True, "anthropic:claude-haiku-4-5-20251001", ""
    return False, None, (
        "no LLM API key in env (set OPENROUTER_API_KEY or ANTHROPIC_API_KEY)"
    )


_HAS_ROUTE, _MODEL, _SKIP_REASON = _resolve_route()


@pytest.fixture(autouse=True)
def _reset_runner():
    llm_runtime.set_runner(None)
    yield
    llm_runtime.set_runner(None)


@pytest.mark.integration
@pytest.mark.skipif(not _HAS_ROUTE, reason=_SKIP_REASON)
def test_phase4_preserve_edit_path_against_drifted_fixture(tmp_path: Path):
    """The drifted fixture's README has a dead command + a broken link
    on top of a valid `npm install` code block. After Phase 4, the LLM
    output must drop the drift, keep the working content, and not
    rename the title or pad with filler.
    """
    repo = build_drifted_repo(tmp_path)
    state = make_run_state(repo, Task.FULL_PASS)
    survey.run(state)
    code_first.run(state)
    drift_audit.run(state)

    assert _MODEL is not None  # guarded by the skipif above
    llm_runtime.set_runner(ReactLLMRunner(model_name=_MODEL))
    readme.run(state)

    proposed = state.readme_proposed or ""
    assert proposed, (
        "Phase 4 produced empty output — LLM call probably failed. Check the "
        "API key and the model name."
    )

    # ---- Preserve-content assertions -----------------------------------
    first_line = proposed.splitlines()[0]
    assert first_line == "# drifted-fixture", (
        f"LLM renamed the title to {first_line!r}. The README's first-line "
        f"H1 is the canonical project name and must be preserved verbatim."
    )
    assert "npm install" in proposed, (
        "The valid `npm install` command from the fixture's code block was "
        "dropped. The preserve-existing-content rule was violated."
    )

    # ---- Drift-removal assertions --------------------------------------
    assert "npm run deploy" not in proposed, (
        "The dead `npm run deploy` command (flagged as drift) should have "
        "been removed."
    )
    assert "docs/MISSING.md" not in proposed, (
        "The broken link to `docs/MISSING.md` (flagged as drift) should "
        "have been removed or replaced."
    )

    # ---- No-filler assertion -------------------------------------------
    # The drifted fixture's drift findings are `dead_command` + `broken_link`
    # — neither has `Needs verification` classification. The LLM must not
    # invent that section from thin air.
    assert "Needs verification" not in proposed, (
        "LLM invented a `Needs verification` section despite no drift "
        "findings with that classification. The omit-empty-sections rule "
        "was violated."
    )
