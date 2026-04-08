"""Simulation routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import Session

from ..database import get_session
from ..models import WorkflowKind
from ..schemas import ListResponse, SimulationCreate, SimulationEvent, SimulationRead, WorkflowUpdateRead
from ..services.workflows import create_simulation
from ..services.runtime import (
    get_graph_job_or_404,
    get_project_or_404,
    get_simulation_or_404,
    list_simulation_events,
    list_simulations,
    list_workflow_updates,
    simulation_read_model,
    workflow_update_read_model,
)

router = APIRouter(prefix="/simulations", tags=["simulations"])


@router.get("", response_model=ListResponse[SimulationRead])
def get_simulation_list(
    project_id: str | None = Query(default=None),
    session: Session = Depends(get_session),
) -> ListResponse[SimulationRead]:
    """List simulations."""
    simulations = list_simulations(session, project_id=project_id)
    return ListResponse(items=[simulation_read_model(item) for item in simulations])


@router.post("", response_model=SimulationRead, status_code=status.HTTP_201_CREATED)
def create_simulation_run(
    payload: SimulationCreate,
    session: Session = Depends(get_session),
) -> SimulationRead:
    """Queue a simulation."""
    project = get_project_or_404(session, payload.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    graph_job = get_graph_job_or_404(session, payload.graph_job_id) if payload.graph_job_id else None
    if graph_job and graph_job.project_id != project.id:
        raise HTTPException(status_code=400, detail="Graph job does not belong to the selected project")
    simulation = create_simulation(
        session,
        project=project,
        graph_job=graph_job,
        mode=payload.mode,
        cohort_size=payload.cohort_size,
    )
    response = simulation_read_model(simulation)
    workflow_runner = session.info.get("workflow_runner")
    if workflow_runner:
        workflow_runner.notify()
    return response


@router.get("/{simulation_id}", response_model=SimulationRead)
def get_simulation(simulation_id: str, session: Session = Depends(get_session)) -> SimulationRead:
    """Fetch a simulation by id."""
    simulation = get_simulation_or_404(session, simulation_id)
    if not simulation:
        raise HTTPException(status_code=404, detail="Simulation not found")
    return simulation_read_model(simulation)


@router.get("/{simulation_id}/events", response_model=ListResponse[SimulationEvent])
def get_simulation_events(simulation_id: str, session: Session = Depends(get_session)) -> ListResponse[SimulationEvent]:
    """List decoded simulation events for a simulation."""
    simulation = get_simulation_or_404(session, simulation_id)
    if not simulation:
        raise HTTPException(status_code=404, detail="Simulation not found")
    return ListResponse(items=list_simulation_events(session, simulation_id))


@router.get("/{simulation_id}/updates", response_model=ListResponse[WorkflowUpdateRead])
def get_simulation_updates(
    simulation_id: str,
    session: Session = Depends(get_session),
) -> ListResponse[WorkflowUpdateRead]:
    """List persisted workflow updates for a simulation."""
    simulation = get_simulation_or_404(session, simulation_id)
    if not simulation:
        raise HTTPException(status_code=404, detail="Simulation not found")
    updates = list_workflow_updates(session, WorkflowKind.simulation, simulation_id)
    return ListResponse(items=[workflow_update_read_model(item) for item in updates])
