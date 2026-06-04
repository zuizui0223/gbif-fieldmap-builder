# AI Change Log

This file records changes made by AI coding agents such as Codex, Claude, ChatGPT, or other assistants.

Each agent should update this file after editing code.

## 2026-06-04 - Claude (claude-sonnet-4-6) — SURVEY_PLANNING_POLICY: transparency, consolidated SDM map, label clarity, country filter

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:

**1. Show all analysis points (no cap)**
- Main candidate map now uses `occ_candidate_input` (all analysis points, uncapped) instead of `occ_map_display` (capped display subset).
- SDM setup map shows all `occ_sdm_train` final presence points (blue) without cap. Only unused excluded QC records are capped at 500.

**2. Clarify record-count labels**
- SDM preprocessing metrics: "Raw records" → "Fetched records (SDM source)"; "After QC exclusion" → "After SDM QC exclusion"; "After exact dedup" → "After deduplication"; "After thinning" → "After spatial thinning"; "Final SDM presence pts" → "Final SDM presence points". Delta values added showing reduction at each stage.
- Target-occurrence panel metric: "Raw records" → "Active survey-area records"; "Active target records" → "Selected for candidates".
- Performance summary: "Raw valid records" → "GBIF fetched records". Genus: "Raw records" → "Active survey-area records".

**3. Consolidated SDM setup map**
- Added `make_sdm_setup_map(occ_sdm_final, excluded_raw, extent_geom, area_mode)` function that combines: SDM prediction extent outline (orange), included analysis points (blue, all shown), excluded QC points (red), and rectangle draw tool for bulk SDM QC exclusion.
- Replaced three separate SDM maps (`sdm_rectangle_qc_panel`, `make_sdm_extent_preview_map`, `make_exclusion_review_map` inside SDM expander) with this single map.
- Reorganized SDM expander: preprocessing controls → extent controls → consolidated setup map → environmental variables → run.
- Removed duplicate "SDM bias-reduction preprocessing" section left over from previous edits.

**4. Remove "Advanced country filter" expander**
- Species and genus GBIF fetch: removed `with st.sidebar.expander("Advanced country filter")` and custom_country text_input.
- Kept only the compact country-code dropdown selectbox.

Features preserved:
- Step 2 survey area for observed candidates only; independent SDM QC and extent; representative GBIF fetch; SDM bias reduction; VIF stepwise threshold 10; block/checkerboard/random/jackknife validation; weighted observed + model scoring; downloads and selected survey site lists.


## 2026-06-04 - Codex (OpenAI) - Apply lightweight survey-planning policy UI

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:
- Read `AGENTS.md`, `CHANGELOG_AI.md`, and `SURVEY_PLANNING_POLICY.md`, then used the latest GitHub `main` as the baseline.
- Removed the main species/genus `Survey planning mode` selectors and fixed the default working policy to species fetch 1,000, genus fetch 3,000, map 500, candidate input 800, SDM 300, and SSDM 150 per species.
- Restored compact country-code filters (`JP`, `US`, etc.) for species and genus GBIF searches, with optional custom two-letter code fields under Advanced.
- Replaced SDM/SSDM environmental preset selectors with editable multiselects prefilled by the balanced ecology variables.
- Made VIF stepwise with threshold 10 the default SDM/SSDM variable-selection behavior while keeping threshold/alternative strategies inside Advanced.
- Restored the single-species validation method selector to the original partition methods, defaulting to `block`; k-fold and checkerboard inputs now appear only when relevant.

Features preserved:
- Step 2 remains observed-data candidate/hotspot selection only.
- Optional SDM retains independent SDM-only QC, bias reduction, prediction extent, predict map, VIF diagnostics, and weighted model-support scoring.
- Optional SSDM remains manual-run only and keeps observed richness separate from predicted stacked richness support.

Verification:
- `python -m py_compile gbif_fieldmap_builder_app.py`
- `git diff --check`

## 2026-06-04 - Codex (OpenAI) - Separate Step 2 observed candidates from optional SDM QC/extent

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:
- Read `AGENTS.md`, the latest `SURVEY_PLANNING_POLICY.md`, and `CHANGELOG_AI.md`; fast-forwarded to the latest GitHub `main` (`fc0bc00`) before editing.
- Removed coordinate QC from the species Step 2 workflow so Step 2 now selects only the observed-data survey area for candidate generation.
- Changed species SDM to start independently from fetched occurrence records, then apply SDM-only rectangle QC, SDM-only bias-reduction preprocessing, and SDM-only prediction extent generation inside `Optional: Build SDM`.
- Prevented the Step 2 survey-area selection from automatically becoming the SDM training set or prediction extent.
- Removed genus Step 2 coordinate QC and kept genus Step 2 as observed richness hotspot area selection only.
- Changed optional SSDM fitting to start from fetched genus records instead of the Step 2 observed-richness target set.

