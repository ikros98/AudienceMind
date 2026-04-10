"""Targeted tests for the compliance scanner compatibility rules."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def load_compliance_scan_module():
    """Load the repository compliance scanner as a module."""
    root = Path(__file__).resolve().parents[2]
    module_path = root / "scripts" / "compliance_scan.py"
    spec = importlib.util.spec_from_file_location("compliance_scan", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_scan_file_allows_audiencemind_in_regular_markdown(tmp_path):
    """AudienceMind should not be treated as a banned legacy token."""
    module = load_compliance_scan_module()
    path = tmp_path / "notes.md"
    path.write_text("# AudienceMind\nAudienceMind is the active product name.\n", encoding="utf-8")

    findings = module.scan_file(path, tmp_path)

    assert findings == []


def test_scan_file_flags_banned_token_in_regular_markdown(tmp_path):
    """Still-banned legacy tokens should be flagged outside ignored paths."""
    module = load_compliance_scan_module()
    path = tmp_path / "notes.md"
    path.write_text("# mirofish\nmirofish should still be banned here.\n", encoding="utf-8")

    findings = module.scan_file(path, tmp_path)

    assert findings
    assert any("banned legacy token" in finding for finding in findings)


def test_scan_file_ignores_docs_superpowers_paths(tmp_path):
    """Planning and spec docs under docs/superpowers should stay out of the scan."""
    module = load_compliance_scan_module()
    path = tmp_path / "docs" / "superpowers" / "plan.md"
    path.parent.mkdir(parents=True)
    path.write_text("# mirofish\nmirofish should be ignored here.\n", encoding="utf-8")

    findings = module.scan_file(path, tmp_path)

    assert findings == []
