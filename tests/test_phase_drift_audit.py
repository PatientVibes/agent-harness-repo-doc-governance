"""Tests for Phase 3 — Drift audit."""

from __future__ import annotations

from pathlib import Path

from repo_doc_governance.models import Classification
from repo_doc_governance.orchestrator import make_run_state
from repo_doc_governance.phase_impls import code_first, drift_audit, survey
from repo_doc_governance.phases import Task

from conftest import (
    build_agents_and_claude_repo,
    build_broken_links_repo,
    build_clean_repo,
    build_drifted_repo,
)


def _run_through_phase3(repo: Path):
    state = make_run_state(repo, Task.FULL_PASS)
    survey.run(state)
    code_first.run(state)
    drift_audit.run(state)
    return state


def test_clean_repo_has_no_drift_findings(tmp_path: Path):
    repo = build_clean_repo(tmp_path)
    state = _run_through_phase3(repo)
    assert state.drift_findings == []


def test_drifted_repo_flags_dead_npm_command(tmp_path: Path):
    repo = build_drifted_repo(tmp_path)
    state = _run_through_phase3(repo)

    dead = [f for f in state.drift_findings if f.kind == "dead_command"]
    assert len(dead) >= 1
    assert any("npm run deploy" in f.detail for f in dead)
    assert all(f.classification == Classification.UPDATE for f in dead)


def test_drifted_repo_flags_broken_link(tmp_path: Path):
    repo = build_drifted_repo(tmp_path)
    state = _run_through_phase3(repo)

    broken = [f for f in state.drift_findings if f.kind == "broken_internal_link"]
    assert any("docs/MISSING.md" in f.detail for f in broken)


def test_drifted_repo_flags_vague_todo(tmp_path: Path):
    repo = build_drifted_repo(tmp_path)
    state = _run_through_phase3(repo)

    stale_todos = [f for f in state.drift_findings if f.kind == "stale_todo"]
    assert len(stale_todos) >= 1
    assert any(f.path == "docs/HANDOFF.md" for f in stale_todos)


def test_broken_links_repo_flags_each_missing_target(tmp_path: Path):
    repo = build_broken_links_repo(tmp_path)
    state = _run_through_phase3(repo)

    broken = [f for f in state.drift_findings if f.kind == "broken_internal_link"]
    assert len(broken) == 2
    targets = " ".join(f.detail for f in broken)
    assert "missing-1.md" in targets
    assert "missing-2.md" in targets


def test_conflicting_agent_files_are_classified_consolidate(tmp_path: Path):
    repo = build_agents_and_claude_repo(tmp_path)
    state = _run_through_phase3(repo)

    conflicts = [
        f
        for f in state.drift_findings
        if f.kind == "conflicting_agent_instructions"
    ]
    paths = {f.path for f in conflicts}
    assert "AGENTS.md" in paths
    assert "CLAUDE.md" in paths
    assert all(f.classification == Classification.CONSOLIDATE for f in conflicts)


def test_single_agent_file_is_not_a_conflict(tmp_path: Path):
    """One agent file == no consolidation finding."""
    repo = build_clean_repo(tmp_path)
    state = _run_through_phase3(repo)
    conflicts = [
        f
        for f in state.drift_findings
        if f.kind == "conflicting_agent_instructions"
    ]
    assert conflicts == []


# ---- Aspirational-doc (plan / spec) exemption ------------------------------


def test_plan_doc_dead_command_is_needs_verification_not_update(tmp_path: Path):
    """A plan doc that references `npm run dev` against a repo without
    `package.json` describes future state — demote to
    `Needs verification`, not `Update`."""
    import json
    import subprocess

    repo = tmp_path / "ad"
    repo.mkdir()
    (repo / "README.md").write_text("# ad\n", encoding="utf-8")
    (repo / "package.json").write_text(
        json.dumps({"name": "ad", "version": "0.0.1", "scripts": {"test": "echo ok"}}),
        encoding="utf-8",
    )
    plan_dir = repo / "docs" / "superpowers" / "plans"
    plan_dir.mkdir(parents=True)
    (plan_dir / "2026-05-19-frontend.md").write_text(
        "# Frontend plan\n\nWhen the frontend lands, run `npm run dev` to start it.\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=str(repo), check=True)
    subprocess.run(["git", "add", "."], cwd=str(repo), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "i"], cwd=str(repo), check=True)

    state = _run_through_phase3(repo)

    findings = [
        f for f in state.drift_findings if "npm run dev" in f.detail
    ]
    assert len(findings) == 1
    f = findings[0]
    assert f.kind == "dead_command_in_aspirational_doc"
    assert f.classification == Classification.NEEDS_VERIFICATION
    # Severity is Low, not High — aspirational doc is less load-bearing.
    from repo_doc_governance.models import Severity
    assert f.severity == Severity.LOW


