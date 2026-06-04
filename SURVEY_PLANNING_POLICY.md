# Survey planning policy for AI coding agents

This app is a field-survey planning tool, not a full all-record SDM analysis platform.

## Core principle

Do not push all GBIF occurrence records into maps, candidate generation, SDM, or SSDM by default.

The app should use fixed, sensible lightweight defaults chosen by the application itself. Do not make general users choose between multiple survey-planning modes just to avoid lag.

The goal is to identify realistic, field-ready survey candidates quickly, reproducibly, and with reduced observer/access bias.

## Required top-level workflow

The main species-mode workflow is:

1. Get occurrence data.
2. Choose the survey area for observed-data candidate generation.
3. Generate survey candidates from observed occurrence data.
4. Optional: build an SDM using its own independent QC and prediction-extent workflow.
5. Add SDM predicted probability as weighted model support to re-rank the observed-data candidates.

The Step 2 survey area must not automatically flow into SDM.

The optional SDM workflow is independent. It should start from the fetched occurrence records, apply SDM-specific coordinate QC, apply SDM bias-reduction preprocessing, define an SDM-specific prediction extent, build the model, and then add model support back to the observed-data candidates.

## GBIF fetch and performance policy

The GBIF fetch cap is the primary performance control. Working-set caps alone are not enough if downloading and cleaning thousands of records already makes the app lag.

Required behavior:

- Run a lightweight GBIF count query first.
- Show the total coordinate-record count before downloading occurrences.
- Use a modest default fetch cap selected by the app.
- Do not default species mode to 10,000 records.
- Do not add a `Survey planning mode` selector to the main UI.
- Do not simply take the first N records when the total exceeds the cap. Prefer a representative retrieval strategy such as distributed offsets, year-stratified retrieval, or another documented approach that reduces ordering bias.

Recommended fixed defaults:

- Species fetch cap: about 1,000 records.
- Genus fetch cap: about 3,000 records.
- Candidate input cap: about 800 records.
- SDM presence cap: about 300 records.
- SSDM presence cap: about 150 records per species.

If a manual `Maximum GBIF records to fetch` control remains, keep the default lightweight and place unusually large values behind an advanced/custom control.

The UI should preserve and report the GBIF total count even when only a subset is fetched.

## Country filter UI

Use the original compact country-code selector.

Preferred UI:

- `Country code filter optional`
- Common two-letter codes such as JP, US, GB, CN, KR, TW, and others
- Empty value for all countries

Do not replace this with a full English country-name selector.

Remove any separate `Advanced country filter` section from the UI.

## Required data separation

Keep these concepts separate in code and UI:

- GBIF total count: number reported by GBIF before download.
- Requested fetch cap: maximum number requested from GBIF.
- Actual fetched records: records remaining after representative retrieval and fetch-stage deduplication.
- `occ_fetched`: cleaned fetched occurrence records.
- `occ_survey_selected`: records selected in Step 2 for observed-data candidate generation only.
- `occ_candidate_input`: spatially representative records used for observed-data candidates.
- `occ_sdm_qc_included`: records remaining after optional SDM-specific coordinate QC.
- `occ_sdm_train`: bias-reduced presence records used for optional SDM.

Do not use `occ_survey_selected` as the default SDM input.

For genus mode, use analogous working sets for observed richness hotspots and optional SSDM.

## Count transparency

The app must explain why counts decrease between stages.

For example:

- GBIF total coordinate records: 2,772
- Requested fetch cap: 1,000
- Actual fetched records after representative retrieval and fetch-stage deduplication: 883
- Active survey-area records: 883
- Records used for observed candidates after exact-coordinate deduplication and grid thinning: 515
- Records available as the SDM source before SDM QC/thinning: 883
- Final SDM presence points after SDM QC and bias reduction: 300

Do not label 883 as `Raw records` if it is already a deduplicated fetched subset. Use precise labels such as `Actual fetched records` or `Fetched records after deduplication`.

## Maps must show all analysis points

The app does not need to show every GBIF record that was not used, but every point actually used in an analysis must be visible on a corresponding map.

Required behavior:

- The observed-candidate map must show all `occ_candidate_input` points used to generate observed-data candidates.
- The SDM input / QC map must show all records that will actually be passed into SDM after SDM-specific QC and bias-reduction preprocessing.
- If points are excluded from analysis, they may be hidden or shown separately, but the user must be able to verify the full set of included analysis points.
- Do not cap the displayed analysis-point layer below the number of points actually used in that analysis.

This rule applies even when the app fetches more records than it ultimately analyzes.

## Step 2 survey-area selection

Step 2 is only for observed-data candidate generation.

Main options:

- Use all fetched records.
- Use only records inside a drawn rectangle.
- Exclude records inside a drawn rectangle.

Do not place coordinate QC in Step 2.

Do not make Step 2 survey-area selection control the SDM training set or SDM prediction extent.

