# AudienceMind QA Test Plan

This plan is for a QA engineer who needs to validate the full AudienceMind platform quickly with a small scenario that runs comfortably on a local OpenAI-compatible or Ollama-compatible setup.

## Goal

Validate that the current AudienceMind stack works end to end:

- backend starts and serves the API
- frontend renders all workflow stages
- graph, simulation, report, and interaction workflows complete successfully
- queued workflow status transitions behave correctly
- split-workbench UI modes render correctly across the main stages
- basic failure handling and guardrails behave as expected

## Recommended Test Profile

Use the smallest practical local profile for a quick run:

- LLM provider: OpenAI-compatible or Ollama-compatible endpoint
- model: one small local or hosted model that is already configured
- database: local SQLite
- runner mode: embedded in the API for the main smoke test
- source material: one pasted note, no large PDFs
- round cap: `10`
- report focus: one short sentence

This keeps the run short while still touching the full product flow.

## Test Environment

Run the app locally:

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload --port 8020
```

In another terminal:

```bash
cd frontend
npm install
npm run dev -- --host 127.0.0.1 --port 3020
```

If Ollama is on the remote development host:

```bash
./scripts/start_ollama_tunnel.sh
./scripts/check_ollama.sh
```

Suggested environment values:

```env
PERSONAGRAPH_GRAPH_BACKEND=graphiti
PERSONAGRAPH_SIMULATION_BACKEND=native
PERSONAGRAPH_REPORT_BACKEND=native
PERSONAGRAPH_EMBED_WORKFLOW_RUNNER=true
```

The `PERSONAGRAPH_*` values above are retained compatibility-only environment names for the AudienceMind runtime.

## Simple Test Scenario

Create one project with this sample data.

Project name:

`Local Grid Messaging Drill`

Project description:

`Quick smoke-test workspace for outage response and communications planning.`

Scenario brief:

`A regional grid outage lasts several hours. Operators restore service in phases while public messaging lags behind field recovery. The analyst team wants to understand the likely pressure points, narrative shifts, and first-day response risks.`

Source note title:

`Operator field note`

Source note content:

`Field teams expect power restoration to reach critical areas before the public sees clear status updates. Local officials may push for reassurance messaging early, while customers may interpret silence as loss of control. Analysts should watch for a gap between operational progress and public confidence.`

Graph objective:

`Surface actor pressure points, communications risk, and restoration dependencies for the first 24 hours.`

Preview rounds:

`10`

Report focus:

`Summarize the biggest decision and communication risks in the first day.`

Report chat prompt:

`What should the team monitor first during the first 24 hours?`

## Test Phases

### 1. Startup And Health

Steps:

1. Start the backend and frontend.
2. Open `http://127.0.0.1:3020`.
3. Open `http://127.0.0.1:8020/health`.

Expected results:

- frontend loads without console-breaking errors
- health endpoint returns JSON
- health response shows the selected LLM provider, graph backend, simulation backend, report backend, queue counts, and workflow runner mode

### 2. New Analysis UI

Steps:

1. Open the `New Analysis` page.
2. Create the sample project.
3. Paste the source note from the scenario above.
4. Confirm the project appears in the history panel.

Expected results:

- project is created successfully
- history panel updates immediately
- the source note appears in the uploaded source list
- source count increments
- no untranslated text or layout breakage appears

### 3. Graph Workflow

Steps:

1. Open `Graph`.
2. Confirm the split layout shows graph on the left and the workbench on the right.
3. Queue a graph job using the sample graph objective.
4. Wait for the graph job to move from `queued` to `running` to `completed`.
5. Select the completed graph artifact.
6. Switch between `Graph`, `Split`, and `Workbench` view modes.

Expected results:

- graph job appears in the queue immediately
- status changes are visible without a manual refresh
- completed graph shows schema summary and findings
- left graph surface renders in `Graph` and `Split` modes
- right-side workbench remains usable in `Split` and `Workbench` modes
- no clipped text, overlapping cards, or broken controls appear

### 4. Setup Workflow

Steps:

1. Open `Setup`.
2. Confirm the selected graph artifact is visible in the left graph surface.
3. Prepare the simulation from the built graph.
4. Wait for setup to complete.
5. Inspect the prepared personas and simulation settings.
6. Switch all three workbench view modes.