Features preserved:
- Count-first representative GBIF fetching, full-name country selector, observed-data candidates, optional SDM/SSDM, weighted model support, prediction maps, VIF/variable diagnostics, and downloads remain available.
- Step 2 survey-area rectangle remains available for observed-data candidate/hotspot generation.
- SDM rectangle QC remains available, but now inside the optional SDM workflow.

Known risks / TODO:
- The older rectangle QC helper remains in code for compatibility but is no longer called from Step 2.
- SSDM has been decoupled from Step 2 selection, but a fuller SSDM-specific rectangle QC UI can still be added later if needed.

## 2026-06-04 - Codex (OpenAI) - Count-first representative GBIF fetching and rectangle QC workflow

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:
- Read `AGENTS.md`, `SURVEY_PLANNING_POLICY.md`, and `CHANGELOG_AI.md`, then used the latest GitHub `main` as the baseline.
- Changed GBIF species and genus downloads to a count-first workflow: taxon match plus `limit=0` count is shown before occurrence download.
- Made survey-planning mode control GBIF fetch caps as well as downstream working subsets: species Fast defaults to 1,000 records, species Detailed to 3,000, genus Fast to 3,000, and genus Detailed to 10,000.
- Added representative GBIF retrieval when totals exceed the cap by sampling evenly spaced result offsets instead of simply taking the first N records, followed by GBIF ID / coordinate deduplication and spatial capping.
- Replaced sidebar country-code entry with a full-name country selector shared by species and genus workflows.
- Added rectangle-based coordinate QC to the main Step 2 workflow and genus workflow; QC exclusions are red on the QC map and removed from downstream candidate generation, SDM/SSDM, extents, and survey-site lists.
- Kept the survey-area rectangle separate from QC rectangles: the survey-area rectangle selects the active target occurrence set, while SDM/SSDM prediction extents are still generated inside the optional model expanders from that active set.
- Simplified environmental variable choices to Recommended variable set or Custom variables; Custom exposes an automatic high-correlation removal checkbox while VIF and detailed settings remain under Advanced.
- Simplified species SDM validation to Recommended spatial validation, Fast random split, or Advanced; k-fold, checkerboard size, and max predict-map pixels are no longer main-screen controls.

Features preserved:
- Raw GBIF records are kept for summary/download while maps, candidates, SDM, and SSDM use representative working subsets by default.
- GBIF taxon matching, paginated occurrence requests, CSV upload, target occurrence set selection, occurrence candidates, genus richness hotspots, optional SDM/SSDM, weighted scoring, NoData cleaning, prediction maps, downloads, and route/site list remain available.
- VIF stepwise and spatial partition diagnostics remain available under advanced settings.

Known risks / TODO:
- GBIF representative retrieval reduces ordering bias but still depends on GBIF result ordering within sampled pages; future validation should compare candidate rankings against all-record downloads.
- SSDM validation is still limited to the existing random-holdout/training-only implementation; full spatial SSDM partitions remain a future enhancement.

## 2026-06-04 - Codex (OpenAI) - Survey-planning representative subset defaults

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:
- Based the edit on the latest GitHub `main` after fast-forwarding to `9193bb4`.
- Read `AGENTS.md`, `SURVEY_PLANNING_POLICY.md`, and `CHANGELOG_AI.md` before editing.
- Added explicit survey-planning mode controls for species and genus workflows: Fast survey planning (recommended), Detailed analysis, and Custom.
- Set Fast survey planning defaults to spatially representative working subsets: map display about 500 records, candidate input about 800 records, SDM presence about 300 records, and SSDM about 150 records per species.
- Kept Detailed analysis higher but still bounded: map about 1000, candidate input about 1500, SDM about 500, and SSDM about 300 per species.
- Custom mode exposes manual caps without making all-record map/model/candidate processing the default.
- Updated `prepare_large_dataset_inputs` so candidate generation and SDM presence inputs are capped spatially representative subsets by default, not only when large dataset mode is active.
- Updated genus occurrence-richness hotspot generation to use a spatially representative working subset while preserving raw/active records for summaries.

