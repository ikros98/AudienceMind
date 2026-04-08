# PersonaGraph

PersonaGraph is the active English-only clean-room implementation for graph-backed scenario simulation, analyst workbench flows, and report generation.

## What Is Here

- `frontend/`: React + Vite workflow used for the `Graph -> Setup -> Simulate -> Report -> Interact` flow
- `backend/`: FastAPI API, SQLModel persistence, queue runner, native OASIS runtime worker, and standalone workflow worker
- `docs/`: architecture, QA, and compliance documentation
- `scripts/`: compliance and local utility scripts
- `deploy/`: deployment helpers, including the local Graphiti compatibility stack

## Workflow

- `Graph`: create a project, upload source files, generate the ontology, and inspect the graph
- `Setup`: prepare the simulation cast, pacing, and runtime config
- `Simulate`: run the environment and inspect posts, comments, and timeline activity
- `Report`: generate the grounded markdown report and browse the sections
- `Interact`: ask follow-up questions against the report and runtime evidence

The main analyst views now share the same split-workbench structure with `Graph`, `Split`, and `Workbench` display modes.

## Local Development

1. Copy `.env.example` to `.env` if you want repo-level defaults.
2. Copy `backend/.env.example` or `frontend/.env.example` if you want service-local overrides.
3. Start the backend from `backend/`.
4. Start the frontend from `frontend/`.

Backend:

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload --port 8020
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

## Workflow Execution

Graph jobs, simulations, and reports are queued first and then executed by a workflow runner.

- local default: the API starts an embedded runner
- split deployment: set `PERSONAGRAPH_EMBED_WORKFLOW_RUNNER=false` for the API and run `uv run personagraph-worker` separately
- queue claims are atomic in the database so API and worker processes can coexist safely
- each workflow record now persists live `progress_percent`, `status_message`, `started_at`, and `completed_at` fields
- durable update feeds are available at `/graph-jobs/{id}/updates`, `/simulations/{id}/updates`, and `/reports/{id}/updates`

## Frontend Surface

The FastAPI backend exposes the compatibility surface under `/api/...` for the frontend in `frontend/`.

- use `frontend` to exercise the split-stage `Graph -> Setup -> Simulate -> Report -> Interact` flow against the clean-room backend
- the default local backend target for that app is `http://localhost:8020`
- the compatibility layer now runs natively on the FastAPI backend by default: graph build/read stays on Graphiti while setup, simulation, posts/comments, interviews, report generation, and report chat use PersonaGraph runtime storage under `backend/data`
- graph data exposed through the workflow API now comes from the live Graphiti graph when available, with a cached baseline payload preserved for delta rendering in the simulation view
- Graphiti ingestion now normalizes ontology labels into Graphiti-safe identifiers at write time while preserving readable labels in the glass payload, so real graph builds do not fall back to placeholder scaffolds
- ontology generation for the workflow flow is now domain-specific instead of the older generic placeholder schema, and graph build automatically regenerates stored generic ontologies before materialization
- brand-reaction scenarios now bias toward a social-simulation ontology with actor roles such as luxury brands, consumer cohorts, fashion media, influencers, executives, and institutional actors instead of flattening everything into a generic brand taxonomy
- Graphiti ingest now stays on single-episode batches like the reference flow, but each episode uses a leaner extraction prompt and the client now retries timeout-like failures with smaller sub-chunks
- the current local chat stack is wired to OpenRouter `qwen/qwen3.6-plus:free`, while embeddings can still stay on a separate dedicated endpoint; if you switch Graphiti to a slower provider path, expect more batches and lower ingest throughput, while faster dedicated inference can still support larger episodes and fewer batches
- local Graphiti development now defaults to a higher `GRAPHITI_TIMEOUT_SECONDS` because large brand briefs on local models regularly exceed the earlier 300-second client budget
- generic Graphiti nodes that are obviously countries or cities now normalize to `Location` on readback, so the glass graph no longer exposes raw `Entity` labels for those nodes
- the native PersonaGraph runtime is now the supported execution path for `frontend`
- non-test simulation runs now execute inside a PersonaGraph-owned OASIS worker process backed by `camel-oasis` and `camel-ai`
- backend test runs still use a deterministic in-process simulation path when `PERSONAGRAPH_LLM_PROVIDER=test` so tests remain fast and reproducible
- graph-grounded preparation persists `prepared_entities.json` and `preparation_manifest.json` alongside generated profiles and config
- each native glass simulation persists runtime artifacts such as `state.json`, `env.json`, platform action logs, post and comment snapshots, worker logs, interview IPC files, and scheduled-event activity under `backend/data/glass/simulations/<simulation_id>/`
- non-test preparation now uses structured graph-grounded persona and config enrichment, including richer trust lenses, narrative roles, platform behavior, agent pacing, seeded posts, scheduled events, and platform tuning, with deterministic fallback preserved for test mode
- graph-grounded preparation now separates evidence nodes from likely simulation actors more aggressively, which keeps the graph rich while making the simulation cast more role-balanced
- preparation now normalizes Graphiti labels and promotes actor-like generic entities such as retail partners, platforms, and institutions into the simulation cast, which keeps Ralph Lauren-style scenarios much closer to the reference cast size
- the run-start contract now preserves the requested round cap through the glass setup UI, the compat API, and the persisted native runtime state
- native preview runs now use denser activity defaults, more seeded posts, and higher per-platform participation so short `10`-round checks produce more realistic social output
- non-test report drafting uses the configured LLM opportunistically for richer outline planning, section drafting, summary, and recommendation text, while live interviews carry richer persona context into the native OASIS worker
- native glass reports now ground their sections and follow-up chat in graph statistics, runtime signals, and persisted interview history instead of relying only on summary strings

