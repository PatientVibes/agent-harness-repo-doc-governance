<!-- DO NOT EDIT — vendored from agent-skills/plugins/repo-documentation-governance/agents/references/templates.md @ 86bbeeaadda6eef66c9923dd15cd5ca819412eba. Edit upstream + re-vendor via "make re-vendor". -->

# Document templates

Templates referenced from `SKILL.md` and `phases.md`. Copy verbatim, then trim sections that do not apply. Mark anything you cannot verify as `Needs verification`.

## Contents

- [README.md template](#readmemd-template)
- [AGENTS.md (canonical) template](#agentsmd-canonical-template)
- [CLAUDE.md (canonical, Claude-first repos) template](#claudemd-canonical-claude-first-repos-template)
- [Thin-wrapper template (for non-canonical agent files)](#thin-wrapper-template-for-non-canonical-agent-files)
- [docs/HANDOFF.md template](#docshandoffmd-template)
- [docs/ARCHITECTURE.md index template](#docsarchitecturemd-index-template)
- [docs/TROUBLESHOOTING.md template](#docstroubleshootingmd-template)
- [PR description template](#pr-description-template)

---

## README.md template

```markdown
# Project Name

Brief description of what this repository does.

## Status

Current state of the project — active / maintenance / archived / experimental.

## Quick start

Commands to install, configure, run, and test.

## Prerequisites

Required runtime, tools, services, credentials, or environment setup.

## Configuration

Important environment variables, config files, secrets, and local setup notes.

## Common commands

Install, run, test, build, lint, format, generate, migrate, deploy.

## Repository structure

Short explanation of the major directories.

## Architecture overview

Concise overview. Link to `docs/ARCHITECTURE.md` for detail.

## Development workflow

How to make changes safely.

## Testing

How to run unit, integration, e2e, or manual tests.

## Deployment

How the project is packaged or deployed, if applicable.

## Troubleshooting

Common issues and fixes, or link to `docs/TROUBLESHOOTING.md`.

## Additional documentation

Links to deeper docs.
```

---

## AGENTS.md (canonical) template

```markdown
# Agent Instructions

Canonical instruction file for AI coding agents working in this repository (Codex, Claude Code, Gemini CLI, Cursor, Copilot, Aider, OpenCode, and others). Tool-specific overrides, if any, live in `CLAUDE.md`, `GEMINI.md`, or `.github/copilot-instructions.md` and point back to this file.

## Repository purpose

One paragraph: what this repo does, who maintains it, what it integrates with.

## Working rules

Non-negotiable rules for agents working in this repo.

- Do not commit to `main`. All changes go through PRs.
- Do not self-approve or self-merge.
- Do not change application behavior as part of documentation cleanup.
- Do not add dependencies without explicit approval.
- Add anything else this repo enforces.

## Scope discipline

How to avoid unnecessary refactoring while working in this repo.

## Build and test commands

Verified commands. Update only after running them.

```bash
# install
<command>

# build
<command>

# test
<command>

# lint
<command>
```

## Documentation rules

How to update docs in this repo. See `docs/HANDOFF.md` for the current state and known issues.

## Code style

Only durable, repo-specific style rules. Do not duplicate language defaults.

## Architecture notes

Short, current architecture guidance. Link to `docs/ARCHITECTURE.md` for detail.

## Known pitfalls

Issues agents commonly get wrong in this repo.

## Handoff expectations

What to report after making changes — PR format, verification commands run, items needing human verification.
```

---

## CLAUDE.md (canonical, Claude-first repos) template

Use the AGENTS.md template above as the body. Adjust the opening paragraph:

```markdown
# Claude Instructions

Canonical instruction file for Claude Code working in this repository. This repo is intentionally Claude-first — it uses `.claude/**` infrastructure, Claude-specific slash commands, and hooks. Other agent files (`AGENTS.md`, `GEMINI.md`, `.github/copilot-instructions.md`) are thin compatibility wrappers that point here.
```

The rest matches the AGENTS.md template.

---

## Thin-wrapper template (for non-canonical agent files)

When `AGENTS.md` is canonical and `CLAUDE.md` is a wrapper:

```markdown
# Claude Instructions

Use `AGENTS.md` as the canonical repository instruction file. Everything in `AGENTS.md` applies to Claude Code.

Claude-specific notes:

- Follow the repository's documented verification commands before final handoff.
- [Add any Claude-only behavior here — for example, slash commands or hooks the repo expects Claude to use.]
```

When `CLAUDE.md` is canonical and `AGENTS.md` is a wrapper:

```markdown
# Agent Instructions

Use `CLAUDE.md` as the canonical repository instruction file. Everything in `CLAUDE.md` applies to all agents.

This repository is intentionally Claude-first, but the operating rules, build commands, and constraints in `CLAUDE.md` apply equally to Codex, Gemini CLI, Cursor, Aider, OpenCode, and any other agent runtime.
```

Symmetric `GEMINI.md` and `.github/copilot-instructions.md` wrappers follow the same shape.

---

## docs/HANDOFF.md template

```markdown
# Handoff

## Current status

One paragraph summary of the repository's current state.

## Recently completed

What has recently changed, with PR or commit references when useful.

## Known issues

Current known problems, with reproduction steps where applicable.

## Next recommended tasks

Specific, actionable next steps, with file paths.

- [ ] Update `path/to/file`: specific action and expected outcome.
- [ ] Verify whether `X` is still required before removing `Y`.

## Verification commands

Commands future agents or maintainers should run before declaring work done.

```bash
<command>
<command>
```

## Open questions

Items that need human confirmation before further work proceeds.
```

---

## docs/ARCHITECTURE.md index template

Use this when the architecture description fits in one file. If it grows past ~150 lines, split into subsystem files (see SKILL.md "Preferred structure") and convert this file into a pure index.

```markdown
# Architecture

## Overview

One or two paragraphs: what the system does, how the major pieces fit together.

## Components

- **Component A** — purpose, where it lives, owner.
- **Component B** — purpose, where it lives, owner.

## Data flow

Short description or diagram of how requests / data move through the system.

## External dependencies

Services, APIs, queues, databases the system depends on.

## Subsystem details

If split into subsystem files, list and link them here.

- [`ARCHITECTURE-FRONTEND.md`](ARCHITECTURE-FRONTEND.md)
- [`ARCHITECTURE-BACKEND.md`](ARCHITECTURE-BACKEND.md)
- [`ARCHITECTURE-DATABASE.md`](ARCHITECTURE-DATABASE.md)
- [`ARCHITECTURE-API.md`](ARCHITECTURE-API.md)
- [`ARCHITECTURE-DEPLOYMENT.md`](ARCHITECTURE-DEPLOYMENT.md)

## Open questions

Architectural decisions that are still unresolved.
```

For each subsystem doc, cover: ownership boundary, entry points, data flow, external dependencies, configuration files, known constraints, verification commands, open questions.

---

## docs/TROUBLESHOOTING.md template

```markdown
# Troubleshooting

## Symptom: <short description>

**Cause:** <root cause>

**Fix:**

```bash
<commands or steps>
```

## Symptom: <another>

...
```

Keep entries action-oriented. Each entry should be reproducible from the symptom description alone.

---

## PR description template

```markdown
# Summary

One paragraph: what this PR changes and why.

# Changes

## Updated

- `README.md`: updated setup, usage, repo structure, and current project status.
- `AGENTS.md`: consolidated canonical agent instructions.
- `docs/HANDOFF.md`: refreshed current status, known issues, and next tasks.

## Added

- `docs/ARCHITECTURE-DATABASE.md`: split database architecture notes from the main architecture overview.

## Moved / archived

- `old-handoff.md` → `docs/archive/old-handoff.md`

## Removed

- `scratch-notes.md`: removed stale temporary notes no longer referenced.

# Source of truth

- Human onboarding: `README.md`
- Agent instructions: `AGENTS.md` (canonical) — `CLAUDE.md`, `GEMINI.md`, `.github/copilot-instructions.md` are thin wrappers.
- Current work state: `docs/HANDOFF.md`
- Architecture index: `docs/ARCHITECTURE.md`

# Verification

## Commands inspected before execution

- `package.json`
- `.github/workflows/ci.yml`

## Commands run

```bash
git status --short
git diff --stat
npm test
```

## Results

- `git status --short`: completed
- `git diff --stat`: completed
- `npm test`: passed

# Not run

- `npm run deploy`: not run because deployment is outside documentation cleanup scope.

# Needs verification

- Confirm whether `docs/legacy-api-notes.md` is still required.
- Confirm whether `AGENTS.md` is the right canonical choice for this repo, or whether `CLAUDE.md` should be canonical instead.

# Governance note

This PR requires human review. An AI agent must not self-approve, self-merge, or bypass branch protection.
```
