# agent-harness-repo-doc-governance

Portable LangChain harness for repo documentation cleanup + AI-agent instruction
consolidation. Ports the Claude Code `repo-documentation-governance` subagent
(at [`PatientVibes/agent-skills/plugins/repo-documentation-governance/`](https://github.com/PatientVibes/agent-skills/tree/master/plugins/repo-documentation-governance))
into a CLI / HTTP / batch-runnable form for CI, cron, webhooks, and unattended
sweeps. Outputs a Pull Request — does NOT merge. 12-component agent harness.

## Status: v0.1.0-rc (LLM phases landed in PR #4)

PRs #1–#4 have landed:
- PR #1 — repo scaffold
- PR #2 — vendored prompts + orchestrator skeleton + `make re-vendor` / `verify-no-local-edits`
- PR #3 — deterministic phases (1, 2, 3, 7, 8 Tier-1)
- PR #4 — LLM phases (4 README, 5 agent-instruction consolidation, 6 HANDOFF) with `create_react_agent` + repo-scoped file tools + injectable `LLMRunner` for tests

Remaining: PR #5 (PR creation + safety-invariant integration tests), PR #6
(modes + subagent wrapper + catalog refresh). Status flips to `v0.1.0` when
PR #6 lands. See the
[design spec](https://github.com/PatientVibes/ai-agents/blob/master/docs/superpowers/specs/2026-05-19-agent-harness-repo-doc-governance-design.md).

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

## Quick start

```bash
uv pip install -e ".[dev]"
repo-doc-gov --version
pytest
```

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
| `OPENROUTER_API_KEY` *or* `ANTHROPIC_API_KEY` | Manual / batch modes | LLM provider key for Phases 4/5/6. Fallback: `~/.config/repo-doc-gov/env` (mode 600), per the `config-env-loading` convention. |
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
| Guardrails | *(PR #5)* Refuse-list enforcement on Phase 8 Tier-2 command execution; `git ls-files --error-unmatch` check before delete (already in Phase 7 candidate classification — `Needs verification` rather than `Delete` for untracked files). |
| Verification | Tier-1 read-only checks landed in PR #3 — `path_exists`, `internal_link_resolves`, `command_declared` results recorded as typed `VerificationResult`. Tier-2 best-effort command execution behind refuse-list lands in PR #5. |
| Subagent orchestration | *(PR #6)* Monorepo case spawns per-package mini-runs (semaphore-bounded); batch mode parallelizes across repos |
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
- Design spec: [`D:/ai-agents/docs/superpowers/specs/2026-05-19-agent-harness-repo-doc-governance-design.md`](../ai-agents/docs/superpowers/specs/2026-05-19-agent-harness-repo-doc-governance-design.md)
- Source skill: [`PatientVibes/agent-skills/plugins/repo-documentation-governance/`](https://github.com/PatientVibes/agent-skills/tree/master/plugins/repo-documentation-governance)
- Sibling harnesses: [`agent-harness-card-extractor`](../agent-harness-card-extractor/) (sequential-pipeline precedent), [`agent-harness-chorus-csd-analyzer`](../agent-harness-chorus-csd-analyzer/) (LangGraph + 12-component pattern)
