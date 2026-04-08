"""Database helpers."""

from __future__ import annotations

from fastapi import Request
from sqlmodel import SQLModel, Session, create_engine

from . import models  # noqa: F401


def create_db_engine(database_url: str):
    """Create a SQLModel engine with SQLite-safe defaults."""
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    return create_engine(database_url, connect_args=connect_args)


def init_database(engine) -> None:
    """Create tables for all registered SQLModel models."""
    SQLModel.metadata.create_all(engine)
    if not engine.url.drivername.startswith("sqlite"):
        return

    sqlite_column_defaults = {
        models.GraphJob.__table__.name: {
            "error_message": "TEXT NOT NULL DEFAULT ''",
            "progress_percent": "REAL NOT NULL DEFAULT 0",
            "status_message": "TEXT NOT NULL DEFAULT ''",
            "started_at": "TIMESTAMP",
            "completed_at": "TIMESTAMP",
        },
        models.Simulation.__table__.name: {
            "error_message": "TEXT NOT NULL DEFAULT ''",
            "progress_percent": "REAL NOT NULL DEFAULT 0",
            "status_message": "TEXT NOT NULL DEFAULT ''",
            "started_at": "TIMESTAMP",
            "completed_at": "TIMESTAMP",
        },
        models.Report.__table__.name: {
            "error_message": "TEXT NOT NULL DEFAULT ''",
            "progress_percent": "REAL NOT NULL DEFAULT 0",
            "status_message": "TEXT NOT NULL DEFAULT ''",
            "started_at": "TIMESTAMP",
            "completed_at": "TIMESTAMP",
        },
    }
    with engine.begin() as connection:
        for table_name, columns in sqlite_column_defaults.items():
            existing_columns = {
                row[1]
                for row in connection.exec_driver_sql(f"PRAGMA table_info('{table_name}')").fetchall()
            }
            for column_name, definition in columns.items():
                if column_name in existing_columns:
                    continue
                connection.exec_driver_sql(
                    f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}"
                )


def get_session(request: Request):
    """Yield a database session bound to the application engine."""
    with Session(request.app.state.engine) as session:
        session.info["settings"] = request.app.state.settings
        session.info["registry"] = request.app.state.registry
        session.info["workflow_runner"] = request.app.state.workflow_runner
        yield session
