"""Legacy-compatible API surface for the React glass frontend."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import time
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlmodel import Session, select

from ..database import get_session
from ..models import GraphJob, Project, Report, Simulation, SourceDocument, WorkflowKind, WorkflowStatus, WorkflowUpdate
from ..services.generation import (
    build_glass_interview_response,
    build_glass_profiles,
    build_glass_report_chat_response,
    sanitize_short_model_text,
    top_terms,
)
from ..services.glass_compat import (
    GlassRuntimeManager,
    SYNTHETIC_GRAPH_ERROR_MESSAGE,
    SyntheticGraphError,
    append_simulation_interviews,
    compact_graph_payload_for_display,
    build_history_entry,
    create_glass_project,
    ensure_graph_materialized,
    envelope_error,
    envelope_ok,
    ensure_real_graph_payload,
    fetch_graphiti_payload,
    glass_project_status,
    graph_base_path,
    graph_entities_for_preparation,
    graph_payload_is_synthetic,
    graph_live_path,
    latest_graph_job,
    latest_report,
    load_graph_base_payload,
    load_graph_payload,
    load_project_metadata,
    load_report_evidence,
    load_simulation_actions,
    load_simulation_comments,
    load_simulation_config,
    load_simulation_env,
    load_simulation_interviews,
    load_simulation_profiles,
    load_simulation_posts,
    load_simulation_state,
    prepare_task_path,
    project_dir,
    project_metadata_path,
    report_dir,
    reset_graph_from_base,
    persist_graph_job_failure,
    save_graph_base_payload,
    save_graph_payload,
    save_simulation_env,
    save_simulation_state,
    simulation_dir,
    simulation_actions_path,
    simulation_config_path,
    simulation_profiles_path,
    simulation_state_path,
)
from ..services.graphiti import GraphitiClient
from ..services.oasis_runtime import send_ipc_command
from ..services.runtime import (
    get_project_or_404,
    get_report_or_404,
    get_simulation_or_404,
    list_graph_jobs,
    list_projects,
    list_reports,
    list_simulations,
    list_source_documents,
)
router = APIRouter(tags=["legacy-compat"])


def _glass_runtime(request: Request) -> GlassRuntimeManager:
    runtime = getattr(request.app.state, "glass_runtime", None)
    if runtime is None:
        raise HTTPException(status_code=500, detail="Glass runtime is not initialized")
    return runtime


def _file_modified_iso(path: Path) -> str:
    if not path.exists():
        return datetime.now(timezone.utc).isoformat()
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()


def _latest_graph_for_project(session: Session, project_id: str) -> GraphJob | None:
    return latest_graph_job(session, project_id)


def _project_payload(session: Session, request: Request, project: Project) -> dict[str, Any]:
    settings = request.app.state.settings
    metadata = load_project_metadata(settings, project.id)
    graph_job = _latest_graph_for_project(session, project.id)
    documents = list_source_documents(session, project.id)
    if graph_job and graph_job.status in {WorkflowStatus.queued, WorkflowStatus.running}:
        _recover_graph_job_if_materialized(session, request, graph_job, project)
        session.refresh(graph_job)
        session.refresh(project)
    if graph_job and graph_job.status == WorkflowStatus.completed:
        try:
            ensure_graph_materialized(session, settings, project=project, graph_job=graph_job)
        except SyntheticGraphError as exc:
            persist_graph_job_failure(
                session,
                graph_job=graph_job,
                project=project,
                message=str(exc),
            )
            session.refresh(graph_job)
            session.refresh(project)
    return {
        "project_id": project.id,
        "name": project.name,
        "status": glass_project_status(project, graph_job, metadata),
        "created_at": project.created_at.isoformat(),
        "updated_at": project.updated_at.isoformat(),
        "file_count": len(documents),
        "files": [
            {"filename": item.filename, "size": item.byte_size}
            for item in documents
        ],
        "simulation_requirement": project.scenario_brief,
        "analysis_summary": sanitize_short_model_text(
            str(metadata.get("analysis_summary", "")).strip() or None,
            f"Prepared an analyst ontology for {project.name or 'the project'}.",
        ),
        "graph_id": graph_job.id if graph_job else None,
        "graph_build_task_id": graph_job.id if graph_job and graph_job.status != WorkflowStatus.completed else None,
        "ontology": metadata.get("ontology"),
        "total_text_length": metadata.get("total_text_length", 0),
        "error": graph_job.error_message if graph_job and graph_job.status == WorkflowStatus.failed else None,
    }


def _recover_graph_job_if_materialized(
    session: Session,
    request: Request,
    graph_job: GraphJob,
    project: Project | None,
) -> bool:
    settings = request.app.state.settings
    if graph_job.status not in {WorkflowStatus.queued, WorkflowStatus.running}:
        return False
    if _glass_runtime(request).graph_build_is_active(graph_job.id):
        return False

    payload = load_graph_payload(settings, graph_job.id)
    if not payload.get("nodes"):
        if settings.graph_backend != "graphiti" or settings.llm_provider == "test":
            return False
        try:
            payload = fetch_graphiti_payload(settings, graph_job.id)
            ensure_real_graph_payload(payload)
        except Exception:  # noqa: BLE001
            return False
        save_graph_base_payload(settings, graph_job.id, payload)
        save_graph_payload(settings, graph_job.id, payload)
    elif graph_payload_is_synthetic(payload):
        return False

    metadata = payload.get("metadata", {}) if isinstance(payload, dict) else {}
    node_count = int(metadata.get("node_count") or 0)
    edge_count = int(metadata.get("edge_count") or 0)
    if node_count <= 0:
        return False

    graph_job.status = WorkflowStatus.completed
    graph_job.progress_percent = 100
    graph_job.status_message = "Graph build completed."
    graph_job.error_message = ""
    graph_job.node_count = node_count
    graph_job.edge_count = edge_count
    graph_job.summary = graph_job.summary or f"Materialized a real graph with {node_count} nodes and {edge_count} edges."
    graph_job.completed_at = datetime.now(timezone.utc)
    graph_job.updated_at = datetime.now(timezone.utc)
    session.add(graph_job)
    if project:
        project.status = WorkflowStatus.running
        project.updated_at = datetime.now(timezone.utc)
        session.add(project)
    session.commit()
    return True


def _selected_graph_payload(session: Session, request: Request, graph_id: str, *, baseline: bool = False) -> dict[str, Any]:
    settings = request.app.state.settings
    graph_job = session.get(GraphJob, graph_id)
    project = session.get(Project, graph_job.project_id) if graph_job else None
    graph_build_active = bool(graph_job and _glass_runtime(request).graph_build_is_active(graph_job.id))
    if graph_job and graph_job.status in {WorkflowStatus.queued, WorkflowStatus.running} and not graph_build_active:
        _recover_graph_job_if_materialized(session, request, graph_job, project)
        session.refresh(graph_job)
        if project:
            session.refresh(project)
    if graph_job and graph_job.status == WorkflowStatus.failed and graph_job.error_message:
        raise SyntheticGraphError(str(graph_job.error_message))
    payload = load_graph_base_payload(settings, graph_id) if baseline else load_graph_payload(settings, graph_id)
    if graph_build_active:
        raise HTTPException(status_code=404, detail="Graph is still building")
    if payload.get("nodes"):
        if graph_payload_is_synthetic(payload):
            if graph_job and project:
                persist_graph_job_failure(
                    session,
                    graph_job=graph_job,
                    project=project,
                    message=SYNTHETIC_GRAPH_ERROR_MESSAGE,
                )
            raise SyntheticGraphError(SYNTHETIC_GRAPH_ERROR_MESSAGE)
        return payload
    if not graph_job or graph_job.status != WorkflowStatus.completed:
        raise HTTPException(status_code=404, detail="Graph not found")
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    ensure_graph_materialized(session, settings, project=project, graph_job=graph_job)
    payload = load_graph_base_payload(settings, graph_id) if baseline else load_graph_payload(settings, graph_id)
    if graph_payload_is_synthetic(payload):
        persist_graph_job_failure(
            session,
            graph_job=graph_job,
            project=project,
            message=SYNTHETIC_GRAPH_ERROR_MESSAGE,
        )
        raise SyntheticGraphError(SYNTHETIC_GRAPH_ERROR_MESSAGE)
    return payload


def _latest_report_for_simulation(session: Session, simulation_id: str) -> Report | None:
    return latest_report(session, simulation_id)


def _graph_task_payload(graph_job: GraphJob) -> dict[str, Any]:
    status_map = {
        WorkflowStatus.queued: "pending",
        WorkflowStatus.running: "processing",
        WorkflowStatus.completed: "completed",
        WorkflowStatus.failed: "failed",
    }
    return {
        "task_id": graph_job.id,
        "status": status_map.get(graph_job.status, "pending"),
        "progress": graph_job.progress_percent,
        "message": graph_job.status_message or "Task update",
        "error": graph_job.error_message or None,
        "result": {"graph_id": graph_job.id, "project_id": graph_job.project_id}
        if graph_job.status == WorkflowStatus.completed
        else None,
        "created_at": graph_job.created_at.isoformat(),
        "updated_at": graph_job.updated_at.isoformat(),
    }


def _report_payload(report: Report, request: Request) -> dict[str, Any]:
    state = _load_report_state(report.id, request)
    return {
        "report_id": report.id,
        "simulation_id": report.simulation_id,
        "status": state.get("status", report.status.value),
        "summary": report.summary,
        "created_at": report.created_at.isoformat(),
        "updated_at": report.updated_at.isoformat(),
        "completed_at": report.completed_at.isoformat() if report.completed_at else "",
        "error": report.error_message or None,
    }


def _delete_path(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    elif path.exists():
        path.unlink(missing_ok=True)


def _compat_scripts_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "scripts" / "compat"


def _delete_workflow_updates(session: Session, workflow_ids: set[str]) -> None:
    if not workflow_ids:
        return
    statement = select(WorkflowUpdate).where(WorkflowUpdate.workflow_id.in_(workflow_ids))
    for item in session.exec(statement):
        session.delete(item)


def _delete_graph_job_artifacts(settings, graph_id: str) -> None:
    _delete_path(graph_live_path(settings, graph_id))
    _delete_path(graph_base_path(settings, graph_id))


def _delete_project_tree(
    session: Session,
    request: Request,
    project: Project,
) -> None:
    settings = request.app.state.settings
    graph_jobs = list_graph_jobs(session, project.id)
    simulations = list_simulations(session, project.id)
    reports = [report for simulation in simulations for report in list_reports(session, simulation.id)]
    workflow_ids = {item.id for item in graph_jobs} | {item.id for item in simulations} | {item.id for item in reports}
    _delete_workflow_updates(session, workflow_ids)

    for report in reports:
        _delete_path(report_dir(settings, report.id))
        session.delete(report)

    for simulation in simulations:
        state = load_simulation_state(settings, simulation.id)
        if str(state.get("runner_status") or "") in {"starting", "running"}:
            raise HTTPException(status_code=409, detail=f"Simulation {simulation.id} is still running")
        _delete_path(simulation_dir(settings, simulation.id))
        session.delete(simulation)

    if settings.graph_backend == "graphiti" and settings.graphiti_base_url and settings.llm_provider != "test":
        client = GraphitiClient(settings)
        try:
            for graph_job in graph_jobs:
                client.delete_graph(graph_job.id, ignore_missing=True)
        finally:
            client.close()

    for graph_job in graph_jobs:
        if _glass_runtime(request).graph_build_is_active(graph_job.id):
            raise HTTPException(status_code=409, detail=f"Graph build {graph_job.id} is still running")
        _delete_graph_job_artifacts(settings, graph_job.id)
        session.delete(graph_job)

    documents = session.exec(select(SourceDocument).where(SourceDocument.project_id == project.id)).all()
    for document in documents:
        storage_path = Path(str(document.storage_path or ""))
        if str(storage_path):
            _delete_path(storage_path)
        session.delete(document)

    source_root = Path(settings.data_dir).resolve() / "sources" / project.id
    _delete_path(source_root)
    _delete_path(project_dir(settings, project.id))
    session.delete(project)


def _graph_entities(
    graph_payload: dict[str, Any],
    *,
    entity_types: set[str] | None = None,
    enrich: bool = True,
) -> dict[str, Any]:
    payload = graph_entities_for_preparation(graph_payload, entity_types=entity_types)
    if enrich:
        return payload
    return {
        **payload,
        "entities": [
            {
                **item,
                "related_edges": [],
                "related_nodes": [],
            }
            for item in payload.get("entities", [])
            if isinstance(item, dict)
        ],
    }


def _interview_response_for_profile(
    request: Request,
    project: Project,
    profile: dict[str, Any],
    prompt: str,
    actions: list[dict[str, Any]],
    *,
    platform: str | None,
) -> str:
    scoped_actions = [
        item
        for item in actions
        if item.get("agent_id") == profile.get("agent_id")
        and (platform is None or str(item.get("platform") or "") == platform)
    ][-4:]
    prompt_text = prompt if platform is None else f"[{platform}] {prompt}"
    return build_glass_interview_response(
        request.app.state.registry.llm,
        project=project,
        profile=profile,
        prompt=prompt_text,
        recent_actions=scoped_actions,
    )


def _profile_map(settings, simulation_id: str) -> dict[str, dict[str, Any]]:
    return {
        str(item["agent_id"]): item
        for item in load_simulation_profiles(settings, simulation_id, "reddit")
        if isinstance(item, dict) and item.get("agent_id")
    }


def _uses_oasis_runtime(settings, simulation_id: str) -> bool:
    state = load_simulation_state(settings, simulation_id)
    return str(state.get("runtime_kind") or "") == "oasis-worker"


def _section_payloads(report_id: str, request: Request) -> list[dict[str, Any]]:
    sections_root = report_dir(request.app.state.settings, report_id) / "sections"
    items: list[dict[str, Any]] = []
    for index, path in enumerate(sorted(sections_root.glob("*.md")), start=1):
        items.append(
            {
                "report_id": report_id,
                "section_index": index,
                "filename": path.name,
                "content": path.read_text(encoding="utf-8"),
            }
        )
    return items


def _load_report_state(report_id: str, request: Request) -> dict[str, Any]:
    state_path = report_dir(request.app.state.settings, report_id) / "state.json"
    if not state_path.exists():
        return {"report_id": report_id, "status": "pending", "progress": 0, "message": "Report pending."}
    from ..services.glass_compat import _read_json  # local import to keep helper private

    payload = _read_json(state_path, {})
    return payload if isinstance(payload, dict) else {"report_id": report_id, "status": "pending", "progress": 0}


@router.post("/api/graph/ontology/generate")
async def generate_ontology(
    request: Request,
    files: list[UploadFile] = File(...),
    simulation_requirement: str = Form(...),
    project_name: str | None = Form(default=None),
    additional_context: str | None = Form(default=None),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Create a project and derive an ontology from the uploaded sources."""
    settings = request.app.state.settings
    registry = request.app.state.registry
    uploaded: list[tuple[str, str, bytes]] = []
    file_meta: list[dict[str, Any]] = []
    for upload in files:
        raw_bytes = await upload.read()
        if not raw_bytes:
            continue
        filename = upload.filename or "source.txt"
        content_type = upload.content_type or "application/octet-stream"
        uploaded.append((filename, content_type, raw_bytes))
        file_meta.append({"filename": filename, "size": len(raw_bytes)})
    if not uploaded:
        return envelope_error("Please upload at least one non-empty file.")

    project, ontology, analysis_summary, total_text_length = create_glass_project(
        session,
        settings,
        registry,
        name=(project_name or "Unnamed Project").strip() or "Unnamed Project",
        requirement=simulation_requirement,
        additional_context=additional_context or "",
        files=uploaded,
    )
    return envelope_ok(
        {
            "project_id": project.id,
            "project_name": project.name,
            "ontology": ontology,
            "analysis_summary": analysis_summary,
            "files": file_meta,
            "total_text_length": total_text_length,
        }
    )


