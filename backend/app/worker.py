"""Standalone workflow worker entrypoint."""

from __future__ import annotations

import signal
from threading import Event

from .config import Settings, get_settings
from .database import create_db_engine, init_database
from .services.runtime import RuntimeRegistry
from .services.workflows import WorkflowRunner


def run_worker(settings: Settings | None = None) -> None:
    """Start a standalone workflow worker and block until shutdown."""
    resolved_settings = settings or get_settings()
    engine = create_db_engine(resolved_settings.database_url)
    init_database(engine)
    registry = RuntimeRegistry(resolved_settings)
    runner = WorkflowRunner(
        engine=engine,
        settings=resolved_settings,
        registry=registry,
        poll_interval_seconds=resolved_settings.workflow_poll_interval_seconds,
    )
    stop_event = Event()

    def handle_signal(signum, _frame) -> None:
        stop_event.set()

    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, handle_signal)

    runner.start()
    try:
        while not stop_event.wait(1.0):
            continue
    finally:
        runner.stop()


def main() -> None:
    """CLI entrypoint for the standalone worker."""
    run_worker()


if __name__ == "__main__":
    main()
