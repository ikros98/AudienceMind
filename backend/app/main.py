"""FastAPI entrypoint for PersonaGraph."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import Settings, get_settings
from .database import create_db_engine, init_database
from .routes.analysis import router as analysis_router
from .routes.graph_jobs import project_router as project_graph_jobs_router
from .routes.graph_jobs import router as graph_jobs_router
from .routes.health import router as health_router
from .routes.legacy_compat import router as legacy_compat_router
from .routes.projects import router as projects_router
from .routes.reports import router as reports_router
from .routes.simulations import router as simulations_router
from .services.glass_compat import GlassRuntimeManager
from .services.runtime import RuntimeRegistry
from .services.workflows import WorkflowRunner


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the FastAPI application."""
    resolved_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = create_db_engine(resolved_settings.database_url)
        registry = RuntimeRegistry(resolved_settings)
        workflow_runner = None
        if resolved_settings.embed_workflow_runner:
            workflow_runner = WorkflowRunner(
                engine=engine,
                settings=resolved_settings,
                registry=registry,
                poll_interval_seconds=resolved_settings.workflow_poll_interval_seconds,
            )
        app.state.settings = resolved_settings
        app.state.engine = engine
        app.state.registry = registry
        app.state.workflow_runner = workflow_runner
        app.state.glass_runtime = GlassRuntimeManager(
            engine=engine,
            settings=resolved_settings,
            registry=registry,
        )
        init_database(engine)
        if workflow_runner:
            workflow_runner.start()
        yield
        app.state.glass_runtime.shutdown()
        if workflow_runner:
            workflow_runner.stop()

    app = FastAPI(
        title=resolved_settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health_router)
    app.include_router(projects_router)
    app.include_router(graph_jobs_router)
    app.include_router(project_graph_jobs_router)
    app.include_router(simulations_router)
    app.include_router(reports_router)
    app.include_router(analysis_router)
    app.include_router(legacy_compat_router)
    return app


app = create_app()
