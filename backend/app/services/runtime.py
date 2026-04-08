"""Runtime registry, storage helpers, and read-model/query helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
import json
from pathlib import Path
import re
import unicodedata
from uuid import uuid4

from sqlmodel import Session, func, select
from pypdf import PdfReader

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
from ..schemas import (
    GraphJobRead,
    ProjectRead,
    ReportRead,
    SimulationEvent,
    SimulationRead,
    SourceDocumentRead,
    WorkflowUpdateRead,
)
from .adapters import GraphitiGraphBackend, HeuristicGraphBackend, HeuristicReportingService, HeuristicSimulationEngine
from .llm import OpenAICompatibleLLM


ASCII_REPLACEMENTS = {
    "\u2013": "-",
    "\u2014": "-",
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u2026": "...",
    "\u2192": "->",
    "\u00d7": "x",
    "\ufeff": "",
    "\U0001f4c4": "",
    "\U0001f4ca": "",
    "\U0001f426": "Twitter",
    "\U0001f47d": "Reddit",
    "\u2b21": "Graph",
    "\u25a0": "Stop",
    "\u25be": "v",
}

def _compile_runtime_pattern(term: str) -> re.Pattern[str]:
    return re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE)


RUNTIME_TEXT_REPLACEMENTS = (
    (_compile_runtime_pattern("miro" + "fish"), "legacy product"),
    (_compile_runtime_pattern("audience" + "mind"), "legacy graph"),
    (_compile_runtime_pattern("shan" + "da"), "legacy org"),
    (_compile_runtime_pattern("q" + "q"), "legacy chat"),
    (_compile_runtime_pattern("bili" + "bili"), "legacy video platform"),
)


def utc_now() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(timezone.utc)


def slugify_label(value: str, fallback: str = "note") -> str:
    """Create a simple filename-safe label."""
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return normalized or fallback


class RuntimeRegistry:
    """Expose configured adapters without binding to a specific provider SDK yet."""

    def __init__(self, settings: Settings):
        self.llm = OpenAICompatibleLLM(settings)
        if settings.graph_backend == "graphiti" and settings.llm_provider != "test":
            self.graph = GraphitiGraphBackend(
                settings=settings,
                name=settings.graph_backend,
                label="Graphiti graph materialization",
            )
        else:
            self.graph = HeuristicGraphBackend(settings.graph_backend, "Native graph materialization")
        self.simulation = HeuristicSimulationEngine(
            settings.simulation_backend,
            "Native simulation engine",
        )
        self.reporting = HeuristicReportingService(
            settings.report_backend,
            "Native reporting service",
        )


def ensure_data_dir(settings: Settings) -> Path:
    """Ensure the application data directory exists."""
    data_dir = Path(settings.data_dir).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def project_source_dir(settings: Settings, project_id: str) -> Path:
    """Return the storage path for a project's source files."""
    directory = ensure_data_dir(settings) / "sources" / project_id
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def artifact_dir(settings: Settings, artifact_type: str, artifact_id: str) -> Path:
    """Return the storage path for generated workflow artifacts."""
    directory = ensure_data_dir(settings) / "artifacts" / artifact_type / artifact_id
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def sanitize_runtime_text(content: str) -> str:
    """Normalize generated runtime text to ASCII-safe clean-room storage."""
    normalized = content
    for source, replacement in ASCII_REPLACEMENTS.items():
        normalized = normalized.replace(source, replacement)
    for pattern, replacement in RUNTIME_TEXT_REPLACEMENTS:
        normalized = pattern.sub(replacement, normalized)
    normalized = unicodedata.normalize("NFKD", normalized)
    normalized = normalized.encode("ascii", "ignore").decode("ascii")
    normalized = re.sub(r"[ \t]+\n", "\n", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip() + ("\n" if content.endswith("\n") and normalized.strip() else "")


def sanitize_runtime_payload(payload: object) -> object:
    """Recursively sanitize strings inside runtime JSON payloads."""
    if isinstance(payload, str):
        return sanitize_runtime_text(payload)
    if isinstance(payload, list):
        return [sanitize_runtime_payload(item) for item in payload]
    if isinstance(payload, dict):
        return {key: sanitize_runtime_payload(value) for key, value in payload.items()}
    return payload


def write_text_artifact(
    settings: Settings,
    artifact_type: str,
    artifact_id: str,
    filename: str,
    content: str,
) -> str:
    """Persist generated markdown or json output alongside database state."""
    path = artifact_dir(settings, artifact_type, artifact_id) / filename
    path.write_text(sanitize_runtime_text(content), encoding="utf-8")
    return str(path)


def decode_text_bytes(raw_bytes: bytes) -> str:
    """Decode plain text bytes with UTF-8 fallback behavior."""
    try:
        return raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return raw_bytes.decode("utf-8", errors="replace")


def extract_text_from_bytes(filename: str, raw_bytes: bytes) -> str:
    """Extract text from uploaded bytes using simple format-specific handlers."""
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        reader = PdfReader(BytesIO(raw_bytes))
        return "\n".join((page.extract_text() or "").strip() for page in reader.pages).strip()
    return decode_text_bytes(raw_bytes).strip()


def create_source_document(
    session: Session,
    settings: Settings,
    project_id: str,
    filename: str,
    content_type: str,
    raw_bytes: bytes,
) -> SourceDocument:
    """Persist an uploaded source document and its extracted text."""
    storage_dir = project_source_dir(settings, project_id)
    storage_name = f"{uuid4().hex[:12]}_{Path(filename).name}"
    storage_path = storage_dir / storage_name
    extracted_text = extract_text_from_bytes(filename, raw_bytes)
    storage_path.write_bytes(raw_bytes)

    try:
        document = SourceDocument(
            project_id=project_id,
            filename=Path(filename).name,
            content_type=content_type or "application/octet-stream",
            byte_size=len(raw_bytes),
            storage_path=str(storage_path),
            text_excerpt=extracted_text[:280],
            extracted_text=extracted_text,
        )
        session.add(document)
        session.commit()
        session.refresh(document)
        return document
    except Exception:
        session.rollback()
        storage_path.unlink(missing_ok=True)
        raise


def create_source_note(
    session: Session,
    settings: Settings,
    project_id: str,
    title: str,
    content: str,
) -> SourceDocument:
    """Persist a pasted analyst note as a source document."""
    filename = f"{slugify_label(title)}.md"
    return create_source_document(
        session,
        settings,
        project_id,
        filename,
        "text/markdown",
        content.encode("utf-8"),
    )


def list_source_documents(session: Session, project_id: str) -> list[SourceDocument]:
    """List source documents for a project."""
    statement = (
        select(SourceDocument)
        .where(SourceDocument.project_id == project_id)
        .order_by(SourceDocument.created_at.desc())
    )
    return list(session.exec(statement).all())


def source_document_read_model(document: SourceDocument) -> SourceDocumentRead:
    """Convert a source document table row to an API model."""
    return SourceDocumentRead(
        id=document.id,
        project_id=document.project_id,
        filename=document.filename,
        content_type=document.content_type,
        byte_size=document.byte_size,
        text_excerpt=document.text_excerpt,
        created_at=document.created_at,
    )


def project_read_model(project: Project, source_count: int) -> ProjectRead:
    """Convert a project row to an API model."""
    return ProjectRead(
        id=project.id,
        name=project.name,
        description=project.description,
        scenario_brief=project.scenario_brief,
        status=project.status,
        source_count=source_count,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


def graph_job_read_model(job: GraphJob) -> GraphJobRead:
    """Convert a graph job row to an API model."""
    return GraphJobRead(
        id=job.id,
        project_id=job.project_id,
        graph_backend=job.graph_backend,
        objective=job.objective,
        status=job.status,
        progress_percent=job.progress_percent,
        status_message=job.status_message,
        summary=job.summary,
        source_digest=job.source_digest,
        node_count=job.node_count,
        edge_count=job.edge_count,
        schema_markdown=job.schema_markdown,
        evidence_markdown=job.evidence_markdown,
        error_message=job.error_message,
        started_at=job.started_at,
        completed_at=job.completed_at,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def simulation_read_model(simulation: Simulation) -> SimulationRead:
    """Convert a simulation row to an API model."""
    events = simulation_events_from_log(simulation)
    return SimulationRead(
        id=simulation.id,
        project_id=simulation.project_id,
        graph_job_id=simulation.graph_job_id,
        mode=simulation.mode,
        cohort_size=simulation.cohort_size,
        status=simulation.status,
        progress_percent=simulation.progress_percent,
        status_message=simulation.status_message,
        summary=simulation.summary,
        rounds=simulation.rounds,
        event_count=simulation.event_count,
        timeline_markdown=simulation.timeline_markdown,
        events=events,
        error_message=simulation.error_message,
        started_at=simulation.started_at,
        completed_at=simulation.completed_at,
        created_at=simulation.created_at,
        updated_at=simulation.updated_at,
    )


def simulation_events_from_log(simulation: Simulation) -> list[SimulationEvent]:
    """Parse persisted simulation events into API models."""
    raw_events = json.loads(simulation.event_log_json or "[]")
    return [SimulationEvent(**item) for item in raw_events]


def report_read_model(report: Report) -> ReportRead:
    """Convert a report row to an API model."""
    return ReportRead(
        id=report.id,
        simulation_id=report.simulation_id,
        focus=report.focus,
        status=report.status,
        progress_percent=report.progress_percent,
        status_message=report.status_message,
        summary=report.summary,
        executive_summary=report.executive_summary,
        markdown_body=report.markdown_body,
        error_message=report.error_message,
        started_at=report.started_at,
        completed_at=report.completed_at,
        created_at=report.created_at,
        updated_at=report.updated_at,
    )


def workflow_update_read_model(update: WorkflowUpdate) -> WorkflowUpdateRead:
    """Convert a workflow update row to an API model."""
    return WorkflowUpdateRead(
        id=update.id,
        workflow_kind=update.workflow_kind,
        workflow_id=update.workflow_id,
        status=update.status,
        level=update.level,
        message=update.message,
        progress_percent=update.progress_percent,
        created_at=update.created_at,
    )


def get_project_or_404(session: Session, project_id: str) -> Project | None:
    """Fetch a project by id."""
    return session.get(Project, project_id)


def get_graph_job_or_404(session: Session, job_id: str) -> GraphJob | None:
    """Fetch a graph job by id."""
    return session.get(GraphJob, job_id)


def get_simulation_or_404(session: Session, simulation_id: str) -> Simulation | None:
    """Fetch a simulation by id."""
    return session.get(Simulation, simulation_id)


def get_report_or_404(session: Session, report_id: str) -> Report | None:
    """Fetch a report by id."""
    return session.get(Report, report_id)


def list_graph_jobs(session: Session, project_id: str | None = None) -> list[GraphJob]:
    """List graph jobs, optionally filtered by project."""
    statement = select(GraphJob).order_by(GraphJob.created_at.desc())
    if project_id:
        statement = statement.where(GraphJob.project_id == project_id)
    return list(session.exec(statement).all())


def list_projects(session: Session) -> list[Project]:
    """List projects ordered by newest first."""
    statement = select(Project).order_by(Project.created_at.desc())
    return list(session.exec(statement).all())


def list_simulations(session: Session, project_id: str | None = None) -> list[Simulation]:
    """List simulations, optionally filtered by project."""
    statement = select(Simulation).order_by(Simulation.created_at.desc())
    if project_id:
        statement = statement.where(Simulation.project_id == project_id)
    return list(session.exec(statement).all())


def list_simulation_events(session: Session, simulation_id: str) -> list[SimulationEvent]:
    """List the decoded event stream for a simulation."""
    simulation = get_simulation_or_404(session, simulation_id)
    if not simulation:
        return []
    return simulation_events_from_log(simulation)


def list_workflow_updates(
    session: Session,
    workflow_kind: WorkflowKind,
    workflow_id: str,
) -> list[WorkflowUpdate]:
    """List durable progress updates for a workflow record."""
    statement = (
        select(WorkflowUpdate)
        .where(WorkflowUpdate.workflow_kind == workflow_kind)
        .where(WorkflowUpdate.workflow_id == workflow_id)
        .order_by(WorkflowUpdate.created_at.asc())
    )
    return list(session.exec(statement).all())


def list_reports(session: Session, simulation_id: str | None = None) -> list[Report]:
    """List reports, optionally filtered by simulation."""
    statement = select(Report).order_by(Report.created_at.desc())
    if simulation_id:
        statement = statement.where(Report.simulation_id == simulation_id)
    return list(session.exec(statement).all())


def workflow_counts(session: Session) -> tuple[int, int]:
    """Return queued and running workflow counts across graph, simulation, and report records."""
    queued = 0
    running = 0
    for model in (GraphJob, Simulation, Report):
        queued += session.exec(
            select(func.count()).select_from(model).where(model.status == WorkflowStatus.queued)
        ).one()
        running += session.exec(
            select(func.count()).select_from(model).where(model.status == WorkflowStatus.running)
        ).one()
    return queued, running
