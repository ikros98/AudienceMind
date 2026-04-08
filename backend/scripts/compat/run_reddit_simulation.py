"""Legacy helper wrapper for the clean-room Reddit OASIS worker."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys


PLATFORM = "reddit"


def infer_simulation_id(config_path: str) -> str:
    if not config_path:
        return ""
    path = Path(config_path).expanduser().resolve()
    if not path.exists():
        return ""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        payload = {}
    for key in ("simulation_id", "id"):
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    parent = path.parent.name.strip()
    return parent if parent.startswith("sim_") else ""


def build_command(args: argparse.Namespace) -> tuple[list[str], Path]:
    simulation_id = str(args.simulation_id or "").strip() or infer_simulation_id(str(args.config or ""))
    if not simulation_id:
        raise SystemExit("Could not determine simulation_id. Pass --simulation-id or a config path inside a simulation directory.")
    backend_root = Path(__file__).resolve().parents[2]
    command = [sys.executable, "-m", "app.oasis_worker", "--simulation-id", simulation_id, "--platform", PLATFORM]
    if args.max_rounds and args.max_rounds > 0:
        command.extend(["--max-rounds", str(args.max_rounds)])
    if args.graph_id:
        command.extend(["--graph-id", args.graph_id])
    if args.enable_graph_memory_update:
        command.append("--enable-graph-memory-update")
    if args.no_wait:
        command.append("--no-wait")
    return command, backend_root


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the clean-room Reddit OASIS worker")
    parser.add_argument("--simulation-id", default="")
    parser.add_argument("--config", default="")
    parser.add_argument("--max-rounds", type=int, default=0)
    parser.add_argument("--graph-id", default="")
    parser.add_argument("--enable-graph-memory-update", action="store_true")
    parser.add_argument("--no-wait", action="store_true")
    args = parser.parse_args()

    command, cwd = build_command(args)
    raise SystemExit(subprocess.run(command, cwd=cwd, check=False).returncode)


if __name__ == "__main__":
    main()
