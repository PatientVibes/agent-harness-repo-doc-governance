# agent-harness-repo-doc-governance

Portable LangChain harness for repo documentation cleanup + AI-agent instruction
consolidation. Ports the Claude Code `repo-documentation-governance` subagent
(at [`PatientVibes/agent-skills/plugins/repo-documentation-governance/`](https://github.com/PatientVibes/agent-skills/tree/master/plugins/repo-documentation-governance))
into a CLI / HTTP / batch-runnable form for CI, cron, webhooks, and unattended
sweeps. Outputs a Pull Request — does NOT merge. 12-component agent harness.

## Status: v0.1.0 — feature complete (6-PR build sequence shipped 2026-05-19)

All six PRs of the design-spec build sequence have landed:

- PR #1 — repo scaffold
- PR #2 — vendored prompts + orchestrator skeleton + `make re-vendor` / `verify-no-local-edits`
- PR #3 — deterministic phases (1, 2, 3, 7, 8 Tier-1)
- PR #4 — LLM phases (4 README, 5 agent-instruction consolidation, 6 HANDOFF) with injectable `LLMRunner`
- PR #5 — Phase 9 PR creation, Phase 8 Tier-2 opt-in execution, refuse-list, `PRCreator` interface, safety-invariant integration tests
- PR #6 — CLI subcommands (`run` / `audit` / `batch`), FastAPI HTTP routes, Claude Code subagent thin-wrapper update, catalog refresh

The design spec at
[`docs/superpowers/specs/2026-05-19-agent-harness-repo-doc-governance-design.md`](https://github.com/PatientVibes/ai-agents/blob/master/docs/superpowers/specs/2026-05-19-agent-harness-repo-doc-governance-design.md)
flipped from `draft` to `implemented` on the PR-#6 commit.

## What it does (when complete)

1. Survey a target repo's files, manifests, CI, docs, agent-instruction files
2. Build a code-first source-of-truth map (trust hierarchy: code > manifests > CI > docs)
3. Drift audit — broken links, dead commands, conflicting agent instructions, stale TODOs
4. Update README, consolidate AGENTS.md / CLAUDE.md / GEMINI.md / Copilot files, refresh HANDOFF
5. Identify stale artifacts; classify Keep / Update / Consolidate / Archive / Delete / Needs verification
6. Open a PR — never commits to main, never self-approves, never self-merges

Three runtime modes:

| Mode | CLI | HTTP | Output |
|---|---|---|---|
| `manual` | `repo-doc-gov run --repo PATH` | `POST /run` | PR opened against base branch |
| `audit` | `repo-doc-gov audit --repo PATH` | `POST /audit` | JSON drift report; no PR, no edits |
| `batch` | `repo-doc-gov batch --config repos.yaml` | n/a | One PR per repo, semaphore-bounded |

## Quick start (contributors)

For working ON the harness — clone, dev-install, run the suite:

```bash
uv pip install -e ".[dev]"
repo-doc-gov --version
pytest                          # default suite (unit + safety; skips integration)
pytest -m integration           # opt-in real-LLM tests (requires API key, see Environment variables)
```

Integration tests dispatch real LLM calls — they self-skip when no
`OPENROUTER_API_KEY` or `ANTHROPIC_API_KEY` is in the environment.
Typical cost is under $0.05 per run with Haiku 4.5.

For consuming the harness against your own repos, see [Usage](#usage) below.

## Usage

### 1. Install on a host

```bash
# Pinned tag (recommended — keeps audit output stable across runs)
uv tool install --from 'git+https://github.com/PatientVibes/agent-harness-repo-doc-governance.git@v0.1.6' agent-harness-repo-doc-governance

# Or track latest:
uv tool install --from 'git+https://github.com/PatientVibes/agent-harness-repo-doc-governance.git' agent-harness-repo-doc-governance

repo-doc-gov --version  # 0.1.6
```

### 2. Authentication

| Mode | Requires |
|---|---|
| `audit` | nothing — read-only, no LLM call, no PR |
| `run` (dry-run, no `--execute`) | an LLM key (`OPENROUTER_API_KEY` *or* `ANTHROPIC_API_KEY`) |
| `run --execute` / `batch --execute` | LLM key + `gh auth login` (interactive) *or* `GH_TOKEN` (unattended) |

LLM-route notes:

- `OPENROUTER_API_KEY` → default model `openrouter/google/gemini-2.5-pro`. Uses `langchain-openai` (already a hard dep).
- `ANTHROPIC_API_KEY` (no OpenRouter key set) → default model `anthropic:claude-sonnet-4-6`. **Requires `uv pip install langchain-anthropic`** — it's not a hard dep because OpenRouter covers Anthropic routes too. If you skip this install, the integration test self-skips and a real `run` will fail at `_make_llm()`.

### 3. Modes

**Audit** — read-only drift report, no LLM, fastest CI gate:

```bash
repo-doc-gov audit --repo /path/to/target --fail-on high
```

Exits non-zero when any finding at or above the named severity exists. `--fail-on` accepts `any | high | blocker | never`. Output is structured JSON on stdout.

**Run** — one repo, opens a PR via `gh`:

```bash
# Dry run: composes the PR body, doesn't touch git
repo-doc-gov run --repo /path/to/target --task full-pass

# Execute: branch + commit + push + gh pr create
repo-doc-gov run --repo /path/to/target --task full-pass --base-branch main --execute --trace /tmp/run.jsonl
```

Tasks: `full-pass` (default), `readme-only`, `todo-cleanup`, `agent-consolidation`, `drift-sweep`, `from-scratch`. Cost is typically \$0.10–\$2.50 per run depending on target size + model.

**Batch** — many repos, semaphore-bounded:

```bash
repo-doc-gov batch --config repos.yaml --concurrency 4 --execute
```

`repos.yaml`:

```yaml
repos:
  - path: /chorus/repos/agent-tool-llm-utils
    # Defaults: task=full-pass, base_branch=main
  - path: /chorus/repos/agent-harness-card-extractor
    task: drift-sweep
    base_branch: master
  - /chorus/repos/agent-tool-pdf-builder   # Bare string = full-pass against main
```

### 4. CI: audit-as-a-gate

Drop into a target repo's `.github/workflows/audit.yml` to gate merges on drift:

```yaml
name: docs audit
on:
  pull_request:
  push:
    branches: [main]
  workflow_dispatch:

permissions:
  contents: read

jobs:
  audit:
    runs-on: ubuntu-latest   # or [self-hosted, <your-label>]
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
        with:
          enable-cache: true
      - name: Install harness
        run: |
          uv tool install --from 'git+https://github.com/PatientVibes/agent-harness-repo-doc-governance.git@v0.1.6' agent-harness-repo-doc-governance
      - name: Run audit
        shell: bash
        run: |
          set -o pipefail
          repo-doc-gov audit --repo . --fail-on high --trace .audit-trace.jsonl | tee audit-report.json
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: audit-${{ github.run_id }}
          path: |
            audit-report.json
            .audit-trace.jsonl
          retention-days: 14
```

Pin to a release tag (`@v0.1.6`) so audit findings stay stable across CI runs. The harness self-policies on the same pattern — see [`.github/workflows/audit.yml`](.github/workflows/audit.yml) (self-hosted runner variant).

## Dependencies

Three PatientVibes tools are pulled from GitHub via `[tool.uv.sources]` in `pyproject.toml`:

| Package | Description | Pinned commit |
|---|---|---|
| `agent-tool-llm-utils` | retry / sanitize / extract-json / checkpoint helpers | `cfdf9aba` |
| `agent-tool-token-tracker` | Per-phase LangChain token-usage capture + cost rollup | `d16943fd` |
| `agent-tool-pipeline-trace` | JSONL structured event log per run | `54545a8c` |

`uv sync` resolves them automatically. The SHAs match those used by
`agent-harness-card-extractor` v0.2.1 at the time this repo was scaffolded.

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `OPENROUTER_API_KEY` *or* `ANTHROPIC_API_KEY` | Manual / batch modes | LLM provider key for Phases 4/5/6. The `ANTHROPIC_API_KEY` route additionally requires `uv pip install langchain-anthropic`. |
| `GH_TOKEN` | Unattended manual / batch modes | GitHub PR creation. Falls back to `gh auth status` for human-invoked runs. |

## 12-component harness implementation

| Component | Implementation |
|---|---|
| Orchestration | Plain Python sequential pipeline (`src/repo_doc_governance/orchestrator.py`) with Pydantic `RunState`; phase-skip list-filter from `task` parameter (`Task` enum → `TASK_TO_PHASES`). Per-phase exception isolation — one phase failing does NOT abort the rest. No custom LangGraph StateGraph; matches `agent-harness-card-extractor` precedent. |
| Tools | Git ops (`git ls-files`, `git status`, `git rev-parse`, `git ls-files --others --exclude-standard`, `git ls-files --error-unmatch`); manifest parsers (npm scripts, Makefile targets, `pyproject` scripts). PR creation via `gh` lands in PR #5. |
| Memory | Per-run `RunState` Pydantic model (`src/repo_doc_governance/state.py`) carrying typed `Inventory` / `CodeFirstMap` / `DriftFinding[]` / `StaleCandidate[]` / `VerificationResult[]` + per-phase diffs + PR body draft. No cross-run memory — each repo run is independent. Cross-process checkpoint saving (`agent_tool_llm_utils.save_checkpoint`) wires up in PR #4. |
| Context mgmt | Phase-scoped prompts. Phase 4 (README) gets inventory + code-first map + README-targeted drift findings. Phase 5 (agent-instructions) gets the list of existing agent files + manifests + conflicting-agent findings; the LLM is expected to use `read_file` to inspect each existing file rather than slurping all of them into the prompt. Phase 6 (HANDOFF) gets handoff-targeted drift findings + the list of existing handoff/TODO/ROADMAP files. |
| Prompt construction | Skill body + `phases.md` + `decisions.md` + `templates.md` vendored from `agent-skills/plugins/repo-documentation-governance/` at a pinned SHA into `src/repo_doc_governance/prompts/`. Every vendored file carries `<!-- DO NOT EDIT — vendored from … @ <SHA>. Edit upstream + re-vendor. -->` on line 1. Refresh via `make re-vendor`. |
| Output parsing | Pydantic models in `src/repo_doc_governance/models.py` — `Inventory`, `CodeFirstMap`, `DriftFinding`, `StaleCandidate`, `VerificationResult`. The `Classification` enum (`Keep / Update / Consolidate / Archive / Delete / Needs verification`) is the contract from `prompts/decisions.md`. |
| State | `RunState` Pydantic model is the in-process state; `phases_completed` / `phases_failed` / `started_at` / `completed_at` track execution metadata. Cross-process checkpoint-and-resume via `agent_tool_llm_utils.save_checkpoint` lands in PR #4. |
| Error handling | Per-phase exception isolation — `NotImplementedError` from a not-yet-landed phase is caught, recorded as a `PhaseFailure`, and the orchestrator continues. `agent_tool_llm_utils.retry_async` for LLM phases lands in PR #4. |
| Guardrails | `safety.py` — `BranchPolicyError` (never commit to main/master/base), `PathOutsideRepoError` (never write outside the target repo), `UntrackedFileError` (never delete an untracked file; `git ls-files --error-unmatch` at the delete step), `RefusedCommandError` (Tier-2 refuse-list covering destructive filesystem ops, package publishing, deployment commands, production DB ops, privileged container ops, curl-pipe-bash style execution, and sudo). All four are exercised by integration tests against real temp git repos. |
| Verification | Tier-1 read-only checks (PR #3) — `path_exists`, `internal_link_resolves`, `command_declared` recorded as typed `VerificationResult`. Tier-2 best-effort command execution behind the refuse-list (PR #5) — opt-in via `state.execute_tier2 = True`; off by default. Each command's manifest script body is inspected against the refuse-list BEFORE execution. |
| Subagent orchestration | `batch` mode (`repo-doc-gov batch --config repos.yaml --concurrency N`) runs `manual` mode against many repos in parallel via a `ThreadPoolExecutor`. Monorepo-as-many-packages is supported by listing each package as its own entry in the batch config. |
| Token tracking | `LLMRunner.run()` returns an `LLMRunResult` with `input_tokens` / `output_tokens` / `latency_s` / `model` / `tool_calls` populated from each LLM call. Phase-9 PR builder wires these into `agent_tool_token_tracker.TokenTracker` in PR #5. |

Cells flip from `*(PR #N)*` to a concrete description as each PR lands.

## Skill — single source of truth

The workflow rules (9 phases, classification criteria, canonical-agent-file
decision tree, safety invariants) live at
[`PatientVibes/agent-skills/plugins/repo-documentation-governance/`](https://github.com/PatientVibes/agent-skills/tree/master/plugins/repo-documentation-governance).
This repo vendors a copy at `src/repo_doc_governance/prompts/` (added in PR #2)
with a `DO NOT EDIT — vendored from …` header.

The vendored copy is refreshed via `make re-vendor` (added in PR #2). The
Makefile target refuses to overwrite if local edits exist, forcing an explicit
re-vendor commit. Drift between the two copies is a code-review red flag.

## Companion Claude Code subagent

After PR #6 ships, the existing Claude Code subagent at
[`agent-skills/plugins/repo-documentation-governance/agents/repo-documentation-governance.md`](https://github.com/PatientVibes/agent-skills/tree/master/plugins/repo-documentation-governance/agents)
becomes a thin wrapper that subprocess-calls this harness's CLI. Same dual-entry
pattern as `pr-review-tools` (skill / agent both wrap `agent-tool-pr-reviewer` CLI).

## Safety invariants

These are enforced in code AND verified by integration tests against temp git
repos (`tmp_path` pytest fixture):

- Never commit to `main` / `master` (`BranchPolicyError`)
- Never self-approve, never self-merge any PR
- Never edit files outside the target repo path (`PathOutsideRepoError`)
- Never execute scripts matching the Phase-8 refuse-list (destructive ops,
  credential access, deploy commands, `curl | bash`, package publishing,
  production DB ops, host-level service modification, broad delete)
- Never delete files not tracked by git (`git ls-files --error-unmatch` check)

## License

MIT. See `LICENSE`.

## Provenance

Designed and scaffolded 2026-05-19. See:
- Design spec: [`docs/superpowers/specs/2026-05-19-agent-harness-repo-doc-governance-design.md`](https://github.com/PatientVibes/ai-agents/blob/master/docs/superpowers/specs/2026-05-19-agent-harness-repo-doc-governance-design.md)
- Source skill: [`PatientVibes/agent-skills/plugins/repo-documentation-governance/`](https://github.com/PatientVibes/agent-skills/tree/master/plugins/repo-documentation-governance)
- Sibling harnesses: [`agent-harness-card-extractor`](https://github.com/PatientVibes/agent-harness-card-extractor) (sequential-pipeline precedent), [`agent-harness-chorus-csd-analyzer`](https://github.com/PatientVibes/agent-harness-chorus-csd-analyzer) (LangGraph + 12-component pattern)
