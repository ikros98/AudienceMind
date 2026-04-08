"""Request and response models for PersonaGraph APIs."""

from __future__ import annotations

from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

from .models import WorkflowKind, WorkflowStatus


class HealthResponse(BaseModel):
    """Health endpoint response."""

    service: str
    env: str
    database_url: str
    llm_provider: str
    graph_backend: str
    simulation_backend: str
    report_backend: str
    workflow_runner_mode: str
    queue_depth: int
    running_count: int
    data_dir: str


class ProjectCreate(BaseModel):
    """Create-project request."""

    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    scenario_brief: str = Field(min_length=1, max_length=4000)


class SourceNoteCreate(BaseModel):
    """Create a source note from pasted analyst text."""

    title: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=40000)


class ProjectRead(BaseModel):
    """Project response."""

    id: str
    name: str
    description: str
    scenario_brief: str
    status: WorkflowStatus
    source_count: int
    created_at: datetime
    updated_at: datetime


class SourceDocumentRead(BaseModel):
    """Source document metadata returned to the frontend."""

    id: str
    project_id: str
    filename: str
    content_type: str
    byte_size: int
    text_excerpt: str
    created_at: datetime


class GraphJobCreate(BaseModel):
    """Create-graph-job request."""

    graph_backend: str = "graphiti"
    objective: str = ""


class GraphJobRead(BaseModel):
    """Graph job response."""

    id: str
    project_id: str
    graph_backend: str
    objective: str
    status: WorkflowStatus
    progress_percent: float
    status_message: str
    summary: str
    source_digest: str
    node_count: int
    edge_count: int
    schema_markdown: str
    evidence_markdown: str
    error_message: str
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class SimulationCreate(BaseModel):
    """Create-simulation request."""

    project_id: str
    graph_job_id: str | None = None
    mode: str = "analysis"
    cohort_size: int = Field(default=250, ge=1, le=100000)


class SimulationRead(BaseModel):
    """Simulation response."""

    id: str
    project_id: str
    graph_job_id: str | None
    mode: str
    cohort_size: int
    status: WorkflowStatus
    progress_percent: float
    status_message: str
    summary: str
    rounds: int
    event_count: int
    timeline_markdown: str
    events: list["SimulationEvent"]
    error_message: str
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class SimulationEvent(BaseModel):
    """Synthetic event emitted by the simulation workflow."""

    round: int
    channel: str
    title: str
    impact: str
    implication: str


class ReportCreate(BaseModel):
    """Create-report request."""

    simulation_id: str
    focus: str = ""


class ReportRead(BaseModel):
    """Report response."""

    id: str
    simulation_id: str
    focus: str
    status: WorkflowStatus
    progress_percent: float
    status_message: str
    summary: str
    executive_summary: str
    markdown_body: str
    error_message: str
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class WorkflowUpdateRead(BaseModel):
    """Persisted progress update for a workflow record."""

    id: str
    workflow_kind: WorkflowKind
    workflow_id: str
    status: WorkflowStatus
    level: str
    message: str
    progress_percent: float
    created_at: datetime


class AnalysisChatRequest(BaseModel):
    """Chat request against generated project artifacts."""

    simulation_id: str
    report_id: str | None = None
    message: str = Field(min_length=1, max_length=4000)


class AnalysisChatResponse(BaseModel):
    """Chat answer returned to the analysis workspace."""

    answer: str
    supporting_points: list[str]
    used_report_id: str | None
    used_simulation_id: str


ItemT = TypeVar("ItemT")


class ListResponse(BaseModel, Generic[ItemT]):
    """Generic list response."""

    items: list[ItemT]
