# AGENTS.md

This repository contains a Streamlit app for GBIF-based field-survey planning.

## Source of truth

GitHub is the only source of truth for this project.

Before editing, every AI coding agent must read the latest relevant files from the current GitHub branch, preferably `main` unless the user explicitly specifies another branch.

Do not use local files, old workspace copies, previous conversation memory, old Codex/Claude thread state, or previously generated snippets as the baseline for edits unless they are first compared against the latest GitHub version.

If local code differs from GitHub, treat GitHub as authoritative.

If there is any uncertainty about whether a feature already exists or has changed, inspect the latest GitHub file first and preserve the current behavior.

## Core rule

Do not remove existing features unless the user explicitly asks for removal.

Existing features that must be preserved:

- GBIF paginated occurrence download
- Flexible CSV upload with latitude/longitude auto-detection
- Map-click occurrence exclusion
- Rectangle/batch occurrence exclusion when implemented
- Red QC-only excluded occurrence points
- Ensemble SDM
- VIF stepwise filtering with a user-defined threshold
- Spatial partition diagnostics for AUC
- Raster-style SDM prediction map
- SDM-high exploration candidate ranges
- Selected survey site list
- Genus-level occurrence richness map when implemented
- SSDM mode when implemented
- HTML/CSV downloads

## Anti-rollback rules

AI agents must not roll back recent work.

Before making changes, check the latest `CHANGELOG_AI.md` and the current target file on GitHub.

Preserve any feature described in `CHANGELOG_AI.md` unless the user explicitly asks to remove or hide it.

Do not reintroduce UI elements or older workflows that were intentionally removed or hidden, such as:

- preliminary straight-line day splitting as a main workflow
- required `Survey days` blocks as a main workflow
- duplicated `Priority survey ranges` table at the bottom, if it has been removed
- daily sampling route layers, if they have been removed
- redundant occurrence buffer plus survey range layers, if they have been simplified

If a requested change conflicts with an existing feature, make the smallest safe change without deleting unrelated functionality.

## Collaboration rules for AI coding agents

1. Read this file before editing.
2. Read the latest relevant files from GitHub before editing.
3. Prefer small diffs over full-file rewrites.
4. Do not push directly to `main` unless the user explicitly asks.
5. Use feature branches and pull requests when possible.
6. After every code change, update `CHANGELOG_AI.md`.
7. Run the following before finishing:

```bash
python -m py_compile gbif_fieldmap_builder_app.py
```

8. If routing or survey-site-list code is changed, confirm the app still works both before and after SDM is built.
9. If occurrence-exclusion code is changed, confirm that red QC points remain visible but are not used for SDM, prediction extent, candidate generation, or survey site lists.
10. If SDM code is changed, confirm that VIF, spatial partition options, prediction maps, and SDM-high exploration candidates still exist.
11. If genus diversity or SSDM code is changed, confirm that the single-species workflow still works.
12. If UI labels are changed, keep the distinction clear:
    - Included points = used for analysis
    - Excluded QC points = visible but not used for analysis

## Large-file editing rule

Avoid rewriting the entire `gbif_fieldmap_builder_app.py` file unless absolutely necessary.

For bug fixes, edit only the smallest relevant section.

For new features, prefer adding helper functions and connecting them with minimal changes.

Before replacing any function, compare the latest GitHub version and ensure no recent behavior is lost.

## Route-planning / survey-site-list note

The app should not pretend to solve real road routing.

Straight-line routing does not account for roads, ferries, mountains, cliffs, restricted access, or island barriers. Field routes should be verified in Google Maps before fieldwork.

The preferred workflow is:

- select candidate survey sites;
- show one unified selected survey site list;
- open selected sites in Google Maps or export CSV/HTML;
- keep any day-splitting or route optimization as optional or hidden unless explicitly requested.

## Genus / SSDM note

Genus-level richness and SSDM workflows can be expensive.

Do not run full SSDM automatically. Use lightweight defaults, record caps, species caps, progress reporting, and shared variable filtering.

Occurrence richness maps and SSDM predicted richness maps must be clearly distinguished:

- Occurrence richness = observed species richness from GBIF records.
- SSDM richness = predicted richness from stacked species-level SDMs.

## Changelog requirement

Every AI edit must add an entry to `CHANGELOG_AI.md` with:

- Date
- Agent
- Changed files
- Summary
- Features preserved
- Known risks / TODO

The changelog should mention when a feature is intentionally hidden or removed, so later agents do not accidentally restore it.
