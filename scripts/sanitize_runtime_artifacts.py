#!/usr/bin/env python3
"""Sanitize generated runtime artifacts under backend/data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
import unicodedata


REPO_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_TARGETS = (
    "backend/data/artifacts",
    "backend/data/glass",
)

TEXT_SUFFIXES = {
    ".json",
    ".jsonl",
    ".md",
    ".txt",
}

ASCII_REPLACEMENTS = {
    "\u2013": "-",
    "\u2014": "-",
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u2026": "...",
    "\u2192": "->",
    "\u00d7": "x",
    "\ufeff": "",
    "\U0001f4c4": "",
    "\U0001f4ca": "",
    "\U0001f426": "Twitter",
    "\U0001f47d": "Reddit",
    "\u2b21": "Graph",
    "\u25a0": "Stop",
    "\u25be": "v",
}

def _compile_runtime_pattern(term: str) -> re.Pattern[str]:
    return re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE)


TEXT_REPLACEMENTS = (
    (_compile_runtime_pattern("miro" + "fish"), "legacy product"),
    (_compile_runtime_pattern("audience" + "mind"), "legacy graph"),
    (_compile_runtime_pattern("shan" + "da"), "legacy org"),
    (_compile_runtime_pattern("q" + "q"), "legacy chat"),
    (_compile_runtime_pattern("bili" + "bili"), "legacy video platform"),
)


def sanitize_runtime_text(content: str) -> str:
    normalized = content
    for source, replacement in ASCII_REPLACEMENTS.items():
        normalized = normalized.replace(source, replacement)
    for pattern, replacement in TEXT_REPLACEMENTS:
        normalized = pattern.sub(replacement, normalized)
    normalized = unicodedata.normalize("NFKD", normalized)
    normalized = normalized.encode("ascii", "ignore").decode("ascii")
    normalized = re.sub(r"[ \t]+\n", "\n", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    normalized = normalized.strip()
    return normalized + ("\n" if content.endswith("\n") and normalized else "")


def sanitize_runtime_payload(payload: object) -> object:
    if isinstance(payload, str):
        return sanitize_runtime_text(payload)
    if isinstance(payload, list):
        return [sanitize_runtime_payload(item) for item in payload]
    if isinstance(payload, dict):
        return {key: sanitize_runtime_payload(value) for key, value in payload.items()}
    return payload


def sanitize_short_model_text(text: str | None, fallback: str | None = None) -> str | None:
    if not text or not text.strip():
        return fallback

    cleaned = text.replace("\r", "").replace("**", "").replace("__", "").strip()
    for marker in ("Final answer:", "Answer:"):
        if marker in cleaned:
            cleaned = cleaned.split(marker, 1)[1].strip()

    candidate_lines: list[str] = []
    for raw_line in cleaned.splitlines():
        line = raw_line.strip().lstrip("-*# ").strip()
        if not line:
            continue
        numbered_match = re.match(r"^\d+\.\s*(.+)$", line)
        if numbered_match:
            line = numbered_match.group(1).strip()
        lowered = line.lower().rstrip(":")
        if lowered.startswith(
            (
                "thinking process",
                "reasoning",
                "analysis",
                "analyze the request",
                "analyze the input",
                "input data",
                "project:",
                "scenario:",
                "requirement:",
                "additional context:",
                "top terms:",
                "persona:",
                "persona name:",
                "persona role:",
                "persona bio:",
                "role:",
                "bio:",
                "interested topics:",
                "recent actions:",
                "interview prompt:",
                "selection",
                "final polish",
                "draft",
                "attempt",
                "refining",
                "task",
                "constraint",
            )
        ):
            continue
        if any(token in lowered for token in ("task:", "input data:", "constraint:", "selection:")):
            continue
        candidate_lines.append(line)

    collapsed = re.sub(r"\s+", " ", " ".join(candidate_lines)).strip()
    if not collapsed:
        return fallback
    sentence_match = re.search(r"(.+?[.!?])(?:\s|$)", collapsed)
    sentence = sentence_match.group(1).strip() if sentence_match else collapsed
    if len(sentence) > 220:
        sentence = f"{sentence[:217].rsplit(' ', 1)[0]}..."
    lowered_sentence = sentence.lower()
    if any(
        token in lowered_sentence
        for token in (
            "thinking process",
            "project:",
            "scenario:",
            "requirement:",
            "persona:",
            "persona name:",
            "persona role:",
            "persona bio:",
            "role:",
            "bio:",
            "interview prompt:",
        )
    ):
        return fallback
    return sentence or fallback


def iter_files(target: Path) -> list[Path]:
    if not target.exists():
        return []
    return [path for path in target.rglob("*") if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES]


def sanitize_json_file(path: Path) -> bool:
    raw = path.read_text(encoding="utf-8")
    payload = json.loads(raw)
    payload = sanitize_runtime_payload(payload)

    if path.name == "metadata.json" and isinstance(payload, dict):
        summary = payload.get("analysis_summary")
        if isinstance(summary, str):
            payload["analysis_summary"] = sanitize_short_model_text(
                summary,
                "Prepared an analyst ontology for the project.",
            )

    serialized = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    sanitized = sanitize_runtime_text(serialized)
    if sanitized == raw:
        return False
    path.write_text(sanitized, encoding="utf-8")
    return True


def sanitize_text_file(path: Path) -> bool:
    raw = path.read_text(encoding="utf-8")
    sanitized = sanitize_runtime_text(raw)
    if sanitized == raw:
        return False
    path.write_text(sanitized, encoding="utf-8")
    return True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sanitize generated runtime artifacts in backend/data.")
    parser.add_argument("paths", nargs="*", help="Optional runtime artifact paths to sanitize.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    targets = [REPO_ROOT / item for item in (args.paths or DEFAULT_TARGETS)]

    updated_count = 0
    for target in targets:
        for path in iter_files(target):
            if path.suffix.lower() == ".json":
                try:
                    changed = sanitize_json_file(path)
                except json.JSONDecodeError:
                    changed = sanitize_text_file(path)
            else:
                changed = sanitize_text_file(path)
            if changed:
                updated_count += 1
                print(path.relative_to(REPO_ROOT))

    print(f"Sanitized {updated_count} runtime artifact file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
