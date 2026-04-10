# Compliance Legacy Token Cleanup Design

## Goal

Remove unused legacy banned-token rules from the compliance scanner so the scanner reflects the current AudienceMind policy instead of carrying historical token checks that are no longer used anywhere in the repository.

## Scope

This cleanup covers:

- `scripts/compliance_scan.py`
- `backend/tests/test_compliance_scan.py`

This cleanup does not cover:

- branding or copy updates outside the compliance scanner and its tests
- ignored-path behavior other than preserving the current `docs/superpowers` and `backend/data` exclusions
- non-ASCII content or filename checks
- any new config surface for scanner rules

## Current Problem

The compliance scanner still carries legacy banned-token checks for names that no longer appear in the repository and are no longer part of the active policy boundary. That creates unnecessary policy complexity and forces tests to assert behavior that no longer serves the current clean-room app.

## Target Policy

After this change, the scanner should continue enforcing the parts of the policy that still matter:

- scan the default implementation paths
- reject non-ASCII filenames
- reject non-ASCII text content
- honor ignored paths such as `backend/data` and `docs/superpowers`

After this change, the scanner should stop carrying stale banned-token rules for unused legacy names.

## Approach Options

### Option 1: Remove all unused legacy banned-token rules

Delete the banned-token list entirely if none of the entries are still required, then simplify the tests to validate the scanner's current structural behavior.

Pros:

- simplest policy
- least maintenance
- directly matches the current repo state

Cons:

- removes the ability to catch those exact historical strings if they reappear later

### Option 2: Keep a reduced banned-token list

Retain only the subset of banned tokens that are still considered policy-relevant, and delete the rest.

Pros:

- preserves some historical guardrails

Cons:

- requires a clear reason for each retained token
- more policy surface than the repo currently appears to need

### Option 3: Move banned tokens into configurable data

Keep the legacy concept but move the tokens into a separate config layer.

Pros:

- flexible for future policy changes

Cons:

- unnecessary complexity for a small cleanup
- adds new surface area without current need

## Recommended Approach

Use Option 1.

If the repository no longer uses or documents any of these legacy tokens, the scanner should not keep comparing against them. The current meaningful policy is structural and language-based, not historical-token-based.

## Implementation Notes

- Update the tests first so they describe the new policy.
- Verify the updated tests fail before scanner changes.
- Make the minimal scanner change needed to remove the stale banned-token logic.
- Keep ignored-path behavior unchanged.
- Keep the scanner output and CLI surface simple; do not add new configuration.

## Testing

Targeted test expectations:

- `AudienceMind` is allowed in a normal markdown file
- files under `docs/superpowers/` are ignored
- no test asserts that a removed legacy token must still be banned

Verification commands:

```bash
cd backend && uv run pytest tests/test_compliance_scan.py -v
python3 scripts/compliance_scan.py
```

## Risks

### Risk: Removing too much policy

If some banned token is still intentionally part of the clean-room policy, deleting it would weaken enforcement.

Mitigation:

- confirm the tokens are no longer used anywhere in the repo before removal
- keep the change scoped to the scanner and its focused tests

### Risk: Breaking scanner behavior unrelated to tokens

The cleanup could accidentally affect ignored paths or text-file scanning.

Mitigation:

- preserve the existing ignore-path logic
- keep the implementation change minimal
- rely on focused targeted tests