@router.post("/api/graph/build")
def build_graph(request: Request, payload: dict[str, Any], session: Session = Depends(get_session)) -> dict[str, Any]:
    """Queue graph materialization for the selected project."""
    project_id = str(payload.get("project_id", "")).strip()
    project = get_project_or_404(session, project_id)
    if not project:
        return envelope_error("Project not found")

    objective = str(payload.get("graph_name") or payload.get("objective") or project.scenario_brief)
    graph_job = GraphJob(
        project_id=project.id,
        graph_backend="graphiti",
        objective=objective,
        status=WorkflowStatus.running,
        progress_percent=1.0,
        status_message="Starting graph build.",
        error_message="",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        started_at=datetime.now(timezone.utc),
    )
    project.status = WorkflowStatus.running
    project.updated_at = datetime.now(timezone.utc)
    session.add(graph_job)
    session.add(project)
    session.commit()
    session.refresh(graph_job)
    _glass_runtime(request).start_graph_build(graph_job.id)
    return envelope_ok(
        {
            "project_id": project.id,
            "task_id": graph_job.id,
            "message": "Graph build task started. Query progress via /task/{task_id}.",
        }
    )


@router.get("/api/graph/task/{task_id}")
def get_graph_task(task_id: str, request: Request, session: Session = Depends(get_session)) -> dict[str, Any]:
    """Return legacy task status payload for a graph job."""
    graph_job = session.get(GraphJob, task_id)
    if not graph_job:
        return envelope_error("Task not found")
    project = session.get(Project, graph_job.project_id)
    if graph_job.status in {WorkflowStatus.queued, WorkflowStatus.running}:
        _recover_graph_job_if_materialized(session, request, graph_job, project)
        session.refresh(graph_job)
    if graph_job.status == WorkflowStatus.completed:
        if project:
            try:
                ensure_graph_materialized(
                    session,
                    request.app.state.settings,
                    project=project,
                    graph_job=graph_job,
                )
            except SyntheticGraphError as exc:
                persist_graph_job_failure(
                    session,
                    graph_job=graph_job,
                    project=project,
                    message=str(exc),
                )
                session.refresh(graph_job)
    return envelope_ok(_graph_task_payload(graph_job))


@router.get("/api/graph/tasks")
def get_graph_tasks(session: Session = Depends(get_session)) -> dict[str, Any]:
    """List graph build tasks in the legacy task envelope."""
    items = [_graph_task_payload(item) for item in list_graph_jobs(session)]
    return {"success": True, "data": items, "count": len(items)}


@router.get("/api/graph/project/list")
def get_project_list(request: Request, session: Session = Depends(get_session)) -> dict[str, Any]:
    """List projects in the legacy glass format."""
    payload = [_project_payload(session, request, project) for project in list_projects(session)]
    return envelope_ok(payload)


@router.get("/api/graph/project/{project_id}")
def get_project(project_id: str, request: Request, session: Session = Depends(get_session)) -> dict[str, Any]:
    """Return a project payload compatible with the glass frontend."""
    project = get_project_or_404(session, project_id)
    if not project:
        return envelope_error("Project not found")
    return envelope_ok(_project_payload(session, request, project))


