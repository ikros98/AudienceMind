# Repository Instructions

This repository now uses the clean-room PersonaGraph application at the repository root.

## Scope And Working Path

- Treat the repository root as the active product path.
- Main app directories:
  - `backend/`
  - `frontend/`
  - `docs/`
  - `scripts/`
  - `deploy/`
- `seed_documents/` contains reusable local fixtures.
- Do not reintroduce a nested app root unless the user explicitly asks for it.

## Product Boundary

- Keep PersonaGraph English-only across code, docs, filenames, UI strings, and examples.
- Do not add retired product names, retired org/community references, or legacy screenshots/assets into the active product path except in narrowly scoped compliance or migration documentation.
- Keep the clean-room implementation structurally separate from any temporary migration artifacts.

## Architecture Expectations

- Frontend: React + Vite split-stage workflow for `Graph -> Setup -> Simulate -> Report -> Interact`.
- Backend: FastAPI + SQLModel with typed schemas and queue-driven workflow execution.
- Keep graph, simulation, and reporting behavior behind adapter boundaries in `backend/app/services/adapters.py`.
- Keep pure generation helpers in `backend/app/services/generation.py` and orchestration in `backend/app/services/workflows.py`.
- Keep persistence and read-model helpers in `backend/app/services/runtime.py`.

## Documentation And Compliance

- Update `README.md`, `docs/rewrite-overview.md`, or `docs/compliance.md` when workflows, commands, or architecture materially change.
- Run `python3 scripts/compliance_scan.py` after adding docs, renaming files, or changing user-facing copy.
- Keep environment examples current when settings change.

## Verification

- Backend:
  - `cd backend && uv run pytest`
- Frontend:
  - `cd frontend && npm run build`
- Compliance:
  - `python3 scripts/compliance_scan.py`
- Deployment config:
  - `docker compose config`

## Documentation Sources

- For Codex workflow questions, use local repo context first.
- For OpenAI or Codex product behavior that needs verification, use official OpenAI documentation only.
- Official AGENTS guidance reference: `https://developers.openai.com/codex/guides/agents-md`

## Git And Safety

- Do not revert unrelated user changes.
- Do not reintroduce deleted legacy code into the active root app.
- Keep the clean-room boundary explicit in docs and code organization.
