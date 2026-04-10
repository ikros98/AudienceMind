# AudienceMind Compliance Notes

## What Must Not Enter The New App
- Retired product names and retired org or community references that do not belong to AudienceMind.
- Non-English copy, comments, filenames, or assets in the new app paths.
- Reused screenshots or branded imagery from the legacy project.

## Scanner Coverage
Use the compliance scanner in `scripts/compliance_scan.py` to check:
- banned legacy brand tokens
- non-ASCII characters inside text files
- non-ASCII filenames

The scanner targets the new app paths by default:
- `frontend`
- `backend`
- `docs`
- `scripts`

The scanner intentionally ignores generated runtime storage under `backend/data/`.
Use `scripts/sanitize_runtime_artifacts.py` when you want to clean stored graph, simulation, report, and glass compatibility artifacts in place.

## Expected Workflow
- Run the scanner after adding or renaming files.
- Run the scanner before committing new AudienceMind implementation work.
- Treat any scanner finding as a blocker until the content is removed or explicitly approved.
- Keep all new implementation work inside the active root app unless an explicit support file is needed.
- Preserve a clean-room boundary: do not copy legacy assets, prompts, comments, or user-facing strings into the new app.

## Example Command
```bash
python3 scripts/compliance_scan.py
python3 scripts/sanitize_runtime_artifacts.py
```
