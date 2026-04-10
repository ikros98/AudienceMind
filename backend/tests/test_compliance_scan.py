"""Targeted tests for the current compliance scanner rules."""

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
    """AudienceMind should not be treated as a compliance violation."""
    module = load_compliance_scan_module()
    path = tmp_path / "notes.md"
    path.write_text("# AudienceMind\nAudienceMind is the active product name.\n", encoding="utf-8")

    findings = module.scan_file(path, tmp_path)

    assert findings == []


def test_compliance_scan_module_has_no_legacy_banned_token_list():
    """The scanner should not keep a stale banned-token policy surface."""
    module = load_compliance_scan_module()

    assert not hasattr(module, "BANNED_PATTERNS")


def test_scan_file_flags_non_ascii_in_regular_markdown(tmp_path):
    """Non-ASCII content in a normal markdown file should be reported."""
    module = load_compliance_scan_module()
    path = tmp_path / "notes.md"
    path.write_text(
        "# Planning notes\nThis line contains Caf\u00e9.\n",
        encoding="utf-8",
    )

    findings = module.scan_file(path, tmp_path)

    assert findings == ["notes.md:2: non-ASCII characters detected"]


def test_scan_file_ignores_docs_superpowers_paths(tmp_path):
    """Planning and spec docs under docs/superpowers should stay out of the scan."""
    module = load_compliance_scan_module()
    path = tmp_path / "docs" / "superpowers" / "plan.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "# Planning notes\nThis file should stay ignored by the scanner: Caf\u00e9.\n",
        encoding="utf-8",
    )

    findings = module.scan_file(path, tmp_path)

    assert findings == []
