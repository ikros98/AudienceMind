#!/usr/bin/env python3
"""Scan the AudienceMind app for banned legacy terms and non-ASCII content."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


DEFAULT_SCAN_PATHS = (
    "frontend",
    "backend",
    "docs",
    "scripts",
)

def _compile_banned_pattern(term: str) -> re.Pattern[str]:
    return re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE)


BANNED_PATTERNS = (
    _compile_banned_pattern("miro" + "fish"),
    _compile_banned_pattern("shan" + "da"),
    _compile_banned_pattern("q" + "q"),
    _compile_banned_pattern("bili" + "bili"),
)

TEXT_FILE_SUFFIXES = {
    ".css",
    ".csv",
    ".env",
    ".example",
    ".html",
    ".js",
    ".json",
    ".jsx",
    ".md",
    ".mjs",
    ".py",
    ".scss",
    ".sh",
    ".sql",
    ".svg",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".vue",
    ".yaml",
    ".yml",
}

IGNORED_DIR_NAMES = {
    ".git",
    ".idea",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "dist",
    "node_modules",
}

IGNORED_PATH_PREFIXES = (
    Path("backend/data"),
    Path("docs/superpowers"),
)

IGNORE_FILE_MARKER = "compliance-scan: ignore-file"
IGNORE_LINE_MARKER = "compliance-scan: ignore-line"


def contains_non_ascii(value: str) -> bool:
    return any(ord(ch) > 127 for ch in value)


def iter_files(base_path: Path) -> list[Path]:
    files: list[Path] = []
    if not base_path.exists():
        return files

    if base_path.is_file():
        return [base_path]

    for path in base_path.rglob("*"):
        if any(part in IGNORED_DIR_NAMES for part in path.parts):
            continue
        if path.is_file():
            files.append(path)
    return files


def is_text_file(path: Path) -> bool:
    if path.suffix.lower() in TEXT_FILE_SUFFIXES:
        return True
    return path.name in {"Dockerfile", "Makefile"}


def scan_file(path: Path, root: Path) -> list[str]:
    findings: list[str] = []
    relative_path = path.relative_to(root)

    if any(relative_path == prefix or prefix in relative_path.parents for prefix in IGNORED_PATH_PREFIXES):
        return findings

    if contains_non_ascii(relative_path.as_posix()):
        findings.append(f"{relative_path}: non-ASCII characters in file path")

    if not is_text_file(path):
        return findings

    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        findings.append(f"{relative_path}: file is not valid UTF-8")
        return findings

    if IGNORE_FILE_MARKER in content:
        return findings

    for line_number, line in enumerate(content.splitlines(), start=1):
        if IGNORE_LINE_MARKER in line:
            continue
        for pattern in BANNED_PATTERNS:
            if pattern.search(line):
                findings.append(
                    f"{relative_path}:{line_number}: banned legacy token '{pattern.pattern}'"
                )
        if contains_non_ascii(line):
            findings.append(f"{relative_path}:{line_number}: non-ASCII characters detected")

    return findings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scan AudienceMind app paths for banned legacy names and non-ASCII content."
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="Optional paths to scan. Defaults to the new AudienceMind app paths.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path.cwd()
    scan_targets = [Path(path) for path in (args.paths or DEFAULT_SCAN_PATHS)]

    findings: list[str] = []
    for target in scan_targets:
        resolved_target = target if target.is_absolute() else root / target
        for file_path in iter_files(resolved_target):
            findings.extend(scan_file(file_path, root))

    if findings:
        print("Compliance scan failed:")
        for finding in findings:
            print(f"  - {finding}")
        return 1

    print("Compliance scan passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
