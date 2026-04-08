"""Small clean-room compatibility logger for downloaded simulation helper scripts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class SimulationLogManager:
    """Append simple text logs to the simulation directory."""

    def __init__(self, simulation_dir: str | Path):
        self.root = Path(simulation_dir)
        self.root.mkdir(parents=True, exist_ok=True)
        self.log_path = self.root / "simulation.log"

    def append(self, line: str) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(str(line).rstrip() + "\n")


class PlatformActionLogger:
    """Append JSONL action rows for a platform."""

    def __init__(self, simulation_dir: str | Path, platform: str):
        self.root = Path(simulation_dir) / str(platform)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "actions.jsonl"

    def log_action(self, payload: dict[str, Any]) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
