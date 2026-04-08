"""Workflow queueing and execution services for PersonaGraph."""

from __future__ import annotations

import json
from threading import Event, Thread
import traceback

from sqlalchemy import update
from sqlmodel import Session, select

from ..config import Settings
from ..models import (
    GraphJob,
    Project,
    Report,
    Simulation,
    SourceDocument,
    WorkflowKind,
    WorkflowStatus,
    WorkflowUpdate,
)
from .runtime import RuntimeRegistry, utc_now, write_text_artifact


def _persist_records(session: Session, *records: object) -> None:
    """Persist one or more SQLModel records in a single transaction."""
    for record in records:
        session.add(record)
    session.commit()


def _workflow_kind(record: GraphJob | Simulation | Report) -> WorkflowKind:
    """Resolve the workflow kind enum for a workflow record."""
    if isinstance(record, GraphJob):
        return WorkflowKind.graph_job
    if isinstance(record, Simulation):
        return WorkflowKind.simulation
    return WorkflowKind.report


def _append_workflow_update(
    session: Session,
    record: GraphJob | Simulation | Report,
    *,
    message: str,
    progress_percent: float,
    level: str = "info",
    commit: bool = True,
) -> None:
    """Persist a workflow status update and mirror it onto the record."""
    record.progress_percent = max(0.0, min(progress_percent, 100.0))
    record.status_message = message[:500]
    record.updated_at = utc_now()
    session.add(record)
    session.add(
        WorkflowUpdate(
            workflow_kind=_workflow_kind(record),
            workflow_id=record.id,
            status=record.status,
            level=level,
            message=record.status_message,
            progress_percent=record.progress_percent,
            created_at=record.updated_at,
        )
    )
    if commit:
        session.commit()


def _mark_failed(
    session: Session,
    record: GraphJob | Simulation | Report,
    summary: str,
    *,
    project: Project | None = None,
) -> None:
    """Record a failed workflow state and optionally update the owning project."""
    failed_at = utc_now()
    record.status = WorkflowStatus.failed
    record.summary = summary[:500]
    record.error_message = summary[:2000]
    record.completed_at = failed_at
    record.updated_at = failed_at
    record.status_message = record.summary
    record.progress_percent = min(record.progress_percent, 99.0)
    if record.progress_percent < 0:
        record.progress_percent = 0.0
    session.add(record)
    session.add(
        WorkflowUpdate(
            workflow_kind=_workflow_kind(record),
            workflow_id=record.id,
            status=record.status,
            level="error",
            message=record.status_message,
            progress_percent=record.progress_percent,
            created_at=failed_at,
        )
    )
    if project is not None:
        project.status = WorkflowStatus.failed
        project.updated_at = record.updated_at
        session.add(project)
        session.commit()
        return
    session.commit()


def create_graph_job(
    session: Session,
    project: Project,
    graph_backend: str,
    objective: str,
) -> GraphJob:
    """Create a queued graph job."""
    now = utc_now()
    job = GraphJob(
        project_id=project.id,
        graph_backend=graph_backend,
        objective=objective,
        status=WorkflowStatus.queued,
        progress_percent=0.0,
        status_message="Queued graph artifact build.",
        error_message="",
        created_at=now,
        updated_at=now,
    )
    project.status = WorkflowStatus.running
    project.updated_at = now
    _persist_records(session, job, project)
    session.refresh(job)
    _append_workflow_update(
        session,
        job,
        message="Queued graph artifact build.",
        progress_percent=0.0,
    )
    return job


def create_simulation(
    session: Session,
    project: Project,
    graph_job: GraphJob | None,
    mode: str,
    cohort_size: int,
) -> Simulation:
    """Create a queued simulation."""
    now = utc_now()
    simulation = Simulation(
        project_id=project.id,
        graph_job_id=graph_job.id if graph_job else None,
        mode=mode,
        cohort_size=cohort_size,
        status=WorkflowStatus.queued,
        progress_percent=0.0,
        status_message="Queued simulation run.",
        error_message="",
        created_at=now,
        updated_at=now,
    )
    project.status = WorkflowStatus.running
    project.updated_at = now
    _persist_records(session, simulation, project)
    session.refresh(simulation)
    _append_workflow_update(
        session,
        simulation,
        message="Queued simulation run.",
        progress_percent=0.0,
    )
    return simulation


