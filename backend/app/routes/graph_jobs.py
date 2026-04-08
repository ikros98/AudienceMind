"""Graph job routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import Session

from ..database import get_session
from ..models import WorkflowKind
from ..schemas import GraphJobCreate, GraphJobRead, ListResponse, WorkflowUpdateRead
from ..services.workflows import create_graph_job
from ..services.runtime import (
    get_graph_job_or_404,
    get_project_or_404,
    graph_job_read_model,
    list_graph_jobs,
    list_workflow_updates,
    workflow_update_read_model,
)

router = APIRouter(prefix="/graph-jobs", tags=["graph-jobs"])


def build_graph_job_for_project(
    session: Session,
    project_id: str,
    payload: GraphJobCreate,
) -> GraphJobRead:
    """Shared project-scoped graph job creation."""
    project = get_project_or_404(session, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    job = create_graph_job(session, project, payload.graph_backend, payload.objective)
    response = graph_job_read_model(job)
    workflow_runner = session.info.get("workflow_runner")
    if workflow_runner:
        workflow_runner.notify()
    return response


@router.get("", response_model=ListResponse[GraphJobRead])
def get_graph_jobs(
    project_id: str | None = Query(default=None),
    session: Session = Depends(get_session),
) -> ListResponse[GraphJobRead]:
    """List graph build jobs."""
    jobs = list_graph_jobs(session, project_id=project_id)
    return ListResponse(items=[graph_job_read_model(item) for item in jobs])


@router.post("/projects/{project_id}", response_model=GraphJobRead, status_code=status.HTTP_201_CREATED)
def enqueue_graph_job(
    project_id: str,
    payload: GraphJobCreate,
    session: Session = Depends(get_session),
) -> GraphJobRead:
    """Queue a graph build job for a project."""
    return build_graph_job_for_project(session, project_id, payload)


@router.get("/projects/{project_id}", response_model=ListResponse[GraphJobRead])
def get_project_graph_jobs(project_id: str, session: Session = Depends(get_session)) -> ListResponse[GraphJobRead]:
    """List graph jobs for a single project."""
    project = get_project_or_404(session, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    jobs = list_graph_jobs(session, project_id=project_id)
    return ListResponse(items=[graph_job_read_model(item) for item in jobs])


project_router = APIRouter(prefix="/projects", tags=["graph-jobs"])


@project_router.get("/{project_id}/graph-jobs", response_model=ListResponse[GraphJobRead])
def get_project_graph_jobs_alias(project_id: str, session: Session = Depends(get_session)) -> ListResponse[GraphJobRead]:
    """Alias for project-scoped graph jobs used by the frontend workspace."""
    return get_project_graph_jobs(project_id, session)


@project_router.post("/{project_id}/graph-jobs", response_model=GraphJobRead, status_code=status.HTTP_201_CREATED)
def enqueue_graph_job_alias(
    project_id: str,
    payload: GraphJobCreate,
    session: Session = Depends(get_session),
) -> GraphJobRead:
    """Alias for project-scoped graph job creation used by the frontend workspace."""
    return build_graph_job_for_project(session, project_id, payload)


@router.get("/{job_id}", response_model=GraphJobRead)
def get_graph_job(job_id: str, session: Session = Depends(get_session)) -> GraphJobRead:
    """Fetch a graph job by id."""
    job = get_graph_job_or_404(session, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Graph job not found")
    return graph_job_read_model(job)


@router.get("/{job_id}/updates", response_model=ListResponse[WorkflowUpdateRead])
def get_graph_job_updates(job_id: str, session: Session = Depends(get_session)) -> ListResponse[WorkflowUpdateRead]:
    """List persisted workflow updates for a graph job."""
    job = get_graph_job_or_404(session, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Graph job not found")
    updates = list_workflow_updates(session, WorkflowKind.graph_job, job_id)
    return ListResponse(items=[workflow_update_read_model(item) for item in updates])
