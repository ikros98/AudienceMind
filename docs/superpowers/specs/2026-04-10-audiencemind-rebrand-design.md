# AudienceMind Rebrand Design

## Goal

Rebrand the active product from `PersonaGraph` to `AudienceMind` across all public-facing documentation and user-visible UI surfaces, while preserving existing internal compatibility identifiers and runtime behavior.

## Scope

This pass covers:

- Root product documentation such as `README.md`
- Product docs under `docs/`
- Frontend user-visible copy, navigation, metadata, and landing-page branding
- Operator-facing docs that describe the active product to users or developers
- User-visible backend labels where the product name is returned directly to clients

This pass does not cover:

- Internal environment variable prefixes such as `PERSONAGRAPH_*`
- Existing CLI commands such as `uv run personagraph-worker`
- Package names, lockfile package names, Docker volume names, database names, or service names
- Internal code symbols, module names, storage keys, workflow thread names, or filenames that are not public branding
- Generated runtime artifacts, caches, or disposable log output

## Product Naming Rule

`AudienceMind` becomes the only product name shown in public-facing docs and UI.

`PersonaGraph` may still appear only where compatibility details must remain accurate, such as:

- existing commands
- existing environment variables
- current internal service identifiers
- implementation notes that explain legacy-compatible runtime behavior

When legacy identifiers appear in documentation, they must be framed as compatibility details rather than product branding.

## Public Surface Changes

### Documentation

Update public docs to describe the product as `AudienceMind`, including:

- product title lines
- architecture and workflow descriptions
- use-case positioning
- compliance guidance
- QA instructions
- backend/frontend READMEs where they describe the product itself

Documentation must continue to show current working commands and env vars even if those identifiers still use `PersonaGraph`.

### Frontend UI

Update visible branding in:

- landing-page hero and supporting marketing copy
- navigation and footer brand labels
- workflow shell and demo page headers
- FAQ entries
- browser title and description metadata

No internal state keys or package names should be renamed in this pass.

### User-Visible Backend Labels

If the backend exposes a product label directly to users, such as a default API display name surfaced in health or status responses, update that label to `AudienceMind` while keeping env var prefixes and internal compatibility wiring unchanged.

## Non-Goals

- No runtime migration
- No compatibility-breaking rename of internal identifiers
- No reorganization of deployment assets
- No cleanup of generated artifact history
- No unrelated copywriting or feature redesign

## Risks And Controls

### Risk: Breaking existing local or deployed setups

Control:

- leave env vars, commands, package names, service names, and Docker/database identifiers unchanged
- keep docs accurate about those legacy-compatible identifiers

### Risk: Incomplete public rebrand

Control:

- run targeted searches for `PersonaGraph` after edits
- review remaining matches and keep only compatibility/internal references

### Risk: Accidental edits to generated or disposable artifacts

Control:

- limit edits to tracked source/docs and obvious user-facing strings
- avoid runtime data, caches, compiled output, and logs

## Verification

Run:

```bash
rg -n --hidden --glob '!**/node_modules/**' --glob '!**/.venv/**' --glob '!**/dist/**' --glob '!**/build/**' 'PersonaGraph' README.md docs frontend backend
cd frontend && npm run build
python3 scripts/compliance_scan.py
```

Expected outcome:

- public docs and UI strings use `AudienceMind`
- remaining `PersonaGraph` matches are limited to compatibility/internal identifiers or intentionally preserved implementation details
- frontend still builds successfully
- compliance scan still passes