## Observed-data candidate generation

Observed occurrence data must generate base survey candidates before any model is run.

The Step 2 selected survey-area records should be converted into a spatially representative candidate-input subset and used to generate observed-data survey candidates.

The map for this step should display all candidate-input points used in the clustering / candidate-generation analysis.

These candidates are the core output of the app.

## Optional SDM workflow

SDM is optional. It should not replace observed-data candidates and should not be required to proceed.

The SDM workflow should be independent from Step 2 and should contain, in this order:

1. Optional SDM coordinate QC.
2. SDM bias-reduction preprocessing.
3. SDM-specific prediction extent selection.
4. Environmental variable selection and collinearity handling.
5. Spatial validation / partitioning.
6. SDM fitting and prediction.
7. Add SDM predicted probability to observed-data candidates as model support.

### Simplify SDM maps

Do not show separate maps for `SDM coordinate QC`, `SDM prediction extent — macro scale`, and `SDM occurrence input` when they serve overlapping purposes.

Use one consolidated SDM setup map whose purpose is only:

- remove suspicious SDM source records by rectangle
- confirm the final SDM occurrence input
- confirm the chosen SDM prediction extent

The consolidated map should support layers or visual distinctions for:

- included SDM analysis points
- excluded QC records, if shown
- SDM prediction extent outline

The user should not have to scroll through multiple nearly identical SDM maps.

### SDM coordinate QC

SDM-specific QC should be inside `Optional: Build SDM`.

Use rectangle-based exclusion only. Do not use point-click QC as the main workflow.

QC-excluded records must not be used for SDM training or SDM extent generation.

### SDM bias reduction

Account for GBIF observer/access bias using sensible defaults such as:

- exact-coordinate deduplication
- grid thinning
- distance thinning
- presence-point caps

The consolidated SDM setup map should show all final included SDM presence points after bias reduction.

### SDM prediction extent

The SDM prediction extent is independent from the Step 2 survey-area rectangle.

Inside `Optional: Build SDM`, allow the user to define the SDM extent from the SDM QC-cleaned occurrence set using:

- buffer
- convex hull
- bounding box

Show the extent outline on the same consolidated SDM setup map.

### Environmental variables and collinearity

Do not show a `Variable preset` selector with `Recommended` versus `Custom` as the main UI.

Instead:

- Show one editable environmental-variable multiselect.
- Pre-populate it with the recommended balanced ecology set.
- Let the user directly add or remove variables from that default selection.
- Automatically apply VIF stepwise filtering with threshold 10 before model fitting.
- Do not show `Variable-selection strategy` or `No VIF` in the main UI.
- Keep VIF threshold, alternative correlation filtering, and detailed diagnostics under Advanced settings only.

Apply the same simplified approach to SSDM shared variable selection.

### Spatial validation

The main UI should expose the original validation-method choices because they are scientifically meaningful:

- block
- checkerboard1
- checkerboard2
- random holdout
- random k-fold
- jackknife

Default validation method: `block`.

Do not replace these with only `Recommended spatial validation` or `Fast random split` labels.

Hide or automatically calculate technical parameters unless they are relevant:

- `k for random k-fold` should only appear when random k-fold is selected, or be automatically set.
- `Checkerboard cell size (degrees)` should only appear for checkerboard methods, or be automatically set.
- `Maximum predict-map pixels` should not appear in the main UI. Use a fixed sensible automatic value or move it to Advanced settings.

## Candidate scoring

SDM predicted probability is optional model support used to re-rank the observed-data candidates.

Candidate ranking should support this structure:

`priority_score = observed_weight * occurrence_support_score + model_weight * model_support_score + optional bonuses`

Recommended default weights:

- observed-data weight: 0.7
- SDM/SSDM model weight: 0.3

If SDM/SSDM has not been run, rank by observed occurrence support only and show that model support is unavailable.

## Validation for publication

The planned paper should test whether representative subsets are sufficient for field-survey planning.

Recommended validation comparisons:

- All records versus representative fetched/working subsets, such as 3000, 1500, 1000, 800, 500, and 300 retained records.
- Top-10 or Top-20 candidate overlap.
- Rank correlation between candidate lists.
- Spatial coverage or environmental-space coverage.
- Runtime and map responsiveness.
- Field detection success at ranked candidate sites.

The expected claim is:

Spatially representative occurrence subsets can preserve field-survey-relevant candidate rankings while greatly reducing computational cost and reducing observer/access-bias effects.

## Anti-rollback rule

Do not reintroduce an all-record-first workflow as the default.

Do not add a main `Survey planning mode` selector.

Do not add an `Advanced country filter` section.

Do not place coordinate QC in Step 2.

Do not automatically send the Step 2 survey-area selection into SDM.

Do not show multiple redundant SDM setup maps.

Do not make the app depend on downloading, rendering, or modeling all available GBIF records before the user can access occurrence-based survey candidates.