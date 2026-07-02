# ACSP - Adaptive Complementarity-based Survey Prioritization

ACSP converts occurrence records into ranked, field-ready survey zones. It is a field-survey decision tool, not an all-record SDM platform.

Development status: **alpha (0.1.0)**. Independent retrospective tests support cross-taxon prioritization of 10 km regional candidate zones over random same-pool selection. Exact-site accuracy, access, detection, abundance, and field efficiency remain unvalidated; see [HIERARCHICAL_VALIDATION_REPORT.md](HIERARCHICAL_VALIDATION_REPORT.md).

## Main workflow

The automatic app asks users to make only three decisions:

1. Enter a species or genus scientific name.
2. Optionally draw one or more realistic survey areas.
3. Optionally add broad-scale SDM/SSDM support.

The app shows one ranked **Recommended survey zones** table and map. Nearby candidate points are consolidated with a complete-link distance rule before final ranking, preventing both duplicate practical visits and long single-link chains. The original candidate points remain visible inside each recommended zone and remain available in the audit CSV for navigation, alternatives, and reproducibility. Optional SDM/SSDM updates the same zone rows with initial rank, model rank, rank change, agreement score, and a plain-language agreement class.

With built-in data, displayed coordinates are representative points for validated 10 km regional zones, not promises of an occupied or accessible exact location. The CSV exports this claim radius explicitly.

Zone ranking is density-neutral: it uses the strongest priority, observed, local-habitat, model, and access evidence within each practical zone rather than rewarding zones for containing more generated grid points. Exports identify the source candidate for every evidence maximum and state when a zone score combines evidence from different member points.

## One integrated evidence algorithm

The production workflow no longer maintains separate "with SDM" and "without SDM" candidate products. Every candidate receives one available-evidence score from observed support, local habitat similarity, optional macro SDM/SSDM support, survey gap, access, and field-validation learning. Missing model evidence is unavailable rather than zero: weights are renormalized for each candidate, so an SDM failure does not penalize otherwise supported sites.

The default configured weights are observed 0.35, local habitat 0.25, macro model 0.15, survey gap 0.10, access 0.10, and field validation 0.05. Agreement among observed/local/macro evidence adds a small consensus bonus. Strong cross-scale divergence is retained as an explicit diagnostic and adds a small exploration bonus only to exploratory candidate types. Zone score is 90% the strongest integrated candidate score plus 10% evidence agreement; candidate count and separate component maxima are not summed into the score.

Trip duration is not fixed by the user. Internally, ACSP builds feasible one- through five-day alternatives, charges each added zone for its minimum insertion cost in the hub-return route, and chooses the knee of the resulting value-versus-duration curve. The primary screen shows only the selected practical zone set and a short reason; the curve remains reproducible diagnostic evidence.

Separate drawn survey areas are treated as separate daily logistics units. A single field day never combines different islands/areas, and each area receives a candidate before additional same-area sites are added. Island-local travel uses a local area hub; ferry and flight schedules are not yet modeled and are explicitly reported as unverified rather than converted into road distance.

When several rectangles are drawn, ACSP treats them as independent survey areas. Candidate generation and recommendation quotas run separately in each area, preventing record-rich regions from taking every recommendation.

## Occurrence and local candidate processing

- GBIF scientific-name matching and paginated occurrence retrieval.
- Coordinate cleaning, exact deduplication, and representative working subsets.
- Conservative automatic removal of remote minor clusters from SDM input.
- Flexible latitude/longitude detection for the retained detailed CSV workflow code.
- Occurrence-supported candidate ranges.
- App-provided GSI terrain for Japan.
- Local habitat candidates using elevation, slope, aspect, roughness, and topographic position.
- Habitat-match, Survey-gap, and Environmental-test candidates.
- Full candidate-pool CSV and field-validation CSV exports.

Observed candidate generation remains available without SDM.

## Automatic SDM ensemble

The automatic species SDM currently fits four probability-producing model families:

1. Logistic regression
2. Random forest
3. ExtraTrees
4. Gradient boosting