@router.delete("/api/graph/project/{project_id}")
def delete_project(project_id: str, request: Request, session: Session = Depends(get_session)) -> dict[str, Any]:
    """Delete a project and its workflow artifacts."""
    project = get_project_or_404(session, project_id)
    if not project:
        return envelope_error(f"Project not found: {project_id}")
    try:
        _delete_project_tree(session, request, project)
        session.commit()
    except HTTPException as exc:
        session.rollback()
        return envelope_error(str(exc.detail))
    except Exception:
        session.rollback()
        raise
    return {"success": True, "message": f"Project deleted: {project_id}"}


@router.post("/api/graph/project/{project_id}/reset")
def reset_project(project_id: str, request: Request, session: Session = Depends(get_session)) -> dict[str, Any]:
    """Reset graph-build state while preserving uploaded sources and ontology metadata."""
    project = get_project_or_404(session, project_id)
    if not project:
        return envelope_error(f"Project not found: {project_id}")
    settings = request.app.state.settings
    graph_jobs = list_graph_jobs(session, project_id)
    active_graph_ids = [item.id for item in graph_jobs if _glass_runtime(request).graph_build_is_active(item.id)]
    if active_graph_ids:
        return envelope_error(f"Graph build still running: {active_graph_ids[0]}")
    if settings.graph_backend == "graphiti" and settings.graphiti_base_url and settings.llm_provider != "test" and graph_jobs:
        client = GraphitiClient(settings)
        try:
            for graph_job in graph_jobs:
                client.delete_graph(graph_job.id, ignore_missing=True)
        finally:
            client.close()
    _delete_workflow_updates(session, {item.id for item in graph_jobs})
    for graph_job in graph_jobs:
        _delete_graph_job_artifacts(settings, graph_job.id)
        session.delete(graph_job)
    project.status = WorkflowStatus.draft
    project.updated_at = datetime.now(timezone.utc)
    session.add(project)
    session.commit()
    session.refresh(project)
    return {
        "success": True,
        "message": f"Project reset: {project_id}",
        "data": _project_payload(session, request, project),
    }


@router.get("/api/graph/data/{graph_id}")
def get_graph_data(
    graph_id: str,
    request: Request,
    session: Session = Depends(get_session),
    baseline: bool = Query(default=False),
    compact: bool = Query(default=False),
) -> dict[str, Any]:
    """Return graph canvas data."""
    try:
        payload = _selected_graph_payload(session, request, graph_id, baseline=baseline)
        if compact or not baseline:
            payload = compact_graph_payload_for_display(payload)
        return envelope_ok(payload)
    except SyntheticGraphError as exc:
        return envelope_error(str(exc))


@router.delete("/api/graph/delete/{graph_id}")
def delete_graph(graph_id: str, request: Request, session: Session = Depends(get_session)) -> dict[str, Any]:
    """Delete a graph job and its persisted graph payload."""
    graph_job = session.get(GraphJob, graph_id)
    if graph_job and _glass_runtime(request).graph_build_is_active(graph_id):
        return envelope_error(f"Graph build still running: {graph_id}")
    settings = request.app.state.settings
    if settings.graph_backend == "graphiti" and settings.graphiti_base_url and settings.llm_provider != "test":
        client = GraphitiClient(settings)
        try:
            client.delete_graph(graph_id, ignore_missing=True)
        finally:
            client.close()
    _delete_workflow_updates(session, {graph_id})
    _delete_graph_job_artifacts(settings, graph_id)
    if graph_job:
        session.delete(graph_job)
        session.commit()
    return {"success": True, "message": f"Graph deleted: {graph_id}"}


@router.post("/api/graph/data/{graph_id}/search")
def search_graph(graph_id: str, request: Request, payload: dict[str, Any], session: Session = Depends(get_session)) -> dict[str, Any]:
    """Search the graph canvas payload."""
    try:
        graph = compact_graph_payload_for_display(_selected_graph_payload(session, request, graph_id))
    except SyntheticGraphError as exc:
        return envelope_error(str(exc))
    query = str(payload.get("query", "")).strip().lower()
    if not query:
        return envelope_ok({"query": "", "total_count": 0, "facts": [], "nodes": [], "edges": []})
    nodes = [
        item
        for item in graph.get("nodes", [])
        if query in str(item.get("name", "")).lower() or query in str(item.get("label", "")).lower()
    ]
    edges = [
        item
        for item in graph.get("edges", [])
        if query in str(item.get("relation_type", "")).lower() or query in str(item.get("fact", "")).lower()
    ]
    facts = [str(item.get("fact")) for item in edges if item.get("fact")]
    return envelope_ok(
        {
            "query": query,
            "total_count": len(nodes) + len(edges),
            "facts": facts,
            "nodes": nodes,
            "edges": edges,
        }
    )


@router.post("/api/graph/data/{graph_id}/subgraph")
def get_subgraph(graph_id: str, request: Request, payload: dict[str, Any], session: Session = Depends(get_session)) -> dict[str, Any]:
    """Return a filtered subgraph payload."""
    try:
        graph = compact_graph_payload_for_display(_selected_graph_payload(session, request, graph_id))
    except SyntheticGraphError as exc:
        return envelope_error(str(exc))
    center_node_uuid = payload.get("center_node_uuid")
    node_labels = {item for item in payload.get("node_labels", []) if isinstance(item, str)}
    edge_types = {item for item in payload.get("edge_types", []) if isinstance(item, str)}

    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    if center_node_uuid:
        edges = [
            item
            for item in edges
            if item.get("source_uuid") == center_node_uuid or item.get("target_uuid") == center_node_uuid
        ]
    if edge_types:
        edges = [item for item in edges if item.get("relation_type") in edge_types]

    referenced_ids = {
        str(edge.get("source_uuid"))
        for edge in edges
    } | {
        str(edge.get("target_uuid"))
        for edge in edges
    }
    filtered_nodes = [
        item
        for item in nodes
        if str(item.get("uuid")) in referenced_ids or not referenced_ids
    ]
    if node_labels:
        filtered_nodes = [item for item in filtered_nodes if item.get("label") in node_labels]
    metadata = {
        "node_count": len(filtered_nodes),
        "edge_count": len(edges),
        "entity_types": sorted({str(item.get("label", "Entity")) for item in filtered_nodes}),
        "edge_types": sorted({str(item.get("relation_type", "related_to")) for item in edges}),
    }
    return envelope_ok({"nodes": filtered_nodes, "edges": edges, "metadata": metadata})


@router.get("/api/simulation/entities/{graph_id}")
def get_graph_entities(
    graph_id: str,
    request: Request,
    session: Session = Depends(get_session),
    entity_types: str = Query(default=""),
    enrich: bool = Query(default=True),
) -> dict[str, Any]:
    """Return graph entities in the legacy entity-reader shape."""
    try:
        graph = _selected_graph_payload(session, request, graph_id)
    except SyntheticGraphError as exc:
        return envelope_error(str(exc))
    requested_types = {item.strip() for item in entity_types.split(",") if item.strip()} or None
    return envelope_ok(_graph_entities(graph, entity_types=requested_types, enrich=enrich))


@router.get("/api/simulation/entities/{graph_id}/{entity_uuid}")
def get_entity_detail(graph_id: str, entity_uuid: str, request: Request, session: Session = Depends(get_session)) -> dict[str, Any]:
    """Return a single graph entity with context."""
    try:
        graph = _selected_graph_payload(session, request, graph_id)
    except SyntheticGraphError as exc:
        return envelope_error(str(exc))
    entities = _graph_entities(graph, enrich=True)["entities"]
    for entity in entities:
        if entity["uuid"] == entity_uuid:
            return envelope_ok(entity)
    return envelope_error(f"Entity not found: {entity_uuid}")


@router.get("/api/simulation/entities/{graph_id}/by-type/{entity_type}")
def get_entities_by_type(graph_id: str, entity_type: str, request: Request, session: Session = Depends(get_session)) -> dict[str, Any]:
    """Return graph entities filtered to one type."""
    try:
        graph = _selected_graph_payload(session, request, graph_id)
    except SyntheticGraphError as exc:
        return envelope_error(str(exc))
    return envelope_ok(_graph_entities(graph, entity_types={entity_type}, enrich=True))


@router.get("/api/simulation/history")
def get_simulation_history(request: Request, session: Session = Depends(get_session)) -> dict[str, Any]:
    """Return simulation history cards for the glass home page."""
    statement = select(Simulation).order_by(Simulation.created_at.desc())
    entries = [build_history_entry(session, request.app.state.settings, simulation) for simulation in session.exec(statement)]
    return envelope_ok([item for item in entries if item])


@router.get("/api/simulation/list")
def get_simulation_list(request: Request, session: Session = Depends(get_session)) -> dict[str, Any]:
    """Return a simple list of simulation metadata."""
    statement = select(Simulation).order_by(Simulation.created_at.desc())
    items = []
    for simulation in session.exec(statement):
        state = load_simulation_state(request.app.state.settings, simulation.id)
        items.append(
            {
                "simulation_id": simulation.id,
                "project_id": simulation.project_id,
                "status": state.get("status", "created"),
                "created_at": simulation.created_at.isoformat(),
                "updated_at": simulation.updated_at.isoformat(),
            }
        )
    return envelope_ok(items)


