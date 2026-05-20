# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed (v0.1.x follow-up — plan-doc scope exemption)
- Phase 3 (drift audit) now demotes `dead_command` findings inside
  plan / spec / design / proposal / RFC docs to
  `dead_command_in_aspirational_doc` with severity `Low` and
  classification `Needs verification` (was severity `High` /
  `Update`). The aspirational-doc path set:
  `docs/superpowers/plans/**`, `docs/superpowers/specs/**`,
  `docs/plans/**`, `docs/specs/**`, `docs/design/**`,
  `docs/proposals/**`, `docs/rfcs/**`.
- **Why:** dogfood pass against the sibling repos surfaced this FP class
  — `agent-harness-card-extractor`'s `docs/superpowers/plans/*-frontend.md`
  references `npm run dev` / `npm test` because the planned frontend
  hasn't shipped. The command isn't drift; it describes a future state.
  Demoting (rather than dropping) preserves the signal for human review.

## [0.1.0] — 2026-05-19

### Added (PR #6 — feature-complete release)
- CLI subcommands: `run` (manual mode — opens a PR), `audit`
  (read-only — JSON output, no PR), `batch` (multi-repo with bounded
  concurrency). `run` and `audit` share the same deterministic engine;
  `audit` stops after Phase 8 Tier-1 and never invokes Phase 4/5/6
  (LLM) or Phase 9 (PR creation) — verified by a test that asserts the
  `StubLLMRunner` has zero recorded calls under `audit`.
- FastAPI HTTP routes in `src/repo_doc_governance/app.py`: `POST /run`,
  `POST /audit`, `GET /health`. Mirror the CLI semantics. No auth
  baked in — production deployments front this with their platform's
  access control.
- Claude Code subagent at
  `agent-skills/plugins/repo-documentation-governance/agents/repo-documentation-governance.md`
  rewritten as a thin wrapper around the harness CLI. The subagent's
  job is now to (1) run `repo-doc-gov audit` and show the drift report,
  (2) on user approval, run `repo-doc-gov run --execute`, (3) surface
  the PR URL + `Needs verification` items. The workflow rules + safety
  invariants are now enforced by the harness; the subagent body
  describes the harness's contract.
- Catalog refresh: `D:/ai-agents/CLAUDE.md` 12-Component Harness
  sentence now lists `agent-harness-repo-doc-governance` as the fourth
  example; `D:/ai-agents/CLAUDE.md` Sibling repos table adds a row;
  `D:/ai-agents/README.md` Agents table updates the row from
  `v0.1.0-rc` to `v0.1.0` and marks the spec status `implemented`.
- Spec status flipped from `draft` → `implemented` at
  `D:/ai-agents/docs/superpowers/specs/2026-05-19-agent-harness-repo-doc-governance-design.md`.
- Retrospective added to `D:/ai-agents/CONTRIBUTING.md` per the
  catalog convention.
- Version bumped to `0.1.0` (from `0.1.0-rc`) in `pyproject.toml` and
  `__init__.py`. 103+ tests pass.

## [Unreleased]

### Added (PR #5)
- `src/repo_doc_governance/safety.py` — load-bearing safety primitives:
  `BranchPolicyError` / `PathOutsideRepoError` / `UntrackedFileError` /
  `RefusedCommandError`. Each invariant from the design spec has both an
  assert function and an integration test against a real temp git repo.
- Refuse-list (`safety.refuse_list_match`) covering destructive
  filesystem ops, credential / secret access, deployment commands,
  production DB ops, package publishing, privileged container ops,
  `curl | bash` / `wget | bash` style execution, and `sudo`. Used by
  both Phase 8 Tier-2 (command execution gate) and as a defense-in-
  depth gate when the LLM would emit a command in a doc.
- **Phase 9 PR-format handoff** (`phase_impls/pr_handoff.py`) — builds
  a `PRPlan` from `RunState`, sets `state.pr_body_draft` (always), and
  when `state.execute_phase9` is True executes the plan: creates a
  feature branch, applies file writes / deletes / moves with safety
  gates, commits (only if HEAD is on a non-protected non-base branch),
  pushes, and calls the configured `PRCreator` (default `GhPRCreator`).
  **Never calls `gh pr merge`** — only `gh pr create`. The
  `test_never_self_merge` test verifies this by asserting the
  `NullPRCreator` test double has no `merge` method.
- `src/repo_doc_governance/pr_creator.py` — abstracted `PRCreator`
  Protocol + `GhPRCreator` (shells out to `gh`) + `NullPRCreator` (test
  double). Phase 9 reads `phase_impls.pr_handoff.get_pr_creator()` so
  tests can swap in a fake without monkeypatching subprocess.
