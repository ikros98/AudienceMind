from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Query, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials

from .auth import bearer_scheme, get_auth_dependency
from .config import Settings, load_settings
from .llm import create_graphiti
from .metadata_store import GraphMetadataStore
from .models import (
    CreateGraphRequest,
    HealthResponse,
    IngestEpisodesRequest,
    SearchRequest,
    SetOntologyRequest,
)
from .service import GraphitiCompatibilityService


def _configure_logging(settings: Settings) -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


def _build_runtime() -> tuple[Settings, GraphitiCompatibilityService]:
    settings = load_settings()
    _configure_logging(settings)
    graphiti = create_graphiti(settings)
    metadata_store = GraphMetadataStore(settings.metadata_dir)
    service = GraphitiCompatibilityService(settings, graphiti, metadata_store)
    return settings, service


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings, service = _build_runtime()
    app.state.settings = settings
    app.state.require_auth = get_auth_dependency(settings)
    app.state.service = service
    await service.startup()
    yield


app = FastAPI(title="AudienceMind Graphiti Compatibility Service", lifespan=lifespan)


def get_service(request: Request) -> GraphitiCompatibilityService:
    return request.app.state.service


async def require_auth(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
):
    await request.app.state.require_auth(credentials)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logging.getLogger("graphiti_service").exception("Unhandled service error")
    return JSONResponse(status_code=500, content={"detail": str(exc)})


@app.get("/health", response_model=HealthResponse)
async def health(service: GraphitiCompatibilityService = Depends(get_service)):
    await service.check_neo4j()
    settings = service.settings
    return HealthResponse(
        status="ok",
        service=settings.service_name,
        neo4j="ok",
        metadata_dir=str(settings.metadata_dir),
        reasoning_force_off=settings.force_reasoning_off,
    )


@app.post("/graphs", dependencies=[Depends(require_auth)], response_model=None)
async def create_graph(
    body: CreateGraphRequest,
    service: GraphitiCompatibilityService = Depends(get_service),
):
    return service.create_graph(body)


@app.put("/graphs/{graph_id}/ontology", dependencies=[Depends(require_auth)], response_model=None)
async def set_ontology(
    graph_id: str,
    body: SetOntologyRequest,
    service: GraphitiCompatibilityService = Depends(get_service),
):
    return service.set_ontology(graph_id, body)


@app.post("/graphs/{graph_id}/episodes", dependencies=[Depends(require_auth)], response_model=None)
async def ingest_episodes(
    graph_id: str,
    body: IngestEpisodesRequest,
    service: GraphitiCompatibilityService = Depends(get_service),
):
    return await service.ingest_episodes(graph_id, body)


@app.get("/graphs/{graph_id}", dependencies=[Depends(require_auth)], response_model=None)
async def get_graph(
    graph_id: str,
    service: GraphitiCompatibilityService = Depends(get_service),
):
    return await service.get_graph(graph_id)


@app.get("/graphs/{graph_id}/nodes", dependencies=[Depends(require_auth)], response_model=None)
async def list_nodes(
    graph_id: str,
    limit: int = Query(default=200, ge=1, le=1000),
    cursor: str | None = Query(default=None),
    service: GraphitiCompatibilityService = Depends(get_service),
):
    return await service.list_nodes(graph_id, limit=limit, cursor=cursor)


@app.get("/graphs/{graph_id}/edges", dependencies=[Depends(require_auth)], response_model=None)
async def list_edges(
    graph_id: str,
    limit: int = Query(default=200, ge=1, le=1000),
    cursor: str | None = Query(default=None),
    service: GraphitiCompatibilityService = Depends(get_service),
):
    return await service.list_edges(graph_id, limit=limit, cursor=cursor)


@app.get("/graphs/{graph_id}/nodes/{node_uuid}", dependencies=[Depends(require_auth)], response_model=None)
async def get_node(
    graph_id: str,
    node_uuid: str,
    service: GraphitiCompatibilityService = Depends(get_service),
):
    return await service.get_node(graph_id, node_uuid)


@app.get("/graphs/{graph_id}/edges/{edge_uuid}", dependencies=[Depends(require_auth)], response_model=None)
async def get_edge(
    graph_id: str,
    edge_uuid: str,
    service: GraphitiCompatibilityService = Depends(get_service),
):
    return await service.get_edge(graph_id, edge_uuid)


@app.get(
    "/graphs/{graph_id}/nodes/{node_uuid}/edges",
    dependencies=[Depends(require_auth)],
    response_model=None,
)
async def get_node_edges(
    graph_id: str,
    node_uuid: str,
    service: GraphitiCompatibilityService = Depends(get_service),
):
    return await service.get_node_edges(graph_id, node_uuid)


@app.post("/graphs/{graph_id}/search", dependencies=[Depends(require_auth)], response_model=None)
async def search_graph(
    graph_id: str,
    body: SearchRequest,
    service: GraphitiCompatibilityService = Depends(get_service),
):
    return await service.search(graph_id, body)


@app.delete("/graphs/{graph_id}", dependencies=[Depends(require_auth)], response_model=None)
async def delete_graph(
    graph_id: str,
    service: GraphitiCompatibilityService = Depends(get_service),
):
    return await service.delete_graph(graph_id)