@router.get("/api/simulation/{simulation_id}")
def get_simulation_record(simulation_id: str, request: Request, session: Session = Depends(get_session)) -> dict[str, Any]:
    """Return merged simulation metadata for compatibility callers."""
    simulation = get_simulation_or_404(session, simulation_id)
    if not simulation:
        return envelope_error("Simulation not found")
    state = load_simulation_state(request.app.state.settings, simulation_id)
    return envelope_ok(
        {
            "simulation_id": simulation.id,
            "project_id": simulation.project_id,
            "graph_id": state.get("graph_id") or simulation.graph_job_id,
            "status": state.get("status", "created"),
            "runner_status": state.get("runner_status", "idle"),
            "current_round": state.get("current_round", 0),
            "total_rounds": state.get("total_rounds", 0),
            "created_at": simulation.created_at.isoformat(),
            "updated_at": simulation.updated_at.isoformat(),
            "error": state.get("error", ""),
        }
    )


@router.post("/api/simulation/create")
def create_simulation(request: Request, payload: dict[str, Any], session: Session = Depends(get_session)) -> dict[str, Any]:
    """Create a simulation record without starting the live run yet."""
    project_id = str(payload.get("project_id", "")).strip()
    project = get_project_or_404(session, project_id)
    if not project:
        return envelope_error("Project not found")
    graph_id = str(payload.get("graph_id") or "") or (
        _latest_graph_for_project(session, project_id).id if _latest_graph_for_project(session, project_id) else None
    )
    simulation = Simulation(
        id=f"sim_{datetime.now(timezone.utc).strftime('%H%M%S')}{uuid4().hex[:6]}",
        project_id=project.id,
        graph_job_id=graph_id,
        mode="analysis",
        cohort_size=18,
        status=WorkflowStatus.draft,
        progress_percent=0,
        status_message="Created simulation workspace.",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    session.add(simulation)
    session.commit()
    session.refresh(simulation)
    save_simulation_state(
        request.app.state.settings,
        simulation.id,
        {
            "status": "created",
            "runner_status": "idle",
            "graph_id": graph_id,
            "twitter_running": False,
            "reddit_running": False,
            "current_round": 0,
            "total_rounds": 0,
            "progress_percent": 0,
            "created_at": simulation.created_at.isoformat(),
        },
    )
    return envelope_ok(
        {
            "simulation_id": simulation.id,
            "project_id": project.id,
            "graph_id": graph_id,
            "status": "created",
            "enable_twitter": bool(payload.get("enable_twitter", True)),
            "enable_reddit": bool(payload.get("enable_reddit", True)),
            "created_at": simulation.created_at.isoformat(),
        }
    )


@router.post("/api/simulation/prepare")
def prepare_simulation(request: Request, payload: dict[str, Any], session: Session = Depends(get_session)) -> dict[str, Any]:
    """Start preparation of profiles and config."""
    simulation_id = str(payload.get("simulation_id", "")).strip()
    simulation = get_simulation_or_404(session, simulation_id)
    if not simulation:
        return envelope_error("Simulation not found")
    settings = request.app.state.settings
    state = load_simulation_state(settings, simulation_id)
    force_regenerate = bool(payload.get("force_regenerate", False))
    profiles_ready = simulation_profiles_path(settings, simulation_id, "reddit").exists()
    config_ready = simulation_config_path(settings, simulation_id).exists()
    if profiles_ready and config_ready and not force_regenerate:
        state.update(
            {
                "status": "ready",
                "profiles_generation_active": False,
                "config_generation_active": False,
                "expected_entities_count": state.get("expected_entities_count"),
                "profiles_count": state.get("profiles_count", 0),
            }
        )
        save_simulation_state(settings, simulation_id, state)
        return envelope_ok(
            {
                "simulation_id": simulation_id,
                "status": "ready",
                "message": "Simulation profiles and config already prepared.",
                "already_prepared": True,
                "expected_entities_count": state.get("expected_entities_count"),
            }
        )
    runtime = _glass_runtime(request)
    runtime.start_prepare(simulation_id)
    return envelope_ok(
        {
            "simulation_id": simulation_id,
            "task_id": f"prep_{simulation_id}",
            "status": "preparing",
            "message": "Preparation task started. Query progress via /api/simulation/prepare/status.",
            "already_prepared": False,
            "expected_entities_count": state.get("expected_entities_count"),
        }
    )


@router.post("/api/simulation/prepare/status")
def get_prepare_status(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    """Return setup preparation status."""
    simulation_id = str(payload.get("simulation_id", "")).strip()
    task_id = str(payload.get("task_id") or f"prep_{simulation_id}")
    status_path = prepare_task_path(request.app.state.settings, simulation_id)
    if not status_path.exists():
        state = load_simulation_state(request.app.state.settings, simulation_id)
        if state.get("status") == "ready":
            return envelope_ok(
                {
                    "task_id": task_id,
                    "simulation_id": simulation_id,
                    "status": "ready",
                    "progress": 100,
                    "message": "Profiles and config are ready.",
                    "already_prepared": True,
                }
            )
        return envelope_ok(
            {
                "task_id": task_id,
                "simulation_id": simulation_id,
                "status": "processing",
                "progress": 0,
                "message": "Preparation is starting.",
                "already_prepared": False,
            }
        )
    from ..services.glass_compat import _read_json

    payload = _read_json(status_path, {})
    return envelope_ok(payload)


@router.get("/api/simulation/{simulation_id}/profiles")
def get_profiles(simulation_id: str, request: Request, platform: str = Query(default="reddit")) -> dict[str, Any]:
    """Return generated persona profiles."""
    profiles = load_simulation_profiles(request.app.state.settings, simulation_id, platform)
    return envelope_ok({"platform": platform, "count": len(profiles), "profiles": profiles})


@router.get("/api/simulation/{simulation_id}/profiles/realtime")
def get_profiles_realtime(simulation_id: str, request: Request, platform: str = Query(default="reddit")) -> dict[str, Any]:
    """Return realtime profile generation state."""
    settings = request.app.state.settings
    profiles_path = simulation_profiles_path(settings, simulation_id, platform)
    profiles = load_simulation_profiles(settings, simulation_id, platform)
    state = load_simulation_state(settings, simulation_id)
    return envelope_ok(
        {
            "platform": platform,
            "count": len(profiles),
            "generated_count": len(profiles),
            "total_expected": state.get("expected_entities_count"),
            "profiles": profiles,
            "is_generating": bool(state.get("profiles_generation_active")),
            "file_modified_at": _file_modified_iso(profiles_path),
        }
    )


@router.get("/api/simulation/{simulation_id}/config")
def get_config(simulation_id: str, request: Request) -> dict[str, Any]:
    """Return the generated simulation config."""
    payload = load_simulation_config(request.app.state.settings, simulation_id)
    return envelope_ok(payload)


@router.get("/api/simulation/{simulation_id}/config/download")
def download_config(simulation_id: str, request: Request) -> FileResponse:
    """Download the generated simulation config."""
    path = simulation_config_path(request.app.state.settings, simulation_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Config file does not exist. Call /prepare first.")
    return FileResponse(path, filename="simulation_config.json", media_type="application/json")


@router.get("/api/simulation/{simulation_id}/config/realtime")
def get_config_realtime(simulation_id: str, request: Request) -> dict[str, Any]:
    """Return realtime config generation state."""
    settings = request.app.state.settings
    state = load_simulation_state(settings, simulation_id)
    config_path = simulation_config_path(settings, simulation_id)
    config = load_simulation_config(settings, simulation_id)
    return envelope_ok(
        {
            "config": config,
            "is_generating": bool(state.get("config_generation_active")),
            "file_modified_at": _file_modified_iso(config_path),
        }
    )


@router.post("/api/simulation/start")
def start_simulation(request: Request, payload: dict[str, Any], session: Session = Depends(get_session)) -> dict[str, Any]:
    """Start the live simulation playback."""
    simulation_id = str(payload.get("simulation_id", "")).strip()
    simulation = get_simulation_or_404(session, simulation_id)
    if not simulation:
        return envelope_error("Simulation not found")
    runtime = _glass_runtime(request)
    max_rounds = payload.get("max_rounds")
    normalized_max_rounds: int | None = None
    if isinstance(max_rounds, (int, float)) and int(max_rounds) > 0:
        normalized_max_rounds = int(max_rounds)
    elif isinstance(max_rounds, str):
        try:
            parsed_max_rounds = int(max_rounds.strip())
        except ValueError:
            parsed_max_rounds = 0
        if parsed_max_rounds > 0:
            normalized_max_rounds = parsed_max_rounds
    platform = str(payload.get("platform") or "parallel")
    runtime.start_run(
        simulation_id,
        platform=platform,
        max_rounds=normalized_max_rounds,
        enable_graph_memory_update=bool(payload.get("enable_graph_memory_update", False)),
        force=bool(payload.get("force", False)),
    )
    state = load_simulation_state(request.app.state.settings, simulation_id)
    applied_rounds = state.get("total_rounds")
    if isinstance(normalized_max_rounds, int) and (not isinstance(applied_rounds, int) or applied_rounds <= 0):
        applied_rounds = normalized_max_rounds
    return envelope_ok(
        {
            "simulation_id": simulation_id,
            "runner_status": state.get("runner_status", "starting"),
            "process_pid": state.get("process_pid", 0),
            "twitter_running": bool(state.get("twitter_running", True)),
            "reddit_running": bool(state.get("reddit_running", True)),
            "started_at": state.get("started_at") or datetime.now(timezone.utc).isoformat(),
            "platform": platform,
            "requested_max_rounds": normalized_max_rounds,
            "max_rounds_applied": applied_rounds if isinstance(applied_rounds, int) else normalized_max_rounds,
        }
    )


@router.post("/api/simulation/stop")
def stop_simulation(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    """Stop the live simulation playback."""
    simulation_id = str(payload.get("simulation_id", "")).strip()
    runtime = _glass_runtime(request)
    state = runtime.stop_run(simulation_id)
    return envelope_ok(
        {
            "simulation_id": simulation_id,
            "runner_status": state.get("runner_status", "stopped"),
            "stopped_at": state.get("stopped_at") or datetime.now(timezone.utc).isoformat(),
            "final_round": state.get("current_round", 0),
            "total_rounds": state.get("total_rounds", 0),
        }
    )


@router.get("/api/simulation/{simulation_id}/run-status")
def get_run_status(simulation_id: str, request: Request) -> dict[str, Any]:
    """Return the live run status."""
    state = load_simulation_state(request.app.state.settings, simulation_id)
    return envelope_ok(
        {
            "simulation_id": simulation_id,
            "runner_status": state.get("runner_status", "idle"),
            "current_round": state.get("current_round", 0),
            "total_rounds": state.get("total_rounds", 0),
            "minutes_per_round": state.get("minutes_per_round", 0),
            "simulated_hours": state.get("simulated_hours", 0),
            "total_simulation_hours": state.get("total_simulation_hours", 0),
            "progress_percent": state.get("progress_percent", 0),
            "twitter_current_round": state.get("twitter_current_round", state.get("current_round", 0)),
            "reddit_current_round": state.get("reddit_current_round", state.get("current_round", 0)),
            "twitter_simulated_hours": state.get("twitter_simulated_hours", state.get("simulated_hours", 0)),
            "reddit_simulated_hours": state.get("reddit_simulated_hours", state.get("simulated_hours", 0)),
            "twitter_running": bool(state.get("twitter_running")),
            "reddit_running": bool(state.get("reddit_running")),
            "twitter_completed": bool(state.get("twitter_completed")),
            "reddit_completed": bool(state.get("reddit_completed")),
            "twitter_actions_count": state.get("twitter_actions_count", 0),
            "reddit_actions_count": state.get("reddit_actions_count", 0),
            "total_actions_count": state.get("total_actions_count", 0),
            "started_at": state.get("started_at", ""),
            "completed_at": state.get("completed_at", ""),
            "process_pid": state.get("process_pid", 0),
            "error": state.get("error", ""),
        }
    )


@router.get("/api/simulation/{simulation_id}/run-status/detail")
def get_run_status_detail(simulation_id: str, request: Request) -> dict[str, Any]:
    """Return detailed live run status including recent actions."""
    settings = request.app.state.settings
    state = load_simulation_state(settings, simulation_id)
    actions = load_simulation_actions(settings, simulation_id)
    recent_actions = actions[-50:]
    return envelope_ok(
        {
            "simulation_id": simulation_id,
            "runner_status": state.get("runner_status", "idle"),
            "current_round": state.get("current_round", 0),
            "total_rounds": state.get("total_rounds", 0),
            "minutes_per_round": state.get("minutes_per_round", 0),
            "simulated_hours": state.get("simulated_hours", 0),
            "twitter_current_round": state.get("twitter_current_round", state.get("current_round", 0)),
            "reddit_current_round": state.get("reddit_current_round", state.get("current_round", 0)),
            "progress_percent": state.get("progress_percent", 0),
            "recent_actions": recent_actions,
            "all_actions": actions,
        }
    )


@router.get("/api/simulation/{simulation_id}/actions")
def get_actions(
    simulation_id: str,
    request: Request,
    limit: int = Query(default=50),
    offset: int = Query(default=0),
    platform: str | None = Query(default=None),
    agent_id: str | None = Query(default=None),
    round_num: int | None = Query(default=None),
) -> dict[str, Any]:
    """Return filtered action log items."""
    actions = load_simulation_actions(request.app.state.settings, simulation_id)
    if platform:
        actions = [item for item in actions if item.get("platform") == platform]
    if agent_id:
        actions = [item for item in actions if item.get("agent_id") == agent_id]
    if round_num is not None:
        actions = [item for item in actions if int(item.get("round_num", 0)) == round_num]
    total = len(actions)
    sliced = actions[offset : offset + limit]
    return envelope_ok({"count": len(sliced), "total": total, "actions": sliced})


@router.get("/api/simulation/{simulation_id}/timeline")
def get_timeline(
    simulation_id: str,
    request: Request,
    start_round: int = Query(default=0),
    end_round: int | None = Query(default=None),
) -> dict[str, Any]:
    """Return round-grouped timeline items."""
    actions = load_simulation_actions(request.app.state.settings, simulation_id)
    grouped: dict[int, list[dict[str, Any]]] = {}
    for action in actions:
        grouped.setdefault(int(action.get("round_num", 0)), []).append(action)
    timeline = [
        {
            "round": round_number,
            "summary": f"Round {round_number} produced {len(items)} actions.",
            "actions": items,
        }
        for round_number, items in sorted(grouped.items())
        if round_number >= start_round and (end_round is None or round_number <= end_round)
    ]
    return envelope_ok({"timeline": timeline})


@router.get("/api/simulation/{simulation_id}/agent-stats")
def get_agent_stats(simulation_id: str, request: Request) -> dict[str, Any]:
    """Return simple per-agent activity counts."""
    profiles = load_simulation_profiles(request.app.state.settings, simulation_id, "reddit")
    actions = load_simulation_actions(request.app.state.settings, simulation_id)
    stats = []
    for profile in profiles:
        count = len([item for item in actions if item.get("agent_id") == profile["agent_id"]])
        stats.append(
            {
                "agent_id": profile["agent_id"],
                "name": profile["name"],
                "platform": profile.get("platform", "reddit"),
                "actions_count": count,
            }
        )
    return envelope_ok({"total_agents": len(stats), "agents": stats})


@router.get("/api/simulation/{simulation_id}/posts")
def get_posts(
    simulation_id: str,
    request: Request,
    platform: str = Query(default="reddit"),
    limit: int = Query(default=50),
    offset: int = Query(default=0),
) -> dict[str, Any]:
    """Return posts from the simulation SQLite database."""
    all_posts = load_simulation_posts(request.app.state.settings, simulation_id, platform)
    total = len(all_posts)
    posts = all_posts[offset : offset + limit]
    return envelope_ok({"platform": platform, "total": total, "count": len(posts), "posts": posts})


@router.get("/api/simulation/{simulation_id}/comments")
def get_comments(
    simulation_id: str,
    request: Request,
    post_id: str | None = Query(default=None),
    limit: int = Query(default=50),
    offset: int = Query(default=0),
) -> dict[str, Any]:
    """Return comments from the Reddit simulation database."""
    all_comments = load_simulation_comments(request.app.state.settings, simulation_id)
    if post_id:
        all_comments = [item for item in all_comments if str(item.get("post_id") or "") == post_id]
    total = len(all_comments)
    comments = all_comments[offset : offset + limit]
    return envelope_ok({"total": total, "count": len(comments), "comments": comments})


@router.post("/api/simulation/generate-profiles")
def generate_profiles_preview(request: Request, payload: dict[str, Any], session: Session = Depends(get_session)) -> dict[str, Any]:
    """Generate preview personas directly from a graph snapshot."""
    graph_id = str(payload.get("graph_id", "")).strip()
    if not graph_id:
        return envelope_error("Please provide graph_id")
    entity_types_payload = payload.get("entity_types")
    entity_types = (
        {str(item).strip() for item in entity_types_payload if str(item).strip()}
        if isinstance(entity_types_payload, list)
        else None
    )
    platform = str(payload.get("platform") or "reddit").strip().lower() or "reddit"
    use_llm = bool(payload.get("use_llm", True))
    try:
        graph_payload = _selected_graph_payload(session, request, graph_id)
    except SyntheticGraphError as exc:
        return envelope_error(str(exc))
    entity_payload = _graph_entities(graph_payload, entity_types=entity_types, enrich=True)
    entities = entity_payload.get("entities", [])
    if not entities:
        return envelope_error("No entities matched the requested criteria")
    graph_job = session.get(GraphJob, graph_id)
    project = session.get(Project, graph_job.project_id) if graph_job else None
    metadata = load_project_metadata(request.app.state.settings, project.id) if project else {}
    ontology = metadata.get("ontology") if isinstance(metadata.get("ontology"), dict) else {}
    if not ontology:
        ontology = {
            "entity_types": [{"name": item} for item in entity_payload.get("entity_types", [])],
            "edge_types": [],
        }
    preview_project = project or Project(
        name="Profile Preview",
        scenario_brief="Generate compatibility personas from a graph snapshot.",
    )
    generated = build_glass_profiles(
        project=preview_project,
        source_digest=str(metadata.get("analysis_summary") or preview_project.scenario_brief or "").strip(),
        ontology=ontology,
        expected_count=len(entities),
        entities=entities,
        llm=request.app.state.registry.llm if use_llm else None,
    )
    profiles = generated.get("twitter_profiles", []) if platform == "twitter" else generated.get("reddit_profiles", [])
    return envelope_ok(
        {
            "platform": platform,
            "entity_types": entity_payload.get("entity_types", []),
            "count": len(profiles),
            "profiles": profiles,
        }
    )


@router.post("/api/simulation/interview/batch")
def interview_batch(request: Request, payload: dict[str, Any], session: Session = Depends(get_session)) -> dict[str, Any]:
    """Return runtime-backed interview responses for a prepared simulation."""
    simulation_id = str(payload.get("simulation_id", "")).strip()
    simulation = get_simulation_or_404(session, simulation_id)
    if not simulation:
        return envelope_error("Simulation not found")
    project = session.get(Project, simulation.project_id)
    if not project:
        return envelope_error("Project not found")
    env = load_simulation_env(request.app.state.settings, simulation_id)
    if env.get("status") != "alive":
        return envelope_error("Simulation environment is not running or has already closed.")

    interviews = payload.get("interviews") or []
    default_platform = str(payload.get("platform") or "").strip() or None
    profiles = _profile_map(request.app.state.settings, simulation_id)
    actions = load_simulation_actions(request.app.state.settings, simulation_id)

    if _uses_oasis_runtime(request.app.state.settings, simulation_id):
        runtime_interviews = []
        profile_lookup = profiles
        for item in interviews:
            agent_id = str(item.get("agent_id", "")).strip()
            prompt = str(item.get("prompt", "")).strip()
            if not agent_id or not prompt:
                continue
            profile = profile_lookup.get(agent_id)
            if not profile:
                continue
            runtime_item = {
                "agent_id": int(profile.get("oasis_user_id", profile.get("user_id", 0))),
                "prompt": prompt,
            }
            item_platform = str(item.get("platform") or "").strip() or default_platform
            if item_platform:
                runtime_item["platform"] = item_platform
            runtime_interviews.append(runtime_item)
        try:
            ipc_response = send_ipc_command(
                request.app.state.settings,
                simulation_id,
                command_type="batch_interview",
                args={
                    "interviews": runtime_interviews,
                    **({"platform": default_platform} if default_platform else {}),
                },
                timeout_seconds=120.0,
            )
        except TimeoutError:
            return envelope_error("Interview environment did not respond in time.")
        if str(ipc_response.get("status") or "") != "completed":
            return envelope_error(str(ipc_response.get("error") or "Interview request failed."))
        raw_results = ((ipc_response.get("result") or {}).get("interview_results") or [])
        results: list[dict[str, Any]] = []
        history_entries: list[dict[str, Any]] = []
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            platform_name = str(item.get("platform") or "")
            response_text = item.get("response")
            if not response_text:
                continue
            external_agent_id = str(item.get("agent_id") or "")
            profile = profiles.get(external_agent_id)
            agent_name = str(item.get("agent_name") or (profile or {}).get("name") or external_agent_id)
            result_item = {
                "agent_id": external_agent_id,
                "agent_name": agent_name,
                "platform": platform_name,
                "response": response_text,
                "confidence": 0.9,
            }
            results.append(result_item)
            history_entries.append(
                {
                    "timestamp": str(item.get("timestamp") or datetime.now(timezone.utc).isoformat()),
                    "simulation_id": simulation_id,
                    "agent_id": external_agent_id,
                    "agent_name": agent_name,
                    "platform": platform_name,
                    "prompt": next(
                        (
                            str(interview.get("prompt"))
                            for interview in interviews
                            if str(interview.get("agent_id", "")).strip() == external_agent_id
                        ),
                        "",
                    ),
                    "response": response_text,
                }
            )
        append_simulation_interviews(request.app.state.settings, simulation_id, history_entries)
        return envelope_ok({"simulation_id": simulation_id, "interview_results": results})

    results = []
    history_entries: list[dict[str, Any]] = []
    for item in interviews:
        agent_id = str(item.get("agent_id", "")).strip()
        prompt = str(item.get("prompt", "")).strip()
        if not agent_id or not prompt:
            continue
        profile = profiles.get(agent_id)
        if not profile:
            continue
        item_platform = str(item.get("platform") or "").strip() or default_platform
        target_platforms = [item_platform] if item_platform in {"twitter", "reddit"} else ["twitter", "reddit"]
        for target_platform in target_platforms:
            response = _interview_response_for_profile(
                request,
                project,
                profile,
                prompt,
                actions,
                platform=target_platform,
            )
            results.append(
                {
                    "agent_id": agent_id,
                    "agent_name": profile.get("name"),
                    "platform": target_platform,
                    "response": response,
                    "confidence": 0.82,
                }
            )
            history_entries.append(
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "simulation_id": simulation_id,
                    "agent_id": agent_id,
                    "agent_name": profile.get("name"),
                    "platform": target_platform,
                    "prompt": prompt,
                    "response": response,
                }
            )
    append_simulation_interviews(request.app.state.settings, simulation_id, history_entries)
    return envelope_ok({"simulation_id": simulation_id, "interview_results": results})


@router.post("/api/simulation/interview")
def interview_single(request: Request, payload: dict[str, Any], session: Session = Depends(get_session)) -> dict[str, Any]:
    """Interview a single persona, optionally across both platforms."""
    simulation_id = str(payload.get("simulation_id", "")).strip()
    agent_id = str(payload.get("agent_id", "")).strip()
    prompt = str(payload.get("prompt", "")).strip()
    platform = str(payload.get("platform") or "").strip() or None
    if not simulation_id or not agent_id or not prompt:
        return envelope_error("Please provide simulation_id, agent_id, and prompt")
    simulation = get_simulation_or_404(session, simulation_id)
    if not simulation:
        return envelope_error("Simulation not found")
    project = session.get(Project, simulation.project_id)
    if not project:
        return envelope_error("Project not found")
    env = load_simulation_env(request.app.state.settings, simulation_id)
    if env.get("status") != "alive":
        return envelope_error("Simulation environment is not running or has already closed.")
    profiles = _profile_map(request.app.state.settings, simulation_id)
    profile = profiles.get(agent_id)
    if not profile:
        return envelope_error("Agent not found")
    actions = load_simulation_actions(request.app.state.settings, simulation_id)
    if _uses_oasis_runtime(request.app.state.settings, simulation_id):
        try:
            ipc_response = send_ipc_command(
                request.app.state.settings,
                simulation_id,
                command_type="interview",
                args={
                    "agent_id": int(profile.get("oasis_user_id", profile.get("user_id", 0))),
                    "prompt": prompt,
                    **({"platform": platform} if platform else {}),
                },
                timeout_seconds=90.0,
            )
        except TimeoutError:
            return envelope_error("Interview environment did not respond in time.")
        if str(ipc_response.get("status") or "") != "completed":
            return envelope_error(str(ipc_response.get("error") or "Interview request failed."))
        result = ipc_response.get("result") or {}
        timestamp = datetime.now(timezone.utc).isoformat()
        history_entries: list[dict[str, Any]] = []
        if platform in {"twitter", "reddit"} and isinstance(result, dict):
            history_entries.append(
                {
                    "timestamp": str(result.get("timestamp") or timestamp),
                    "simulation_id": simulation_id,
                    "agent_id": agent_id,
                    "agent_name": profile.get("name"),
                    "platform": platform,
                    "prompt": prompt,
                    "response": result.get("response"),
                }
            )
            append_simulation_interviews(request.app.state.settings, simulation_id, history_entries)
            return envelope_ok({"agent_id": agent_id, "prompt": prompt, "result": result, "timestamp": history_entries[0]["timestamp"]})
        platform_results = (result.get("platforms") or {}) if isinstance(result, dict) else {}
        for platform_name, platform_result in platform_results.items():
            if not isinstance(platform_result, dict):
                continue
            history_entries.append(
                {
                    "timestamp": str(platform_result.get("timestamp") or timestamp),
                    "simulation_id": simulation_id,
                    "agent_id": agent_id,
                    "agent_name": profile.get("name"),
                    "platform": platform_name,
                    "prompt": prompt,
                    "response": platform_result.get("response"),
                }
            )
        append_simulation_interviews(request.app.state.settings, simulation_id, history_entries)
        return envelope_ok({"agent_id": agent_id, "prompt": prompt, "result": result, "timestamp": timestamp})
    if platform in {"twitter", "reddit"}:
        response = _interview_response_for_profile(request, project, profile, prompt, actions, platform=platform)
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "simulation_id": simulation_id,
            "agent_id": agent_id,
            "agent_name": profile.get("name"),
            "platform": platform,
            "prompt": prompt,
            "response": response,
        }
        append_simulation_interviews(request.app.state.settings, simulation_id, [entry])
        return envelope_ok(
            {
                "agent_id": agent_id,
                "prompt": prompt,
                "result": {
                    "agent_id": agent_id,
                    "response": response,
                    "platform": platform,
                    "timestamp": entry["timestamp"],
                },
                "timestamp": entry["timestamp"],
            }
        )

    results = {}
    history_entries = []
    timestamp = datetime.now(timezone.utc).isoformat()
    for target_platform in ("twitter", "reddit"):
        response = _interview_response_for_profile(request, project, profile, prompt, actions, platform=target_platform)
        results[target_platform] = {
            "agent_id": agent_id,
            "response": response,
            "platform": target_platform,
            "timestamp": timestamp,
        }
        history_entries.append(
            {
                "timestamp": timestamp,
                "simulation_id": simulation_id,
                "agent_id": agent_id,
                "agent_name": profile.get("name"),
                "platform": target_platform,
                "prompt": prompt,
                "response": response,
            }
        )
    append_simulation_interviews(request.app.state.settings, simulation_id, history_entries)
    return envelope_ok(
        {
            "agent_id": agent_id,
            "prompt": prompt,
            "result": {
                "agent_id": agent_id,
                "prompt": prompt,
                "platforms": results,
            },
            "timestamp": timestamp,
        }
    )


@router.post("/api/simulation/interview/all")
def interview_all(request: Request, payload: dict[str, Any], session: Session = Depends(get_session)) -> dict[str, Any]:
    """Interview all prepared personas with the same prompt."""
    simulation_id = str(payload.get("simulation_id", "")).strip()
    prompt = str(payload.get("prompt", "")).strip()
    platform = str(payload.get("platform") or "").strip() or None
    if not simulation_id or not prompt:
        return envelope_error("Please provide simulation_id and prompt")
    simulation = get_simulation_or_404(session, simulation_id)
    if not simulation:
        return envelope_error("Simulation not found")
    profiles = load_simulation_profiles(request.app.state.settings, simulation_id, "reddit")
    interviews = [{"agent_id": item["agent_id"], "prompt": prompt} for item in profiles]
    batch_payload = {"simulation_id": simulation_id, "interviews": interviews}
    if platform:
        batch_payload["platform"] = platform
    batch_result = interview_batch(request, batch_payload, session)
    if batch_result.get("success") is not True:
        return batch_result
    results = batch_result["data"]["interview_results"]
    result_map = {
        f"{item.get('platform', 'unknown')}_{item['agent_id']}": item
        for item in results
    }
    return envelope_ok(
        {
            "interviews_count": len(profiles),
            "result": {
                "interviews_count": len(results),
                "results": result_map,
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )


@router.post("/api/simulation/interview/history")
def get_interview_history(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    """Return persisted interview history for a simulation."""
    simulation_id = str(payload.get("simulation_id", "")).strip()
    platform = str(payload.get("platform") or "").strip() or None
    agent_id = str(payload.get("agent_id") or "").strip() or None
    limit = int(payload.get("limit", 100) or 100)
    if not simulation_id:
        return envelope_error("Please provide simulation_id")
    history = load_simulation_interviews(request.app.state.settings, simulation_id)
    if platform:
        history = [item for item in history if str(item.get("platform") or "") == platform]
    if agent_id:
        history = [item for item in history if str(item.get("agent_id") or "") == agent_id]
    history = history[-limit:]
    return envelope_ok({"count": len(history), "history": history})


@router.post("/api/simulation/env-status")
def get_env_status(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    """Return environment readiness for live interviews."""
    simulation_id = str(payload.get("simulation_id", "")).strip()
    if not simulation_id:
        return envelope_error("Simulation not found")
    detail = load_simulation_env(request.app.state.settings, simulation_id)
    return envelope_ok(
        {
            "simulation_id": simulation_id,
            "env_alive": detail.get("status") == "alive",
            "twitter_available": bool(detail.get("twitter_available")),
            "reddit_available": bool(detail.get("reddit_available")),
            "message": "Environment is ready." if detail.get("status") == "alive" else "Environment is not running.",
            "runtime_kind": load_simulation_state(request.app.state.settings, simulation_id).get("runtime_kind", "synthetic"),
        }
    )


@router.post("/api/simulation/close-env")
def close_env(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    """Request graceful shutdown of the post-run interview environment."""
    simulation_id = str(payload.get("simulation_id", "")).strip()
    if not simulation_id:
        return envelope_error("Simulation not found")
    if _uses_oasis_runtime(request.app.state.settings, simulation_id):
        try:
            ipc_response = send_ipc_command(
                request.app.state.settings,
                simulation_id,
                command_type="close_env",
                args={},
                timeout_seconds=30.0,
            )
            if str(ipc_response.get("status") or "") != "completed":
                return envelope_error(str(ipc_response.get("error") or "Environment close request failed."))
        except TimeoutError:
            return envelope_error("Environment did not acknowledge the close request in time.")
    save_simulation_env(
        request.app.state.settings,
        simulation_id,
        {
            "status": "closed",
            "twitter_available": False,
            "reddit_available": False,
            "closed_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    return envelope_ok(
        {
            "simulation_id": simulation_id,
            "message": "Environment closed.",
            "status": "closed",
        }
    )


@router.get("/api/simulation/script/{script_name}/download")
def download_simulation_script(script_name: str) -> FileResponse:
    """Download clean-room compatibility helper scripts using legacy filenames."""
    allowed_scripts = {
        "run_twitter_simulation.py",
        "run_reddit_simulation.py",
        "run_parallel_simulation.py",
        "action_logger.py",
    }
    if script_name not in allowed_scripts:
        raise HTTPException(status_code=400, detail=f"Unknown script: {script_name}")
    path = _compat_scripts_dir() / script_name
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Compatibility script not found: {script_name}")
    return FileResponse(path, filename=script_name, media_type="text/x-python")


@router.post("/api/report/generate")
def generate_report(request: Request, payload: dict[str, Any], session: Session = Depends(get_session)) -> dict[str, Any]:
    """Start report generation for a completed or running simulation."""
    simulation_id = str(payload.get("simulation_id", "")).strip()
    simulation = get_simulation_or_404(session, simulation_id)
    if not simulation:
        return envelope_error("Simulation not found")
    force_regenerate = bool(payload.get("force_regenerate", False))
    existing = _latest_report_for_simulation(session, simulation_id)
    if existing and existing.status == WorkflowStatus.completed and not force_regenerate:
        return envelope_ok(
            {
                "simulation_id": simulation_id,
                "report_id": existing.id,
                "status": "completed",
                "message": "Report already generated.",
                "already_generated": True,
            }
        )
    if existing and existing.status == WorkflowStatus.running and not force_regenerate:
        return envelope_ok(
            {
                "simulation_id": simulation_id,
                "report_id": existing.id,
                "status": "generating",
                "message": "Report generation already in progress.",
                "already_generated": False,
            }
        )
    report = Report(
        id=f"report_{uuid4().hex[:12]}",
        simulation_id=simulation_id,
        focus="Decision support and scenario implications",
        status=WorkflowStatus.queued,
        progress_percent=0,
        status_message="Queued report generation.",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    session.add(report)
    session.commit()
    session.refresh(report)
    runtime = _glass_runtime(request)
    runtime.start_report(report.id)
    return envelope_ok(
        {
            "simulation_id": simulation_id,
            "report_id": report.id,
            "task_id": report.id,
            "status": "generating",
            "message": "Report generation started.",
            "already_generated": False,
        }
    )


@router.post("/api/report/generate/status")
def get_report_generate_status(request: Request, payload: dict[str, Any], session: Session = Depends(get_session)) -> dict[str, Any]:
    """Return the latest report generation state for a simulation."""
    simulation_id = str(payload.get("simulation_id", "")).strip()
    report_id = str(payload.get("task_id", "")).strip()
    report = session.get(Report, report_id) if report_id else _latest_report_for_simulation(session, simulation_id)
    if not report:
        return envelope_error("Report not found")
    state = _load_report_state(report.id, request)
    return envelope_ok(
        {
            "task_id": report.id,
            "report_id": report.id,
            "simulation_id": report.simulation_id,
            "status": state.get("status", "pending"),
            "progress": state.get("progress", 0),
            "message": state.get("message", "Waiting for report generation."),
            "already_completed": state.get("status") == "completed",
            "outline_ready": bool(state.get("outline_ready")),
            "current_section": state.get("current_section"),
            "completed_sections": state.get("completed_sections", []),
            "evidence_summary": state.get("evidence_summary", {}),
        }
    )


@router.get("/api/report/by-simulation/{simulation_id}")
def get_report_by_simulation(simulation_id: str, request: Request, session: Session = Depends(get_session)) -> dict[str, Any]:
    """Return the latest report linked to a simulation."""
    report = _latest_report_for_simulation(session, simulation_id)
    if not report:
        return {"success": False, "error": f"No report exists for simulation: {simulation_id}", "has_report": False}
    return {"success": True, "data": _report_payload(report, request), "has_report": True}


@router.get("/api/report/list")
def get_report_list(request: Request, simulation_id: str | None = Query(default=None), session: Session = Depends(get_session)) -> dict[str, Any]:
    """List reports in the legacy helper format."""
    items = [_report_payload(item, request) for item in list_reports(session, simulation_id)]
    return {"success": True, "data": items, "count": len(items)}


@router.get("/api/report/{report_id}")
def get_report(report_id: str, request: Request, session: Session = Depends(get_session)) -> dict[str, Any]:
    """Return report metadata and outline."""
    report = get_report_or_404(session, report_id)
    if not report:
        return envelope_error("Report not found")
    state = _load_report_state(report_id, request)
    sections = _section_payloads(report_id, request)
    evidence_summary = load_report_evidence(request.app.state.settings, report_id)
    meta: dict[str, Any] = {}
    markdown_content = report.markdown_body
    outline = state.get("outline") if isinstance(state.get("outline"), dict) else {}
    fallback_sections = [
        {"title": item.get("title") or item.get("filename", f"Section {index + 1}"), "content": item["content"]}
        for index, item in enumerate(sections)
    ]
    outline_sections = outline.get("sections") if isinstance(outline.get("sections"), list) else []
    return envelope_ok(
        {
            "report_id": report.id,
            "simulation_id": report.simulation_id,
            "status": state.get("status", "pending"),
            "outline": {
                "title": outline.get("title") or meta.get("outline", {}).get("title") or state.get("title", f"Report {report.id}"),
                "summary": outline.get("summary") or meta.get("outline", {}).get("summary") or state.get("summary", report.summary),
                "sections": outline_sections or fallback_sections,
            },
            "evidence_summary": evidence_summary,
            "markdown_content": markdown_content,
            "created_at": report.created_at.isoformat(),
            "completed_at": report.completed_at.isoformat() if report.completed_at else "",
            "error": report.error_message or None,
        }
    )


@router.get("/api/report/{report_id}/download")
def download_report(report_id: str, request: Request, session: Session = Depends(get_session)) -> FileResponse:
    """Download report markdown."""
    report = get_report_or_404(session, report_id)
    if not report:
        raise HTTPException(status_code=404, detail=f"Report not found: {report_id}")
    path = report_dir(request.app.state.settings, report_id) / "full_report.md"
    if not path.exists():
        if not report.markdown_body.strip():
            raise HTTPException(status_code=404, detail=f"Report markdown is unavailable: {report_id}")
        path.write_text(report.markdown_body, encoding="utf-8")
    return FileResponse(path, filename=f"{report_id}.md", media_type="text/markdown")


@router.delete("/api/report/{report_id}")
def delete_report(report_id: str, request: Request, session: Session = Depends(get_session)) -> dict[str, Any]:
    """Delete a report and its persisted artifacts."""
    report = get_report_or_404(session, report_id)
    if not report:
        return envelope_error(f"Report not found: {report_id}")
    _delete_workflow_updates(session, {report_id})
    _delete_path(report_dir(request.app.state.settings, report_id))
    session.delete(report)
    session.commit()
    return {"success": True, "message": f"Report deleted: {report_id}"}


@router.get("/api/report/{report_id}/progress")
def get_report_progress(report_id: str, request: Request, session: Session = Depends(get_session)) -> dict[str, Any]:
    """Return incremental report progress information."""
    report = get_report_or_404(session, report_id)
    if not report:
        return envelope_error(f"Report not found or progress unavailable: {report_id}")
    return envelope_ok(_load_report_state(report_id, request))


@router.get("/api/report/{report_id}/sections")
def get_report_sections(report_id: str, request: Request) -> dict[str, Any]:
    """Return all generated report sections."""
    sections = _section_payloads(report_id, request)
    return envelope_ok({"report_id": report_id, "sections": sections})


@router.get("/api/report/{report_id}/section/{section_index}")
def get_report_section(report_id: str, section_index: int, request: Request) -> dict[str, Any]:
    """Return a single report section."""
    sections = _section_payloads(report_id, request)
    for section in sections:
        if section["section_index"] == section_index:
            return envelope_ok(section)
    return envelope_error("Section not found")


@router.get("/api/report/{report_id}/agent-log")
def get_agent_log(report_id: str, request: Request, from_line: int = Query(default=0)) -> dict[str, Any]:
    """Return structured report generation log entries."""
    path = report_dir(request.app.state.settings, report_id) / "agent_log.jsonl"
    if not path.exists():
        return envelope_ok({"logs": [], "total_lines": 0, "from_line": from_line})
    lines = path.read_text(encoding="utf-8").splitlines()
    payload = [json.loads(line) for line in lines[from_line:] if line.strip()]
    return envelope_ok({"logs": payload, "total_lines": len(lines), "from_line": from_line})


@router.get("/api/report/{report_id}/agent-log/stream")
def get_agent_log_stream(report_id: str, request: Request) -> dict[str, Any]:
    """Return the full structured agent log."""
    path = report_dir(request.app.state.settings, report_id) / "agent_log.jsonl"
    if not path.exists():
        return envelope_ok({"logs": [], "count": 0})
    logs = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return envelope_ok({"logs": logs, "count": len(logs)})


@router.get("/api/report/{report_id}/console-log")
def get_console_log(report_id: str, request: Request, from_line: int = Query(default=0)) -> dict[str, Any]:
    """Return raw console-style report generation logs."""
    path = report_dir(request.app.state.settings, report_id) / "console_log.txt"
    if not path.exists():
        return envelope_ok({"logs": [], "total_lines": 0, "from_line": from_line})
    lines = path.read_text(encoding="utf-8").splitlines()
    return envelope_ok({"logs": lines[from_line:], "total_lines": len(lines), "from_line": from_line})


@router.get("/api/report/{report_id}/console-log/stream")
def get_console_log_stream(report_id: str, request: Request) -> dict[str, Any]:
    """Return the full console log."""
    path = report_dir(request.app.state.settings, report_id) / "console_log.txt"
    if not path.exists():
        return envelope_ok({"logs": [], "count": 0})
    logs = path.read_text(encoding="utf-8").splitlines()
    return envelope_ok({"logs": logs, "count": len(logs)})


@router.get("/api/report/check/{simulation_id}")
def check_report_status(simulation_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    """Return whether a simulation already has a completed report."""
    report = _latest_report_for_simulation(session, simulation_id)
    has_report = report is not None
    report_status = report.status.value if report else None
    report_id = report.id if report else None
    interview_unlocked = has_report and report and report.status == WorkflowStatus.completed
    return envelope_ok(
        {
            "simulation_id": simulation_id,
            "has_report": has_report,
            "report_status": report_status,
            "report_id": report_id,
            "interview_unlocked": bool(interview_unlocked),
        }
    )


@router.post("/api/report/tools/search")
def report_tools_search(request: Request, payload: dict[str, Any], session: Session = Depends(get_session)) -> dict[str, Any]:
    """Search a graph payload for report debugging and parity support."""
    graph_id = str(payload.get("graph_id", "")).strip()
    query = str(payload.get("query", "")).strip()
    if not graph_id or not query:
        return envelope_error("Please provide both graph_id and query")
    graph = _selected_graph_payload(session, request, graph_id)
    lowered = query.lower()
    nodes = [
        item
        for item in graph.get("nodes", [])
        if lowered in str(item.get("name", "")).lower() or lowered in str(item.get("label", "")).lower()
    ]
    edges = [
        item
        for item in graph.get("edges", [])
        if lowered in str(item.get("relation_type", "")).lower() or lowered in str(item.get("fact", "")).lower()
    ]
    facts = [str(item.get("fact")) for item in edges if item.get("fact")]
    return envelope_ok({"query": query, "total_count": len(nodes) + len(edges), "facts": facts, "nodes": nodes, "edges": edges})


@router.post("/api/report/tools/statistics")
def report_tools_statistics(request: Request, payload: dict[str, Any], session: Session = Depends(get_session)) -> dict[str, Any]:
    """Return graph statistics for report debugging and parity support."""
    graph_id = str(payload.get("graph_id", "")).strip()
    if not graph_id:
        return envelope_error("Please provide graph_id")
    graph = _selected_graph_payload(session, request, graph_id)
    metadata = graph.get("metadata", {})
    return envelope_ok(
        {
            "graph_id": graph_id,
            "node_count": metadata.get("node_count", len(graph.get("nodes", []))),
            "edge_count": metadata.get("edge_count", len(graph.get("edges", []))),
            "entity_types": metadata.get("entity_types", []),
            "edge_types": metadata.get("edge_types", []),
        }
    )


@router.post("/api/report/chat")
def report_chat(request: Request, payload: dict[str, Any], session: Session = Depends(get_session)) -> dict[str, Any]:
    """Answer report chat questions using the clean-room reporting adapter."""
    simulation_id = str(payload.get("simulation_id", "")).strip()
    message = str(payload.get("message", "")).strip()
    chat_history = payload.get("chat_history") or []
    simulation = get_simulation_or_404(session, simulation_id)
    if not simulation:
        return envelope_error("Simulation not found")
    project = session.get(Project, simulation.project_id)
    if not project:
        return envelope_error("Project not found")
    report = _latest_report_for_simulation(session, simulation_id)
    normalized_history = [
        {
            "role": str(item.get("role") or "user").strip(),
            "content": str(item.get("content") or "").strip(),
        }
        for item in chat_history
        if isinstance(item, dict) and str(item.get("content") or "").strip()
    ][-6:]
    state = load_simulation_state(request.app.state.settings, simulation_id)
    graph_id = str(state.get("graph_id") or "")
    graph_payload = _selected_graph_payload(session, request, graph_id) if graph_id else {"nodes": [], "edges": [], "metadata": {}}
    graph_metadata = graph_payload.get("metadata", {}) if isinstance(graph_payload, dict) else {}
    query_terms = top_terms(message, limit=4)
    facts: list[str] = []
    if query_terms:
        for edge in graph_payload.get("edges", []):
            if not isinstance(edge, dict):
                continue
            haystack = " ".join(
                str(edge.get(key) or "")
                for key in ("fact", "relation_type", "source_name", "target_name")
            ).lower()
            if any(term.lower() in haystack for term in query_terms):
                fact = str(edge.get("fact") or edge.get("relation_type") or "").strip()
                if fact and fact not in facts:
                    facts.append(fact)
            if len(facts) >= 4:
                break
    sections = _section_payloads(report.id, request) if report else []
    section_snippets = [
        f"{item.get('title')}: {sanitize_short_model_text(str(item.get('content') or ''), str(item.get('title') or 'Section')) or str(item.get('title') or 'Section')}"
        for item in sections[:3]
    ]
    interview_history = load_simulation_interviews(request.app.state.settings, simulation_id)[-3:]
    interview_snippets = [
        f"{item.get('agent_name') or item.get('agent_id')}: {sanitize_short_model_text(str(item.get('response') or ''), 'Interview evidence available.') or 'Interview evidence available.'}"
        for item in interview_history
    ]
    evidence = load_report_evidence(request.app.state.settings, report.id) if report else {}
    if facts:
        evidence = {
            **evidence,
            "graph": {
                **(evidence.get("graph", {}) if isinstance(evidence.get("graph"), dict) else {}),
                "signals": facts,
            },
        }
    answer, sources, tool_calls = build_glass_report_chat_response(
        request.app.state.registry.llm,
        project=project,
        simulation=simulation,
        report=report,
        message=message,
        sections=sections,
        evidence=evidence,
        chat_history=normalized_history,
    )
    sources = [*sources, *facts, *interview_snippets]
    sources = [item for item in sources if item][:8]
    if graph_id and not any(item["name"] == "graph_statistics" for item in tool_calls):
        tool_calls.append({"name": "graph_statistics", "status": "completed"})
    if facts and not any(item["name"] == "panorama_search" for item in tool_calls):
        tool_calls.append({"name": "panorama_search", "status": "completed"})
    if interview_history and not any(item["name"] == "interview_history" for item in tool_calls):
        tool_calls.append({"name": "interview_history", "status": "completed"})
    return envelope_ok(
        {
            "simulation_id": simulation_id,
            "response": answer,
            "tool_calls": tool_calls,
            "sources": sources,
        }
    )
