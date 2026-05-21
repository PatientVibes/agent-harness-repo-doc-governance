"""Phase 3 — Drift audit.

Compares documentation against the actual repository. Deterministic. No LLM.

Detects:
  - Broken internal `.md` links (link target doesn't resolve on disk).
  - Dead commands (`npm run X` / `make Y` / `pnpm X` quoted in docs but
    not declared in any manifest in `code_first_map.declared_commands`).
  - Missing paths referenced from docs (a doc says `see foo/bar.py` but
    `foo/bar.py` doesn't exist on disk).
  - Conflicting agent-instruction files (multiple agent files exist with
    overlapping content — flagged for Phase 5 to consolidate).
  - Stale TODOs (vague "clean up later" / "investigate this" markers).

Each finding gets a `Classification` from `prompts/decisions.md`:
  - broken link → `Update`
  - dead command → `Update`
  - missing path → `Needs verification` (could be the doc is right and
    the code was deleted, or the path was renamed)
  - conflicting agent files → `Consolidate`
  - vague TODO → `Update`
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from repo_doc_governance.models import (
    Classification,
    DocFile,
    DocKind,
    DriftFinding,
    Severity,
)
from repo_doc_governance.phase_impls._utils import git_ls_files, is_git_repo
from repo_doc_governance.state import RunState


# Markdown link: [text](target) — target may be relative path, http, anchor.
_MD_LINK_RE = re.compile(r"\[(?P<text>[^\]]*)\]\((?P<target>[^)\s]+)\)")

# Inline code that looks like a command — we focus on these common runners
# because they have well-defined manifest mappings.
_COMMAND_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("npm", re.compile(r"`(npm (?:run )?[A-Za-z0-9:_-]+)`")),
    ("pnpm", re.compile(r"`(pnpm (?:run )?[A-Za-z0-9:_-]+)`")),
    ("yarn", re.compile(r"`(yarn (?:run )?[A-Za-z0-9:_-]+)`")),
    ("make", re.compile(r"`(make [A-Za-z0-9_/-]+)`")),
]

# Vague-TODO heuristics from `prompts/phases.md` Phase 6 rules.
_VAGUE_TODO_PHRASES: tuple[str, ...] = (
    "clean up later",
    "investigate this",
    "fix this",
    "look into this",
    "todo: ?",
    "tbd",
    "tbc",
    "fix me later",
)

_TODO_LINE_RE = re.compile(r"(?i)\btodo\b|\bfixme\b")


def run(state: RunState) -> RunState:
    repo = state.target_repo
    findings: list[DriftFinding] = []

    if state.inventory is None:
        # Drift audit needs inventory; record one informational finding and bail.
        state.drift_findings.append(
            DriftFinding(
                path=".",
                kind="phase_skipped",
                severity=Severity.INFO,
                classification=Classification.NEEDS_VERIFICATION,
                detail="Phase 3 requires Phase 1 inventory; was the task table changed?",
            )
        )
        return state

    declared = _all_declared_commands(state)
    tracked_files = {df.path for df in state.inventory.doc_files}
    tracked_files.update(df.path for df in state.inventory.agent_files)
    tracked_files.update(df.path for df in state.inventory.handoff_files)
    # All files (tracked + just-the-list — keep it simple)
    all_files: set[str] = set()
    for df in (
        *state.inventory.doc_files,
        *state.inventory.agent_files,
        *state.inventory.handoff_files,
    ):
        all_files.add(df.path)

    docs_to_scan: list[DocFile] = list(state.inventory.doc_files) + list(
        state.inventory.agent_files
    ) + list(state.inventory.handoff_files)

    for doc in docs_to_scan:
        abs_path = repo / doc.path
        try:
            text = abs_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        findings.extend(_audit_internal_links(repo, doc, text))
        findings.extend(_audit_commands(doc, text, declared))
        if doc.kind in (DocKind.HANDOFF, DocKind.TODO, DocKind.ROADMAP):
            findings.extend(_audit_vague_todos(doc, text))

    findings.extend(_audit_conflicting_agent_files(state))
    findings.extend(_audit_undocumented_env_vars(state))

    state.drift_findings.extend(findings)
    return state


# ---------------------------------------------------------------------------
# Internal-link audit
# ---------------------------------------------------------------------------


def _audit_internal_links(repo: Path, doc: DocFile, text: str) -> list[DriftFinding]:
    out: list[DriftFinding] = []
    doc_dir = (repo / doc.path).parent
    in_fence = _fenced_code_lines(text)

    for line_no, line in enumerate(text.splitlines(), start=1):
        if line_no in in_fence:
            # Inside a ``` fenced code block — author is showing an
            # example, not asserting a link. Skip.
            continue
        for match in _MD_LINK_RE.finditer(line):
            target = match.group("target").strip()
            if not target:
                continue
            # Skip external URLs and pure anchors.
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            # Skip template placeholders (`${foo}`, `{{foo}}`).
            if "${" in target or "{{" in target:
                continue
            # Strip anchor + query
            link_path = target.split("#", 1)[0].split("?", 1)[0]
            if not link_path or not link_path.endswith(".md"):
                # Phase 3's contract here is .md → .md / .md → file. We only
                # flag missing `.md` link targets to avoid false positives on
                # image/asset links that may be intentionally stub-able.
                if not link_path.endswith(".md"):
                    continue
            resolved = (doc_dir / link_path).resolve()
            if not resolved.exists():
                out.append(
                    DriftFinding(
                        path=doc.path,
                        kind="broken_internal_link",
                        severity=Severity.MEDIUM,
                        classification=Classification.UPDATE,
                        detail=f"Link target does not exist: {target}",
                        line=line_no,
                    )
                )
    return out


def _fenced_code_lines(text: str) -> set[int]:
    """Return the set of 1-indexed line numbers that lie inside ``` fences.

    Treats every ``` (with optional language tag) as toggling fenced-ness.
    Lines on the fence markers themselves are also marked fenced so a
    closing ``` is never treated as in-content. Robust to nested fences
    of the same depth — markdown doesn't really support nested fences,
    so we don't either.
    """
    fenced: set[int] = set()
    in_fence = False
    for line_no, line in enumerate(text.splitlines(), start=1):
        stripped = line.lstrip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            fenced.add(line_no)
            continue
        if in_fence:
            fenced.add(line_no)
    return fenced


# ---------------------------------------------------------------------------
# Dead-command audit
# ---------------------------------------------------------------------------


def _all_declared_commands(state: RunState) -> set[str]:
    """Union of all declared commands across all manifests + the
    code-first map. Used as the source-of-truth oracle for Phase 3."""
    declared: set[str] = set()
    if state.inventory is not None:
        for m in state.inventory.manifests:
            declared.update(m.declared_commands)
    if state.code_first_map is not None:
        for cmds in state.code_first_map.declared_commands.values():
            declared.update(cmds)
    return declared


def _audit_commands(
    doc: DocFile, text: str, declared: set[str]
) -> list[DriftFinding]:
    out: list[DriftFinding] = []
    is_aspirational = is_aspirational_doc(doc.path)
    for line_no, line in enumerate(text.splitlines(), start=1):
        for tool_name, pattern in _COMMAND_PATTERNS:
            for match in pattern.finditer(line):
                cmd = match.group(1).strip()
                # Build a generous "is this declared?" check so the audit
                # doesn't flag style variations (`npm run test` vs `npm test`).
                if _command_is_declared(cmd, declared):
                    continue
                # Refuse-list / blocklist / denylist documentation context:
                # the command is being documented as one the harness REFUSES
                # to run, not as one users should run. Demote to INFO+Keep
                # so Phase 4 doesn't try to "fix" it. Surfaced by the
                # harness's own README dogfood under PR #8.
                if _line_is_refuse_list_documentation(line):
                    out.append(
                        DriftFinding(
                            path=doc.path,
                            kind="dead_command_in_refuse_list_documentation",
                            severity=Severity.INFO,
                            classification=Classification.KEEP,
                            detail=(
                                f"`{cmd}` appears in refuse-list / blocklist "
                                f"documentation context (line mentions "
                                f"refuse/blocked/rejected), not as a "
                                f"runnable command. No action needed."
                            ),
                            line=line_no,
                        )
                    )
                    continue
                if is_aspirational:
                    # Plan / spec / design docs describe future or
                    # alternative state. A `dead_command` here is usually
                    # a planned-but-not-yet-shipped reference, not drift.
                    # Demote to `Needs verification` so the human can
                    # confirm whether the plan landed or not.
                    out.append(
                        DriftFinding(
                            path=doc.path,
                            kind="dead_command_in_aspirational_doc",
                            severity=Severity.LOW,
                            classification=Classification.NEEDS_VERIFICATION,
                            detail=(
                                f"`{cmd}` is referenced in a plan/spec doc but "
                                f"not declared in any {tool_name}-flavored manifest. "
                                f"Confirm whether the plan landed."
                            ),
                            line=line_no,
                        )
                    )
                else:
                    out.append(
                        DriftFinding(
                            path=doc.path,
                            kind="dead_command",
                            severity=Severity.HIGH,
                            classification=Classification.UPDATE,
                            detail=(
                                f"`{cmd}` is referenced but not declared in any "
                                f"{tool_name}-flavored manifest."
                            ),
                            line=line_no,
                        )
                    )
    return out


_ASPIRATIONAL_PATH_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)(^|/)docs/superpowers/plans/"),
    re.compile(r"(?i)(^|/)docs/superpowers/specs/"),
    re.compile(r"(?i)(^|/)docs/plans/"),
    re.compile(r"(?i)(^|/)docs/specs/"),
    re.compile(r"(?i)(^|/)docs/design/"),
    re.compile(r"(?i)(^|/)docs/proposals/"),
    re.compile(r"(?i)(^|/)docs/rfcs/"),
)


# Refuse-list documentation context: words that mark a command as one the
# harness or runtime REFUSES to execute, not as one users should run.
# Single-line check — the harness's own README dogfood (the surfacing
# repro) has both the keyword and the command on the same line.
_REFUSE_LIST_KEYWORDS_RE = re.compile(
    r"(?i)\b(refuse[ds]?|refuses|refuse[- ]list|blocked|blocklist|"
    r"denylist|deny[- ]list|rejected|forbidden|disallowed)\b"
)


def _line_is_refuse_list_documentation(line: str) -> bool:
    """True iff the line documents a command as refused/blocked, not as
    one users should run. Avoids flagging `npm publish` etc. as dead
    commands when they appear in a refuse-list / blocklist / denylist
    context.
    """
    return bool(_REFUSE_LIST_KEYWORDS_RE.search(line))


def is_aspirational_doc(path: str) -> bool:
    """True for docs that describe a future / proposed / alternative
    state of the repo — plan docs, spec docs, design notes, proposals,
    RFCs. Dead-command findings in these get demoted from
    `Update` to `Needs verification` because the command is usually
    a planned-but-not-yet-shipped reference, not drift.
    """
    path_fwd = path.replace("\\", "/")
    return any(p.search(path_fwd) for p in _ASPIRATIONAL_PATH_PATTERNS)


def _command_is_declared(cmd: str, declared: set[str]) -> bool:
    if cmd in declared:
        return True
    # Variants — `npm run test` vs `npm test`, `pnpm X` vs `pnpm run X`.
    if cmd.startswith("npm run "):
        bare = "npm " + cmd[len("npm run "):]
        if bare in declared:
            return True
    if cmd.startswith("npm test") or cmd.startswith("npm start"):
        run_form = "npm run " + cmd.split(" ", 1)[1]
        if run_form in declared:
            return True
    return False


# ---------------------------------------------------------------------------
# Vague-TODO audit
# ---------------------------------------------------------------------------


def _audit_vague_todos(doc: DocFile, text: str) -> list[DriftFinding]:
    out: list[DriftFinding] = []
    lowered_lines = [(i, line.lower()) for i, line in enumerate(text.splitlines(), start=1)]
    for line_no, lowered in lowered_lines:
        if not _TODO_LINE_RE.search(lowered):
            continue
        if any(phrase in lowered for phrase in _VAGUE_TODO_PHRASES):
            out.append(
                DriftFinding(
                    path=doc.path,
                    kind="stale_todo",
                    severity=Severity.LOW,
                    classification=Classification.UPDATE,
                    detail=(
                        "Vague TODO marker — `prompts/phases.md` Phase 6 "
                        "requires specific actionable items with file paths."
                    ),
                    line=line_no,
                )
            )
    return out


# ---------------------------------------------------------------------------
# Conflicting-agent-files audit
# ---------------------------------------------------------------------------


def _audit_conflicting_agent_files(state: RunState) -> list[DriftFinding]:
    """If two or more of AGENTS.md / CLAUDE.md / GEMINI.md / copilot
    instructions exist at the repo root, flag for Phase 5 consolidation.

    `prompts/decisions.md` "Canonical agent file rationale": the *choice*
    of which is canonical is for Phase 5. Phase 3 just records the
    conflict and classifies it `Consolidate`.
    """
    if state.inventory is None:
        return []

    root_level = [
        df
        for df in state.inventory.agent_files
        if "/" not in df.path  # repo-root only
        and df.kind in (DocKind.AGENT_INSTRUCTIONS, DocKind.COPILOT_INSTRUCTIONS)
    ]
    # README is also in agent_files (per `_utils.is_agent_file`); the
    # consolidation rule is about agent-instruction files, not READMEs.
    root_level = [df for df in root_level if df.kind != DocKind.README]

    if len(root_level) < 2:
        return []

    names = sorted({df.path for df in root_level})
    return [
        DriftFinding(
            path=df.path,
            kind="conflicting_agent_instructions",
            severity=Severity.MEDIUM,
            classification=Classification.CONSOLIDATE,
            detail=(
                f"Multiple agent-instruction files present: {names}. "
                f"Phase 5 must pick a canonical and reduce the others to wrappers."
            ),
        )
        for df in root_level
    ]


# ---------------------------------------------------------------------------
# Env-var coverage audit
# ---------------------------------------------------------------------------
#
# Surfaced by the v0.1.4 dogfood (closed PR
# `PatientVibes/agent-harness-card-extractor#3`): the LLM Phase-4 pass got
# 6 of 8 missing env-var rows but silently dropped `ENABLE_AUDIT` /
# `ENABLE_PREPROCESSING`. "Env var referenced in code but absent from
# README" is deterministic; Phase 3 should produce these findings so Phase
# 4 only has to render them, not discover them.

