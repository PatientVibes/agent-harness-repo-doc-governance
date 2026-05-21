"""CLI entry point.

Three subcommands, mapping 1:1 to the modes in the design spec:

  - `run`    — manual / active-development mode. Opens a PR via `gh`.
  - `audit`  — read-only. Outputs structured JSON. Writes nothing.
               Default mode for CI drift checks.
  - `batch`  — multi-repo. Runs `run` against each repo in a YAML config
               under a bounded semaphore. One PR per repo.

`run` and `audit` share the same deterministic engine (Phases 1, 2, 3, 7,
8 Tier-1). `audit` stops after that — never invokes the LLM phases or
Phase 9. `run` continues through Phases 4, 5, 6, 9. `batch` invokes the
`run` flow per-repo.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from repo_doc_governance import __version__
from repo_doc_governance.orchestrator import make_run_state, run, summary
from repo_doc_governance.phases import Phase, Task


_AUDIT_PHASES = (
    Phase.SURVEY,
    Phase.CODE_FIRST,
    Phase.DRIFT_AUDIT,
    Phase.STALE_ARTIFACTS,
    Phase.VERIFICATION,
)
"""Phases that `audit` mode runs. NEVER includes Phase 4/5/6 (LLM) or
Phase 9 (PR creation) — audit is read-only by contract."""


def main(argv: list[str] | None = None) -> int:
    _load_config_env()

    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "run":
        return _cmd_run(args)
    if args.command == "audit":
        return _cmd_audit(args)
    if args.command == "batch":
        return _cmd_batch(args)
    parser.error(f"unknown command: {args.command}")
    return 2  # unreachable; argparse already exits


def _load_config_env() -> None:
    """Auto-source `${XDG_CONFIG_HOME:-~/.config}/repo-doc-gov/env` so
    operators can stash `OPENROUTER_API_KEY` / `ANTHROPIC_API_KEY` /
    `GH_TOKEN` in one file with mode 600 instead of exporting per-shell.

    Sibling-tool precedent: `agent-tool-llm-proofreader` ships the same
    pattern. Already-set env vars win — the file never overrides what
    the operator (or CI) explicitly exported.

    POSIX: warns to stderr if the file is group/world-readable. The
    `python-dotenv` dep is already declared in `pyproject.toml`.
    """
    try:
        from dotenv import load_dotenv
    except ImportError:
        return  # dotenv missing — best-effort, never block the CLI

    xdg_config = os.environ.get("XDG_CONFIG_HOME")
    config_dir = Path(xdg_config) if xdg_config else Path.home() / ".config"
    env_file = config_dir / "repo-doc-gov" / "env"
    if not env_file.is_file():
        return

    if os.name == "posix":
        try:
            mode = env_file.stat().st_mode
        except OSError:
            mode = None
        if mode is not None and (mode & 0o077):
            print(
                f"warning: {env_file} has group/world permissions "
                f"(mode {oct(mode)[-3:]}); recommend 600. Run "
                f"`chmod 600 {env_file}`.",
                file=sys.stderr,
            )

    load_dotenv(env_file, override=False)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="repo-doc-gov",
        description=(
            "Portable repo documentation cleanup + AI-agent instruction "
            "consolidation harness. Outputs a PR, not a merge."
        ),
    )
    parser.add_argument(
        "--version", action="version", version=f"repo-doc-gov {__version__}"
    )
    subparsers = parser.add_subparsers(dest="command", required=False)

    p_run = subparsers.add_parser(
        "run", help="Manual / active-development mode. Opens a PR via `gh`."
    )
    _add_repo_args(p_run)
    _add_task_arg(p_run)
    p_run.add_argument(
        "--base-branch", default="main", help="Branch the PR will target (default: main)."
    )
    p_run.add_argument(
        "--execute",
        action="store_true",
        help=(
            "Actually create the branch, commit, push, and open the PR. "
            "Without this flag, `run` is dry-run (composes the PR body only)."
        ),
    )
    p_run.add_argument(
        "--execute-tier2",
        action="store_true",
        help="Run Phase 8 Tier-2 commands (off by default, refuse-list enforced).",
    )
    p_run.add_argument(
        "--json", action="store_true", help="Emit summary as JSON to stdout."
    )
    p_run.add_argument(
        "--trace",
        type=Path,
        default=None,
        help="Write a JSONL pipeline trace to this path (off by default).",
    )

    p_audit = subparsers.add_parser(
        "audit", help="Read-only. JSON output. No PR, no file writes."
    )
    _add_repo_args(p_audit)
    p_audit.add_argument(
        "--fail-on",
        choices=("any", "high", "blocker", "never"),
        default="any",
        help=(
            "Exit non-zero if findings at-or-above the given severity exist. "
            "Useful for CI gating. `never` always exits 0."
        ),
    )
    p_audit.add_argument(
        "--trace",
        type=Path,
        default=None,
        help="Write a JSONL pipeline trace to this path (off by default).",
    )

    p_batch = subparsers.add_parser(
        "batch", help="Multi-repo. Runs `run` against each repo in a YAML config."
    )
    p_batch.add_argument(
        "--config",
        required=True,
        type=Path,
        help="YAML file describing the repos to process.",
    )
    p_batch.add_argument(
        "--concurrency", type=int, default=4, help="Max parallel repos (default 4)."
    )
    p_batch.add_argument(
        "--execute",
        action="store_true",
        help="Actually open a PR per repo (otherwise dry-run).",
    )
    p_batch.add_argument(
        "--json", action="store_true", help="Emit one JSON object per repo to stdout."
    )

    return parser


def _add_repo_args(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--repo",
        required=True,
        type=Path,
        help="Path to the target repo (must be a git working tree).",
    )


def _add_task_arg(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--task",
        default=Task.FULL_PASS.value,
        choices=[t.value for t in Task],
        help="Which subset of phases to run (default: full-pass).",
    )


# ---------------------------------------------------------------------------
# Subcommand implementations
# ---------------------------------------------------------------------------


def _cmd_run(args: argparse.Namespace) -> int:
    state = make_run_state(args.repo, args.task)
    state.base_branch = args.base_branch
    state.execute_phase9 = args.execute
    state.execute_tier2 = args.execute_tier2
    state.trace_path = args.trace
    result = run(state)
    if args.json:
        json.dump(_jsonable_summary(result), sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        _human_summary(result)
    return 0 if not result.phases_failed else 1


def _cmd_audit(args: argparse.Namespace) -> int:
    state = make_run_state(args.repo, Task.FULL_PASS)
    state.phases_to_run = list(_AUDIT_PHASES)
    state.base_branch = "main"  # irrelevant — audit doesn't create branches
    state.execute_phase9 = False  # never executes
    state.trace_path = args.trace
    result = run(state)

    report = _audit_report(result)
    json.dump(report, sys.stdout, indent=2)
    sys.stdout.write("\n")

    return _audit_exit_code(report, args.fail_on)


def _cmd_batch(args: argparse.Namespace) -> int:
    repos = _load_batch_config(args.config)
    if not repos:
        print("error: no repos in config", file=sys.stderr)
        return 2

    exit_codes: list[int] = []
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = [
            pool.submit(_batch_one, entry, args.execute) for entry in repos
        ]
        for fut in futures:
            res = fut.result()
            exit_codes.append(res["exit_code"])
            if args.json:
                json.dump(res, sys.stdout, indent=2)
                sys.stdout.write("\n")
    return max(exit_codes) if exit_codes else 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _human_summary(state) -> None:
    s = summary(state)
    print(f"target_repo:      {s['target_repo']}")
    print(f"task:             {s['task']}")
    print(f"phases_completed: {', '.join(s['phases_completed'])}")
    if s["phases_failed"]:
        print("phases_failed:")
        for f in s["phases_failed"]:
            print(f"  - {f['phase']} ({f['error_type']}): {f['message']}")
    if state.pr_body_draft:
        print("---- PR body draft ----")
        print(state.pr_body_draft)
    if state.pr_url:
        print(f"PR opened: {state.pr_url}")


def _jsonable_summary(state) -> dict:
    out = dict(summary(state))
    out["schema_version"] = 1
    out["pr_url"] = state.pr_url
    out["pr_branch_name"] = state.pr_branch_name
    out["pr_body_draft"] = state.pr_body_draft
    out["canonical_agent_file"] = state.canonical_agent_file
    out["trace_path"] = str(state.trace_path) if state.trace_path else None
    return out


def _audit_report(state) -> dict:
    """Audit mode's output shape. Stable schema for CI consumers."""
    return {
        "schema_version": 1,
        "target_repo": str(state.target_repo),
        "drift_findings": [f.model_dump(mode="json") for f in state.drift_findings],
        "stale_artifact_candidates": [
            c.model_dump(mode="json") for c in state.stale_artifact_candidates
        ],
        "verification_results": [
            v.model_dump(mode="json") for v in state.verification_results
        ],
        "summary": {
            "drift_findings": len(state.drift_findings),
            "stale_candidates": len(state.stale_artifact_candidates),
            "verification_failures": sum(
                1 for v in state.verification_results if not v.ok
            ),
        },
    }