def create_report(
    session: Session,
    project: Project,
    simulation: Simulation,
    focus: str,
) -> Report:
    """Create a queued report job."""
    now = utc_now()
    report = Report(
        simulation_id=simulation.id,
        focus=focus,
        status=WorkflowStatus.queued,
        progress_percent=0.0,
        status_message="Queued report generation.",
        error_message="",
        created_at=now,
        updated_at=now,
    )
    project.status = WorkflowStatus.running
    project.updated_at = now
    _persist_records(session, report, project)
    session.refresh(report)
    _append_workflow_update(
        session,
        report,
        message="Queued report generation.",
        progress_percent=0.0,
    )
    return report

def _queued_graph_job(session: Session) -> GraphJob | None:
    statement = (
        select(GraphJob)
        .where(GraphJob.status == WorkflowStatus.queued)
        .order_by(GraphJob.created_at.asc())
    )
    return session.exec(statement).first()


def _queued_simulation(session: Session) -> Simulation | None:
    statement = (
        select(Simulation)
        .where(Simulation.status == WorkflowStatus.queued)
        .order_by(Simulation.created_at.asc())
    )
    queued_items = list(session.exec(statement).all())
    for simulation in queued_items:
        if not simulation.graph_job_id:
            return simulation
        graph_job = session.get(GraphJob, simulation.graph_job_id)
        if not graph_job or graph_job.status in {WorkflowStatus.completed, WorkflowStatus.failed}:
            return simulation
    return None


def _queued_report(session: Session) -> Report | None:
    statement = (
        select(Report)
        .where(Report.status == WorkflowStatus.queued)
        .order_by(Report.created_at.asc())
    )
    queued_items = list(session.exec(statement).all())
    for report in queued_items:
        simulation = session.get(Simulation, report.simulation_id)
        if not simulation or simulation.status in {WorkflowStatus.completed, WorkflowStatus.failed}:
            return report
    return None


def _claim_record(session: Session, record: GraphJob | Simulation | Report) -> bool:
    """Move a queued workflow record into running state, returning False if another worker won the claim."""
    model = type(record)
    claimed_at = utc_now()
    result = session.exec(
        update(model)
        .where(model.id == record.id)
        .where(model.status == WorkflowStatus.queued)
        .values(
            status=WorkflowStatus.running,
            progress_percent=1.0,
            status_message="Claimed by workflow runner.",
            error_message="",
            started_at=claimed_at,
            completed_at=None,
            updated_at=claimed_at,
        )
    )
    session.commit()
    return bool(result.rowcount)


def _execute_graph_job(session: Session, registry: RuntimeRegistry, job: GraphJob) -> None:
    """Execute a claimed graph job."""
    project = session.get(Project, job.project_id)
    if not project:
        raise RuntimeError("Project not found for graph job")

    _append_workflow_update(
        session,
        job,
        message="Loading project sources for graph preparation.",
        progress_percent=12.0,
    )
    settings = session.info["settings"]
    documents = list(
        session.exec(
            select(SourceDocument)
            .where(SourceDocument.project_id == project.id)
            .order_by(SourceDocument.created_at.desc())
        ).all()
    )
    _append_workflow_update(
        session,
        job,
        message=f"Prepared {len(documents)} source documents for graph generation.",
        progress_percent=32.0,
    )

    def graph_progress(progress_percent: float, message: str) -> None:
        bounded_progress = max(32.0, min(progress_percent, 96.0))
        _append_workflow_update(
            session,
            job,
            message=message,
            progress_percent=bounded_progress,
        )

    artifacts = registry.graph.build_artifacts(
        llm=registry.llm,
        project=project,
        documents=documents,
        objective=job.objective,
        graph_id=job.id,
        progress_callback=graph_progress,
    )
    _append_workflow_update(
        session,
        job,
        message="Graph artifacts generated. Persisting schema and evidence outputs.",
        progress_percent=78.0,
    )
    write_text_artifact(settings, "graph-jobs", job.id, "schema.md", artifacts.schema_markdown)
    write_text_artifact(settings, "graph-jobs", job.id, "evidence.md", artifacts.evidence_markdown)
    if artifacts.graph_payload is not None:
        write_text_artifact(
            settings,
            "graph-jobs",
            job.id,
            "graph.json",
            json.dumps(artifacts.graph_payload, indent=2, sort_keys=True),
        )
    completed_at = utc_now()
    job.status = WorkflowStatus.completed
    job.progress_percent = 100.0
    job.status_message = "Graph artifact ready for downstream simulation."
    job.summary = artifacts.summary
    job.source_digest = artifacts.source_digest
    job.node_count = artifacts.node_count
    job.edge_count = artifacts.edge_count
    job.schema_markdown = artifacts.schema_markdown
    job.evidence_markdown = artifacts.evidence_markdown
    job.error_message = ""
    job.completed_at = completed_at
    job.updated_at = completed_at
    project.updated_at = completed_at
    session.add(job)
    session.add(project)
    session.add(
        WorkflowUpdate(
            workflow_kind=WorkflowKind.graph_job,
            workflow_id=job.id,
            status=job.status,
            level="info",
            message=job.status_message,
            progress_percent=job.progress_percent,
            created_at=completed_at,
        )
    )
    session.commit()