def test_regular_doc_dead_command_stays_high_update(tmp_path: Path):
    """Compare baseline — a dead command outside a plan/spec dir is
    still HIGH + Update."""
    repo = build_drifted_repo(tmp_path)  # README references `npm run deploy`
    state = _run_through_phase3(repo)
    dead = [f for f in state.drift_findings if f.kind == "dead_command"]
    assert dead, "expected at least one dead_command finding"
    f = dead[0]
    assert f.classification == Classification.UPDATE
    from repo_doc_governance.models import Severity
    assert f.severity == Severity.HIGH


def test_refuse_list_documentation_does_not_flag_as_dead_command(tmp_path: Path):
    """A README that documents the harness's refuse-list (e.g. `npm publish`,
    `kubectl apply`) must NOT produce a high-severity `dead_command`
    finding. Surfaced by the harness's own README dogfood under PR #8.
    """
    import json
    import subprocess

    repo = tmp_path / "rl"
    repo.mkdir()
    (repo / "README.md").write_text(
        "# rl-fixture\n\n"
        "## Safety\n\n"
        "`RefusedCommandError` (Tier-2 refuse-list — `npm publish`, "
        "`kubectl apply`) is raised when a Tier-2 command matches the "
        "refuse-list.\n",
        encoding="utf-8",
    )
    (repo / "package.json").write_text(
        json.dumps(
            {"name": "rl", "version": "0.0.1", "scripts": {"test": "echo ok"}}
        ),
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=str(repo), check=True)
    subprocess.run(["git", "add", "."], cwd=str(repo), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "i"], cwd=str(repo), check=True)

    state = _run_through_phase3(repo)

    # No high-severity `dead_command` should be emitted for `npm publish`.
    dead = [
        f for f in state.drift_findings
        if f.kind == "dead_command" and "npm publish" in f.detail
    ]
    assert dead == [], (
        f"`npm publish` was flagged as a dead_command despite appearing "
        f"in refuse-list documentation context. Findings: {dead}"
    )

    # Instead it should be recorded as `dead_command_in_refuse_list_documentation`
    # at INFO + Keep — surfaced for transparency, not for action.
    refuse_list = [
        f for f in state.drift_findings
        if f.kind == "dead_command_in_refuse_list_documentation"
    ]
    assert len(refuse_list) >= 1
    assert any("npm publish" in f.detail for f in refuse_list)

    from repo_doc_governance.models import Severity
    assert all(f.severity == Severity.INFO for f in refuse_list)
    assert all(f.classification == Classification.KEEP for f in refuse_list)


def test_line_is_refuse_list_documentation_matches_expected_keywords():
    """Unit test of the line-context classifier."""
    from repo_doc_governance.phase_impls.drift_audit import (
        _line_is_refuse_list_documentation,
    )

    # Positive — words the issue calls out plus reasonable variants.
    assert _line_is_refuse_list_documentation("the refuse-list contains `npm publish`")
    assert _line_is_refuse_list_documentation("the refuse list contains `npm publish`")
    assert _line_is_refuse_list_documentation("refused commands include `npm publish`")
    assert _line_is_refuse_list_documentation("refuses to run `npm publish`")
    assert _line_is_refuse_list_documentation("blocked: `kubectl apply`")
    assert _line_is_refuse_list_documentation("blocklist: `rm -rf /`")
    assert _line_is_refuse_list_documentation("denylist includes `npm publish`")
    assert _line_is_refuse_list_documentation("rejected by safety: `make deploy`")
    assert _line_is_refuse_list_documentation("forbidden command `npm publish`")

    # Negative — running a command, not refusing one.
    assert not _line_is_refuse_list_documentation("Run `npm test` to start.")
    assert not _line_is_refuse_list_documentation("Use `npm publish` to release.")
    assert not _line_is_refuse_list_documentation("First, run `make build`.")


