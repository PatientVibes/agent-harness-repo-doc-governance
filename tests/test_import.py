"""Smoke test — the package imports and exposes a version."""

import re

import repo_doc_governance


def test_package_imports():
    assert repo_doc_governance is not None


def test_version_is_set():
    assert hasattr(repo_doc_governance, "__version__")
    assert isinstance(repo_doc_governance.__version__, str)
    assert re.match(r"^\d+\.\d+\.\d+(-\w+)?$", repo_doc_governance.__version__)


def test_cli_module_imports():
    from repo_doc_governance import cli

    assert callable(cli.main)
