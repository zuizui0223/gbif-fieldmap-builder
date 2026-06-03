# AI Change Log

This file records changes made by AI coding agents such as Codex, Claude, ChatGPT, or other assistants.

Each agent should update this file after editing code.

## 2026-06-03 - Codex - Issue #2 first step: genus occurrence richness mode

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:
- Added top-level Analysis mode selector with Single species survey planning and Genus diversity / SSDM.
- Added first-stage Genus diversity / SSDM workflow: genus name input, optional country/year filters, paginated GBIF genus occurrence download, grouping by species, species summary table, occurrence-based richness grid map, richness hotspot candidates, and CSV/HTML downloads.
- Full SSDM stacking is intentionally not implemented yet; this step stops at stable occurrence-based richness mapping.

Features preserved:
- Existing single-species GBIF pagination, CSV upload, red QC occurrence exclusion, SDM, VIF, spatial partition diagnostics, predict map, SDM-high exploration candidates, survey site list, route/export helpers, and downloads remain in Single species survey planning mode.

Known risks / TODO:
- Genus richness is occurrence-based and may reflect GBIF sampling bias.
- Full per-species SDM/SSDM stacking remains TODO after occurrence richness map behavior is validated.

## 2026-06-02 - Claude (Anthropic) — Issue #1 follow-up: simplify map layers and remove Priority table

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:
- Removed "Priority survey ranges" table from main UI bottom. Candidate site info still visible on the map and in the Survey site list section.
- Removed "Daily sampling route layers" checkbox from sidebar and daily-routes drawing from build_map(). App does not crash when route_plan is empty.
- Removed "Occurrence buffers" layer checkbox and drawing block from build_map().
- Renamed "Survey ranges" layer to "Candidate circles" (key: candidate_circles). One unified circle layer around candidate sites using survey_range_m as radius; color green for SDM-high, red for occurrence-supported, same as before.
- Removed "Occurrence display buffer radius" sidebar number_input (no longer needed); build_map() receives 0.0 for that param.
- Sidebar Layers now shows only: SDM predict map, Occurrences, Candidate circles.

Features preserved:
- SDM, VIF, spatial partition, predict map features all unchanged.
- Candidate site generation, priority scoring, occurrence exclusion all unchanged.
- build_map() signature unchanged (occurrence_buffer_m param kept, passed as 0.0).

## 2026-06-02 - Claude (Anthropic) — Issue #1 follow-up: hide day-split, unified selected list only

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:
- Removed "Optional: split selected sites by survey day" expander entirely from the UI. Day 1 / Day 2 / survey_day_lists UI is no longer shown.
- Main output is now a single unified "Selected survey sites" list only.
- Return value always uses survey_day=1 for selected sites so the map route layer still renders.
- Clear selected sites uses sl_reset_token (from previous commit) to fully clear the multiselect widget.
- Auto, Manual map click, and rectangle selection all unchanged.
- survey_day_lists session state key and helper functions (_make_day_gmaps_urls, make_survey_day_csv, make_survey_day_html) kept in code for future re-use but not exposed in UI.

Features preserved:
- All SDM/VIF/spatial partition/predict map features unchanged.
- All selection logic unchanged.

## 2026-06-02 - Claude (Anthropic) — Issue #1 follow-up: fix clear-selected and simplify day split

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:
- Fix 1: "Clear selected sites" now fully clears the Selected site IDs multiselect widget. Added sl_reset_token to session state; each Clear action increments the token, which changes the multiselect widget key (key=f"sl_manual_ids_{token}"), forcing Streamlit to create a fresh widget instance. Token also incremented in clear_loaded_data.
- Fix 2: Replaced the "Optional: split selected sites by survey day" expander contents with a st.data_editor approach. Selected sites are shown in an editable table with a survey_day SelectboxColumn (options: Day 1, Day 2, ..., Unassigned). User edits the survey_day column directly, then clicks "Apply day assignments" to write back to survey_day_lists. Removed all staging "Copy to Day X" buttons. Add day / Remove last day controls remain. Per-day Google Maps links and CSV/HTML downloads still shown after assignment.