def test_env_var_in_code_but_not_in_readme_is_flagged_undocumented(
    tmp_path: Path,
):
    """Closes the v0.1.4 dogfood coverage gap (#34): env vars consumed
    by code but missing from the README env-var table must produce
    deterministic `env_var_undocumented` findings so Phase 4 only
    renders the row instead of having to discover it.
    """
    import subprocess

    repo = tmp_path / "ev"
    repo.mkdir()
    (repo / "README.md").write_text(
        "# ev\n\n## Environment variables\n\n"
        "| Variable | Default | Description |\n"
        "|---|---|---|\n"
        "| `RENDER_DPI` | `300` | Documented. |\n",
        encoding="utf-8",
    )
    (repo / "pyproject.toml").write_text(
        "[project]\nname='ev'\nversion='0.0.1'\n", encoding="utf-8"
    )
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text(
        "import os\n"
        "dpi = int(os.environ.get('RENDER_DPI', '300'))\n"
        "undocumented = os.environ.get('UNDOCUMENTED_KNOB', 'x')\n"
        "second = os.getenv('SECOND_KNOB')\n"
        "third = os.environ['THIRD_KNOB']\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=str(repo), check=True)
    subprocess.run(["git", "add", "."], cwd=str(repo), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "i"], cwd=str(repo), check=True)

    state = _run_through_phase3(repo)

    flagged_names = sorted(
        f.detail.split("`")[1]
        for f in state.drift_findings
        if f.kind == "env_var_undocumented"
    )
    # Three undocumented vars; documented `RENDER_DPI` is NOT flagged.
    assert flagged_names == ["SECOND_KNOB", "THIRD_KNOB", "UNDOCUMENTED_KNOB"]
    assert all(
        f.path == "README.md"
        for f in state.drift_findings
        if f.kind == "env_var_undocumented"
    )
    assert all(
        f.classification == Classification.UPDATE
        for f in state.drift_findings
        if f.kind == "env_var_undocumented"
    )


def test_env_var_secret_names_are_suppressed(tmp_path: Path):
    """`_KEY` / `_TOKEN` / `_SECRET` / `_PASSWORD` suffixes are typically
    documented in README prose, not the env-var table. Flagging them as
    undocumented produces high-FP — the suppression list keeps the
    audit clean against API-key-driven projects.
    """
    import subprocess

    repo = tmp_path / "secret"
    repo.mkdir()
    (repo / "README.md").write_text(
        "# secret\n\nEnv vars: see deployment notes for OPENROUTER_API_KEY.\n",
        encoding="utf-8",
    )
    (repo / "pyproject.toml").write_text(
        "[project]\nname='s'\nversion='0.0.1'\n", encoding="utf-8"
    )
    (repo / "app.py").write_text(
        "import os\n"
        "k = os.environ.get('OPENROUTER_API_KEY')\n"
        "t = os.environ.get('GH_TOKEN')\n"
        "s = os.getenv('SOME_SECRET')\n"
        "p = os.environ['DB_PASSWORD']\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=str(repo), check=True)
    subprocess.run(["git", "add", "."], cwd=str(repo), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "i"], cwd=str(repo), check=True)

    state = _run_through_phase3(repo)
    findings = [f for f in state.drift_findings if f.kind == "env_var_undocumented"]
    assert findings == [], (
        f"Secret-suffix env vars must be suppressed. Got: "
        f"{[f.detail for f in findings]}"
    )


def test_env_var_writes_are_not_treated_as_reads(tmp_path: Path):
    """`os.environ['X'] = ...` is the harness *setting* X, not consuming
    it. Must not produce an `env_var_undocumented` finding for X.
    """
    import subprocess

    repo = tmp_path / "writes"
    repo.mkdir()
    (repo / "README.md").write_text("# writes\n", encoding="utf-8")
    (repo / "pyproject.toml").write_text(
        "[project]\nname='w'\nversion='0.0.1'\n", encoding="utf-8"
    )
    (repo / "setup.py").write_text(
        "import os\n"
        "# Set a debug flag — this is a WRITE, not a read.\n"
        "os.environ['ASSIGNED_BY_SETUP'] = '1'\n"
        "# Also a real READ — should still be flagged.\n"
        "consumed = os.environ.get('TRULY_CONSUMED', 'x')\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=str(repo), check=True)
    subprocess.run(["git", "add", "."], cwd=str(repo), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "i"], cwd=str(repo), check=True)

    state = _run_through_phase3(repo)
    names = sorted(
        f.detail.split("`")[1] for f in state.drift_findings
        if f.kind == "env_var_undocumented"
    )
    assert names == ["TRULY_CONSUMED"], (
        f"Expected only TRULY_CONSUMED to be flagged; got: {names}"
    )