Features preserved:
- Raw GBIF records remain preserved for transparency, summaries, and downloads.
- Observed-data candidates remain available before SDM/SSDM.
- SDM/SSDM remain optional model support for prioritization, not prerequisites.
- Existing GBIF download, CSV upload, target occurrence selection, SDM, SSDM, variable selection, route/site list, and downloads remain available.

Known risks / TODO:
- Representative subset defaults intentionally change candidate rankings compared with all-record processing; this matches the survey-planning policy and should be evaluated in planned subset-vs-all-record validation.

## 2026-06-03 - Claude (claude-sonnet-4-6) — Simplify Step 2 / Sampling design UI; move SDM extent inside expander

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:

**Step 2 heading renamed**
- `"2 — Prepare records"` → `"2 — Prepare records and choose survey range"`.

**Coordinate QC expander relabeled**
- `"Optional: Coordinate quality check"` → `"Advanced: coordinate QC — click points to exclude suspicious records"` (shows count when points are excluded). Functionally unchanged; click-to-exclude, rectangle draw, clear button, and red excluded points all preserved.

**Sidebar sampling design simplified**
- Always-visible controls reduced to two: **Survey range radius (m)** and **Candidate grouping scale (m)** (renamed from "DBSCAN cluster distance").
- All technical controls moved into a collapsed **"Advanced sampling settings"** expander: spatial thinning, large dataset mode, max map points, exact dedup, grid thinning, candidate center method, min records per cluster.
- "Occurrence record-count weight" renamed to **"Record-density bonus"** and moved into advanced settings.
- "Occurrence image popups" moved into advanced settings.
- Candidate scoring (Observed-data weight + SDM model weight) remains always-visible.

**SDM prediction extent moved inside "Optional: Build SDM" expander**
- Area mode, buffer/hull/bounding-box controls, hard exclusion radius, and the extent preview map are now inside the "Build SDM and predict map" expander.
- Users see occurrence-based survey candidates without any SDM extent section appearing on the page.
- Variables (`area_mode`, `buffer_km`, `rectangle_margin_km`, `exclusion_buffer_km`, `excluded_occ`, `extent_geom`) remain accessible to the `if run_sdm:` block via Python scope (Streamlit `with` blocks do not create new Python scope).

Features preserved:
- Target occurrence set selection, coordinate QC, large dataset caps, SDM/SSDM, VIF, variable presets, weighted scoring, route planner, downloads all unchanged.

## 2026-06-03 - Claude (claude-sonnet-4-6) — Weighted model support: fix model_support_score refresh bug + UI status banners

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:

**Bug fix: model_support_score not updated after SDM runs (species mode)**
- After `predict_suitability` populates `sdm_suitability`, code now explicitly writes `model_support_score = sdm_suitability.clip(0,1)` before the final `add_priority_rank` call. Previously the column stayed at 0.0 from the first call.

**Improved `add_priority_rank` fallback logic**
- When `model_support_score = 0.0` but `sdm_suitability` is non-NaN (meaning SDM ran after the score was initialised), `sdm_suitability` is used instead. Docstring added.

**Model support status banners**
- Species mode: info/success banner in "3 — Occurrence-based survey site suggestions" showing weights and SDM status.
- Genus mode: info/success banner in "4 — Selected hotspot sites" showing weights and SSDM status.

Features preserved:
- Observed-data candidates available without SDM/SSDM. All scoring columns preserved.


## 2026-06-03 - Claude (claude-sonnet-4-6) — Simplify environmental variable selection with presets; add Balanced ecology preset

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:

**New constants**
- `BALANCED_ECOLOGY_PRESET = ["bio1", "bio4", "bio12", "bio15", "bio14", "elevation"]` — 6 interpretable variables: temperature level (bio1), temperature seasonality (bio4), annual precipitation (bio12), precipitation seasonality (bio15), driest month precipitation / dryness (bio14), and elevation (topography).
- `ENV_VARIABLE_PRESETS = ["Balanced ecology preset", "Climate only preset", "Topography only preset", "Custom variables"]` — list of preset options.

**SDM variable selection UI (species mode, inside "Optional: Build SDM" expander)**
- Replaced raw topography/climate multiselects + variable-strategy selectbox with a clean **"Environmental variable preset"** selectbox as the main UI.
- Default preset is **"Balanced ecology preset"** — users get a sensible 6-variable set without needing to know bio variable numbers.
- "Climate only preset" selects all 19 WorldClim BIO variables with a caption recommending variable selection for large sets.
- "Topography only preset" selects elevation, slope, roughness.
- "Custom variables" shows the manual multiselects (topography + climate).
- Advanced variable selection (strategy, VIF/correlation threshold, custom final selection) moved into a **collapsed "Advanced variable selection" expander** — not required and not shown by default.

