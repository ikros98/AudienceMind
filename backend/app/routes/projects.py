"""Project routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlmodel import Session

from ..database import get_session
from ..models import Project
from ..schemas import (
    ListResponse,
    ProjectCreate,
    ProjectRead,
    SourceDocumentRead,
    SourceNoteCreate,
)
from ..services.runtime import (
    create_source_document,
    create_source_note,
    get_project_or_404,
    list_projects,
    list_source_documents,
    project_read_model,
    source_document_read_model,
    utc_now,
)

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=ListResponse[ProjectRead])
def get_projects(session: Session = Depends(get_session)) -> ListResponse[ProjectRead]:
    """List projects."""
    items = [
        project_read_model(project, len(list_source_documents(session, project.id)))
        for project in list_projects(session)
    ]
    return ListResponse(items=items)


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectCreate, session: Session = Depends(get_session)) -> ProjectRead:
    """Create a new project."""
    now = utc_now()
    project = Project(
        name=payload.name,
        description=payload.description,
        scenario_brief=payload.scenario_brief,
        created_at=now,
        updated_at=now,
    )
    session.add(project)
    session.commit()
    session.refresh(project)
    return project_read_model(project, source_count=0)


@router.get("/{project_id}", response_model=ProjectRead)
def get_project(project_id: str, session: Session = Depends(get_session)) -> ProjectRead:
    """Fetch a project by id."""
    project = get_project_or_404(session, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project_read_model(project, len(list_source_documents(session, project.id)))


@router.get("/{project_id}/sources", response_model=ListResponse[SourceDocumentRead])
def get_project_sources(project_id: str, session: Session = Depends(get_session)) -> ListResponse[SourceDocumentRead]:
    """List source documents attached to a project."""
    project = get_project_or_404(session, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    documents = [source_document_read_model(item) for item in list_source_documents(session, project_id)]
    return ListResponse(items=documents)


@router.post("/{project_id}/sources", response_model=ListResponse[SourceDocumentRead], status_code=status.HTTP_201_CREATED)
async def upload_project_sources(
    project_id: str,
    files: list[UploadFile] = File(...),
    session: Session = Depends(get_session),
) -> ListResponse[SourceDocumentRead]:
    """Upload source documents for a project."""
    project = get_project_or_404(session, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    settings = session.info["settings"]
    created_documents: list[SourceDocumentRead] = []
    for upload in files:
        raw_bytes = await upload.read()
        if not raw_bytes:
            continue
        document = create_source_document(
            session,
            settings,
            project_id,
            upload.filename or "source.txt",
            upload.content_type or "application/octet-stream",
            raw_bytes,
        )
        created_documents.append(source_document_read_model(document))

    if not created_documents:
        raise HTTPException(status_code=400, detail="No non-empty files were uploaded")

    return ListResponse(items=created_documents)


@router.post("/{project_id}/source-notes", response_model=SourceDocumentRead, status_code=status.HTTP_201_CREATED)
def create_project_source_note(
    project_id: str,
    payload: SourceNoteCreate,
    session: Session = Depends(get_session),
) -> SourceDocumentRead:
    """Create a text note source for a project."""
    project = get_project_or_404(session, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    settings = session.info["settings"]
    document = create_source_note(session, settings, project_id, payload.title, payload.content)
    return source_document_read_model(document)