Features preserved:
- All selection logic (auto, manual map click, rectangle Draw) unchanged.
- All SDM/VIF/spatial partition/predict map features unchanged.
- survey_day_lists session state and day-list downloads preserved.

## 2026-06-02 - Claude (Anthropic) — Issue #1 follow-up: Survey site list UI simplification

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:
- Renamed main heading from "Survey day site lists" to "Survey site list".
- Primary output is now "Selected survey sites" — a single unified list from sl_selected_site_ids.
- Auto / Manual / rectangle selection logic is unchanged.
- "Selected survey sites" table shown immediately after selection with per-site 📍 Google Maps links, "Open all in Google Maps", CSV download, HTML download, and "Clear selected sites" button.
- Day management (Add/Remove day, Copy to Day X, per-day tables and Google Maps links, day-list downloads) moved into a collapsed expander "Optional: split selected sites by survey day" — not shown unless the user opens it.
- Day assignment now uses "Copy to Day X" (copies from selected list; selected list is not cleared).
- Empty Day 1 / Day 2 lists are no longer visible as the main output.
- Return value: prefers day-list rows when any day has sites; otherwise returns selected sites with survey_day=1 so the map route layer still renders.
- Renamed "Clear staging" / "Staging selection" labels to "Clear selected sites" / "Selected site IDs".

Features preserved:
- All selection logic (auto, manual map click, rectangle Draw) unchanged.
- Day list state (survey_day_lists) preserved and still functional inside the expander.
- All SDM/VIF/spatial partition/predict map features unchanged.

## 2026-06-02 - Claude (Anthropic) — Fix StreamlitAPIException in coordinate_exclusion_panel

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:
- Removed two direct assignments to st.session_state.restore_excluded_row_ids that caused StreamlitAPIException: the pre-widget guard (checking stale IDs) and the post-recover-button reset. Both were unnecessary because the multiselect widget's options= already restricts valid choices, and st.rerun() after recovery naturally leaves the selection empty on the next render.
- Click exclusion behavior and rectangle exclusion behavior unchanged.

Features preserved:
- All existing features unchanged.

## 2026-06-02 - Claude (Anthropic) — Issue #1 follow-up: simplify QC rectangle workflow

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:
- Simplified QC rectangle workflow: drawing a rectangle now immediately excludes all occurrence points inside (no staging, no Exclude/Restore/Clear buttons).
- Removed "Exclude rectangle-selected", "Restore rectangle-selected", and "Clear rectangle selection" buttons from coordinate_exclusion_panel.
- Existing click-to-exclude/restore behavior is unchanged.
- "Clear excluded coordinates" button remains as the reset/undo fallback.
- Candidate site rectangle selection already added to staging immediately — no change needed.
- Excluded points remain red QC points and are not used for SDM, prediction extent, candidates, or survey day lists.

Features preserved:
- All existing SDM/VIF/spatial partition/predict map features.
- Existing point-click exclusion/restore behavior.
- Survey day site lists, HTML/CSV downloads.

## 2026-06-02 - Claude (Anthropic) — ROUTE_QC_PATCH_NOTES: rectangle selection fixes

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:
- Removed "Blue = included, red = excluded..." caption from coordinate_exclusion_panel (per patch note §1). Existing click-based exclusion/restore behavior unchanged.
- Added extract_drawn_features() helper: normalises all_drawings / last_active_drawing from streamlit-folium regardless of dict or list format.
- Added ids_inside_drawn_rectangles() helper: returns IDs inside any drawn Polygon/Rectangle feature.
- coordinate_exclusion_panel: added Draw plugin (add_draw=True), added "all_drawings" and "last_active_drawing" to returned_objects, added rectangle batch QC actions — Exclude / Restore / Clear rectangle-selected occurrence points. Red QC points remain visible and excluded from SDM/extent/candidates/routes.
- make_exclusion_review_map: restored add_draw parameter and fg_ex.add_to(fmap) so excluded red points are visible on the map.
- route_planner_panel manual mode: replaced ad-hoc dict-only feature parsing with extract_drawn_features() + ids_inside_drawn_rectangles(); added "last_active_drawing" to returned_objects so rectangle selection works even when all_drawings returns a list.