- `src/repo_doc_governance/pr_builder.py` — `PRPlan` dataclass +
  `build_pr_plan(state)` pure-function. Renders the PR body from the
  template in `prompts/templates.md`, populating Summary, Changes,
  Source of truth, Verification, Not run, Needs verification,
  Governance note from `RunState`. Untracked-by-git stale candidates
  are filtered out of `files_to_delete` at the planner level (Phase 9
  does another last-mile check at the delete step).
- **Phase 8 Tier-2** added to `phase_impls/verification.py` — opt-in
  via `state.execute_tier2 = True`. For each declared command, reads
  the manifest script body, runs `safety.assert_command_safe(cmd,
  body)` against the refuse-list, executes safe commands with a 120s
  timeout, and records `command_execution` `VerificationResult` rows
  (`ok=True` for exit-zero, `ok=False` for refused/non-zero/timeout).
- RunState additions: `readme_proposed` / `agent_files_proposed` /
  `handoff_proposed` / `handoff_path` (full bodies for Phase 9 to
  write), `base_branch` (default `main`), `branch_prefix` (default
  `doc-governance`), `execute_phase9` (default False — dry-run /
  audit-mode), `execute_tier2` (default False), `pr_url`,
  `pr_branch_name`.
- Tests: `test_safety_invariants.py` (5 invariants × 1–4 cases each,
  all hitting real `git init`/`git commit` against `tmp_path`),
  `test_pr_builder.py` (planner output shape + dry-run branch isolation).
  Suite total: **92 tests pass**.

### Added (PR #4)
- `src/repo_doc_governance/llm_runtime.py` — `LLMRunner` protocol +
  `LLMRunResult` dataclass + `ReactLLMRunner` (default, wraps
  `langgraph.create_react_agent` with read-only repo-scoped file tools)
  + `StubLLMRunner` (tests). Module-level `get_runner()` / `set_runner()`
  is the injection point.
- `make_repo_scoped_tools(repo)` builds `read_file` + `glob_files` tools
  whose resolved paths must be inside `repo.resolve()`. Path traversal
  is rejected at the tool level.
