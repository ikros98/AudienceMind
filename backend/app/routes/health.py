"""Health route."""

from __future__ import annotations

from fastapi import APIRouter, Request
from sqlmodel import Session
from urllib.parse import urlsplit, urlunsplit

from ..schemas import HealthResponse
from ..services.runtime import workflow_counts

router = APIRouter(tags=["health"])


def redact_database_url(database_url: str) -> str:
    """Hide embedded credentials before returning runtime metadata."""
    parsed = urlsplit(database_url)
    if not parsed.username and not parsed.password:
        return database_url

    host = parsed.hostname or ""
    if parsed.port:
        host = f"{host}:{parsed.port}"
    credential_prefix = "***:***@" if parsed.password else "***@"
    return urlunsplit((parsed.scheme, f"{credential_prefix}{host}", parsed.path, parsed.query, parsed.fragment))


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    """Return service metadata for local verification."""
    settings = request.app.state.settings
    registry = request.app.state.registry
    workflow_runner_mode = "embedded" if request.app.state.workflow_runner else "external"
    with Session(request.app.state.engine) as session:
        queue_depth, running_count = workflow_counts(session)
    return HealthResponse(
        service=settings.app_name,
        env=settings.env,
        database_url=redact_database_url(settings.database_url),
        llm_provider=registry.llm.name,
        graph_backend=registry.graph.name,
        simulation_backend=registry.simulation.name,
        report_backend=registry.reporting.name,
        workflow_runner_mode=workflow_runner_mode,
        queue_depth=queue_depth,
        running_count=running_count,
        data_dir=settings.data_dir,
    )
