"""Analysis routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from ..database import get_session
from ..models import WorkflowStatus
from ..schemas import AnalysisChatRequest, AnalysisChatResponse
from ..services.runtime import (
    get_project_or_404,
    get_report_or_404,
    get_simulation_or_404,
)

router = APIRouter(prefix="/analysis", tags=["analysis"])


@router.post("/chat", response_model=AnalysisChatResponse)
def analysis_chat(
    payload: AnalysisChatRequest,
    session: Session = Depends(get_session),
) -> AnalysisChatResponse:
    """Answer a question using the current project, simulation, and report artifacts."""
    simulation = get_simulation_or_404(session, payload.simulation_id)
    if not simulation:
        raise HTTPException(status_code=404, detail="Simulation not found")
    if simulation.status != WorkflowStatus.completed:
        raise HTTPException(status_code=400, detail="Simulation is not ready for analysis chat")

    project = get_project_or_404(session, simulation.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    report = get_report_or_404(session, payload.report_id) if payload.report_id else None
    if report and report.simulation_id != simulation.id:
        raise HTTPException(status_code=400, detail="Report does not belong to the selected simulation")
    if report and report.status != WorkflowStatus.completed:
        raise HTTPException(status_code=400, detail="Report is not ready for analysis chat")
    registry = session.info["registry"]
    answer, supporting_points = registry.reporting.answer_question(
        llm=registry.llm,
        project=project,
        simulation=simulation,
        report=report,
        message=payload.message,
    )
    return AnalysisChatResponse(
        answer=answer,
        supporting_points=supporting_points,
        used_report_id=report.id if report else None,
        used_simulation_id=simulation.id,
    )