**SSDM variable selection UI (genus mode, inside SSDM expander)**
- Same preset-based redesign applied symmetrically to SSDM.
- Default is "Balanced ecology preset".
- Advanced variable selection (shared VIF strategy, thresholds) collapsed inside "Advanced variable selection" expander.
- All existing variable-selection strategies (No VIF, Correlation filter, VIF stepwise, Advanced custom) preserved in the advanced expander.

Features preserved:
- All variable-selection strategies (No VIF, Correlation filter, VIF stepwise, Ecological preset, Advanced custom) preserved.
- VIF stepwise is not the default (No VIF is default inside the expander); preset selection is the primary interface.
- Single-species SDM, SSDM, occurrence candidates, and route planner unchanged.

Known risks / TODO:
- Sessions that previously had custom variable selections will default to Balanced ecology preset on next load; users should re-select Custom if needed.

## 2026-06-03 - Codex (OpenAI) - Issue #10 optional model-support scoring and variable-selection strategies

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:
- Made the shared species/genus workflow explicit: observed occurrence data generate the base survey candidates, while SDM/SSDM adds optional model support for prioritization.
- Added candidate scoring controls for species and genus modes: observed-data weight and SDM/SSDM model weight, defaulting to 0.7 and 0.3.
- Standardized output scoring columns: `occurrence_support_score`, `model_support_score`, `observed_weight`, `model_weight`, `priority_score`, and `score_explanation`.
- Updated candidate ranking so `priority_score = observed_weight * occurrence_support_score + model_weight * model_support_score + optional bonuses`.
- Species mode uses observed occurrence support plus optional SDM suitability-derived model support.
- Genus mode uses observed richness/record support plus optional SSDM predicted richness-derived model support; observed richness hotspots can be re-ranked with SSDM support after SSDM runs.
- Replaced default-on VIF controls with variable-selection strategy options: No VIF, Correlation filter, VIF stepwise, Ecological preset / representative climate set, and Advanced custom selection.
- Added ecological preset / correlation-cluster representative variable selection and richer diagnostics fields including `final_status`, `reason`, `protected_by_group`, `fallback_kept`, and `vif_stage`.
- Kept raster NoData/fill-value cleaning safeguards before SDM and SSDM variable selection/modeling.

Features preserved:
- Observed occurrence candidates remain available without SDM/SSDM, and SDM/SSDM never replaces or becomes required for candidate generation.

## 2026-06-03 - Codex (OpenAI) - Issue #10 target occurrence rectangle selection

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:
- Added Step 2 target occurrence set controls: use all cleaned records, use only records inside a drawn rectangle, or exclude records inside a drawn rectangle.
- Clarified that the rectangle is not the final SDM/SSDM extent; it only selects which occurrence records are used to derive candidates and prediction extents.
- Added shared target-selection map/helper and separate active target sets for species mode and genus mode.
- Derived single-species occurrence candidates, SDM train inputs, and buffer/convex-hull/bounding-box prediction extents from the selected target occurrence set.
- Derived genus observed richness grids/hotspots and optional SSDM inputs/extents from the selected target occurrence set.
- Added count metrics for raw records, records inside rectangle, records excluded by rectangle, active target records, candidate inputs, and SDM/SSDM inputs.

Features preserved:
- Coordinate red-point exclusion, large dataset caps, GBIF downloads, single-species SDM/VIF/predict maps, genus richness, optional SSDM, route planning, and downloads remain available.

## 2026-06-03 - Codex (OpenAI) - GBIF retry handling for connection resets

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:
- Added a shared GBIF JSON request helper with retry/backoff for temporary HTTP 429/5xx, timeout, and connection-reset failures.
- Routed species and genus GBIF match/search/occurrence requests through the retry helper.
- Prevented single-species GBIF downloads from crashing the app when a request fails, matching the safer genus-mode behavior.
- Improved user-facing GBIF failure messages with guidance to retry, lower the record cap, or clear filters.

Features preserved:
- GBIF paginated downloads, large dataset caps, genus richness/SSDM, single-species SDM/VIF/predict maps, exclusion, route planning, and downloads remain available.