Final suitability is the equal-weight mean of the four predicted probabilities. ACSP also reports the best individual model; it does not silently replace the ensemble with that model.

After prediction, ACSP uses the SDM in two distinct ways:

- Existing occurrence/local candidates receive suitability as model support. Candidates with both strong observed support and strong model support receive a transparent agreement bonus and can move upward in the recommendation.
- High-suitability cells away from known records and existing candidates are added as spatially separated `model-only exploratory` sites. When at least three recommendation slots are available, the best such site is retained for field validation without replacing the observed candidate workflow.

The same logic applies to genus mode: observed richness hotspots are re-ranked by SSDM support, while spatially separated SSDM-high cells are added as model-only richness exploration sites.

The one-click SDM/SSDM path derives five macro-climate predictors from cached NASA POWER MERRA-2 1981-2010 normals. Its native climate grid is about 0.5-degree latitude by 0.625-degree longitude and is interpolated only to draw and evaluate the prediction grid; interpolation does not create finer climate information. This fast macro filter is combined with the separate high-resolution local terrain/habitat candidate workflow. Advanced/manual SDM keeps the existing WorldClim/CHELSA choices. The drawn observed-candidate survey areas do not automatically become the SDM extent.

Automatic validation uses occurrence count and minimum geographic span:

| Condition | Validation design |
|---|---|
| fewer than 15 presences | jackknife |
| fewer than 30, or minimum extent span below 2 degrees | random 75/25 holdout |
| 30-49 presences | random 5-fold CV |
| 50 or more presences with adequate span | four-quadrant spatial block CV |

The app exports:

- AUC and warning for every ensemble member
- best individual model and AUC
- ensemble members and weights
- source, excluded, and retained occurrence counts
- background-point count
- partition method and selection reason
- retained environmental variables
- environment source and independent prediction extent
- manuscript-ready methods text

High AUC from random partitioning is explicitly flagged as potentially optimistic.

## Genus and SSDM

Genus names route to the observed-richness/SSDM workflow. Observed richness candidates work without SSDM. The optional SSDM stacks capped per-species SDMs over a shared prediction grid and reports per-species model status, AUC, partition, retained variables, and predicted richness.

## Python package

The installable Python distribution is named `acsp-survey`; its import package is `acsp`. A normal install includes the reusable package, the Streamlit application dependencies, and the app support modules.

```bash
python -m pip install .
```

```python
from acsp import (
    DEFAULT_ENSEMBLE_ALGORITHMS,
    choose_spatial_partition,
    make_classifier,
    recommend_candidates,
    recommend_survey_zones,
    integrated_candidate_scores,
    spatial_block_recovery_validation,
    sdm_method_record,
)

recommended = recommend_candidates(candidates, per_area=3)
recommended_zones = recommend_survey_zones(candidates, per_area=3)
scored = integrated_candidate_scores(candidates)
island_extent = (139.30, 34.60, 139.50, 34.85)  # west, south, east, north
recommended_in_extent = recommend_candidates(candidates, per_area=3, extent=island_extent)
partition, reason = choose_spatial_partition(86, geographic_span_degrees=1.8)
models = {name: make_classifier(name) for name in DEFAULT_ENSEMBLE_ALGORITHMS}
```

`spatial_block_recovery_validation()` supports repeated random spatial-block holdout. Its candidate-builder callback receives training occurrences only; known-location candidates and direct occurrence/distance-derived score components are excluded before Top-k recovery is compared with random Top-k draws from the same candidate pool.

Current Python APIs cover integrated evidence scoring, spatial-block recovery validation, candidate quotas, deterministic survey-zone aggregation, SDM rank/agreement diagnostics, classifier construction, equal-weight prediction, partition selection, ensemble-performance summaries, and method records. GBIF retrieval and raster orchestration remain app-level APIs for now.

## R package

An early base-R package is provided in [`r-acsp`](r-acsp).