Typical local commands:

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload --port 8020

cd ../frontend
npm install
npm run dev
```

The frontend defaults to `http://localhost:3020` in local development.
When the frontend is opened on `localhost`, the client now pins local API traffic to `http://127.0.0.1:8020` to avoid intermittent IPv6 `localhost` resolution failures on machines where the backend only listens on IPv4 loopback.

### OpenRouter LLM setup

The current local default chat model is OpenRouter:

```env
LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_MODEL_NAME=qwen/qwen3.6-plus:free
```

Put your OpenRouter key in the repo root `.env`:

```env
LLM_API_KEY=your_openrouter_api_key_here
```

The local Graphiti service will inherit that same key and chat endpoint by default. Only set `GRAPHITI_LLM_API_KEY` or edit `deploy/graphiti/local.env` if you want Graphiti to use a different provider from the main app.

The backend sync step now installs the native OASIS runtime dependencies used by the glass simulation worker:

- `camel-oasis`
- `camel-ai`
- `openai`

## Main Environment Variables

- `PERSONAGRAPH_DATABASE_URL`
- `PERSONAGRAPH_DATA_DIR`
- `PERSONAGRAPH_ALLOWED_ORIGINS`
- `PERSONAGRAPH_LLM_PROVIDER`
- `PERSONAGRAPH_LLM_BASE_URL`
- `PERSONAGRAPH_LLM_API_KEY`
- `PERSONAGRAPH_LLM_MODEL`
- `PERSONAGRAPH_GRAPH_BACKEND`
- `PERSONAGRAPH_GRAPHITI_BASE_URL`
- `PERSONAGRAPH_GRAPHITI_API_KEY`
- `PERSONAGRAPH_GRAPHITI_TIMEOUT_SECONDS`
- `PERSONAGRAPH_SIMULATION_BACKEND`
- `PERSONAGRAPH_REPORT_BACKEND`
- `PERSONAGRAPH_EMBED_WORKFLOW_RUNNER`
- `PERSONAGRAPH_WORKFLOW_POLL_INTERVAL_SECONDS`

## Containers

Run the split stack with Postgres, API, worker, and frontend:

```bash
docker compose up --build
```

Default ports:

- frontend: `http://localhost:4173`
- container API: `http://localhost:8000`
- Postgres: `localhost:5432`

## Ollama Development

Forward the remote Ollama instance locally:

```bash
ssh -N -L 11434:127.0.0.1:11434 -i ~/.ssh/ndeamonrd.pem paperspace@184.105.157.30
```

Then point the backend base URL to `http://127.0.0.1:11434/v1`.

Helper scripts:

```bash
./scripts/start_ollama_tunnel.sh
./scripts/check_ollama.sh
```

## Verification

```bash
cd backend && uv run pytest
cd frontend && npm run build
python3 scripts/compliance_scan.py
python3 scripts/sanitize_runtime_artifacts.py
docker compose config
```

## Reference Docs

- [Implementation Plan](./IMPLEMENTATION_PLAN.md)
- [Architecture Overview](./docs/rewrite-overview.md)
- [Final Use Cases](./docs/final-use-cases.md)
- [Most Valuable Use Cases](./docs/use-cases.md)
- [Use-Case Expansion Map](./docs/use-case-expansion-map.md)
- [Compliance Notes](./docs/compliance.md)
- [QA Test Plan](./docs/qa-test-plan.md)
