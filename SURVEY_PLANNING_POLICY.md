# Survey planning policy for AI coding agents

This app is a field-survey planning tool, not a full all-record SDM analysis platform.

## Core principle

Do not push all GBIF occurrence records into maps, candidate generation, SDM, or SSDM by default.

For normal survey planning, the app should first show the GBIF total count, then fetch only a field-survey-appropriate representative subset.

The goal is not to maximize the number of occurrence records used in every computation. The goal is to identify realistic, field-ready survey candidates quickly, reproducibly, and with reduced observer/access bias.

## Required top-level workflow

The main species-mode workflow is:

1. Get occurrence data.
2. Choose the survey area for observed-data candidate generation.
3. Generate survey candidates from observed occurrence data.
4. Optional: build an SDM using its own independent QC and prediction-extent workflow.
5. Add SDM predicted probability as weighted model support to re-rank the observed-data candidates.

The Step 2 survey area must not automatically flow into SDM.

The survey-area selection exists only to decide where observed occurrence-based survey candidates are generated.

The optional SDM workflow is independent. It should start from the fetched occurrence records, apply SDM-specific coordinate QC, apply SDM bias-reduction preprocessing, define an SDM-specific prediction extent, build the model, and then add model support back to the observed-data candidates.

## Scientific rationale

For field-survey planning, using every public occurrence record is often unnecessary and can be harmful.

Large GBIF/iNaturalist-style datasets are commonly clustered near roads, towns, popular trails, and accessible places. These clusters can make maps slow, bias candidate ranking toward well-observed areas, and make optional SDM/SSDM workflows too heavy for a Streamlit app.

This is a deliberate methodological choice, not careless data loss.

## GBIF fetch policy

The GBIF fetch cap is the primary performance control. Working-set caps alone are not enough if downloading and cleaning thousands of records already makes the app lag.

Required behavior:

- Run a lightweight GBIF count query first.
- Show the total coordinate-record count before downloading occurrences.
- Let the user choose how many records to fetch.
- Fast survey planning should use a modest default fetch cap.
- Detailed analysis and Custom may allow larger caps.
- Do not default species mode to 10,000 records.
- Do not simply take the first N records when the total is larger than the cap. Prefer a representative retrieval strategy, such as distributed offsets, year-stratified retrieval, or another documented approach that reduces ordering bias.

Recommended starting defaults:

- Species Fast survey planning fetch cap: about 1,000 records.
- Species Detailed analysis fetch cap: about 3,000 records.
- Genus Fast survey planning fetch cap: about 3,000 records.
- Genus Detailed analysis fetch cap: about 10,000 records only when necessary and safe.

The UI should preserve and report the GBIF total count even when only a subset is fetched.

## Country filter UI

Do not require general users to know two-letter country codes.

Preferred UI:

- A searchable country selector using full English country names.
- `All countries` as an explicit option.
- Internally convert the selected country name to the ISO two-letter code required by GBIF.
- Remove the separate `Custom country code optional` text field from the main UI.

## Required data separation

Keep these concepts separate in code and UI:

- GBIF total count: number reported by GBIF before download.
- Fetched records: the representative subset actually downloaded.
- `occ_fetched`: cleaned fetched occurrence records.
- `occ_survey_selected`: records selected in Step 2 for observed-data candidate generation only.
- `occ_candidate_input`: spatially representative records used for observed-data candidates.
- `occ_sdm_qc_included`: records remaining after optional SDM-specific coordinate QC.
- `occ_sdm_train`: bias-reduced presence records used for optional SDM.

Do not use `occ_survey_selected` as the default SDM input.

For genus mode, use analogous working sets for observed richness hotspots and optional SSDM.

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

### SDM prediction extent

The SDM prediction extent is independent from the Step 2 survey-area rectangle.

Inside `Optional: Build SDM`, allow the user to define the SDM extent from the SDM QC-cleaned occurrence set using:

- buffer
- convex hull
- bounding box

### Environmental variables and collinearity

The main SDM UI should be simple for general users:

- Recommended variable set
- Custom variables

When Custom variables are selected, offer a simple recommended option to automatically remove highly correlated variables.

Keep VIF stepwise, thresholds, detailed diagnostics, and other technical controls under Advanced settings.

### Spatial validation

The main UI should use plain-language validation choices:

- Recommended spatial validation
- Fast random split
- Advanced

Hide `k for random k-fold`, `Checkerboard cell size (degrees)`, and similar technical settings unless Advanced is selected.

Hide `Maximum predict-map pixels` from the main UI and calculate a sensible automatic value from survey-planning mode.

## Candidate scoring

SDM predicted probability is optional model support used to re-rank the observed-data candidates.

Candidate ranking should support this structure:

`priority_score = observed_weight * occurrence_support_score + model_weight * model_support_score + optional bonuses`

Recommended default weights:

- observed-data weight: 0.7
- SDM/SSDM model weight: 0.3

If SDM/SSDM has not been run, rank by observed occurrence support only and show that model support is unavailable.

## Survey-planning mode UI

Prefer a simple mode selector rather than many technical controls by default:

- Fast survey planning, recommended default.
- Detailed analysis.
- Custom.

Fast survey planning should control both the GBIF fetch cap and the downstream working-set caps.

Technical controls should be hidden under advanced settings unless the user chooses Custom or Advanced.

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

Do not place coordinate QC in Step 2.

Do not automatically send the Step 2 survey-area selection into SDM.

Do not make the app depend on downloading, rendering, or modeling all available GBIF records before the user can access occurrence-based survey candidates.