# Env-var names whose suffix marks them as a secret. Secrets are
# referenced separately under the README's prose / "Environment variables"
# preamble, not as table rows — flagging them as undocumented produces FPs.
_SECRET_NAME_SUFFIXES: tuple[str, ...] = (
    "_KEY", "_TOKEN", "_SECRET", "_PASSWORD", "_PASSPHRASE", "_CREDENTIAL",
    "_CREDENTIALS", "_API_KEY", "_ACCESS_KEY", "_PRIVATE_KEY",
)

# Source-file extensions to scan. Python first per the issue scope; JS/TS/
# Rust/Go can land in follow-ups under the same shape.
_ENV_SCANNABLE_EXTENSIONS: tuple[str, ...] = (".py",)


def _audit_undocumented_env_vars(state: RunState) -> list[DriftFinding]:
    """Detect env vars referenced in source files but absent from the
    README's env-var documentation. One finding per undocumented name.
    """
    if state.inventory is None:
        return []
    repo = state.target_repo

    readme_text = _read_root_readme(state)
    if not readme_text:
        # No README at all: out of scope. Phase 4 will create one from
        # the template; the env-var rows can land then.
        return []

    referenced = _extract_python_env_var_refs(repo)
    if not referenced:
        return []

    documented = _extract_documented_env_var_names(readme_text)
    undocumented = sorted(
        name for name in referenced
        if name not in documented and not _looks_like_secret_name(name)
    )

    readme_rel = _find_root_readme_path(state) or "README.md"
    return [
        DriftFinding(
            path=readme_rel,
            kind="env_var_undocumented",
            severity=Severity.MEDIUM,
            classification=Classification.UPDATE,
            detail=(
                f"`{name}` is referenced in source files but not documented "
                f"in {readme_rel}. Add a row to the env-var table."
            ),
        )
        for name in undocumented
    ]


