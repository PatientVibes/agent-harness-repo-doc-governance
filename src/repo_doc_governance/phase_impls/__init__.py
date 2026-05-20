"""Per-phase implementations.

Each module exposes a single `run(state: RunState) -> RunState` function.
`phases.py:_build_dispatch()` is the single entry point that resolves
the per-phase callables — it lazy-imports each module as needed.

This module's `__init__.py` deliberately does NOT eagerly import the
phase modules. Eager imports here caused a circular import surfaced
when `pytest tests/test_safety_invariants.py` ran in isolation:

  test → safety.py → phase_impls.__init__ → phase_impls.agent_instructions
       → state.py → phases.py → _build_dispatch() → phase_impls.code_first
       → state.py (still partially initialized) → ImportError.

Letting `_build_dispatch()` be the only entry point that triggers the
imports breaks the cycle — when `safety.py` imports `_utils`, only the
small `_utils` module loads; the heavier phase modules load on the
orchestrator path where `state.py` is already fully initialized.
"""