## 2026-06-03 - Codex (OpenAI) - Issue #10 large GBIF dataset auto-capping

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:
- Automatically enables effective large dataset handling when more than 1,000 valid occurrence records are loaded, even if the sidebar checkbox was left off.
- Keeps `occ_raw` as the full coordinate-cleaned record set, while using capped/thinned `occ_map_display`, `occ_candidate_input`, and `occ_sdm_train` datasets for interactive maps, candidate clustering, and SDM.
- Caps interactive occurrence maps to at most 1,000 points in large dataset mode and disables occurrence image popups by default for large datasets.
- Uses spatially balanced capping so candidate generation is limited to about 1,000 records and SDM training is limited to about 500 records in large dataset mode.
- Shows a large dataset summary and performance metrics so users can see which record set is used for raw data, map display, candidate generation, and SDM.
- Updated optional SDM presence caps so raw GBIF records are not accidentally forced into SDM when large datasets would freeze the app.

Features preserved:
- Coordinate exclusion, occurrence candidate ranges, SDM/VIF/spatial partition diagnostics, predict maps, SSDM workflows, route planning, and HTML downloads remain available.

## 2026-06-03 - Codex (OpenAI) - Issue #10 VIF NoData cleaning and SSDM UI consistency

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:
- Based the change on the latest GitHub main state (`bd96628`, Issue #4c merged).
- Added shared raster/environment cleaning helpers for SDM and SSDM workflows.
- Converted raster `src.nodata`, non-finite values, and extreme fill/sentinel values below `-1e20` or above `1e20` to NaN.
- Applied environment-table cleaning before single-species SDM VIF/model fitting and before SSDM shared VIF/model fitting.
- Dropped rows with invalid environmental values and reported drop counts in SDM VIF tables and SSDM VIF diagnostics / model summaries.
- Added guards so VIF stops with a clear error if extreme raster sentinel values remain after cleaning.
- Updated SSDM bias-reduction UI to default to `Auto (Recommended)` and moved detailed thinning controls under `Advanced / Custom`.
- Made SSDM bias-reduction wording parallel with the species SDM bias-reduction preprocessing panel.

Features preserved:
- Single species SDM, SSDM, shared SSDM VIF, occurrence richness, large dataset controls, spatial partition diagnostics, predict maps, route planner, and downloads remain available.

Known risks / TODO:
- Rows outside valid raster coverage are now dropped before VIF/SDM. Very sparse datasets may need broader extents, lower-resolution rasters, or fewer selected variables.

## 2026-06-03 - Claude (claude-sonnet-4-6) — Issue #4 follow-up: SDM bias-reduction preprocessing + SSDM per-species thinning

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:

**SDM bias-reduction preprocessing (species mode)**
- Added a "SDM bias-reduction preprocessing" section at the top of the "Optional: Build SDM" expander with four controls: exact coordinate deduplication (default on), grid thinning in degrees (default 0.05°), distance thinning / spThin-like (default 1 000 m, 0 = off), maximum SDM presence points cap (default 0 = no cap).
- Caption explains the purpose: GBIF records cluster near roads/cities/trails; spatial thinning reduces sampling bias before SDM fitting. Explicitly notes these settings apply only to SDM training and do not affect occurrence-based survey candidates.
- After the expander, a new `occ_for_sdm` pipeline applies these settings to `occ_after_exclusion` (QC-cleaned but not otherwise pre-processed), keeping the SDM preprocessing pipeline independent of the occurrence-candidate clustering pipeline.
- Five-column preprocessing metrics panel displayed (always visible, outside the expander): Raw records → After QC exclusion → After exact dedup → After thinning → Final SDM presence points.
- SDM training (`build_presence_background`, `build_predict_map`, `make_sdm_exploration_candidates`) now use `occ_for_sdm` instead of `occ_sdm_train`.
- `current_sdm_occurrence_row_ids` now tracks `occ_for_sdm` row IDs; SDM cache invalidation triggers when preprocessing settings or QC exclusions change.
- `occ_sdm_train` (sidebar-preprocessed set) remains as the basis for occurrence-candidate clustering and SDM extent preview — unchanged behavior for occurrence candidates.

**SSDM per-species bias-reduction preprocessing (genus mode)**
- Added `per_species_grid_thin_deg` and `per_species_distance_thin_m` parameters to `fit_stacked_species_sdms`.
- Per-species preprocessing order: exact coordinate dedup → grid thinning → distance thinning → presence cap. Applied before each species SDM fit.
- Exposed as UI controls in the SSDM expander: "Per-species grid thinning (degrees, 0 = off)" (default 0.05°) and "Per-species distance thinning (m, 0 = off)" (default 0).

Features preserved:
- Occurrence-based survey candidates and richness hotspots unchanged and always available before SDM/SSDM.
- Single-species SDM VIF, partition, predict map, exploration candidates, route planner unchanged.
- Genus richness grid, SSDM shared VIF, SSDM partition, downloads unchanged.

## 2026-06-03 - Claude (claude-sonnet-4-6) — Issue #4 follow-up: fix widget key conflict, non-blocking QC, symmetric headings

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:

**Fix `restore_excluded_row_ids` widget key conflict**
- Removed `restore_excluded_row_ids` from `init_session_state` defaults and from `clear_loaded_data`.
- Removed the `st.multiselect("Excluded row IDs", ..., key="restore_excluded_row_ids")` widget and its associated "Recover selected excluded rows" button from `coordinate_exclusion_panel`. This eliminates the Streamlit widget-state conflict reported in the issue.
- Click-to-restore still works: clicking an already-excluded point on the QC map toggles it back to included.

**Non-blocking, collapsed QC panel**
- `coordinate_exclusion_panel` expander changed from `expanded=True` to `expanded=False`. The QC section is now clearly optional and does not block the occurrence candidate section.
- Expander label shows the current excluded count: "Optional: Coordinate quality check (N excluded)" when exclusions are active.
- Added a large-dataset hint: when `occ_raw > 500` records, a note recommends using rectangle drawing for bulk exclusion.

**Symmetric numbered section headings (species and genus modes)**
- Species mode: `2 — Prepare records` → `3 — Occurrence-based survey site suggestions` → `4 — Selected survey sites` (route planner) → `Optional: Build SDM`.
- Genus mode: `2 — Prepare records and species summary` → `3 — Occurrence-based richness hotspots` → `4 — Selected hotspot sites` → `Optional: Run SSDM`.
- Both modes now follow a parallel 1–4 + optional structure as requested.

**Genus panel restructure**
- The previous top-level `st.subheader("Genus diversity — occurrence richness hotspots")` (before data-load check) was replaced with numbered section subheaders placed after data loads, keeping the same data-guard logic.
- Step 4 "Selected hotspot sites" now uses the hotspot candidates table (previously "Richness hotspot candidates") with the same data and downloads.

Features preserved:
- All exclusion logic (click, rectangle, clear), SDM/SSDM, VIF, route planner, downloads unchanged.

## 2026-06-03 - Claude (claude-sonnet-4-6) — Issue #2 follow-up: shared SSDM VIF, BIO protection, VIF diagnostics, partition settings

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:

**Shared SSDM VIF (run once, not per species)**
- Removed per-species VIF from `fit_stacked_species_sdms`. VIF is now run **once** on a pooled sample (up to 1,000 genus occurrence records + shared background grid points) before the species loop.
- The same retained variable set (`kept_vars`) is used for every per-species model, preventing inconsistent variable sets and the BIO-variable disappearance bug reported by the user.
- Added `ssdm_variable_diagnostics(env_df, variables)` — computes diagnostic table before VIF: variable, group (climate/topography/other), min, max, sd, unique_values, missing_fraction, max_abs_corr, VIF, status.
- Added `run_ssdm_shared_vif(env_df, variables, vif_threshold)` — wraps `vif_step` with BIO-variable protection: if VIF removes all `bio1`–`bio19` variables, the least-correlated BIO variable is automatically restored and marked `fallback-kept (BIO protection)`.

**SSDM partition settings exposed**
- `fit_stacked_species_sdms` now accepts `ssdm_partition_method` (default `"random holdout"`) and `ssdm_test_split` (default `0.20`). Passes `holdout_test_size` through to `fit_sdm`.
- `fit_sdm` gains `holdout_test_size=0.25` parameter (used by random holdout); single-species SDM callers are unchanged and keep the existing 0.25 default.
- UI: added `SSDM partition method` selectbox (`random holdout` / `none (training only)`) and `SSDM holdout test split proportion` number input. `none` skips validation for fastest exploratory runs.
- UI caption clearly states: "Spatial block/checkerboard partitions are available in single-species SDM but not yet implemented for SSDM."

**VIF diagnostics table in UI**
- After SSDM runs with VIF enabled, displays `Shared VIF diagnostics` table showing per-variable stats, max_abs_corr, VIF, and final status (kept/removed/fallback-kept).
- If BIO fallback was triggered, a `st.warning` is shown explaining which variable was restored.
- Added `ssdm_vif_diagnostics.csv` download button.

**UI label update**
- Checkbox label changed from "Apply VIF stepwise filtering for each species SDM" → "Apply shared VIF for SSDM (run once on pooled data)".
- Updated caption to explain shared VIF behavior and BIO protection.

**Single-species SDM unchanged**
- VIF, spatial partition, and all single-species SDM workflow are unmodified.

Features preserved:
- Genus occurrence richness, hotspots, SSDM maps, SSDM downloads, large-dataset mode, exclusion/QC, route planner unchanged.

## 2026-06-03 - Claude (claude-sonnet-4-6) — Issue #4: Unify species/genus workflows; make SDM/SSDM optional

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:
- **Mode switching fix**: Added `_last_analysis_mode` to session state. On every mode switch between "Single species survey planning" and "Genus diversity / SSDM", widget-collision-prone state (map-click signatures, selected site IDs, draw signatures, QC rectangle IDs) is reset. This prevents Streamlit session-state inconsistencies when users freely alternate between modes.
- **Species mode — occurrence candidates before SDM**: Added "Occurrence-supported survey candidates" section immediately after DBSCAN clustering, before the SDM section. Shows candidate table with priority scores, plus CSV/KML download buttons. Users can plan surveys from raw occurrence data without running SDM.
- **Species mode — SDM is optional**: Changed SDM expander from `expanded=True` to `expanded=False` and relabeled from "Build SDM and predict map" to "Optional: Build SDM and predict map". Relabeled the subheader to "SDM (optional enhancement)". SDM exploration candidates and suitability scoring are still fully available when the user chooses to run SDM.
- **Genus mode — hotspots before SSDM**: Updated heading and caption to emphasize that occurrence richness hotspots are the primary output (no modeling required). The optional SSDM expander was already collapsed; caption now explicitly points users to it as an enhancement-only section.
- **Large datasets**: Occurrence candidates are always computed from spatially thinned clusters regardless of dataset size, consistent with existing large-dataset-mode behavior.

Features preserved:
- All existing species SDM, VIF, spatial partition, predict map, exclusion/QC, and route planner features unchanged.
- All genus richness grid, hotspot, SSDM, and download features unchanged.

## 2026-06-03 - Claude (Anthropic) — Issue #2 follow-up: SSDM eligibility label and map legends

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:
- Renamed sidebar label "Minimum records flag for future SSDM" → "Minimum records for SSDM eligibility". Added help text: species below this threshold can still appear in the occurrence-based richness map but will be skipped in SSDM.
- Added add_richness_legend() helper: yellow-green gradient legend for occurrence richness maps. Title is metric-aware ("Observed species richness", "Occurrence record count", "Species meeting min. records threshold"). Note clarifies this is based on GBIF records, not modeled suitability.
- Added add_ssdm_richness_legend() helper: blue-red gradient legend for SSDM maps. Continuous variant shows "Predicted richness (suitability sum)" with note that values are not integer species counts. Binary variant shows "Predicted species richness" with note that values are the count of species above the suitability threshold.
- make_richness_map() now calls add_richness_legend() after drawing the grid.
- make_ssdm_map() now calls add_ssdm_richness_legend() using the actual min/max values from the grid, dispatching on value_col to choose the correct legend variant.

Features preserved:
- All genus/SSDM features, single-species SDM, VIF, spatial partition, predict map, route planner, downloads unchanged.

## 2026-06-03 - Codex (OpenAI) - Add VIF filtering to optional SSDM

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:
- Added per-species VIF stepwise filtering to the optional SSDM workflow.
- Added SSDM UI controls for applying VIF filtering and setting the VIF threshold.
- Each species SDM now fits using its own VIF-filtered variable set when enabled.
- Added VIF status, threshold, kept variables, and removed variables to ssdm_species_model_summary.csv.

Features preserved:
- Genus occurrence richness, optional SSDM maps, large dataset controls, single species SDM, VIF, spatial partition diagnostics, predict map, route planner, and downloads remain available.

Known risks / TODO:
- Different species may keep different environmental variables after VIF filtering, which is expected for per-species SDMs but should be reviewed in the summary CSV.

## 2026-06-03 - Codex (OpenAI) - Issue #2 follow-up: optional stacked species SDM

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:
- Added an explicit "Optional SSDM: stack species SDMs" section in Genus diversity / SSDM mode.
- SSDM does not run automatically; it runs only when the user clicks Run SSDM.
- Added per-species SDM fitting for species with enough occurrence records.
- Added a shared environmental prediction grid for all modeled species.
- Added continuous SSDM richness as the sum of predicted suitability values.
- Added binary SSDM richness as the sum of species predictions above the user-defined suitability threshold.
- Added continuous and binary SSDM richness maps.
- Added SSDM outputs: ssdm_species_model_summary.csv, ssdm_richness_grid.csv, and ssdm_hotspot_candidates.csv.
- Added safeguards for max species to model, max presence points per species, shared background cells, progress per species, and skipping species with too few records.
- Clarified that occurrence richness is observed richness while SSDM richness is predicted stacked richness.

Features preserved:
- Occurrence richness grid, genus downloads, single species planning, coordinate exclusion, large dataset controls, SDM, VIF, spatial partition diagnostics, predict map, route planner, and downloads remain available.

Known risks / TODO:
- SSDM can still be computationally heavy when many species, variables, or prediction cells are selected; defaults are conservative and the run is manual.

## 2026-06-03 - Codex (OpenAI) - Issue #3 large dataset mode

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:
- Added Large dataset mode controls and a Max occurrence points shown on map setting.
- Separated the single-species data flow into occ_raw, occ_analysis, occ_map_display, and occ_sdm_train.
- Limited occurrence maps to a display subset while keeping raw records available for exclusion state and counts.
- Disabled occurrence image popups by default when raw valid records exceed 500.
- Added exact coordinate deduplication and optional grid thinning before clustering and SDM.
- Moved clustering, candidate generation, SDM extent, background generation, SDM fitting, predict map, and SDM-high exploration to the reduced occ_sdm_train set instead of all raw GBIF records.
- Added performance summary metrics for raw records, after exclusion, analysis records, SDM training records, map points, dedupe removals, and grid-thinning removals.

Features preserved:
- GBIF paginated occurrence download, CSV upload, map-click exclusion, candidate generation, ensemble SDM, VIF, spatial partition diagnostics, predict map, SDM-high candidates, route planner, and downloads remain available.

Known risks / TODO:
- In very large datasets, only displayed map points can be toggled by clicking; increase Max occurrence points shown on map to inspect more points.

## 2026-06-03 - Codex (OpenAI) - Fix genus GBIF backbone key selection

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:
- Fixed genus-mode GBIF taxon resolution to use exact GENUS matches from species/match when available.
- Fixed species/search fallback to use GBIF backbone nubKey instead of checklist-specific dataset keys.
- Prevented unrelated or unranked matches such as Campanulae fungi names from being used as genus occurrence taxon keys.
- Updated genus download status text to show the GBIF backbone taxonKey.

Features preserved:
- Genus occurrence richness outputs, single species planning, coordinate exclusion, SDM, VIF, spatial partition diagnostics, predict map, route planner, and downloads remain unchanged.

Known risks / TODO:
- Homonymous or highly ambiguous genus names may still need manual verification in future UI.

## 2026-06-03 - Codex (OpenAI) - Fix genus zero-record coordinate detection

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:
- Preserved the expected GBIF genus occurrence columns even when a genus download returns zero records.
- Added a genus-mode warning for zero coordinate records before latitude/longitude auto-detection runs.

Features preserved:
- Single species planning, CSV upload, coordinate exclusion, SDM, VIF, spatial partition diagnostics, predict map, route planner, and genus richness outputs remain unchanged.

Known risks / TODO:
- If GBIF returns zero records because of a strict country/year filter, the user still needs to loosen the filter or choose another genus.

## 2026-06-03 - Codex (OpenAI) - Issue #2 first step: genus occurrence richness mode

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:
- Added an Analysis mode selector with Single species survey planning and Genus diversity / SSDM.
- Added Genus diversity / SSDM mode with a separate genus input, country filter keys, GBIF paginated genus occurrence download, species grouping, species summary table, occurrence-based richness grid map, hotspot candidates, and CSV/HTML downloads.
- Kept full SSDM out of this step; the genus mode is occurrence-richness only until this map is stable.
- Added GBIF genus-name fallback matching through species search and catches genus download errors in the UI so a failed genus lookup does not crash the app.
- Used a lighter default genus fetch cap to reduce Streamlit Cloud blocking risk while preserving the 300-record GBIF pagination behavior.

Features preserved:
- Single species GBIF download, CSV upload, coordinate exclusion, clustering, SDM, VIF, spatial partition diagnostics, predict map, SDM-high candidates, route planner, and HTML download remain unchanged.

Known risks / TODO:
- Full SSDM is intentionally not implemented yet.
- Very large genus downloads can still take time because GBIF is paginated at 300 records per request.

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
