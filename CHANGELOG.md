# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.6] — 2026-05-20

### Added (Phase 3: deterministic env-var coverage audit)

The v0.1.4 dogfood against `agent-harness-card-extractor` showed the
LLM Phase 4 pass finding 6 of 8 missing env-var rows but silently
dropping `ENABLE_AUDIT` / `ENABLE_PREPROCESSING`. "Env var referenced
in code but absent from README" is deterministic; Phase 3 now
produces these findings so Phase 4 only has to render the row, not
discover it. Closes #34 (PR #37).

- New `_audit_undocumented_env_vars(state)` walks `git ls-files`-
  tracked `.py` files and matches three Python read patterns:
  `os.environ.get`, `os.getenv`, and `os.environ['X']` excluding
  writes (negative lookahead on `=`).
- Documented-name extractor matches all-caps tokens (≥4 chars) inside
  backticks in the README — the documented convention.
- New `env_var_undocumented` finding kind at `Severity.MEDIUM` +
  `Classification.UPDATE`, pointed at the README.
- FP guards: secret-name suffixes (`_KEY` / `_TOKEN` / `_SECRET` /
  `_PASSWORD` / `_PASSPHRASE` / `_CREDENTIAL[S]` / `_API_KEY` /
  `_ACCESS_KEY` / `_PRIVATE_KEY`) are suppressed — these typically
  live in README prose, not the env-var table.
- Scope: Python first. JS (`process.env.X`), Rust (`std::env::var`),
  Go (`os.Getenv`) can land under the same shape in follow-ups.

### Test count

144 tests + 1 opt-in `-m integration` test. Was 140 in v0.1.5.

## [0.1.5] — 2026-05-20

### Fixed (Phase 9 stale-branch edge case: HEAD on the stale branch)

