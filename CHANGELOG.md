# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added (PR #2)
- Vendored skill body + 3 references (`phases.md`, `decisions.md`, `templates.md`) from
  `agent-skills/plugins/repo-documentation-governance/` @
  `2d4e2aac7677914bcd417cb752f1a7e9a4e72194` into `src/repo_doc_governance/prompts/`.
  All four files carry a `<!-- DO NOT EDIT — vendored from … @ <SHA>. Edit upstream + re-vendor. -->`
  header on line 1.
- `Makefile` with `re-vendor` target — clones agent-skills at a configurable ref
  (default master), rewrites the four vendored files with a fresh SHA in the
  header, and refuses to proceed if any vendored file is missing the header
  (a defense against silent local edits).
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