def _execute_simulation(session: Session, registry: RuntimeRegistry, simulation: Simulation) -> None:
    """Execute a claimed simulation."""
    project = session.get(Project, simulation.project_id)
    if not project:
        raise RuntimeError("Project not found for simulation")

    _append_workflow_update(
        session,
        simulation,
        message="Validating project and graph inputs for simulation.",
        progress_percent=14.0,
    )
    graph_job = session.get(GraphJob, simulation.graph_job_id) if simulation.graph_job_id else None
    if graph_job and graph_job.status != WorkflowStatus.completed:
        raise RuntimeError("Simulation dependency graph job is not completed")

    settings = session.info["settings"]
    _append_workflow_update(
        session,
        simulation,
        message="Generating simulation timeline and event stream.",
        progress_percent=44.0,
    )
    artifacts = registry.simulation.build_artifacts(
        llm=registry.llm,
        project=project,
        graph_job=graph_job,
        mode=simulation.mode,
        cohort_size=simulation.cohort_size,
    )
    _append_workflow_update(
        session,
        simulation,
        message="Simulation artifacts generated. Persisting timeline and event log.",
        progress_percent=82.0,
    )
    write_text_artifact(settings, "simulations", simulation.id, "timeline.md", artifacts.timeline_markdown)
    write_text_artifact(settings, "simulations", simulation.id, "events.json", json.dumps(artifacts.events, indent=2))
    completed_at = utc_now()
    simulation.status = WorkflowStatus.completed
    simulation.progress_percent = 100.0
    simulation.status_message = "Simulation artifacts ready for report generation."
    simulation.summary = artifacts.summary
    simulation.rounds = artifacts.rounds
    simulation.event_count = artifacts.event_count
    simulation.timeline_markdown = artifacts.timeline_markdown
    simulation.event_log_json = json.dumps(artifacts.events)
    simulation.error_message = ""
    simulation.completed_at = completed_at
    simulation.updated_at = completed_at
    project.updated_at = completed_at
    session.add(simulation)
    session.add(project)
    session.add(
        WorkflowUpdate(
            workflow_kind=WorkflowKind.simulation,
            workflow_id=simulation.id,
            status=simulation.status,
            level="info",
            message=simulation.status_message,
            progress_percent=simulation.progress_percent,
            created_at=completed_at,
        )
    )
    session.commit()


def _execute_report(session: Session, registry: RuntimeRegistry, report: Report) -> None:
    """Execute a claimed report."""
    simulation = session.get(Simulation, report.simulation_id)
    if not simulation:
        raise RuntimeError("Simulation not found for report")
    if simulation.status != WorkflowStatus.completed:
        raise RuntimeError("Report dependency simulation is not completed")

    project = session.get(Project, simulation.project_id)
    if not project:
        raise RuntimeError("Project not found for report")

    settings = session.info["settings"]
    _append_workflow_update(
        session,
        report,
        message="Loading simulation evidence for report drafting.",
        progress_percent=16.0,
    )
    artifacts = registry.reporting.build_report_artifacts(
        llm=registry.llm,
        project=project,
        simulation=simulation,
        focus=report.focus,
    )
    _append_workflow_update(
        session,
        report,
        message="Report draft generated. Persisting markdown output.",
        progress_percent=84.0,
    )
    write_text_artifact(settings, "reports", report.id, "report.md", artifacts.markdown_body)
    completed_at = utc_now()
    report.status = WorkflowStatus.completed
    report.progress_percent = 100.0
    report.status_message = "Report ready in the analysis workspace."
    report.summary = artifacts.summary
    report.executive_summary = artifacts.executive_summary
    report.markdown_body = artifacts.markdown_body
    report.error_message = ""
    report.completed_at = completed_at
    report.updated_at = completed_at
    project.status = WorkflowStatus.completed
    project.updated_at = completed_at
    session.add(report)
    session.add(project)
    session.add(
        WorkflowUpdate(
            workflow_kind=WorkflowKind.report,
            workflow_id=report.id,
            status=report.status,
            level="info",
            message=report.status_message,
            progress_percent=report.progress_percent,
            created_at=completed_at,
        )
    )
    session.commit()


