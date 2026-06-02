# AI Change Log

This file records changes made by AI coding agents such as Codex, Claude, ChatGPT, or other assistants.

Each agent should update this file after editing code.

## 2026-06-02 - Claude (Anthropic) — export redesign

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:
- Renamed route section to "Export survey sites for Google Maps".
- Added two export modes: 1. Auto (top-ranked sites with top_n, min_priority_score, min_sdm_suitability, include_occurrence_supported, include_sdm_high filters); 2. Manual (map-click toggle, preserved).
- Added make_export_csv() producing Google Maps / My Maps import-ready CSV with columns: name, latitude, longitude, priority_rank, priority_score, sdm_suitability, occurrence_support_score, n_occurrences, candidate_type, candidate_method, selection_reason, access_note, google_maps_url.
- Added make_export_kml() for KML download (Google Earth / My Maps compatible).
- Download buttons: google_maps_auto_sites.csv/.kml and google_maps_selected_sites.csv/.kml.
- "Open selected sites in Google Maps" link button.
- Warning text: export does not guarantee road/ferry/mountain/cliff/restricted-access feasibility.
- Moved travel mode, start/end location, day-splitting controls into collapsed "Advanced" expander (day-by-day planner fully preserved per AGENTS.md).
- Added _make_gmaps_url_with_end helper retained from previous iteration.
- EXPORT_CSV_COLS constant added at module level.

Features preserved:
- GBIF pagination
- CSV upload
- Map-click occurrence exclusion
- Red QC excluded points
- Ensemble SDM, VIF stepwise filtering, spatial partition diagnostics
- Raster-style SDM predict map
- SDM-high exploration candidates
- Day-by-day route planner (in Advanced expander)
- HTML/CSV downloads

Known risks / TODO:
- Google Maps URL waypoint cap is 8; routes with >9 sites silently drop excess waypoints.
- KML description is plain text; could be improved with HTML CDATA tables.

## 2026-06-02 - Claude (Anthropic)

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:
- Renamed "Survey route planner" → "Google Maps-based survey site planning".
- Added two planning modes: A. Auto (top-ranked candidates with priority/suitability thresholds) and B. Manual (existing map-click selection, fully preserved).
- Auto mode: top_n, min_priority_score, min_sdm_suitability filters; shows selected sites table and dropped sites; generates Google Maps verification route URL.
- Added optional end_location field and helper function `_make_gmaps_url_with_end`.
- Added warning text: Google Maps verification required; no road/ferry/mountain/cliff guarantee.
- Added "🗺️ Open verification route in Google Maps" button with disclaimer caption.
- Moved survey-days / max-sites-per-day / max-straight-line-distance into a collapsed "Advanced: preliminary day splitting" expander (feature preserved per AGENTS.md).
- Added google_maps_checked, accessible, access_mode, access_note columns to make_validation_template and to ordered DataFrame output.
- Route returns survey_day=1 when day-splitting is not used, so the map route layer still renders.

Features preserved:
- GBIF pagination
- CSV upload
- Map-click occurrence exclusion
- Red QC excluded points
- Ensemble SDM, VIF stepwise filtering, spatial partition diagnostics
- Raster-style SDM predict map
- SDM-high exploration candidates
- Day-by-day route planner (in Advanced expander)
- HTML/CSV downloads

Known risks / TODO:
- Google Maps URL waypoint cap is 8; routes with >9 sites silently drop lower-priority waypoints.
- end_location with start_location shifts waypoint list by one; verify edge cases with 1-2 sites.

## Template

```md
## YYYY-MM-DD - Agent name

Changed files:
- path/to/file.py

Summary:
- Briefly describe what changed.

Features preserved:
- GBIF pagination
- CSV upload
- map-click occurrence exclusion
- red QC excluded points
- SDM
- VIF stepwise filtering
- spatial partition diagnostics
- predict map
- SDM-high exploration candidates
- route planner
- downloads

Known risks / TODO:
- List anything that still needs checking.
```

## 2026-06-02 - ChatGPT

Changed files:
- AGENTS.md
- CHANGELOG_AI.md

Summary:
- Added AI collaboration rules and a shared changelog format.
- Defined core features that future AI edits must preserve.
- Added routing caution that straight-line route planning does not account for roads, ferries, mountains, cliffs, restricted access, or island barriers.
- Added requirement that every AI agent update this changelog after code changes.

Features preserved:
- No application code changed.

Known risks / TODO:
- Add GitHub Actions syntax check workflow.
- Improve route planning so Google Maps verification and accessible-site selection are explicit.
