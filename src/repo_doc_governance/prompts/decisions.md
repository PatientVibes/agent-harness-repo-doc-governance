<!-- DO NOT EDIT — vendored from agent-skills/plugins/repo-documentation-governance/agents/references/decisions.md @ 86bbeeaadda6eef66c9923dd15cd5ca819412eba. Edit upstream + re-vendor via "make re-vendor". -->

# Decision rules

Criteria for classifying each finding from the drift audit, plus the rationale behind the rules in `SKILL.md`. Load when classifying findings or when an edge case forces you to weigh trade-offs.

## Contents

- [Classification rules](#classification-rules)
- [Trust hierarchy rationale](#trust-hierarchy-rationale)
- [Canonical agent file rationale](#canonical-agent-file-rationale)
- [Anti-patterns to avoid](#anti-patterns-to-avoid)
- [Edge cases](#edge-cases)
- [Mode of operation](#mode-of-operation)

---

## Classification rules

When auditing existing documentation, classify each finding as one of: `Keep / Update / Consolidate / Archive / Delete / Needs verification`.

### Keep

Content is:

- Current
- Accurate
- Referenced from somewhere useful
- Specific
- Maintained
- Important for onboarding or operation

### Update

Content is:

- Mostly useful but partially stale
- Missing current commands
- Missing current paths
- Still relevant but poorly organized

### Consolidate

Content is:

- Repeated across several files
- Split between model-specific agent files when it should be in the canonical one
- Conflicting but clearly about the same topic
- Better represented in one canonical source

### Archive

Content is:

- Historical
- Potentially useful for context
- No longer current guidance
- Too detailed for README or canonical agent file
- Not safe to delete because the rationale for a past decision lives only here

Move to `docs/archive/`.

### Delete

Content is:

- Clearly temporary
- Clearly generated (and not the generator's source)
- Clearly duplicated
- Clearly obsolete
- Clearly misleading
- Not referenced from anywhere
- Not useful as historical context

Confirm with the Phase 7 checklist before deleting. Tracked files only; never delete untracked working-tree files without asking.

### Needs verification

Use when:

- The claim may be current but cannot be confirmed from code/config.
- It references external systems not visible in the repo.
- It describes a deployment process not represented in files.
- It conflicts with another document and code does not disambiguate.
- Removing it could cause loss of important context.

`Needs verification` items go in the PR summary for the human reviewer. Never silently delete or "fix" them.

---

## Trust hierarchy rationale

When two sources disagree, trust in this order:

1. Source code and runtime configuration
2. Build/test/package/deploy manifests
3. CI workflow files
4. Runtime entry points
5. README and maintained docs
6. Agent instruction files
7. Handoff/TODO/ROADMAP/planning notes
8. Older notes, drafts, and archives

The principle: **what runs is true; what is written about what runs may have drifted.** Documentation rots faster than code, agent files rot faster than READMEs (because they are read by agents that don't push back when they're wrong), and old planning notes rot fastest of all.

When layers 1–4 are themselves ambiguous (for example, the manifest references a script that doesn't exist on disk), mark the claim `Needs verification` rather than invent.

---

## Canonical agent file rationale

The choice between `AGENTS.md` and `CLAUDE.md` as canonical is one of the few decisions in this workflow that has lasting downstream effects on the repo. Default to `AGENTS.md` unless evidence pushes the other way.

**Why `AGENTS.md` is the default:**

- It is an open standard, donated to the Linux Foundation's Agentic AI Foundation in December 2025.
- It is the convention OpenAI Codex reads first; Cursor, OpenCode, Aider, and others read it. Claude Code also reads it.
- It is tool-neutral by construction. The repo does not subtly center one agent runtime.
- Future agents will not need to relitigate the choice if the file already exists with content.

**Signals the repo is Claude-first** (use `CLAUDE.md` as canonical):

- Heavy `.claude/**` infrastructure: project-level slash commands, hooks, settings.
- Explicit declaration in existing docs ("Claude-first", "primary agent: Claude Code").
- No evidence of other agent runtimes touching the repo (no `.codex/`, no `.cursor/`, no `agents` field in tool configs).
- Maintainer stated the preference explicitly.

**When ambiguous:** default to `AGENTS.md`. Leave a thin `CLAUDE.md` wrapper pointing to it so existing Claude-specific workflows keep working.

**Record the choice** in the PR summary. Future agents should not waste time re-deciding.

---

## Anti-patterns to avoid

These are the failure modes this skill exists to prevent.

- Rewriting every document for tone only — no content change, just churn.
- Creating many new docs without removing old ones.
- Keeping separate contradictory instructions for Claude, Gemini, Codex, and Copilot.
- Preserving stale TODOs because they "might matter."
- Deleting historical context without checking references.
- Deleting untracked files in the user's working tree.
- Adding new documentation tooling (linters, frameworks, generators) unless explicitly requested.
- Turning README into a full technical manual.
- Turning the canonical agent file into a giant prompt dump.
- Claiming commands were verified when they were only inspected.
- Making code changes under the cover of documentation cleanup.
- Hand-editing auto-generated documentation instead of fixing its source.
- Imposing a TODO format (checkboxes, owner-neutral phrasing) on a repo that already uses Linear IDs or `TODO(name):` markers.
- Hiding unresolved uncertainty by guessing instead of marking `Needs verification`.

---

## Edge cases

### Monorepo

- Walk each package as a mini-repo for Phases 1–4.
- Each package keeps its own README.
- Agent files live at the root unless a package overrides; nested `AGENTS.md` follows the spec's "closer overrides earlier" precedence (files closer to the working directory take priority).
- Resolve cross-package contradictions at the root, not in individual packages.

### No existing docs

- Phases 4–6 may *create* canonical files rather than just update them.
- Use the templates in `templates.md` verbatim.
- Mark anything you cannot verify as `Needs verification`.
- Do not invent architecture from naming conventions — confirm against source, config, route definitions, schemas, migrations, deployment files, or tests.

### Auto-generated documentation

- Never hand-edit. Identify the generator from build config (`swagger-jsdoc`, `typedoc`, `sphinx`, `mkdocs`, OpenAPI generators, etc.).
- Mark the file as generated in the inventory.
- Fix the source or generator config instead.
- If the generator is broken or removed, surface that in the PR — don't paper over it by writing static docs.

### Architecture doc over ~150 lines

- Split into subsystem files: `docs/ARCHITECTURE-{FRONTEND,BACKEND,DATABASE,API,DEPLOYMENT,AGENTS}.md`.
- Keep `docs/ARCHITECTURE.md` as a short index that links to subsystem files.
- Reason: future agents will over-summarize or misread a single large architecture file.

### Conflicting agent files with active contributors

- Do not delete a contradicting file silently. Active contributors may rely on it.
- Note the conflict in the PR summary and propose the resolution; let the human pick.

### Tracked file that looks stale but is referenced from CI

- Do not delete. CI may import or curl the file at build time.
- Mark `Needs verification` in the PR.

### File only referenced from a Git tag, release artifact, or external system

- Treat as `Keep` or `Archive`, not `Delete`.
- External consumers may break if the file moves.

---

## Mode of operation

This skill currently operates in manual / active-development mode: invoked by a human, produces a PR for human review.

Two related forward-looking modes exist as separate problems and should not bleed into this skill:

- **Read-only CI drift check** — reports broken links, dead commands, oversized architecture docs, duplicate agent instructions, vague stale TODOs. Reports only; never edits.
- **Scheduled autonomous PR creation** — opens a PR with proposed doc cleanup and `Needs verification` markers; never merges, never approves, never executes uninspected scripts.

If those become real, they belong in a sibling skill (`repo-documentation-drift-auditor`), not in this one. Keeping this skill focused on manual cleanup keeps its contract small and reviewable.