Features preserved:
- GBIF pagination, CSV upload, existing map-click exclusion/restore, red QC excluded points
- Ensemble SDM, VIF, spatial partition, predict map, SDM-high exploration candidates
- Survey day site lists, HTML/CSV downloads

Known risks / TODO:
- streamlit-folium < 0.13 may not return all_drawings; last_active_drawing fallback mitigates this.

## 2026-06-02 - Claude (Anthropic) — Issue #1: survey day site lists + rectangle selection

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:
- Implements Issue #1: Replace route splitting with manual day lists and box selection.
- Renamed section to "Survey day site lists".
- Added manual day-based site grouping: Day 1 / Day 2 / ... expanders with per-day site tables, remove-site controls, and Google Maps route buttons per day (split into Part 1 / Part 2 for >10 sites, i.e. >8 waypoints).
- Added staging area workflow: select sites → assign to survey day.
- Auto mode: filter by top_n, min_priority, min_suitability, site type → confirm to staging.
- Manual mode: map click toggle + rectangle Draw selection (folium.plugins.Draw) → adds sites inside drawn rectangle to staging.
- Added rectangle batch QC selection in coordinate_exclusion_panel: draw rectangle → Exclude / Restore / Clear rectangle points.
- Fixed bug: fg_ex (excluded red points) was not added to make_exclusion_review_map; now correctly added so red QC points are visible.
- Added Draw plugin to make_exclusion_review_map (add_draw=True) and make_route_selection_map (add_draw=True).
- New helpers: _make_day_gmaps_urls, make_survey_day_csv, make_survey_day_html, SURVEY_DAY_CSV_COLS.
- CSV columns: survey_day, order_within_day, site_id, candidate_type, priority_rank, priority_score, sdm_suitability, occurrence_support_score, n_occurrences, latitude, longitude, google_maps_url, access_note.
- HTML download: self-contained per-day tables with 📍 Google Maps links.
- New session state keys: survey_day_lists, survey_day_count, sl_selected_site_ids, sl_last_draw_sig, qc_rect_selected_ids, qc_last_draw_sig.
- clear_loaded_data resets all new day-list state.
- Preliminary straight-line day splitting (split_route_into_days) preserved in codebase but removed from main UI per Issue #1.

Features preserved:
- GBIF pagination, CSV upload, map-click occurrence exclusion, red QC excluded points
- Ensemble SDM, VIF stepwise filtering, spatial partition diagnostics
- Raster-style SDM predict map, SDM-high exploration candidates
- HTML/CSV downloads

Known risks / TODO:
- folium.plugins.Draw requires streamlit-folium >= 0.13 for all_drawings return; older versions silently ignore rectangle selection.
- Day list state persists across SDM rebuilds; stale site IDs are pruned but day numbers are not reset.

## 2026-06-02 - Claude (Anthropic) — survey site list

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:
- Renamed section to "Survey site list".
- Two modes: 1. Auto (top-ranked with top_n, min_priority, min_suit, type filters); 2. Manual (map-click toggle, order preserved).
- Site list table shows: site_id, priority_rank, priority_score, sdm_suitability, occurrence_support_score, n_occurrences, latitude, longitude, candidate_type, and a clickable "📍 Open" Google Maps link per site (via st.column_config.LinkColumn).
- Action buttons: "🗺️ Open all sites as Google Maps route", "⬇ Download shareable HTML", "📋 Copy shareable text list" (popover with st.code block).
- CSV download demoted to optional collapsed expander.
- Shareable HTML (make_shareable_html) generates a self-contained page with table and per-site Google Maps links.
- Shareable text list (_make_shareable_text) shown in st.code block with built-in copy button.
- Warning text added as caption below the subheader.
- Advanced day splitting expander retained (AGENTS.md compliance).

Features preserved:
- GBIF pagination, CSV upload, map-click occurrence exclusion, red QC excluded points
- Ensemble SDM, VIF, spatial partition, predict map, SDM-high exploration candidates
- Day-by-day route planner (Advanced expander)
- HTML/CSV downloads

Known risks / TODO:
- st.popover requires Streamlit >= 1.31; older deployments should upgrade.
- Google Maps route URL caps at 8 waypoints; longer lists drop excess silently.

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
