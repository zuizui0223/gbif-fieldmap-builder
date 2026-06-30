# ACSP - Adaptive Complementarity-based Survey Prioritization

ACSP converts occurrence records into ranked, field-ready survey-site candidates. It is a field-survey decision tool, not an all-record SDM platform.

Development status: **alpha (0.1.0)**. Field validation and retrospective benchmark studies are still required before treating the rankings as a validated general method.

## Main workflow

The automatic app asks users to make only three decisions:

1. Enter a species or genus scientific name.
2. Optionally draw one or more realistic survey areas.
3. Optionally generate SDM/SSDM-supported candidates.

The app then shows two directly comparable outputs:

- **Candidates without SDM/SSDM**: observed occurrence and local habitat evidence.
- **Candidates with SDM/SSDM**: the same field-planning framework enriched with model support and model-high exploratory sites.

Every result map shows the complete eligible candidate pool. Recommended sites are highlighted with a green outline. Tables and downloads contain explicit site IDs, survey-area IDs, support scores, coordinates, reasons, and field-validation templates.

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

Macro-climate predictors are read from CHELSA V2.1 BIOCLIM 30-second Cloud-Optimized GeoTIFFs. Only raster windows intersecting the QC-derived SDM extent are read. The drawn observed-candidate survey areas do not automatically become the SDM extent.

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
    sdm_method_record,
)

recommended = recommend_candidates(candidates, per_area=3)
partition, reason = choose_spatial_partition(86, geographic_span_degrees=1.8)
models = {name: make_classifier(name) for name in DEFAULT_ENSEMBLE_ALGORITHMS}
```

Current Python APIs cover candidate quotas, classifier construction, equal-weight prediction, partition selection, ensemble-performance summaries, and method records. GBIF retrieval and raster orchestration remain app-level APIs for now.

## R package

An early base-R package is provided in [`r-acsp`](r-acsp).

```r
remotes::install_github("zuizui0223/acsp", subdir = "r-acsp")
library(acsp)

recommended <- acsp_recommend(candidates, per_area = 3)
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
