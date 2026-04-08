"""SQLModel tables for PersonaGraph workflow state and generated artifacts."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import uuid4

from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


class WorkflowStatus(str, Enum):
    """Shared status values used across project workflow objects."""

    draft = "draft"
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"


class WorkflowKind(str, Enum):
    """Supported workflow record kinds."""

    graph_job = "graph_job"
    simulation = "simulation"
    report = "report"


class Project(SQLModel, table=True):
    """Project metadata and analyst intent."""

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    name: str
    description: str = ""
    scenario_brief: str
    status: WorkflowStatus = WorkflowStatus.draft
    created_at: datetime = Field(default_factory=utc_now, nullable=False)
    updated_at: datetime = Field(default_factory=utc_now, nullable=False)


class SourceDocument(SQLModel, table=True):
    """Uploaded or pasted source material attached to a project."""

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    project_id: str = Field(index=True)
    filename: str
    content_type: str = "text/plain"
    byte_size: int = 0
    storage_path: str = ""
    text_excerpt: str = ""
    extracted_text: str = ""
    created_at: datetime = Field(default_factory=utc_now, nullable=False)


class GraphJob(SQLModel, table=True):
    """Graph build job metadata."""

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    project_id: str = Field(index=True)
    graph_backend: str = "graphiti"
    objective: str = ""
    status: WorkflowStatus = WorkflowStatus.queued
    progress_percent: float = 0.0
    status_message: str = ""
    summary: str = ""
    source_digest: str = ""
    node_count: int = 0
    edge_count: int = 0
    schema_markdown: str = ""
    evidence_markdown: str = ""
    error_message: str = ""
    started_at: datetime | None = Field(default=None, nullable=True)
    completed_at: datetime | None = Field(default=None, nullable=True)
    created_at: datetime = Field(default_factory=utc_now, nullable=False)
    updated_at: datetime = Field(default_factory=utc_now, nullable=False)


class Simulation(SQLModel, table=True):
    """Simulation run metadata."""

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    project_id: str = Field(index=True)
    graph_job_id: Optional[str] = Field(default=None, index=True)
    mode: str = "analysis"
    cohort_size: int = 250
    status: WorkflowStatus = WorkflowStatus.queued
    progress_percent: float = 0.0
    status_message: str = ""
    summary: str = ""
    rounds: int = 0
    event_count: int = 0
    timeline_markdown: str = ""
    event_log_json: str = "[]"
    error_message: str = ""
    started_at: datetime | None = Field(default=None, nullable=True)
    completed_at: datetime | None = Field(default=None, nullable=True)
    created_at: datetime = Field(default_factory=utc_now, nullable=False)
    updated_at: datetime = Field(default_factory=utc_now, nullable=False)


class Report(SQLModel, table=True):
    """Analysis report metadata."""

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    simulation_id: str = Field(index=True)
    focus: str = ""
    status: WorkflowStatus = WorkflowStatus.queued
    progress_percent: float = 0.0
    status_message: str = ""
    summary: str = ""
    executive_summary: str = ""
    markdown_body: str = ""
    error_message: str = ""
    started_at: datetime | None = Field(default=None, nullable=True)
    completed_at: datetime | None = Field(default=None, nullable=True)
    created_at: datetime = Field(default_factory=utc_now, nullable=False)
    updated_at: datetime = Field(default_factory=utc_now, nullable=False)


class WorkflowUpdate(SQLModel, table=True):
    """Durable status update emitted while a workflow record progresses."""

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    workflow_kind: WorkflowKind = Field(index=True)
    workflow_id: str = Field(index=True)
    status: WorkflowStatus
    level: str = "info"
    message: str = ""
    progress_percent: float = 0.0
    created_at: datetime = Field(default_factory=utc_now, nullable=False)