- `src/repo_doc_governance/phase_impls/_prompts.py` — section-aware
  loader for the vendored `phases.md` / `decisions.md` / `templates.md`
  files. LLM phases pull only the slice they need (e.g. "## Phase 4 —
  README update") into the system prompt rather than the full file.
- `src/repo_doc_governance/phase_impls/_diff.py` — `unified_diff(repo,
  rel_path, proposed)` helper used by all three LLM phases.
- **Phase 4 README** (`phase_impls/readme.py`) — builds a prompt from
  the inventory, code-first map, and README-targeted drift findings and
  asks the LLM for the proposed new README body. Unified diff goes in
  `state.readme_diff`. No filesystem mutation.
- **Phase 5 Agent-instruction consolidation** (`phase_impls/agent_instructions.py`)
  — deterministically picks the canonical file (`AGENTS.md` default;
  `CLAUDE.md` when `.claude/**` infrastructure is present), then asks the
  LLM for the canonical body and template-fills thin wrappers for the
  others. `state.canonical_agent_file` records the decision so the PR
  body (Phase 9) can quote it. `state.agent_files_diff` is the
  concatenated per-file diff, separated by `--- file: <path> ---`.
- **Phase 6 HANDOFF** (`phase_impls/handoff.py`) — picks an existing
  `docs/HANDOFF.md` or `HANDOFF.md`, falls back to creating
  `docs/HANDOFF.md`, asks the LLM to refresh it using the existing
  TODO/ROADMAP/HANDOFF inputs + handoff-targeted drift findings. Diff
  goes in `state.handoff_diff`.
- Per-phase test files: `test_phase_readme.py`,
  `test_phase_agent_instructions.py`, `test_phase_handoff.py`,
  `test_llm_runtime.py`. Tests use `StubLLMRunner` (no real LLM call)
  to verify prompt content + diff computation + canonical decision.
  Path-traversal rejection on `read_file` tool exercised against a
  real `tmp_path` siblings setup.
- Orchestrator tests updated for PR #4 — `README_ONLY` task now
  completes `CODE_FIRST` + `README` and only `PR_HANDOFF` remains a
  stub.

### Added (PR #3)
- Typed Pydantic models in `src/repo_doc_governance/models.py` —
  `Classification`, `Severity`, `DocKind`, `ManifestKind`, `DocFile`,
  `ManifestEntry`, `Inventory`, `CodeFirstMap`, `DriftFinding`,
  `StaleCandidate`, `VerificationResult`. `Classification` is the
  `Keep / Update / Consolidate / Archive / Delete / Needs verification`
  enum from `prompts/decisions.md`.
- `RunState` updated to use the typed phase outputs. `inventory` /
  `code_first_map` default to `None` until their phase runs; the
  finding/result lists default empty.
- Deterministic phase implementations in `src/repo_doc_governance/phase_impls/`:
  - `survey.py` (Phase 1) — `git ls-files`-based inventory + manifest/doc
    classification + primary-language tally + branch / clean-status capture.
    Falls back to a bounded directory walk when the target isn't a git
    working tree.
  - `code_first.py` (Phase 2) — extracts declared commands from npm
    `package.json` scripts, Makefile targets, and `pyproject.toml`
    `[project.scripts]`; records CI workflow paths, runtime entry points,
    and `.env.example`-class files. Falls back gracefully when Phase 1
    was skipped (e.g. `readme-only` task).
  - `drift_audit.py` (Phase 3) — detects broken internal `.md` links,
    dead commands (`npm run X` / `make Y` quoted in docs but not declared
    in any manifest), vague TODOs ("clean up later", "investigate this",
    "tbd"), and conflicting agent-instruction files at the repo root.
    Each finding gets a `Classification` per `prompts/decisions.md`.
  - `stale_artifacts.py` (Phase 7) — candidate identification only; never
    mutates files. Honours the safety invariants: untracked files →
    `Needs verification` (never `Delete`); files referenced by basename
    from any doc → `Needs verification`. Auto-`Delete` only for tracked
    OS-droppings (`*.bak / *.tmp / .DS_Store`); `scratch.md` and
    `handoff-final-final.md` style droppings → `Archive`.
  - `verification.py` (Phase 8 Tier-1) — records read-only
    `path_exists` / `internal_link_resolves` / `command_declared` checks
    as typed `VerificationResult` rows. Tier-2 (command execution behind
    refuse-list) lands in PR #5.
- `tests/conftest.py` — fixture-builder helpers that init real git repos
  via `tmp_path` (no shared `.git/` state checked in): `build_clean_repo`,
  `build_drifted_repo`, `build_broken_links_repo`,
  `build_agents_and_claude_repo`, `build_monorepo`,
  `build_stale_artifacts_repo`.
- Per-phase test files: `test_phase_survey.py`, `test_phase_code_first.py`,
  `test_phase_drift_audit.py`, `test_phase_stale_artifacts.py`,
  `test_phase_verification.py`. 50 tests total across the suite, all
  hitting real `git init` + real `git ls-files` rather than mocks.

### Added (PR #2)
- Vendored skill body + 3 references (`phases.md`, `decisions.md`, `templates.md`) from
  `agent-skills/plugins/repo-documentation-governance/` @
  `2d4e2aac7677914bcd417cb752f1a7e9a4e72194` into `src/repo_doc_governance/prompts/`.
  All four files carry a `<!-- DO NOT EDIT — vendored from … @ <SHA>. Edit upstream + re-vendor. -->`
  header on line 1.
- `Makefile` with `re-vendor` target — clones agent-skills at a configurable ref
  (default master) and rewrites the four vendored files with a fresh SHA in the
  header. Guards against the "someone hand-edited a vendored file after vendoring"
  anti-pattern by comparing each destination's body (line 3 onward, skipping the
  DO-NOT-EDIT header) against the upstream content at the SHA recorded in the
  header. If any file has drifted, the target lists the drifted files and stops;
  bypass with `FORCE=1` if the local edits are intentional (and documented in
  CHANGELOG). Catches a class of silent overwrite that a header-presence check
  alone would miss — that fix lands in this PR per a codex review finding.
- Orchestrator skeleton: `Phase` IntEnum (1–9), `Task` str-Enum (six task types
  per SKILL.md triage table), `TASK_TO_PHASES` routing table, `RunState`
  Pydantic model with phase-output fields stubbed, sequential `run()` with
  per-phase exception isolation (defensive — one phase failing does not abort
  the rest), `summary()` for `--json` CLI output.
- Phase functions are stubs that `raise NotImplementedError` with a pointer
  to the build sequence in the design spec. Real implementations land in PR #3–#5.
- Tests (`tests/test_orchestrator.py`, 14 cases) covering task→phases routing,
  RunState defaults, run() exception-handling, summary() shape, and vendored
  prompt headers.

## [0.1.0-rc] — 2026-05-19

### Added
- Initial scaffold per
  [design spec](https://github.com/PatientVibes/ai-agents/blob/master/docs/superpowers/specs/2026-05-19-agent-harness-repo-doc-governance-design.md).
- `pyproject.toml` with three `agent-tool-*` deps pinned via `[tool.uv.sources]`
  to the SHAs currently used by `agent-harness-card-extractor` v0.2.1.
- `repo-doc-gov` CLI entry point (subcommands not yet implemented — PR #2+).
- Package skeleton at `src/repo_doc_governance/` with prompts/ placeholder for
  the PR #2 skill vendoring step.
- Pytest smoke tests asserting import, version, and CLI module wiring.
- MIT LICENSE under Chris Moore copyright.

### Pre-1.0 release notes
This is an RC (release-candidate) version. The harness is feature-incomplete
until PR #6 ships and the spec status flips to `implemented`. Until then,
no `run` / `audit` / `batch` subcommand actually does anything.
