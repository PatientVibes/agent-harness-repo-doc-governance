# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
