# AudienceMind Backend

FastAPI service for the new AudienceMind application.

The React workflow frontend primarily talks to the backend through the compatibility surface under `/api/`, which is implemented in `app/routes/legacy_compat.py` but backed by the current native AudienceMind runtime.

## Current API Surface

- `GET /health`
- `GET /projects`
- `POST /projects`
- `GET /projects/{project_id}`
- `GET /projects/{project_id}/sources`
- `POST /projects/{project_id}/sources`
- `POST /projects/{project_id}/source-notes`
- `GET /projects/{project_id}/graph-jobs`
- `POST /projects/{project_id}/graph-jobs`
- `GET /graph-jobs`
- `GET /graph-jobs/{job_id}`
- `GET /simulations`
- `POST /simulations`
- `GET /simulations/{simulation_id}`
- `GET /simulations/{simulation_id}/events`
- `GET /reports`
- `POST /reports`
- `GET /reports/{report_id}`
- `POST /analysis/chat`

Artifacts are written under `PERSONAGRAPH_DATA_DIR`:

- `sources/<project_id>/...`
- `artifacts/graph-jobs/<graph_job_id>/...`
- `artifacts/simulations/<simulation_id>/...`
- `artifacts/reports/<report_id>/...`
- `glass/projects/<project_id>/...`
- `glass/graphs/<graph_job_id>.json`
- `glass/simulations/<simulation_id>/...`
- `glass/reports/<report_id>/...`

Workflow execution is split across:

- `app/services/generation.py` for pure local generation helpers
- `app/services/adapters.py` for graph, simulation, and reporting adapter boundaries
- `app/services/runtime.py` for registry, persistence helpers, read models, and queries
- `app/services/workflows.py` for queueing, atomic claims, execution, and workflow status transitions

Graph jobs, simulations, and reports now persist `queued`, `running`, `completed`, and `failed` states plus failure detail. They can be executed either by an embedded background runner or by the standalone worker entrypoint in `app/worker.py`.

The runner:

- polls for queued work using `PERSONAGRAPH_WORKFLOW_POLL_INTERVAL_SECONDS`
- re-queues `running` workflow records on startup to recover from interrupted local runs
- processes graph jobs before simulations and reports so queued dependencies settle in order
- claims queued work atomically in the database before execution so API and worker processes can coexist safely

## Local Run

```bash
uv sync
uv run uvicorn app.main:app --reload --port 8020
```

Copy `.env.example` to `.env` if you want a local backend-specific configuration file. The settings loader now reads both `backend/.env` and `../.env`.

## Standalone Worker

Run the API without the embedded runner:

```bash
PERSONAGRAPH_EMBED_WORKFLOW_RUNNER=false uv run uvicorn app.main:app --reload --port 8020
```

Run the worker in a separate terminal:

```bash
uv run personagraph-worker
```

## Container Run

The backend image is in `backend/Dockerfile`. The full split stack is defined in `../docker-compose.yml`.

## Test

```bash
uv run pytest
```
