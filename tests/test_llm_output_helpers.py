"""Unit tests for `phase_impls/_llm_output.py` defensive helpers.

Surfaced in v0.1.3 dogfood (#27) — Sonnet 4.6 emits chain-of-thought
prose above the first H1 of LLM phase outputs in violation of the
explicit "raw markdown only" hard rule. `strip_llm_preamble` is the
defensive post-processor that catches the bug regardless of the
model's behavior.
"""

from __future__ import annotations

from repo_doc_governance.phase_impls._llm_output import strip_llm_preamble


def test_strip_preamble_drops_prose_above_h1():
    """The motivating case — Sonnet 4.6 v0.1.3 dogfood."""
    raw = (
        "Now I have a thorough understanding of the repo. The manifests "
        "declare no runnable commands directly...\n"
        "\n"
        "# Agent Instructions\n"
        "\n"
        "body\n"
    )
    assert strip_llm_preamble(raw) == "# Agent Instructions\n\nbody\n"


def test_strip_preamble_is_no_op_when_already_clean():
    raw = "# Title\n\nbody\n"
    assert strip_llm_preamble(raw) == raw


def test_strip_preamble_handles_no_h1_gracefully():
    """If the LLM forgot the H1 entirely, leave the output alone so a
    human can inspect what came back."""
    raw = "Just some prose with no heading at all.\n"
    assert strip_llm_preamble(raw) == raw


def test_strip_preamble_handles_empty_input():
    assert strip_llm_preamble("") == ""


def test_strip_preamble_keeps_h2_after_h1():
    raw = "Preamble.\n\n# Title\n\n## Subsection\n\nbody\n"
    assert strip_llm_preamble(raw) == "# Title\n\n## Subsection\n\nbody\n"


def test_strip_preamble_respects_leading_whitespace_on_h1():
    """An H1 that has leading whitespace (rare but possible) still
    counts — `# ` is matched against `line.lstrip()`."""
    raw = "Preamble.\n\n  # Title\n\nbody\n"
    assert strip_llm_preamble(raw) == "  # Title\n\nbody\n"


def test_strip_preamble_does_not_treat_hash_without_space_as_h1():
    """A `#noheading` line is NOT an H1 — markdown requires `# Title`
    with a space."""
    raw = "Preamble.\n\n#hashtag-not-heading\n\n# Real Title\n\nbody\n"
    assert (
        strip_llm_preamble(raw)
        == "# Real Title\n\nbody\n"
    )


def test_strip_preamble_preserves_trailing_newline_state():
    """If the input ends with a newline, the output ends with a newline;
    if not, the output doesn't add one."""
    with_nl = "Pre.\n\n# T\n\nbody\n"
    assert strip_llm_preamble(with_nl).endswith("\n")

    without_nl = "Pre.\n\n# T\n\nbody"
    assert not strip_llm_preamble(without_nl).endswith("\n")


def test_strip_preamble_readme_no_drift_repro():
    """Reproduces the Phase 4 leak from v0.1.3 dogfood — the LLM
    correctly recognized no drift but emitted a meta-statement above
    the existing README, defeating Phase 9's no-change short-circuit.
    """
    raw = (
        "No drift was flagged and the repo contents confirm all existing "
        "README content is accurate. The README is output verbatim.\n"
        "\n"
        "# agent-harness-card-extractor\n"
        "\n"
        "ID card and insurance card data extraction agent.\n"
    )
    expected = (
        "# agent-harness-card-extractor\n"
        "\n"
        "ID card and insurance card data extraction agent.\n"
    )
    assert strip_llm_preamble(raw) == expected
