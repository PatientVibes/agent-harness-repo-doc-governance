# agent-harness-repo-doc-governance

Portable LangChain harness for repo documentation cleanup + AI-agent instruction
consolidation. Ports the Claude Code `repo-documentation-governance` subagent
(at [`PatientVibes/agent-skills/plugins/repo-documentation-governance/`](https://github.com/PatientVibes/agent-skills/tree/master/plugins/repo-documentation-governance))
into a CLI / HTTP / batch-runnable form for CI, cron, webhooks, and unattended
sweeps. Outputs a Pull Request — does NOT merge. 12-component agent harness.

## Status: v0.1.0-rc (scaffold only)

This is the PR-#1 scaffold. None of the workflow phases are implemented yet.
See the [design spec](https://github.com/PatientVibes/ai-agents/blob/master/docs/superpowers/specs/2026-05-19-agent-harness-repo-doc-governance-design.md)
for the 6-PR landing plan; status flips to `v0.1.0` when PR #6 lands.

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
| Tools | *(PR #3+)* Git ops (`git ls-files`, `git status`, `git blame`), file ops (Read / Write / Edit / Glob / Grep), classification rules, PR creation via `gh` |
| Memory | Per-run `RunState` Pydantic model (`src/repo_doc_governance/state.py`) carrying inventory, drift findings, stale-artifact candidates, verification results, per-phase diffs, PR body draft. No cross-run memory — each repo run is independent. Cross-process checkpoint saving (`agent_tool_llm_utils.save_checkpoint`) wires up in PR #3. |
| Context mgmt | *(PR #4)* Phase-scoped LLM context; only Phase 5 (agent-instruction consolidation) loads all AGENTS / CLAUDE / GEMINI / Copilot files together |
| Prompt construction | Skill body + `phases.md` + `decisions.md` + `templates.md` vendored from `agent-skills/plugins/repo-documentation-governance/` at a pinned SHA into `src/repo_doc_governance/prompts/`. Every vendored file carries `<!-- DO NOT EDIT — vendored from … @ <SHA>. Edit upstream + re-vendor. -->` on line 1. Refresh via `make re-vendor`. |
| Output parsing | *(PR #3+)* Pydantic models for inventory, findings, classifications, PR body |
| State | `RunState` Pydantic model is the in-process state; `phases_completed` / `phases_failed` / `started_at` / `completed_at` track execution metadata. Cross-process checkpoint-and-resume via `agent_tool_llm_utils.save_checkpoint` lands in PR #3. |
| Error handling | *(PR #3+)* `agent_tool_llm_utils.retry_async` with `not is_transient(...)` fatal classifier; per-phase exception isolation (one phase fails → mark and continue, PR notes the skip) |
| Guardrails | *(PR #5)* Input sanitization; refuse-list enforcement on Phase 8 Tier-2 command execution; `git ls-files --error-unmatch` check before delete |
| Verification | *(PR #4)* Tier-1 read-only (paths exist, links resolve, commands defined); Tier-2 best-effort command execution behind refuse-list; one retry per phase via the `verification-retry-loop` skill pattern |
| Subagent orchestration | *(PR #6)* Monorepo case spawns per-package mini-runs (semaphore-bounded); batch mode parallelizes across repos |
| Token tracking | *(PR #4)* `agent_tool_token_tracker.TokenTracker` records every LLM call source / phase / model / tokens / latency / cost |

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