_SEVERITY_RANK = {"info": 0, "low": 1, "medium": 2, "high": 3, "blocker": 4}


def _audit_exit_code(report: dict, fail_on: str) -> int:
    if fail_on == "never":
        return 0
    threshold = {"any": 0, "high": 3, "blocker": 4}[fail_on]
    for finding in report["drift_findings"]:
        sev = _SEVERITY_RANK.get(finding["severity"], 0)
        if sev >= threshold and fail_on != "any":
            return 1
        if fail_on == "any":
            return 1
    if report["summary"]["verification_failures"] > 0 and fail_on == "any":
        return 1
    return 0


def _load_batch_config(path: Path) -> list[dict]:
    """Load a YAML or JSON batch config. Returns a list of `{path, task,
    base_branch}` dicts."""
    text = path.read_text(encoding="utf-8")
    try:
        import yaml

        data = yaml.safe_load(text)
    except ImportError:
        data = json.loads(text)
    if isinstance(data, dict):
        repos = data.get("repos", [])
    else:
        repos = data
    out: list[dict] = []
    for entry in repos:
        if isinstance(entry, str):
            entry = {"path": entry}
        out.append(
            {
                "path": entry["path"],
                "task": entry.get("task", Task.FULL_PASS.value),
                "base_branch": entry.get("base_branch", "main"),
            }
        )
    return out


def _batch_one(entry: dict, execute: bool) -> dict:
    state = make_run_state(Path(entry["path"]), entry["task"])
    state.base_branch = entry["base_branch"]
    state.execute_phase9 = execute
    result = run(state)
    return {
        "path": entry["path"],
        "task": entry["task"],
        "pr_url": result.pr_url,
        "phases_completed": [p.name for p in result.phases_completed],
        "phases_failed": [
            {"phase": f.phase.name, "error_type": f.error_type}
            for f in result.phases_failed
        ],
        "exit_code": 1 if result.phases_failed else 0,
    }


if __name__ == "__main__":
    raise SystemExit(main())