def _read_root_readme(state: RunState) -> str:
    rel = _find_root_readme_path(state)
    if rel is None:
        return ""
    try:
        return (state.target_repo / rel).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _find_root_readme_path(state: RunState) -> str | None:
    if state.inventory is None:
        return None
    for df in state.inventory.agent_files:
        if df.kind == DocKind.README and "/" not in df.path:
            return df.path
    return None


def _extract_python_env_var_refs(repo: Path) -> set[str]:
    """Walk tracked `.py` files; return the set of env-var names
    referenced (reads only). Best-effort: missing files / OS errors
    are skipped silently. Untracked files are NOT scanned — the audit
    follows the same `git ls-files` convention as the rest of survey.

    Test files are skipped — fixture string literals like
    `os.environ.get("FAKE_VAR")` inside test bodies would otherwise
    surface as harness drift findings (the regex doesn't distinguish
    Python-IN-string-literal from Python-actually-executed).
    """
    if not is_git_repo(repo):
        return set()
    try:
        tracked = git_ls_files(repo)
    except Exception:
        return set()

    out: set[str] = set()
    for rel in tracked:
        if not rel.endswith(_ENV_SCANNABLE_EXTENSIONS):
            continue
        if _is_test_file(rel):
            continue
        try:
            text = (repo / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        out.update(_extract_python_env_names_via_ast(text))
    return out


def _extract_python_env_names_via_ast(text: str) -> set[str]:
    """AST-based extractor. Catches:

    - `os.environ.get("NAME", ...)`
    - `os.getenv("NAME", ...)`
    - `os.environ["NAME"]` — only when it's a Load context (a READ).
      Writes (`os.environ["X"] = ...`) appear as Store-context
      Subscripts and are correctly skipped.

    Skips:

    - Comments (not in the AST).
    - Strings (Constant nodes that contain example code — the
      regex-based pass historically misfired on docstrings).
    - Syntax-broken files — best-effort; returns an empty set rather
      than raising so the rest of the audit keeps working.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return set()

    names: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _call_targets_environ(node)
            if name is not None:
                names.add(name)
        elif isinstance(node, ast.Subscript):
            if isinstance(node.ctx, ast.Load) and _subscripts_environ(node):
                name = _subscript_str_index(node)
                if name is not None:
                    names.add(name)

    return names


def _call_targets_environ(node: ast.Call) -> str | None:
    """If `node` is `os.environ.get('NAME', ...)` or `os.getenv('NAME', ...)`,
    return `NAME`. Else None."""
    if not node.args:
        return None
    arg0 = node.args[0]
    if not (isinstance(arg0, ast.Constant) and isinstance(arg0.value, str)):
        return None
    func = node.func
    # os.getenv(...)
    if (
        isinstance(func, ast.Attribute)
        and func.attr == "getenv"
        and isinstance(func.value, ast.Name)
        and func.value.id == "os"
    ):
        return arg0.value
    # os.environ.get(...)
    if (
        isinstance(func, ast.Attribute)
        and func.attr == "get"
        and isinstance(func.value, ast.Attribute)
        and func.value.attr == "environ"
        and isinstance(func.value.value, ast.Name)
        and func.value.value.id == "os"
    ):
        return arg0.value
    return None


def _subscripts_environ(node: ast.Subscript) -> bool:
    """True iff `node.value` is `os.environ`."""
    val = node.value
    return (
        isinstance(val, ast.Attribute)
        and val.attr == "environ"
        and isinstance(val.value, ast.Name)
        and val.value.id == "os"
    )


def _subscript_str_index(node: ast.Subscript) -> str | None:
    idx = node.slice
    if isinstance(idx, ast.Constant) and isinstance(idx.value, str):
        return idx.value
    return None


def _is_test_file(rel_path: str) -> bool:
    """True iff the path is part of a test suite — `tests/` directory,
    `test_*.py` / `*_test.py` filename, or `conftest.py`. Test files
    contain fixture string literals that the env-var regex can't
    distinguish from real code, so we drop them from the scan.
    """
    p = rel_path.replace("\\", "/")
    parts = p.split("/")
    if "tests" in parts or "test" in parts:
        return True
    base = parts[-1]
    if base == "conftest.py":
        return True
    if base.startswith("test_") and base.endswith(".py"):
        return True
    if base.endswith("_test.py"):
        return True
    return False


# A README documents an env var if its name appears inside backticks
# (the README convention) OR as a bare word in a likely env-var context.
# We match the conservative form: `\`<NAME>\`` anywhere in the text.
_ENV_DOCUMENTED_RE = re.compile(r"`([A-Z_][A-Z0-9_]{2,})`")


def _extract_documented_env_var_names(readme_text: str) -> set[str]:
    """Set of all-caps tokens that appear inside backticks in the README.
    Conservative — only matches the documented convention. Tokens shorter
    than 4 chars (e.g. `URL`) are excluded to avoid sweeping generic acronyms.
    """
    return {match.group(1) for match in _ENV_DOCUMENTED_RE.finditer(readme_text)}


def _looks_like_secret_name(name: str) -> bool:
    """Names suffixed with `_KEY`, `_TOKEN`, etc. are secrets — they're
    typically referenced in README prose, not the env-var table, so they
    would otherwise be high-FP."""
    upper = name.upper()
    return any(upper.endswith(suffix) for suffix in _SECRET_NAME_SUFFIXES)