Expected results:

- setup starts immediately
- setup completes successfully
- the setup detail shows personas, hot topics, and runtime settings
- the left graph surface stays in sync with the selected project context
- view mode switching works cleanly

### 5. Simulate Workflow

Steps:

1. Open `Simulate`.
2. Start the prepared simulation with a preview cap of `10` rounds.
3. Confirm event timeline items render while the run is active.
4. Confirm the graph surface is still visible in split mode.
5. Switch all three workbench view modes.

Expected results:

- selected simulation details render correctly
- event stream is non-empty
- event count matches the visible run context
- no stale or missing selection state appears after switching modes

### 6. Report Workflow

Steps:

1. Open `Report`.
2. Queue a report using the sample report focus.
3. Wait for the report to complete.
4. Confirm the markdown preview renders.
5. Ask the sample report chat question in the report chat.
6. Switch all three workbench view modes.

Expected results:

- report queues and completes successfully
- report preview contains a title, executive summary, and recommendations
- report chat returns an answer grounded in the simulation and report
- the chat button is only usable when the report is ready
- no layout breakage appears while switching view modes

### 7. Interaction Workflow

Steps:

1. Open `Interact`.
2. Ask one question in report chat.
3. Select an individual persona and ask a direct question.
4. Run a small multi-agent survey.

Expected results:

- report chat returns a grounded answer
- the persona selector is populated
- the individual persona interview returns an answer
- survey responses return for the selected personas

## Required UI Checks

The QA engineer should explicitly check these on top of the workflow steps:

- side navigation correctly highlights the current stage
- top bar shows the correct step number and stage title
- status pills visually distinguish `draft`, `queued`, `running`, `completed`, and `failed`
- forms are usable at desktop width and at a narrower laptop-width viewport
- buttons disable while background actions are in flight
- empty states are readable and consistent
- no Chinese or Malay text appears anywhere in the tested AudienceMind flow

## Required API Checks

Validate the following responses with browser devtools or `curl`:

- `GET /health`
- `GET /projects`
- `GET /projects/{project_id}`
- `GET /projects/{project_id}/sources`
- `GET /projects/{project_id}/graph-jobs`
- `GET /graph-jobs/{job_id}`
- `GET /simulations/{simulation_id}`
- `GET /simulations/{simulation_id}/events`
- `GET /reports/{report_id}`

Expected API behavior:

- object IDs remain stable through the workflow
- workflow records expose status and timestamps
- completed simulation returns non-empty events
- completed report returns markdown

## Negative And Guardrail Checks

Run these after the main happy path:

1. In `Graph`, try to queue a graph job for a project with no sources.
Expected: the UI blocks the action with a clear error.

2. In `Report` or `Interact`, try to send a question before selecting a completed report.
Expected: the send button stays disabled.

3. Refresh the page on `Graph`, `Simulate`, and `Report`.
Expected: the selected or latest relevant data reloads without breaking the stage.

4. If possible, restart the backend during a queued job.
Expected: the app recovers and workflow state remains visible after restart.

## Optional Split-Deployment Check

Run this only if there is time:

1. Start the API with `PERSONAGRAPH_EMBED_WORKFLOW_RUNNER=false`.
2. Start `uv run personagraph-worker` in a separate terminal; the worker command name is retained for compatibility.
3. Repeat the main happy path quickly.

Expected results:

- `/health` reports external runner mode
- queued work still completes
- UI behavior is unchanged from the embedded-runner path

## Evidence To Capture

Capture these artifacts:

- screenshot of each main stage in `Split` mode
- screenshot of one completed graph artifact
- screenshot of one completed run timeline
- screenshot of one completed report preview
- raw `/health` response
- list of defects with exact steps, actual result, expected result, and browser/environment details

## Exit Criteria

Testing is complete when all of the following are true:

- the main happy path passes end to end
- UI checks pass on all five stages
- required API checks pass
- guardrail checks behave as expected
- any failures are recorded with reproduction steps and severity

## Suggested Time Budget

- setup: 10 minutes
- happy path: 15 to 20 minutes
- UI and guardrail checks: 15 minutes
- optional split-worker pass: 10 minutes

Total expected time: about 40 to 55 minutes.
