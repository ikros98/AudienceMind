# AudienceMind Architecture Overview

## Scope
The repository root is the English-only implementation path for AudienceMind. It contains the active product codebase, current branding, and compliance controls.

## Core Principles
- Keep any archived or support material outside the active root app.
- Do not reuse retired brand names, assets, screenshots, prompts, or user-facing copy in the active app.
- Keep the app English-only across code comments, docs, logs, examples, and UI text.
- Treat compliance checks as part of the normal build workflow, not as a manual cleanup step.

## Delivery Areas
- `frontend`: split-stage workflow UI and frontend API client.
- `backend`: API, workflow orchestration, and adapter boundaries.
- `docs`: implementation guidance and compliance notes.
- `scripts`: local automation for compliance and developer checks.
- Generated runtime storage under `backend/data` is treated as disposable artifact output, not clean-room source; compliance scans now target implementation paths and a dedicated sanitizer can normalize stored artifacts when needed.

## Implemented Vertical Slice
- Project creation and source ingestion through uploaded files and pasted analyst notes.
- Project-scoped graph artifact creation now supports live Graphiti materialization and cached baseline/live payload snapshots persisted to disk.
- Graphiti-bound ontologies are now sanitized into Graphiti-safe identifiers before ingestion, while the read path restores human-readable labels for the glass workflow.
- Graphiti ingestion now mirrors the reference single-episode flow more closely, using leaner extraction instructions plus timeout-aware sub-chunk retries so large local-model graph builds are less likely to stall mid-ingest.
- Ontology generation is domain-specific rather than generic placeholder schema, and graph build refreshes stored generic ontologies before materialization when older draft projects are reopened.
- Simulation creation now supports native clean-room preparation, a native OASIS-backed worker for non-test runs, live environment lifecycle, persisted timeline/action/post/comment artifacts, and compatibility reads through FastAPI.
- Native preparation now derives personas and config from the materialized graph entity inventory, persists preparation manifests, and schedules event injections for later runtime rounds.
- Report generation now supports native clean-room orchestration with sanitized section, markdown, and log reads persisted to disk.
- Report-grounded chat uses the current simulation and optional report context.
- The `/api/...` compatibility facade is the stable contract used by the current React workflow client.
- Workflow services now persist explicit `queued`, `running`, `completed`, and `failed` states plus failure detail for graph jobs, simulations, and reports.
- Workflow records now also persist live `progress_percent`, `status_message`, `started_at`, and `completed_at` telemetry so the frontend can show long-running state without inventing client-side progress.
- Durable workflow update feeds are now exposed per artifact so graph, simulation, and report stages can surface an audit trail of queueing, execution, restart recovery, completion, and failure.
- Backend lifespan now starts a durable local workflow runner that executes queued jobs outside the request path and re-queues interrupted `running` work on restart.
- The queue can now run in two modes: embedded during local development or as a dedicated standalone worker process for split deployment.
- Queue claims are now atomic in the database so API and worker processes can share the same workflow tables safely.
- The frontend now uses a reusable split-workbench stage layout with `Graph`, `Split`, and `Workbench` view modes across the analyst workflow.
- The compatibility layer now uses native graph, simulation, and reporting behavior by default while keeping FastAPI as the only client-facing backend for the workflow UI.
- Native workflow runs now persist posts, comments, environment state, graph deltas, interviews, and report sections inside AudienceMind-owned runtime storage.
- Native reports now ground their summaries in graph statistics, runtime posts/comments, active-agent selection, and interview evidence rather than using only action-count summaries.
- The native AudienceMind runtime is the supported path for graph, simulation, report, and interaction workflows.
- Native simulations launch an AudienceMind-owned OASIS worker process that writes authoritative runtime artifacts, including action logs, environment state, post/comment snapshots, worker logs, and filesystem IPC messages for live interviews and environment shutdown.
- Backend tests still use a deterministic in-process simulation path when `PERSONAGRAPH_LLM_PROVIDER=test`, a retained compatibility-only test flag, so test-mode speed and reproducibility are preserved without changing the production runtime path.
- Non-test preparation uses structured graph-grounded persona and config enrichment, including richer trust lenses, narrative roles, platform behavior, agent pacing, seeded posts, scheduled events, and platform tuning, while preserving deterministic fallbacks for tests and provider failures.
- Brand-reaction scenarios now select a social-simulation ontology and cast shape first, biasing toward roles such as consumer cohorts, fashion media, influencers, executives, institutional actors, and competitors while keeping products, events, and locations as supporting evidence.
- Preparation now normalizes Graphiti label drift and promotes actor-like generic entities into the cast, so graph builds with retailer, partner, or platform nodes stay closer to the reference preparation depth instead of collapsing to a tiny persona set.
- The run-start path keeps the requested round cap consistent between setup, route state, API payloads, and persisted runtime state, which makes preview checks reproducible.
- Native preview runs now use denser OASIS activity defaults, more seeded posts, and higher per-platform participant caps so short runs show realistic contention instead of a thin trace.
- Non-test reports use outline-aware section drafting and richer evidence packaging so the analyst workflow carries graph, runtime, and interview context through both report generation and follow-up chat.

## Required Checks Before Shipping
- No banned legacy brand names appear in the new app paths.
- No non-ASCII filenames appear in the new app paths.
- No non-ASCII characters appear in source or docs unless explicitly allowed and documented.
- All new user-facing documentation is in English.
