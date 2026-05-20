"""Typed Pydantic models for phase outputs.

These tighten the schemas of the per-phase fields on RunState. Phase
implementations populate them in PR #3 (deterministic phases) and PR #4
(LLM phases). The classification vocabulary (`Keep / Update / Consolidate
/ Archive / Delete / Needs verification`) is the contract from
`prompts/decisions.md` and is enforced as an Enum here so a stray free-form
string can never sneak into the PR body.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class Classification(str, Enum):
    """Per `prompts/decisions.md` classification rules."""

    KEEP = "Keep"
    UPDATE = "Update"
    CONSOLIDATE = "Consolidate"
    ARCHIVE = "Archive"
    DELETE = "Delete"
    NEEDS_VERIFICATION = "Needs verification"


class Severity(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class DocKind(str, Enum):
    README = "readme"
    AGENT_INSTRUCTIONS = "agent_instructions"
    COPILOT_INSTRUCTIONS = "copilot_instructions"
    HANDOFF = "handoff"
    TODO = "todo"
    ROADMAP = "roadmap"
    ARCHITECTURE = "architecture"
    TROUBLESHOOTING = "troubleshooting"
    OTHER_DOC = "other_doc"


class ManifestKind(str, Enum):
    NODE_PACKAGE = "node_package"
    PYTHON_PYPROJECT = "python_pyproject"
    PYTHON_REQUIREMENTS = "python_requirements"
    RUST_CARGO = "rust_cargo"
    GO_MOD = "go_mod"
    JAVA_MAVEN = "java_maven"
    GRADLE = "gradle"
    MAKEFILE = "makefile"
    DOCKERFILE = "dockerfile"
    COMPOSE = "compose"
    CI_WORKFLOW = "ci_workflow"


class DocFile(BaseModel):
    """A documentation-class file discovered in Phase 1."""

    path: str
    """Repo-relative path with forward slashes."""

    kind: DocKind
    size_bytes: int


class ManifestEntry(BaseModel):
    """A build / package / CI manifest discovered in Phase 1+2."""

    path: str
    kind: ManifestKind
    declared_commands: list[str] = Field(default_factory=list)
    """Surface form of declared commands — e.g. ['npm test', 'npm run build', 'make test']."""


class Inventory(BaseModel):
    """Phase 1 output."""

    target_repo: str
    is_git_repo: bool
    tracked_files: int = 0
    """Count from `git ls-files`. Zero when not a git repo."""

    primary_languages: list[str] = Field(default_factory=list)
    manifests: list[ManifestEntry] = Field(default_factory=list)
    doc_files: list[DocFile] = Field(default_factory=list)
    agent_files: list[DocFile] = Field(default_factory=list)
    """README + AGENTS / CLAUDE / GEMINI / copilot instructions live here."""

    handoff_files: list[DocFile] = Field(default_factory=list)
    """HANDOFF / TODO / ROADMAP / planning files live here."""

    generated_candidates: list[str] = Field(default_factory=list)
    """Files that look auto-generated (matched by name pattern)."""

    branch: str | None = None
    is_clean: bool = True
    """False if `git status --porcelain` has any output."""


class CodeFirstMap(BaseModel):
    """Phase 2 output — the trust-layer-1..4 view of the repo."""

    declared_commands: dict[str, list[str]] = Field(default_factory=dict)
    """Manifest path → list of declared commands found in that manifest."""

    ci_workflows: list[str] = Field(default_factory=list)
    entry_points: list[str] = Field(default_factory=list)
    env_examples: list[str] = Field(default_factory=list)


class DriftFinding(BaseModel):
    """Phase 3 output — one finding."""

    path: str
    """Repo-relative path of the file the finding is about."""

    kind: str
    """e.g. 'broken_internal_link', 'dead_command', 'missing_path',
    'stale_todo', 'conflicting_agent_instructions'."""

    severity: Severity
    classification: Classification
    detail: str
    line: int | None = None


class StaleCandidate(BaseModel):
    """Phase 7 output — a stale-artifact candidate."""

    path: str
    kind: str
    """e.g. 'tmp_artifact', 'scratch_note', 'duplicate_handoff',
    'editor_droppings', 'os_droppings'."""

    classification: Classification
    """One of Archive / Delete / Needs verification.
    Untracked files are never auto-classified Delete (see decisions.md)."""

    tracked_by_git: bool
    referenced_count: int = 0
    """How many other files mention this path. 0 → safer to delete."""

    reason: str


class VerificationResult(BaseModel):
    """Phase 8 Tier-1 output — one read-only check."""

    check: str
    """e.g. 'path_exists', 'internal_link_resolves', 'command_declared'."""

    target: str
    ok: bool
    detail: str = ""
