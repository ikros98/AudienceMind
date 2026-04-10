# AudienceMind Platform Plan

## Summary

- Keep the English-only `AudienceMind` application at the repository root as the active product.
- Preserve an analyst-focused experience with a typed frontend, typed backend, durable local persistence, and explicit adapter boundaries.
- Keep infrastructure-specific integrations behind replaceable interfaces so providers can change without rewriting the product core.
- Maintain a clean and well-documented structure that can serve as the baseline for future development.

## Scope

- Active app root: repository root
- Frontend: `frontend/`
- Backend: `backend/`
- Docs and compliance tooling: `docs/`, `scripts/`
- Planning docs: `improvement.md`, `future-improvement.md`

## Frontend Direction

- Use React + TypeScript + Vite.
- Create a distinct AudienceMind visual language:
  - analyst workstation feel
  - neutral palette
  - no fish imagery
  - no black/orange console aesthetic
- Keep a single shared workflow layout.
- Primary information architecture:
  - `Graph`
  - `Setup`
  - `Simulate`
  - `Report`
  - `Interact`
- Keep all UI copy English-only.
- Keep the UI English-only and avoid pulling in unrelated branded assets or multilingual UI behavior.

## Backend Direction

- Use FastAPI with typed schemas.
- Prefer a local SQLite-backed development setup with an env-configurable database URL.
- Organize APIs by domain:
  - `health`
  - `projects`
  - `graph jobs`
  - `simulations`
  - `reports`
- Add adapter interfaces for:
  - LLM providers
  - graph backends
  - simulation engines
  - reporting/evidence services
- Keep code, API docs, logs, and comments English-only.

## Compliance And Content Rules

- No retired third-party product, org, or community branding in the active app.
- No non-English content in the app code, docs, assets, examples, or filenames unless explicitly approved.
- Keep the compliance scanner covering the active app paths.
- Do not reintroduce deleted or archived code into the active root app.

## Integration Notes

- The remote Ollama host is reachable and can be used for development validation through SSH port forwarding:

```bash
ssh -N -L 11434:127.0.0.1:11434 -i ~/.ssh/ndeamonrd.pem paperspace@184.105.157.30
```

- Validate local LLM integration against that forwarded endpoint after the new backend adapters are in place.

## Deliverables

- `frontend/`
- `backend/`
- `improvement.md`
- `future-improvement.md`
- Compliance tooling and platform documentation
- Basic build/test verification for the new app
