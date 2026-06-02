# AGENTS.md

This repository contains a Streamlit app for GBIF-based field-survey planning.

## Core rule

Do not remove existing features unless the user explicitly asks for removal.

Existing features that must be preserved:

- GBIF paginated occurrence download
- Flexible CSV upload with latitude/longitude auto-detection
- Map-click occurrence exclusion
- Red QC-only excluded occurrence points
- Ensemble SDM
- VIF stepwise filtering with a user-defined threshold
- Spatial partition diagnostics for AUC
- Raster-style SDM prediction map
- SDM-high exploration candidate ranges
- Day-by-day route planner
- HTML/CSV downloads

## Collaboration rules for AI coding agents

1. Read this file before editing.
2. Prefer small diffs over full-file rewrites.
3. Do not push directly to `main` unless the user explicitly asks.
4. Use feature branches and pull requests when possible.
5. After every code change, update `CHANGELOG_AI.md`.
6. Run the following before finishing:

```bash
python -m py_compile gbif_fieldmap_builder_app.py
```

7. If routing code is changed, confirm the app still works both before and after SDM is built.
8. If occurrence-exclusion code is changed, confirm that red QC points remain visible but are not used for SDM, prediction extent, candidate generation, or route planning.
9. If SDM code is changed, confirm that VIF, spatial partition options, prediction maps, and SDM-high exploration candidates still exist.
10. If UI labels are changed, keep the distinction clear:
    - Blue points = included and used for analysis
    - Red points = excluded QC-only and not used for analysis

## Route-planning note

The current route planner may include preliminary straight-line ordering. Straight-line routing does not account for roads, ferries, mountains, cliffs, restricted access, or island barriers. Field routes should be verified in Google Maps before fieldwork.

Future routing improvements should preserve the current preliminary route planner while adding explicit Google Maps verification and accessible-site selection.

## Changelog requirement

Every AI edit must add an entry to `CHANGELOG_AI.md` with:

- Date
- Agent
- Changed files
- Summary
- Features preserved
- Known risks / TODO