def test_clean_repo_has_no_env_var_findings(tmp_path: Path):
    """The clean-repo fixture has a Node README + `src/index.js`, no
    Python at all. Audit must produce zero env-var findings."""
    repo = build_clean_repo(tmp_path)
    state = _run_through_phase3(repo)
    assert [
        f for f in state.drift_findings if f.kind == "env_var_undocumented"
    ] == []


def test_is_aspirational_doc_matches_plan_dirs():
    """Spec-level test of the path classifier itself."""
    assert drift_audit.is_aspirational_doc("docs/superpowers/plans/x.md")
    assert drift_audit.is_aspirational_doc("docs/superpowers/specs/x.md")
    assert drift_audit.is_aspirational_doc("docs/plans/2026-foo.md")
    assert drift_audit.is_aspirational_doc("docs/specs/foo.md")
    assert drift_audit.is_aspirational_doc("docs/design/arch.md")
    assert drift_audit.is_aspirational_doc("docs/proposals/foo.md")
    assert drift_audit.is_aspirational_doc("docs/rfcs/0001.md")
    # Non-aspirational
    assert not drift_audit.is_aspirational_doc("README.md")
    assert not drift_audit.is_aspirational_doc("docs/HANDOFF.md")
    assert not drift_audit.is_aspirational_doc("docs/ARCHITECTURE.md")
    assert not drift_audit.is_aspirational_doc("AGENTS.md")


# ---- Code-fence stripping --------------------------------------------------


def test_links_inside_code_fence_are_skipped(tmp_path: Path):
    """A `[text](target.md)` link inside ```...``` is an example, not a
    real link. Phase 3 must not flag it as broken.
    """
    import subprocess

    repo = tmp_path / "fence"
    repo.mkdir()
    (repo / "README.md").write_text(
        "# fence-fixture\n\n"
        "Here's an example of what to write elsewhere:\n\n"
        "```markdown\n"
        "See [Contributing](./CONTRIBUTING.md) for guidance.\n"
        "Also see [Specs](specs/foo.md).\n"
        "```\n\n"
        "And a real broken link: [broken](docs/missing.md)\n",
        encoding="utf-8"
    )
    (repo / "package.json").write_text('{"scripts": {}}', encoding="utf-8")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=str(repo), check=True)
    subprocess.run(["git", "add", "."], cwd=str(repo), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "i"], cwd=str(repo), check=True)

    state = _run_through_phase3(repo)

    broken = [f for f in state.drift_findings if f.kind == "broken_internal_link"]
    # The two links inside the code fence should NOT be flagged. Only the
    # one outside (docs/missing.md) should land as a finding.
    assert len(broken) == 1
    assert "docs/missing.md" in broken[0].detail


def test_fenced_code_lines_helper():
    """Unit test of the line-set builder. Closing ``` toggles back out."""
    text = (
        "intro\n"
        "```python\n"
        "code line 1\n"
        "code line 2\n"
        "```\n"
        "outside again\n"
    )
    fenced = drift_audit._fenced_code_lines(text)
    # 1-indexed. Lines 2-5 are in the fence (open marker + body + close marker).
    assert 1 not in fenced
    assert 2 in fenced
    assert 3 in fenced
    assert 4 in fenced
    assert 5 in fenced
    assert 6 not in fenced


def test_template_placeholder_links_are_skipped(tmp_path: Path):
    """Links containing `${...}` or `{{...}}` are template placeholders
    (e.g. in Astro / Mustache examples) — never real targets."""
    import subprocess

    repo = tmp_path / "tmpl"
    repo.mkdir()
    (repo / "README.md").write_text(
        "# tmpl\n\n"
        "Astro example: [Doc](${base}/docs/foo.md)\n"
        "Mustache: [Path]({{path}}.md)\n",
        encoding="utf-8"
    )
    (repo / "package.json").write_text('{"scripts": {}}', encoding="utf-8")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=str(repo), check=True)
    subprocess.run(["git", "add", "."], cwd=str(repo), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "i"], cwd=str(repo), check=True)

    state = _run_through_phase3(repo)
    broken = [f for f in state.drift_findings if f.kind == "broken_internal_link"]
    assert broken == []
