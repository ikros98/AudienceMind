"""Report routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import Session

from ..database import get_session
from ..models import WorkflowKind
from ..schemas import ListResponse, ReportCreate, ReportRead, WorkflowUpdateRead
from ..services.workflows import create_report
from ..services.runtime import (
    get_project_or_404,
    get_report_or_404,
    get_simulation_or_404,
    list_reports,
    list_workflow_updates,
    report_read_model,
    workflow_update_read_model,
)

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("", response_model=ListResponse[ReportRead])
def get_report_list(
    simulation_id: str | None = Query(default=None),
    session: Session = Depends(get_session),
) -> ListResponse[ReportRead]:
    """List reports."""
    reports = list_reports(session, simulation_id=simulation_id)
    return ListResponse(items=[report_read_model(item) for item in reports])


@router.post("", response_model=ReportRead, status_code=status.HTTP_201_CREATED)
def create_report_request(
    payload: ReportCreate,
    session: Session = Depends(get_session),
) -> ReportRead:
    """Queue a report."""
    simulation = get_simulation_or_404(session, payload.simulation_id)
    if not simulation:
        raise HTTPException(status_code=404, detail="Simulation not found")
    project = get_project_or_404(session, simulation.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    report = create_report(session, project, simulation, payload.focus)
    response = report_read_model(report)
    workflow_runner = session.info.get("workflow_runner")
    if workflow_runner:
        workflow_runner.notify()
    return response


@router.get("/{report_id}", response_model=ReportRead)
def get_report(report_id: str, session: Session = Depends(get_session)) -> ReportRead:
    """Fetch a report by id."""
    report = get_report_or_404(session, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return report_read_model(report)


@router.get("/{report_id}/updates", response_model=ListResponse[WorkflowUpdateRead])
def get_report_updates(report_id: str, session: Session = Depends(get_session)) -> ListResponse[WorkflowUpdateRead]:
    """List persisted workflow updates for a report."""
    report = get_report_or_404(session, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    updates = list_workflow_updates(session, WorkflowKind.report, report_id)
    return ListResponse(items=[workflow_update_read_model(item) for item in updates])
