"""Shared token-tracker + pipeline-trace recording for LLM phases.

Every LLM phase (4, 5, 6) calls `record_llm_call(state, source, ref, result)`
after each `runner.run(...)`. The helper accumulates per-source token
usage into `state.token_tracker` and (when configured) emits an
`llm_call` event into `state.pipeline_trace`.

Phases stay decoupled from the tracker / trace SDKs — they only pass the
`LLMRunResult` shape; this helper does the dispatch.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from repo_doc_governance.llm_runtime import LLMRunResult
    from repo_doc_governance.state import RunState


def record_llm_call(
    state: "RunState", *, source: str, ref: str, result: "LLMRunResult"
) -> None:
    """Record one LLM call's usage on the run-scoped tracker + trace.

    `source` is the phase identifier (e.g. `phase4_readme`); `ref` is a
    free-text per-call hint (e.g. the file path being generated) used
    when scanning the trace later.
    """
    state.token_tracker.record(
        source=source,
        model=result.model,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        ref=ref,
        latency_ms=result.latency_s * 1000.0,
    )
    if state.pipeline_trace is not None:
        state.pipeline_trace.llm_call(
            source=source,
            model=result.model,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            latency_s=result.latency_s,
            summary=ref,
        )