```r
remotes::install_github("zuizui0223/acsp", subdir = "r-acsp")
library(acsp)

recommended <- acsp_recommend(candidates, per_area = 3)
zones <- acsp_zones(candidates)
recommended_in_extent <- acsp_recommend(candidates, extent = c(139.30, 34.60, 139.50, 34.85))
partition <- acsp_sdm_partition(86, geographic_span_degrees = 1.8)
algorithms <- acsp_default_algorithms()
```

For a local clone, use `remotes::install_local("r-acsp")`. The R package currently mirrors recommendation quotas, partition selection, default ensemble specification, and method-record generation. Full raster SDM/SSDM fitting is a planned package extension.

## Install and run the app

Install the Python distribution, then launch the bundled Streamlit app with its command-line entry point:

```bash
python -m pip install .
acsp-fieldmap
```

For development from a source checkout, this remains equivalent:

```bash
python -m streamlit run gbif_fieldmap_builder_app.py
```

Streamlit Community Cloud:

- Repository: `zuizui0223/acsp`
- Branch: `main`
- Main file: `gbif_fieldmap_builder_app.py`

## Repository structure

- `gbif_fieldmap_builder_app.py`: Streamlit application and raster/GBIF orchestration
- `acsp/`: reusable Python package and packaged app command
- `r-acsp/`: reusable R package
- `acsp_discover.py`: retained survey-protocol and legacy set-selection methods
- `test_*.py`: regression and package tests
- `CITATION.cff`: software citation metadata
- `.github/workflows/package-checks.yml`: Python package, app-installation, and R package CI

## Validation and publication path

The method should be benchmarked against random sampling, occurrence-only ranking, SDM-high ranking, and environmental-representativeness baselines. Recommended evaluation metrics include new-population recovery, discoveries per field day, environmental coverage, geographic independence, and improvement after field feedback.

The package now exposes `stratified_random_taxa()`, `spatial_block_candidate_benchmark()`, `multi_taxon_weight_benchmark()`, and `calibrate_candidate_weights()` for reproducible weight studies. The intended design samples taxa across occurrence-count strata with a recorded seed, rebuilds candidates from training spatial blocks only, tunes weights on calibration taxa, and reports performance on completely unseen taxa against same-pool random Top-k, local-only, macro-model-only, and the current default weights. Failed taxa remain in the audit table and are not silently replaced. Retrospective GBIF recovery does not identify accessibility or detectability weights; those require prospective field-validation records.

`benchmark_random_species_models.py` provides the separate model-accuracy benchmark: seeded random taxa, repeated spatial-block holdout, four individual algorithms plus the ensemble, auditable predictions, ROC-AUC, PR-AUC, Brier score, log loss, TSS, calibration, Boyce-style rank correlation, taxon bootstrap intervals, and taxon-held-out ensemble calibration. `benchmark_izu_random_taxa.py` remains the separate four-island candidate-recovery benchmark. The prospective field protocol is in [FIELD_VALIDATION_IZU.md](FIELD_VALIDATION_IZU.md).

For a reproducible paper or report:

1. archive the exact GitHub release used;
2. export the candidate pools and SDM method CSV;
3. report automatic QC exclusions and partition warnings;
4. retain field-validation outcomes; and
5. cite the archived release using `CITATION.cff`.

GitHub Actions runs on every push, pull request, and manual dispatch. It tests the Python package across Python 3.10–3.12, builds and installs a wheel in an isolated environment, checks the packaged Streamlit command, and runs `R CMD check` for `r-acsp`. PyPI, CRAN, and DOI/Zenodo publication require final author metadata, release review, and repository-owner credentials.

## Current limitations

- Straight-line map links do not model roads, ferries, cliffs, permissions, or trail time.
- Presence-only SDM AUC can be optimistic, especially under random holdout.
- Local access and detectability require field verification.
- App-provided NDVI, land cover, and stronger all-taxa survey-effort layers remain future work.
- The R package does not yet expose full raster SDM/SSDM fitting.

## License

MIT. See [LICENSE](LICENSE).
