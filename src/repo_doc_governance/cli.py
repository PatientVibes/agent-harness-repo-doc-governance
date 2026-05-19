"""CLI entry point.

PR #1 wires the entry point and version flag only. Subcommands (run / audit / batch)
land in subsequent PRs per the design spec.
"""

import argparse
import sys

from repo_doc_governance import __version__


def main(argv: list[str] | None = None) -> int:
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

    subparsers.add_parser("run", help="(PR #5) Manual mode — opens a PR.")
    subparsers.add_parser("audit", help="(PR #6) Read-only mode — JSON output, no PR.")
    subparsers.add_parser("batch", help="(PR #6) Multi-repo mode.")

    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    print(
        f"Subcommand '{args.command}' is not implemented yet — see the design spec.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
