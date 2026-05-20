"""Import-order regression tests.

Catches the circular-import class surfaced by the v0.1.2 real-LLM
dogfood: when `pytest tests/test_safety_invariants.py` ran in isolation,
collection failed with `ImportError: cannot import name 'RunState' from
partially initialized module 'repo_doc_governance.state'`. The full
suite masked the cycle because earlier test files populated
`sys.modules['repo_doc_governance.state']` first.

This test exercises the import order in a fresh Python subprocess so
the fix sticks — if any future change re-introduces eager imports in
`phase_impls/__init__.py` (or otherwise reforms the cycle), this test
fails immediately.
"""

from __future__ import annotations

import subprocess
import sys


def _run_in_fresh_process(snippet: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", snippet],
        capture_output=True,
        text=True,
    )


def test_safety_module_imports_in_isolation():
    """Reproduces the v0.1.2 dogfood report: a fresh `import safety` must
    succeed without triggering the eager phase-impls load chain that
    historically caused a `state.py` partial-init ImportError.
    """
    result = _run_in_fresh_process(
        "from repo_doc_governance import safety"
    )
    assert result.returncode == 0, (
        f"Importing safety in isolation failed.\n"
        f"stdout: {result.stdout!r}\n"
        f"stderr: {result.stderr!r}"
    )


def test_safety_invariants_test_file_imports_in_isolation():
    """Mirrors the exact import pattern at the top of
    `tests/test_safety_invariants.py`. If this passes from a fresh
    Python process, `pytest tests/test_safety_invariants.py` collects.
    """
    result = _run_in_fresh_process(
        "from repo_doc_governance import llm_runtime, safety\n"
        "from repo_doc_governance.orchestrator import make_run_state\n"
        "from repo_doc_governance.phase_impls import (\n"
        "    code_first, drift_audit, pr_handoff, stale_artifacts,\n"
        "    survey, verification,\n"
        ")\n"
        "from repo_doc_governance.phase_impls import pr_handoff as pr_handoff_phase\n"
        "from repo_doc_governance.phases import Task\n"
    )
    assert result.returncode == 0, (
        f"Importing the test_safety_invariants.py header in isolation "
        f"failed.\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )


def test_phase_impls_init_does_not_eagerly_load_phase_modules():
    """Defense in depth: importing `phase_impls` must NOT have already
    pulled in any individual phase module. That eager load was the
    root of the original cycle.
    """
    result = _run_in_fresh_process(
        "import sys\n"
        "from repo_doc_governance import phase_impls  # noqa: F401\n"
        "eager_loaded = [\n"
        "    name for name in sys.modules\n"
        "    if name.startswith('repo_doc_governance.phase_impls.')\n"
        "    and not name.endswith('._utils')\n"
        "]\n"
        "if eager_loaded:\n"
        "    raise SystemExit(\n"
        "        'phase_impls/__init__.py is eagerly importing: '\n"
        "        + ', '.join(eager_loaded)\n"
        "    )\n"
    )
    assert result.returncode == 0, (
        f"phase_impls/__init__.py eagerly loaded phase modules.\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
