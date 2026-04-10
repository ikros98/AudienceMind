# Improvement Plan

## Purpose
This document lists the improvements that should be delivered as part of the AudienceMind baseline itself. These items reduce legal, compliance, and maintenance risk immediately.

## Improvements To Deliver In The Current Platform
- Build and keep the product in the clean repository root app rather than reintroducing archived code paths.
- Keep branding, screenshots, logos, community references, and product copy aligned with English-only AudienceMind language.
- Use a modular frontend with a shared workspace shell instead of route-by-route duplicated layouts and oversized components.
- Use typed frontend and backend contracts so project, graph, simulation, and report workflows are explicit and testable.
- Replace fragile file-only and in-memory workflow state with durable application state and recoverable job execution.
- Add provider adapter boundaries for LLM, graph, and simulation integrations so infrastructure choices can change without rewriting the product core.
- Enforce English-only code comments, docs, logs, examples, filenames, and UI strings for the new app.
- Add automated compliance checks for banned legacy names and non-ASCII content in the new app paths.
- Remove tracked secrets from the new implementation and rely on example env files plus runtime configuration.
- Add baseline automated tests and build validation so the platform has an enforceable quality floor.

## Current Issues This Addresses
- The repo can still mix branding, product behavior, and documentation concerns too tightly.
- Large frontend and backend files make safe change isolation difficult.
- Workflow orchestration needs to stay recoverable after restarts.
- Existing tests need to keep improving to maintain high-confidence changes.
- Compliance concerns are spread across code, assets, docs, and deployment naming.