def reset_interrupted_workflows(session: Session) -> None:
    """Re-queue workflow records that were left running across a restart."""
    updated = False
    for model in (GraphJob, Simulation, Report):
        statement = select(model).where(model.status == WorkflowStatus.running)
        for record in session.exec(statement).all():
            record.status = WorkflowStatus.queued
            record.progress_percent = 0.0
            record.status_message = "Re-queued after workflow runner restart."
            record.updated_at = utc_now()
            session.add(record)
            session.add(
                WorkflowUpdate(
                    workflow_kind=_workflow_kind(record),
                    workflow_id=record.id,
                    status=record.status,
                    level="warn",
                    message=record.status_message,
                    progress_percent=record.progress_percent,
                    created_at=record.updated_at,
                )
            )
            updated = True
    if updated:
        session.commit()


class WorkflowRunner:
    """Background worker that drains queued graph, simulation, and report jobs."""

    def __init__(
        self,
        *,
        engine,
        settings: Settings,
        registry: RuntimeRegistry,
        poll_interval_seconds: float = 0.25,
    ):
        self.engine = engine
        self.settings = settings
        self.registry = registry
        self.poll_interval_seconds = poll_interval_seconds
        self._stop_event = Event()
        self._wake_event = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        """Start the background runner."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = Thread(target=self._run_loop, name="personagraph-workflow-runner", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the background runner."""
        self._stop_event.set()
        self.notify()
        if self._thread:
            self._thread.join(timeout=5)

    def notify(self) -> None:
        """Wake the runner when new queued work is available."""
        self._wake_event.set()

    def _session(self) -> Session:
        session = Session(self.engine)
        session.info["settings"] = self.settings
        session.info["registry"] = self.registry
        session.info["workflow_runner"] = self
        return session

    def _run_loop(self) -> None:
        with self._session() as session:
            reset_interrupted_workflows(session)

        while not self._stop_event.is_set():
            try:
                processed = self._process_next()
            except Exception:
                traceback.print_exc()
                processed = False
            if processed:
                continue
            self._wake_event.wait(self.poll_interval_seconds)
            self._wake_event.clear()

    def _process_next(self) -> bool:
        with self._session() as session:
            graph_job = _queued_graph_job(session)
            if graph_job:
                if not _claim_record(session, graph_job):
                    return True
                graph_job = session.get(GraphJob, graph_job.id)
                if not graph_job:
                    return True
                try:
                    _execute_graph_job(session, self.registry, graph_job)
                except Exception as exc:
                    project = session.get(Project, graph_job.project_id)
                    _mark_failed(session, graph_job, f"Graph generation failed: {exc}", project=project)
                return True

            simulation = _queued_simulation(session)
            if simulation:
                if not _claim_record(session, simulation):
                    return True
                simulation = session.get(Simulation, simulation.id)
                if not simulation:
                    return True
                try:
                    _execute_simulation(session, self.registry, simulation)
                except Exception as exc:
                    project = session.get(Project, simulation.project_id)
                    _mark_failed(session, simulation, f"Simulation generation failed: {exc}", project=project)
                return True

            report = _queued_report(session)
            if report:
                if not _claim_record(session, report):
                    return True
                report = session.get(Report, report.id)
                if not report:
                    return True
                try:
                    _execute_report(session, self.registry, report)
                except Exception as exc:
                    simulation = session.get(Simulation, report.simulation_id)
                    project = session.get(Project, simulation.project_id) if simulation else None
                    _mark_failed(session, report, f"Report generation failed: {exc}", project=project)
                return True

        return False