The v0.1.3 stale-branch fix (PR #23, closing #15) handles the case
where a stale local feature branch from a prior failed run blocks
the next `git checkout -b`. It force-deletes via `git branch -D`.

But `git branch -D` refuses to delete the current HEAD. Surfaced in
the v0.1.4 dogfood retry against `agent-harness-card-extractor`:
the previous run left HEAD on the feature branch, `gh pr close
--delete-branch` cleaned only the remote, and the next run errored
at `git branch -D` with `CalledProcessError` exit 1. Closes #32
(PR #35).

- `_delete_stale_local_branch_if_present` now takes `base_branch`.
  When HEAD is on the stale branch, it runs `git checkout <base>`
  first via the new `_git_current_branch` helper. The next step
  would `checkout -b` off `<base>` anyway — matches natural flow.

### Test count

140 tests + 1 opt-in `-m integration` test. Was 139 in v0.1.4.

## [0.1.4] — 2026-05-20

Two bugs surfaced by the v0.1.3 real-LLM dogfood against
`agent-harness-card-extractor` (closed PR
`PatientVibes/agent-harness-card-extractor#2`). Cost of that one run
was \$2.47 with Sonnet 4.6 — both fixes are required to make the
harness production-usable against any plan-doc-heavy target.

### Fixed (LLM preamble leakage defeated Phase 9 no-change short-circuit)

Sonnet 4.6 emits chain-of-thought / meta-commentary prose ABOVE the
first H1 of every LLM phase output, in violation of the explicit
"Output raw markdown only" hard rule. Examples from the closed
dogfood PR:

- `README.md` (Phase 4): `No drift was flagged and the repo contents
  confirm all existing README content is accurate. The README is
  output verbatim.`
- `AGENTS.md` (Phase 5): `Now I have a thorough understanding of the
  repo. The manifests declare no runnable commands directly...`
- `docs/HANDOFF.md` (Phase 6): `Now I have a thorough understanding
  of the repository. Let me write the HANDOFF file.`

The Phase 9 no-change short-circuit (shipped in v0.1.2) was defeated
because the preamble creates a diff against the existing file —
v0.1.3 shipped "preamble added" PRs for what should have been
no-ops. Gemini 2.5 Pro did not produce this in the v0.1.2 dogfood;
model-family-specific behavior. Closes #27 (PR #29).

- **New `phase_impls/_llm_output.py::strip_llm_preamble`** — finds
  the first `# ` H1 in the model output and drops everything before
  it. No-op when output is already clean; returns the input
  unchanged when no H1 is present (so an operator can still
  inspect). Trailing-newline-preserving.
- Called from Phases 4, 5, and 6 immediately after `result.text.strip()`.

### Fixed (Phase 6 input bloat from inlining aspirational plan/spec docs)

v0.1.3 PR #21 added "inline every handoff/TODO/ROADMAP file" to the
Phase 6 prompt. The dogfood target's big aspirational plan docs
under `docs/superpowers/plans/` (one was 1,319 lines) were classified
as handoff content by the survey and inlined verbatim — **728,634
input tokens** for a single Phase 6 call, **\$2.18 cost** (25×
regression vs v0.1.2's ~\$0.10 on pdf-builder). Closes #28 (PR #30).

- **Phase 6 now filters `inv.handoff_files` through
  `drift_audit.is_aspirational_doc(...)`** — the same classifier
  Phase 3 already uses to demote drift findings in plan/spec dirs.
  Plan / spec / design / proposal / RFC docs are excluded from the
  Phase 6 prompt's "CURRENT HANDOFF / TODO / ROADMAP FILES" inlined
  section AND the `handoff_findings` list.
- The long-term cleaner shape — classify plan/spec docs at survey
  time so they're never in `inv.handoff_files` — is deferred. This
  patch is the minimum-viable cost gate.

### Test count

127 tests + 1 opt-in `-m integration` test (which now passes against
Haiku 4.5 with both fixes in place). Was 125 in v0.1.3.

## [0.1.3] — 2026-05-20

### Added (Phase 5 + Phase 6 prompt tightening — same anti-pattern as Phase 4 pre-v0.1.2)

Phases 5 and 6 previously pushed the LLM to fetch existing files via a
`read_file` tool. That design was never validated against a real LLM,
and the Phase 4 v0.1.2 fix is strong evidence that inlining the current
content directly in the prompt is the more robust pattern. The same fix
now applies to Phase 5 (agent instructions) and Phase 6 (handoff / TODO
/ ROADMAP). Closes #12 (PR #21).

- **Phase 5 user prompt now includes the body of every existing
  agent-instruction file** under a "CURRENT AGENT-INSTRUCTION FILES
  (preserve all content unless flagged as drift)" header. Includes
  every `AGENT_INSTRUCTIONS` / `COPILOT_INSTRUCTIONS` file from the
  inventory (so `.github/copilot-instructions.md` and other nested
  locations are read, not just root-level files).
- **Phase 6 user prompt now includes the body of every existing
  HANDOFF / TODO / ROADMAP file** under a "CURRENT HANDOFF / TODO /
  ROADMAP FILES" header with an explicit per-TODO decision contract
  (kept / rewritten / completed / archived / deleted / `Needs
  verification`).
- **Phase 5 and Phase 6 system prompts rewritten to mirror Phase 4's
  seven hard rules** where applicable: preserve-existing-content
  (unless drift-flagged), no-title-renames, omit-empty-sections,
  manifest-faithful commands, cross-repo references are content,
  `Needs verification` items survive, raw markdown output only.

### Added (Phase 4 preserve-edit path real-LLM integration test)

Closes the dogfood loop opened by v0.1.2 — that release validated the
no-drift path (LLM returns byte-identical content, Phase 9 short-
circuits); this one validates the **preserve-while-editing** path.
Closes #13 (PR #22).

- **New opt-in integration test** at
  `tests/test_phase4_preserve_edit_integration.py` runs Phase 4
  against the existing `build_drifted_repo` fixture (1 dead `npm`
  command + 1 broken link + valid `npm install` content) with a real
  LLM (Anthropic Haiku 4.5 via direct or OpenRouter route).
- Asserts the title is preserved verbatim, valid content survives,
  drift is removed, and the LLM does not invent `Needs verification`
  filler sections.
- Gated by `@pytest.mark.integration` + skipif on key availability
  (and `langchain_anthropic` importability for the Anthropic-direct
  route). Cost < $0.05 per run with Haiku 4.5.
- README "Quick start" updated with the `pytest -m integration`
  invocation + one-line cost note.

### Fixed (Phase 9 stale-local-branch recovery)

Phase 9 failures between `git checkout -b` and `gh pr create` left a
stale local feature branch, causing the next run's `git checkout -b`
to exit 128. Hit twice during the v0.1.2 real-LLM dogfood and
required manual `git branch -D` to recover. Closes #15 (PR #23).

- **New `_delete_stale_local_branch_if_present` helper** detects the
  stale branch via `git rev-parse --verify --quiet refs/heads/<name>`
  and force-deletes via `git branch -D` before `git checkout -b`.
- Cleanup is visible to the operator: a one-line stderr warning plus
  a `phase9_stale_branch_deleted` trace event when tracing is on.

### Fixed (refuse-list documentation false positives)

Phase 3 was flagging `npm publish` (and similar) as a high-severity
`dead_command` whenever it appeared in refuse-list / blocklist
documentation context — e.g. ``Tier-2 refuse-list — `npm publish`,
`kubectl apply` ``. Surfaced on the harness's own README during the
first audit-workflow run (v0.1.1 retro). Closes #14 (PR #24).

- **New `_line_is_refuse_list_documentation(line)` helper** (case-
  insensitive, word-boundary regex on `refuse|refused|refuses|refuse-list
  |blocked|blocklist|denylist|rejected|forbidden|disallowed`). Same
  shape as the existing `is_aspirational_doc` path.
- When context matches, records a `dead_command_in_refuse_list_documentation`
  finding at `Severity.INFO` + `Classification.KEEP` — transparency
  in the audit without triggering Phase 4 to "fix" it.

### Fixed (circular import surfaced by isolated test-file runs)

`pytest tests/test_safety_invariants.py` (or any standalone test-file
invocation) failed at collection with `ImportError: cannot import name
'RunState' from partially initialized module 'repo_doc_governance.state'`.
Full-suite runs masked it because earlier files pre-populated
`sys.modules`. Closes #16 (PR #25).

- **`phase_impls/__init__.py` no longer eagerly imports phase modules.**
  `phases.py:_build_dispatch()` (which already does the lazy imports)
  is now the sole entry point and the cycle breaks. Per the issue's
  recommended option (1).
- New `tests/test_imports.py` with 3 subprocess-based regression gates
  so the fix can't be silently undone:
  `test_safety_module_imports_in_isolation`,
  `test_safety_invariants_test_file_imports_in_isolation`,
  `test_phase_impls_init_does_not_eagerly_load_phase_modules`.

### Test count

125 tests + 1 opt-in `-m integration` test (skips by default).
Was 117 in v0.1.2.

## [0.1.2] — 2026-05-20

### Added (Phase 4 prompt tightening + Phase 9 no-change handling)

First real-LLM end-to-end run (Gemini 2.5 Pro via OpenRouter against
`agent-tool-pdf-builder`) surfaced both fixes.

- **Phase 4 user prompt now includes the current README content
  verbatim** under a "CURRENT README CONTENT (preserve all of this
  unless flagged as drift)" header. Without this the LLM was asked to
  "update" a doc it had never seen and fell back to writing from the
  template skeleton — the "rewriting for tone only" anti-pattern that
  `prompts/decisions.md` warns against.
- **Phase 4 system prompt rewritten with seven explicit hard rules**:
  preserve-existing-content (unless drift-flagged), no-title-renames,
  omit-empty-sections (no `Needs verification` filler), manifest-
  faithful commands (no inventing `pip install` for `uv` projects),
  cross-repo references are content (not boilerplate), `Needs
  verification` items survive as `Needs verification` items, raw
  markdown output only.
- **Phase 9 no-change short-circuit**: when the LLM proposes content
  byte-identical to disk (the correct behavior when there's no drift
  to fix), Phase 9 detects an empty index and returns with `pr_url=None`
  instead of failing on `git commit`. `state.pr_branch_name` is still
  recorded for inspection. Verified against pdf-builder: the prior
  `--execute` run crashed at `git commit`; same input now exits cleanly
  with no PR opened.
- Tests: `test_readme_phase_includes_current_readme_content` gates the
  load-bearing user-prompt fix; `test_phase9_no_change_short_circuits_cleanly`
  exercises the Phase 9 no-change path end-to-end against a tmp_path
  git repo. 117 tests total.

## [0.1.1] — 2026-05-20

### Added (CI gate rollout)
- `.github/workflows/audit.yml` and `.github/workflows/pytest.yml` —
  self-policing CI on this repo. Audit gates merges on High/Blocker
  drift findings; pytest gates on the test suite. Both run on a
  repo-scoped self-hosted runner on `gh-runner.mshome.net` (labels
  `[self-hosted, repo-doc-gov]`). Audit mode is read-only and never
  invokes an LLM, so no API key required in CI.
- Documents the rollout pattern for replicating the audit gate to
  sibling repos (`uv tool install agent-harness-repo-doc-governance @
  git+...@v0.1.1`).

### Changed (v0.1.x follow-up — token tracker + pipeline trace wiring)
- `RunState` now carries a `token_tracker: TokenTracker` (always
  present, accumulator-style — see `agent-tool-token-tracker`) and an
  optional `pipeline_trace: PipelineTrace` (instantiated by the
  orchestrator iff `state.trace_path` is set — see
  `agent-tool-pipeline-trace`).
- The orchestrator emits `pipeline_start`, per-phase
  `phase_start` / `phase_end`, `pipeline_end`, and `error` events into
  the trace file when configured. LLM phases (4, 5, 6) emit an
  `llm_call` event and record token usage on the tracker via
  `phase_impls/_observability.record_llm_call`.
- `summary(state)` now includes `token_usage` (per-source totals).
- CLI: `run` and `audit` both gained `--trace PATH` to write a JSONL
  pipeline trace alongside the run.
- **Bug fix:** `README_ONLY` task now includes Phase 1 (Survey).
  Without it, Phase 4 (README) bailed early on `state.inventory is None`.

### Changed (v0.1.x follow-up — drift-audit FP suppression)
- Phase 3 (drift audit) now demotes `dead_command` findings inside
  plan / spec / design / proposal / RFC docs to
  `dead_command_in_aspirational_doc` with severity `Low` and
  classification `Needs verification` (was severity `High` /
  `Update`). The aspirational-doc path set:
  `docs/superpowers/plans/**`, `docs/superpowers/specs/**`,
  `docs/plans/**`, `docs/specs/**`, `docs/design/**`,
  `docs/proposals/**`, `docs/rfcs/**`.
- **Code-fence stripping.** Phase 3 link/command audit now skips any
  line that lies inside a ` ``` ` fenced code block. Authors routinely
  embed markdown EXAMPLES inside code fences (e.g. "paste this row into
  the README table") — those `[text](target)` patterns are
  demonstrations, not real links. Same fence-tracker prevents
  false-positive dead-command flags from inside ``` shell blocks too.
- **Template placeholder skip.** Links whose target contains `${...}`
  (Astro / shell-interp) or `{{...}}` (Mustache / Handlebars) are
  template fragments by definition, not real paths — skipped.
- **Why:** dogfood pass against the sibling repos surfaced both FP
  classes. The plan-doc demotion came from
  `agent-harness-card-extractor`'s `docs/superpowers/plans/*-frontend.md`
  references to `npm run dev` for a planned-but-unshipped frontend.
  The code-fence / template-placeholder skips came from auditing
  `ai-agents`, which (pre-fix) flagged 27 "broken internal links"
  almost all of which were inside ```markdown blocks documenting
  what to paste into OTHER files. Post-fix, the same audit returns
  zero false-positive broken links.

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
