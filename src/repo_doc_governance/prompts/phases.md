<!-- DO NOT EDIT — vendored from agent-skills/plugins/repo-documentation-governance/agents/references/phases.md @ 2d4e2aac7677914bcd417cb752f1a7e9a4e72194. Edit upstream + re-vendor via "make re-vendor". -->

# Phase reference

Detailed checklists for the nine phases summarized in `SKILL.md`. Load this when you reach a phase that needs more than the SKILL.md summary.

## Contents

- [Phase 1 — Survey](#phase-1--survey)
- [Phase 2 — Code-first source-of-truth detection](#phase-2--code-first-source-of-truth-detection)
- [Phase 3 — Drift audit](#phase-3--drift-audit)
- [Phase 4 — README update](#phase-4--readme-update)
- [Phase 5 — Agent instruction consolidation](#phase-5--agent-instruction-consolidation)
- [Phase 6 — Handoff / TODO / ROADMAP cleanup](#phase-6--handoff--todo--roadmap-cleanup)
- [Phase 7 — Stale artifact cleanup](#phase-7--stale-artifact-cleanup)
- [Phase 8 — Safe verification](#phase-8--safe-verification)
- [Phase 9 — PR-format handoff](#phase-9--pr-format-handoff)

---

## Phase 1 — Survey

Inventory what is actually in the repo, *from the filesystem and from git*, not from prose docs (which may be stale).

**Identify:**

- Primary language or framework
- Package manager and lockfile
- Build system
- Test framework
- Runtime / deployment model
- Main entry points
- Major directories
- Existing documentation files
- Agent instruction files
- Handoff / TODO / ROADMAP / planning files
- Generated outputs
- Temporary files
- Obvious stale artifacts
- Current branch and working-tree state

**Files to look for:**

```text
package.json   pnpm-lock.yaml   yarn.lock   package-lock.json
pyproject.toml   requirements.txt   Pipfile   poetry.lock
Cargo.toml   go.mod   pom.xml   build.gradle   settings.gradle
Makefile   Taskfile.yml   justfile
Dockerfile   docker-compose.yml   compose.yml
.github/workflows/**   .gitlab-ci.yml   .circleci/**
README.md   AGENTS.md   CLAUDE.md   GEMINI.md
.github/copilot-instructions.md   .github/instructions/**
.claude/**   .agents/**
HANDOFF.md   docs/HANDOFF.md   TODO.md   ROADMAP.md
docs/**   notes/**   planning/**   architecture/**
```

**Useful inventory commands:**

```bash
git ls-files | wc -l
git ls-files | head -50
git log --oneline -20
git status --short
find . -maxdepth 3 -type f -not -path './node_modules/*' -not -path './.git/*' -not -path './target/*' -not -path './dist/*' | sort
```

Build an internal inventory before editing. Note which files are tracked, which are untracked, and which are referenced elsewhere.

---

## Phase 2 — Code-first source-of-truth detection

Before reading README, HANDOFF, or existing agent files, inspect runtime and configuration sources. Build the repo map from code; *then* compare existing docs against it.

**Read first:**

- Package manifests (versions, scripts, dependencies)
- Build files
- Runtime entry points (`main.*`, `app/`, `src/index.*`, `cmd/**`)
- Docker / compose files
- Environment examples (`.env.example`, `.env.sample`)
- Test configuration
- CI workflow files
- API route definitions
- Database migration / configuration files
- Framework-specific config (`next.config.*`, `vite.config.*`, `tsconfig.json`, etc.)

**Trust hierarchy (full):**

1. Actual source code and runtime configuration
2. Build/test/package/deploy manifests
3. CI workflow files
4. Runtime entry points
5. README and maintained docs
6. Agent instruction files
7. Handoff/TODO/ROADMAP/planning notes
8. Older notes, drafts, and archives

If docs conflict with code or configuration, trust the code. If code/configuration is itself ambiguous, mark the claim `Needs verification` — do not guess.

---

## Phase 3 — Drift audit

Compare documentation against the actual repository.

**Look for:**

- Commands that no longer work (referenced in docs but not in `package.json` / `Makefile` / etc.)
- Scripts that no longer exist
- File paths that no longer exist
- Old project names
- Removed services
- Deprecated environment variables
- Outdated architecture descriptions
- Duplicate setup instructions
- Conflicting agent instructions across `AGENTS.md` / `CLAUDE.md` / `GEMINI.md` / Copilot files
- Completed TODOs that were never marked done
- Vague or unactionable TODOs
- References to removed branches
- References to removed dependencies
- References to generated files as if they were source files
- Stale screenshots or reports
- Old migration plans no longer relevant
- "Temporary" notes that became permanent clutter

**Internal-link audit (always run):**

```bash
# Find all .md links in docs and verify each target resolves
grep -rEn '\]\([^)]+\.md[^)]*\)' README.md docs/ AGENTS.md CLAUDE.md GEMINI.md 2>/dev/null \
  | while IFS=: read -r file line content; do
      link=$(echo "$content" | grep -oE '\]\([^)]+\.md[^)]*\)' | head -1 | sed 's/^](//;s/)$//;s/#.*//')
      [ -n "$link" ] || continue
      case "$link" in
        http*|//*) continue ;;
      esac
      dir=$(dirname "$file")
      target="$dir/$link"
      [ -f "$target" ] || echo "BROKEN: $file:$line → $link"
    done
```

**Command-existence audit:** for every command quoted in docs (`npm run X`, `make Y`, `python scripts/Z.py`), verify it exists in the corresponding manifest. If not, classify `Update` or `Needs verification`.

**Classify each finding:** `Keep / Update / Consolidate / Archive / Delete / Needs verification`. Criteria in `decisions.md`.

---

## Phase 4 — README update

Make `README.md` accurate and practical. Include only the sections that apply. Full template in `templates.md`.

**Section guide (use what fits, drop the rest):**

- **Project name + brief description** — what this repo does, one paragraph
- **Status** — current state of the project
- **Quick start** — install, configure, run, test
- **Prerequisites** — required runtime, tools, services, credentials
- **Configuration** — important env vars, config files, secrets, local setup
- **Common commands** — install, run, test, build, lint, format, generate, migrate, deploy
- **Repository structure** — short explanation of major directories
- **Architecture overview** — concise; link to `docs/ARCHITECTURE.md` for detail
- **Development workflow** — how to make changes safely
- **Testing** — how to run unit / integration / e2e tests
- **Deployment** — how the project is packaged or deployed, if applicable
- **Troubleshooting** — common issues; link to `docs/TROUBLESHOOTING.md`
- **Additional documentation** — links to deeper docs

**README rules:**

- Verify every command against the actual repo before writing it down.
- Prefer copy/paste-ready commands.
- Note assumptions explicitly.
- Do not claim tests pass unless they were run in Phase 8.
- Do not duplicate long content from deeper docs — link instead.
- Do not turn README into an architecture encyclopedia.

---

## Phase 5 — Agent instruction consolidation

Pick one canonical file (see SKILL.md "Canonical agent instruction file"). Reduce the rest to thin wrappers.

**Canonical file should include:**

- Repository purpose (one paragraph)
- Working rules (non-negotiables for agents)
- Scope discipline (how to avoid unnecessary refactoring)
- Build and test commands (verified)
- Documentation rules (how to update docs)
- Code style (only durable, repo-specific rules)
- Architecture notes (short, current)
- Known pitfalls (issues agents commonly get wrong)
- Handoff expectations (what to report after changes)

**Remove from agent files:**

- Duplicated instructions
- Model-specific motivational pep-talk
- Outdated project assumptions
- Contradictory rules across files
- Overly broad instructions
- Speculative roadmap content
- Old task-specific prompts
- Long context dumps that belong in `docs/`
- Instructions that encourage unnecessary rewrites
- Instructions that conflict with current repo structure

**Keep:**

- Specific commands
- Safety constraints
- Known repo pitfalls
- Required verification steps
- Current architecture boundaries
- Tool-specific notes (only where genuinely needed)

Wrapper template in `templates.md`.

---

## Phase 6 — Handoff / TODO / ROADMAP cleanup

For each item, decide one of: keep, rewrite, mark complete, archive, delete, `Needs verification`.

**TODO rules:**

- Avoid vague items like "clean up later" or "investigate this."
- Prefer specific, actionable items with file paths.
- Mark completed TODOs done; do not silently leave them.
- Do not maintain a large speculative backlog unless requested.
- Distinguish *current work* from *future ideas* (different files or sections).
- Defer to existing repo conventions — Linear/Jira IDs, `TODO(name):` markers, plain-text task lists. Do not impose a checkbox style if the project uses something else.

**Default TODO format (when no existing convention applies):**

```markdown
- [ ] Update `path/to/file`: specific action and expected outcome.
- [ ] Verify whether `X` is still required before removing `Y`.
- [ ] Replace stale reference to `old-command` after confirming the new workflow.
```

**`docs/HANDOFF.md` structure** — full template in `templates.md`. Sections: current status, recently completed, known issues, next recommended tasks, verification commands, open questions.

---

## Phase 7 — Stale artifact cleanup

**Common stale artifacts:**

```text
*.bak  *.tmp  *.old  *.orig  *.rej
.DS_Store  Thumbs.db
scratch.md  notes-old.md
old-handoff.md  handoff-final-final.md  handoff-v2-FINAL.md
generated-report.md  test-output.txt
coverage dumps
temporary exports
obsolete prompt files
duplicated planning docs
stale screenshots
```

**Before deleting, confirm all of:**

1. Not referenced from README, docs, scripts, config, or CI (`grep -rn '<filename>' .`).
2. Not auto-generated by a known tool (check build config; if generated, fix the generator or its config — never hand-edit generated docs).
3. Not part of release history or release artifacts.
4. Not useful as historical context (if it is, archive instead).
5. **Tracked by git** — run `git ls-files --error-unmatch <path>`. If the command fails (file is untracked), ask the user before touching it. It may be in-progress work.

**Deletion is appropriate when the file is clearly:**

- Temporary
- Generated
- Duplicate
- Superseded
- Misleading
- Not referenced
- Not needed for build/test/runtime
- Not useful as historical context

**Archive instead of delete when:**

- The content may explain a past decision.
- The file is obsolete but still informative.
- The project lacks a better record of the decision.
- You are not fully certain deletion is safe.

Archive location: `docs/archive/`. Do not create an archive directory just to preserve junk.

---

## Phase 8 — Safe verification

Verification has two tiers. Mixing them is the most common failure mode.

### Tier 1: required, read-only

Always run. Every claim in updated docs needs a check.

- Paths referenced in docs exist on disk.
- Internal `.md` links resolve (see Phase 3 link audit).
- Every command quoted in docs is defined in the corresponding manifest (`package.json` scripts, `Makefile` targets, `composer.json` scripts, etc.).
- Schemas/routes/tables referenced in architecture docs exist in the code.

Safe baseline commands:

```bash
git status --short
git diff --stat
git ls-files | wc -l
find . -maxdepth 3 -type f -not -path './node_modules/*' -not -path './.git/*' | sort
```

### Tier 2: optional, command execution

Best-effort. Inspect the script or build manifest before running.

**Always read first:**

- `package.json` before `npm test`, `npm run build`, `npm run lint`
- `pom.xml` before `mvn test`
- `build.gradle` before `gradle test`
- `Makefile` before `make <target>`
- CI workflow files before copying commands from them
- Any shell script you are about to execute

**Refuse to execute scripts that contain:**

- Destructive filesystem operations (`rm -rf`, broad delete, `find -delete`)
- Credential or secret access
- Secret exfiltration patterns
- Unrecognized network calls
- `curl | bash` execution
- Package publishing (`npm publish`, `cargo publish`, `mvn deploy`)
- Deployment commands (`terraform apply`, `kubectl apply`, `helm install`)
- Production database operations
- Host-level service modification (`systemctl`, `service`)
- Privileged container operations
- Broad deletion commands

**When possible, run verification in an isolated environment:**

- Ephemeral container
- Temporary workspace
- CI sandbox
- Read-only mounted repo
- Non-privileged user
- No production credentials
- No host Docker socket

If safe execution is not possible, do not run the command. Report:

```text
Not run: npm test
Reason: package.json test script invokes an unreviewed shell script with network access.
```

Only claim a command passed if it was actually run and passed. Never infer verification from inspection alone.

---

## Phase 9 — PR-format handoff

The agent's output is a Pull Request description, not a commit. The agent must not commit directly to `main`, self-approve, or self-merge.

Full PR template lives in `templates.md`. Required sections:

- **Summary** — what changed and why, one paragraph
- **Changes** — separated into Updated / Added / Moved / Removed, with one-line justifications
- **Source of truth** — declare which file is canonical for agent instructions and why
- **Verification** — commands inspected before execution, commands run, commands explicitly not run with reasons
- **Needs verification** — items the human reviewer must confirm
- **Governance note** — PR requires human review; AI must not self-approve or bypass branch protection

The PR should separate documentation moves, deletions, and additions clearly enough that a human reviewer can sign off file-by-file.
