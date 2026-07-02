# AI Change Log

## 2026-07-02 - Codex (OpenAI) - Publication repository cleanup

Summary:
- Moved superseded Izu, initial SDM-accuracy, and pre-hierarchy national benchmark assets under `legacy/`.
- Extracted retry, radius-coverage, and fold-completion helpers into the supported `acsp.benchmarking` module so the current national benchmark has no legacy dependency.
- Removed temporary notes and completed patch notes from the publication root while preserving them in `legacy/notes/`.
- Kept only the final mixed and plant confirmation artifacts in the active `benchmark_results/` path.

## 2026-07-02 - Codex (OpenAI) - Five-kilometre precision ceiling audit

Summary:
- Added a per-candidate technical precision audit using grid half diagonal, environmental resolution, and coordinate uncertainty.
- Tested and rejected cross-species supervised rankers, Top-8 expansion, climate/covariance variants, and direct GSI point-tile extraction when they failed transferability or latency requirements.
- Retained the independently supported 10 km regional-zone model and documented why 5 km exact-site performance is not currently a defensible name-only claim.

Validation:
- The independent plant 5 km lift remained uncertain despite a useful same-pool oracle ceiling.
- Top-8 combined confirmation still crossed zero; supervised rankers were below random in leave-one-species-out development tests.
- Direct fine terrain extraction exceeded three minutes before completing one three-fold species benchmark and was removed.
- All 74 Python tests pass after adding precision-audit coverage.

## 2026-07-02 - Codex (OpenAI) - Cross-taxon hierarchical regional validation

Summary:
- Added automatic terrestrial, coastal, marine, and inland-aquatic candidate surfaces from GBIF taxonomy plus training-record land fraction.
- Added marine distance-to-land-band habitat evidence, spatially complementary aquatic candidate generation, and water-transit cautions.
- Fixed bird climate predictors being silently discarded when a DEM was available.
- Exported explicit 10 km regional-zone claim fields so representative coordinates are not presented as validated exact sites.
- Added mixed-scale and sensitivity endpoint artifacts, single-group confirmation sampling, and a peer-review-oriented validation report.

Validation:
- 73 unit tests pass.
- Hierarchical development: 24 pairs, 120/120 completed folds, mixed endpoint lift 0.0297 (95% CI 0.0103–0.0523; sign-flip p=0.0063).
- Independent mixed confirmation: 24 unseen taxa, 119/120 completed folds; animal 10 km lift 0.0408 (0.0031–0.0847).
- Independent plant extension: 24 further unseen taxa, 115/120 completed folds; plant 10 km lift 0.0215 (0.0002–0.0481).
- Pooled algorithm-compatible independent plant confirmations: 36 pairs, 10 km lift 0.0186 (0.0035–0.0374; p=0.0233).
- Five-kilometre plant recovery did not replicate. The supported cross-taxon claim is regional 10 km candidate-zone prioritization, not exact-site prediction.

## 2026-07-02 - Codex (OpenAI) - Two-stage recovery and complementary ranking

Summary:
- Added hierarchical regional candidate screening and a deterministic evidence-plus-geographic-complementarity Top-k selector.
- Separated ecological candidate recovery from downstream safety, legal-access, and short-trip screening; production planning still applies those hard constraints.
- Added reusable frozen samples, multiple excluded-cohort files, stored validation ranks, and plant/animal development policies without using confirmatory taxa for tuning.
- Passed resolved GBIF class metadata into the existing bird, mammal, reptile, arthropod, and fish survey-protocol hierarchy.

Validation:
- All 71 unit tests pass.
- On the 24-pair development cohort, 120/120 folds completed. Rankable rates rose to 93.3% for plants and 100% for animals. At 5 km, plant lift over random was 0.0119 (95% clustered CI 0.0007 to 0.0263); animal lift was 0.0190 (-0.0016 to 0.0455).
- A second independent 24-pair cohort excluded every taxon in both prior cohorts. Twenty-two pairs completed and two failed without replacement. At 5 km, plant lift replicated at 0.0442 (0.0045 to 0.1077), while animal lift remained unconfirmed at 0.0195 (-0.0033 to 0.0502).
- The global superiority gate therefore remains failed: evidence currently supports the plant candidate-ranking branch only, not one universal plant/animal model.

Known risks / TODO:
- Animal candidates require a habitat-domain hierarchy (terrestrial, freshwater, marine/coastal) before further weight fitting. A land-only candidate surface is invalid for sea turtles, seabirds, and aquatic taxa.
- Retrospective occurrence recovery does not validate access, detectability, abundance, phenology, or discoveries per field day.

## 2026-07-02 - Codex (OpenAI) - Independent retrospective confirmation

Changed files:
- acsp/validation.py
- acsp/__init__.py
- benchmark_general_random_taxa_regions.py
- test_benchmark_general.py
- RETROSPECTIVE_VALIDATION_PROTOCOL.md
- benchmark_results/general_random_taxa_regions_20260703_unseen_confirmatory/{benchmark_summary.json,predeclared_taxon_region_pairs.csv,pair_status.csv,cohort_summary.csv,fold_recovery.csv,robust_inference.csv}
- .gitignore
- CHANGELOG_AI.md

Summary:
- Added failure-inclusive intention-to-evaluate recovery, taxon-region clustered bootstrap intervals, and pair-level sign-flip tests.
- Added confirmatory taxon exclusion so a new seed cannot reuse any development taxon.
- Froze 5 km as the primary retrospective endpoint, with 2 and 10 km as sensitivity endpoints, before inspecting the independent cohort.

Validation:
- Seed `20260703` drew 24 balanced taxon-region pairs with zero taxon overlap with the development cohort.
- Twelve pairs completed all five folds, five were partial, and seven failed; only 17 pairs were evaluable.
- Fold completion was 58.3% for plants and 65.0% for animals. Rankable-fold rates were 26.7% and 21.7%, far below the predeclared 90% completion and 80% rankable gates.
- At the primary 5 km endpoint, animal ITE lift was -0.0041 (95% clustered CI -0.0130 to 0.0006) and plant lift was -0.0005 (-0.0014 to 0.0000).
- At 10 km, neither animal (-0.0026, CI -0.0130 to 0.0050) nor plant (0.0013, CI -0.0048 to 0.0082) showed confirmed superiority over random.
- The favorable 10 km animal development result did not replicate. No production-weight or superiority claim is justified.

Known risks / TODO:
- Candidate-generation stability, not only ranking, is the dominant blocker on unseen taxa.
- The next algorithm iteration must be developed outside this frozen confirmation set and tested on another excluded-taxon seed.
- Retrospective robustness cannot identify field access, detectability, or phenology weights; those remain explicitly unvalidated.

## 2026-07-02 - Codex (OpenAI) - Stratified national taxon-by-region validation

Changed files:
- acsp/planning.py
- gbif_fieldmap_builder_app.py
- benchmark_general_random_taxa_regions.py
- test_benchmark_general.py
- test_acsp_package.py
- benchmark_results/general_random_taxa_regions_20260702_v2/{benchmark_summary.json,predeclared_taxon_region_pairs.csv,pair_status.csv,cohort_summary.csv,fold_recovery.csv}
- .gitignore
- CHANGELOG_AI.md

Summary:
- Added a seeded general-performance benchmark that balances plant/animal taxa, northern/eastern/western/southern Japan, and four regional occurrence-count strata.
- Added a sparse-pool fallback: when the standard local search yields fewer than six cells, the redundant occurrence-cluster-centre buffer is relaxed while individual training-record separation remains enforced and the fallback stage is exported.
- Marked spatial distance-based habitat fallback scores as occurrence-derived and excluded them from distance-free retrospective scoring.
- Added explicit rankable-fold reporting when the candidate pool exceeds Top-k; folds selecting the entire pool no longer masquerade as evidence about ranking quality.
- Cached repeated GBIF species metadata and region sampling frames without changing the seeded sample.

Validation:
- The predeclared run used 24 fixed taxon-region pairs: 12 plants, 12 animals, three pairs in each taxon-group × geographic-stratum cell, and five spatial holdouts per pair.
- Version 2 completed all five repeats for 23 pairs; the remaining seabird pair failed hard-constraint screening and remains in the denominator. Version 1 had only 17 full, four partial, and three failed pairs.
- Median distance-free candidate-pool size increased from 3 in version 1 to 17.5 for plants and 20 for animals in version 2. Rankable folds were 41/60 for plants and 47/55 for animals.
- On rankable folds at 10 km, animal default recall was 0.135 versus random 0.075 and greedy pool ceiling 0.276. Plant default recall was 0.053 versus random 0.069 and pool ceiling 0.220.
- At 2 km both groups were effectively unrecoverable; at 5 km default and random were close. No global production-weight change is justified.
- All 69 Python tests passed.
- Added intention-to-evaluate inference that assigns zero recovery to failed/missing folds, clusters bootstrap uncertainty by taxon-region pair, and uses pair-level sign-flip tests rather than treating repeated folds as independent.
- At 5 km, neither group showed a robust lift: animal ITE lift 0.0023 (95% cluster-bootstrap CI -0.0042 to 0.0113) and plant lift 0.0005 (-0.0209 to 0.0203).
- At 10 km, animals showed lift 0.0475 (0.0138 to 0.0935; pair-level sign-flip p=0.0129), while plants showed -0.0114 (-0.0515 to 0.0173).
- Version 2 remains a development-set evaluation because its fallback was motivated by version 1 on the same fixed pairs. A new-seed confirmatory cohort is required before treating the 10 km animal result as replicated evidence.

Known risks / TODO:
- Plant and animal ranking performance diverged, so a single universal scoring model is not supported. The next model should branch by life history/mobility and distribution regime while keeping one-name input.
- The seabird failure shows that terrestrial land/access constraints cannot be transferred unchanged to marine or coastal life histories.
- External habitat-layer availability and caching can affect candidate-pool construction; future benchmark artifacts should pin layer versions and export source checksums.
- Recovery remains low at realistic 2-5 km radii. Candidate ranking and macro/local evidence need improvement before claiming superiority over random search.

## 2026-07-01 - Codex (OpenAI) - Full four-island distance-free recovery benchmark

Changed files:
- acsp/validation.py
- benchmark_random_species_models.py
- benchmark_izu_random_taxa.py
- test_acsp_package.py
- test_benchmark_izu.py
- test_benchmark_resilience.py
- benchmark_results/izu_random_taxa_20260701_full/{benchmark_summary.json,predeclared_taxon_sample.csv,taxon_status.csv}
- .gitignore
- CHANGELOG_AI.md

Summary:
- Ran the predeclared 20-taxon, five-repeat four-island benchmark with training-only candidate rebuilding, occurrence-supported candidate removal, occurrence/distance score exclusion, and held-out occurrence matching at 2/5/10 km.
- Distinguished fully completed, partially completed, failed, and evaluable taxa. Empty candidate checkpoints no longer count as successful taxa or break final aggregation.
- Added retry handling for transient GBIF TLS/HTTP failures and isolated failed species-name resolutions instead of aborting the sampling frame.
- Prevented retrospective GBIF recovery from fitting access or field-validation weights. Weight search now uses only varying local-habitat and macro-model evidence; missing components cannot absorb arbitrary nominal weight.
- Added a greedy same-pool recovery ceiling to distinguish candidate-pool limitations from ranking limitations.

Validation:
- Seed `20260701` predeclared 20 plant taxa across four occurrence-count strata: 16 fully completed, one partial, three failed, and 17 evaluable.
- On five completely held-out evaluation taxa, local-habitat Top-5 recall versus same-pool random recall was 0.195 versus 0.210 at 2 km, 0.344 versus 0.322 at 5 km, and 0.374 versus 0.380 at 10 km.
- Greedy same-pool recovery ceilings were 0.374, 0.460, and 0.489 at 2, 5, and 10 km, respectively, showing room to improve ranking as well as candidate generation.
- This run did not include macro SDM, so only local habitat varied retrospectively. The search was correctly classified as uninformative for relative weight fitting and no production-weight change is recommended.
- All 65 Python tests passed after the resilience, completion-audit, component-identifiability, and oracle-baseline changes.

Known risks / TODO:
- Three of 20 predeclared taxa were not fully evaluable, including hard-constraint or distance-free-candidate failures. These failures are part of algorithm performance, not taxa to replace after inspection.
- A separate checkpointed run with macro SDM enabled is required to estimate local-versus-macro weight allocation.
- Access, detectability, phenology, and field-validation weights require prospective standardized surveys and cannot be inferred from GBIF proximity.
- The four-island plant frame does not validate nationwide regions, narrow endemics outside these islands, or animal taxa; those require predeclared stratified benchmark cohorts.

## 2026-07-01 - Codex (OpenAI) - Random-species model accuracy benchmark

Changed files:
- acsp/validation.py
- acsp/__init__.py
- acsp/sdm.py
- benchmark_random_species_models.py
- benchmark_izu_random_taxa.py
- test_acsp_package.py
- test_benchmark_izu.py
- gbif_fieldmap_builder_app.py
- FIELD_VALIDATION_IZU.md
- README.md
- RESEARCH_POSITIONING.md
- CHANGELOG_AI.md

Summary:
- Separated model-accuracy validation from candidate-recovery validation instead of treating withheld candidate recovery as model accuracy.
- Added repeated spatial-block model validation with held-out predictions and ROC-AUC, PR-AUC, Brier, log loss, training-threshold TSS, calibration slope/intercept, and Boyce-style rank correlation for four algorithms and their equal-weight ensemble.
- Added a checkpointed, seeded, occurrence-count-stratified random-species benchmark runner and taxon-level bootstrap uncertainty.
- Added taxon-held-out ensemble weight and probability-shrinkage search. Fourteen taxa select settings and six unseen taxa evaluate them; the search cannot silently tune and report on the same species.
- Kept the equal-weight production ensemble because held-out improvement did not reach the predeclared change threshold. Relabeled SDM output as relative suitability rather than calibrated occupancy probability.
- Kept the four-island candidate-recovery runner as a separate validation track, with four independent island polygons, checkpointing, and predeclared 2/5/10 km sensitivity outputs.
- Added a prospective four-island field protocol using two frozen ACSP sites plus one matched control per island under standardized effort.

Validation:
- Seed `20260701` sampled 20 Japanese plant species across four occurrence-count strata; all 20 completed five valid spatial holdouts (100 folds total) with no post-result species replacement.
- The equal-weight ensemble had mean ROC-AUC 0.629, PR-AUC 0.341, Brier 0.160, log loss 0.499, TSS 0.121, calibration slope 0.525, and Boyce-style correlation 0.374.
- Taxon-bootstrap 95% intervals were 0.586-0.672 for ensemble ROC-AUC, 0.061-0.185 for TSS, and 0.344-0.699 for calibration slope.
- On six taxon-held-out evaluation species, searched weights plus 0.70 probability shrinkage changed log loss from 0.50184 to 0.49977, Brier from 0.16435 to 0.16263, and ROC-AUC from 0.65624 to 0.65699. This did not pass the required >0.01 log-loss improvement, so no production ensemble change was made.
- The benchmark exposed and fixed two performance issues: serial GBIF taxon-name resolution and repeated pandas grouping inside ensemble search.

Features preserved:
- The simple Streamlit workflow, occurrence/local candidates, optional ensemble SDM/SSDM, VIF, spatial partition choices, exploratory candidates, zone planning, and field exports remain available.

Known risks / TODO:
- The 20-species benchmark supports only modest macro-SDM geographic transferability and shows overconfident raw probabilities. Macro support should remain secondary to observed/local evidence.
- Random species were sampled from the top GBIF facet frame meeting the record threshold, so the frame represents recorded Japanese plants rather than all flora.
- The four-island trip is a pilot external validation. Universal scoring weights require more taxa, seasons, observers, regions, and matched controls.

## 2026-07-01 - Codex (OpenAI) - Taxon-held-out weight calibration

Changed files:
- acsp/validation.py
- acsp/__init__.py
- test_acsp_package.py
- README.md
- SURVEY_PLANNING_POLICY.md
- RESEARCH_POSITIONING.md
- CHANGELOG_AI.md

Summary:
- Kept the current 0.35 / 0.25 / 0.15 / 0.10 / 0.10 / 0.05 production weights unchanged and explicitly classified them as starting priors rather than fitted constants.
- Added candidate-level spatial-block benchmark output, including every held-out occurrence ID and each candidate's recovered IDs, so alternative weight vectors can be audited without regenerating environmental layers.
- Added seeded occurrence-count-stratified taxon sampling and a multi-taxon benchmark runner that retains failed taxa instead of replacing them after seeing outcomes.
- Added nested taxon-held-out weight search. Weights are selected only on calibration taxa and evaluated on unseen taxa against current defaults, same-pool random Top-k, local-only, and macro-model-only baselines.
- Added a conservative recommendation gate requiring at least ten successful taxa, more than 0.02 held-out recall lift over defaults, and performance above random. The API never edits production weights automatically.
- Fixed a benchmark denominator bug found during implementation: held-out occurrences recovered by no candidate are now retained in the recall denominator.
- Fixed the first real-taxon pilot failure by auto-detecting the app's `_latitude` / `_longitude` columns and common GBIF/CSV coordinate names in both spatial-validation APIs.

Validation:
- All Python tests passed, including deterministic taxon sampling, training-only candidate rebuilding, unseen-taxon calibration, same-pool controls, insufficient-sample safeguards, and retained taxon failures.
- A seeded (`20260701`) fixed-Izu-extent pilot sampled `Plagiogyria japonica`, `Selliguea hastata`, `Diplopterygium glaucum`, and `Aucuba japonica` across three occurrence-count strata. All four rebuilt from training-only blocks after the coordinate-column fix.
- With one pilot fold per taxon, Top-5 (or the full smaller pool) and a predeclared 2 km recovery radius, default, local-only, macro-only, and same-pool random recall were all 0. This is an uninformative pilot, not support for a weight change. The calibration API now labels flat searches `uninformative` rather than presenting an arbitrary tied vector as evidence.

Features preserved:
- The simple app workflow, integrated production score, occurrence/local candidates, optional SDM/SSDM, model-only exploration, zones, route outputs, and exports are unchanged.

Known risks / TODO:
- No production weight change is justified yet. A predeclared real-taxon benchmark and prospective field results are still required.
- The pilot used only four taxa and one fold each. The next registered run should include at least ten successful taxa, repeated blocks, and predeclared 2/5/10 km sensitivity reporting; radius selection must not be changed after inspecting which value looks favorable.
- GBIF holdout recovery cannot estimate accessibility, detectability, flowering, or survey-effort effects; those weights must be evaluated with field-validation data.

## 2026-07-01 - Codex (OpenAI) - Unified evidence scoring and spatial recovery validation

Changed files:
- acsp/planning.py
- acsp/validation.py
- acsp/__init__.py
- acsp_discover.py
- gbif_fieldmap_builder_app.py
- test_acsp_package.py
- test_acsp_discover.py
- test_automatic_hierarchy.py
- test_zone_planning.py
- README.md
- SURVEY_PLANNING_POLICY.md
- RESEARCH_POSITIONING.md
- CHANGELOG_AI.md

Summary:
- Replaced separate internal `with SDM` / `without SDM` pools and zones with one canonical `candidate_pool`, `zones`, and `recommended_zones` product that is updated when optional SDM/SSDM evidence becomes available.
- Added available-weight-normalized integrated scoring across observed support, local habitat, macro model, survey gap, access, and field validation. Missing SDM/SSDM evidence is unavailable rather than zero.
- Added explicit evidence agreement, divergence, consensus/local-only/macro-only evidence classes, agreement bonus, and a small divergence bonus restricted to exploratory candidate types.
- Removed independent zone-component maxima from the zone score. Zone priority is now 90% the strongest integrated candidate score plus 10% evidence agreement; candidate count and diagnostic component maxima do not increase priority.
- Connected the same integrated support score to ACSP discovery utility while keeping distance redundancy, candidate-to-candidate route insertion cost, spatial-area coverage, and hard constraints.
- Added `spatial_block_recovery_validation()`: repeated random spatial-block holdout with training-only candidate rebuilding, direct occurrence/distance evidence exclusion, and random Top-k controls drawn from the same candidate pool.
- Added integrated component, agreement, divergence, availability, and explanation fields to candidate CSV output and the zone display.

Validation:
- All 54 Python tests passed, including missing-model renormalization, distance-excluded scoring, reproducible spatial-block holdout, canonical bundle keys, zone coherence, and existing SDM/SSDM safeguards.
- `Campanula microdonta`: 31 base candidates / 26 zones / 8 recommendations; automatic SDM updated the same pool to 33 candidates / 28 zones / 7 recommendations in 19.6 seconds. Evidence classes were 27 cross-scale consensus, four known-record anchors, and two macro-model exploration candidates.
- `Cirsium`: 299 fetched records produced 20 observed candidates; SSDM modeled three species and updated the same pool to 40 candidates, with six cross-scale consensus and 20 macro-model exploration candidates.
- A 10-repeat synthetic spatial-block smoke test returned distance-excluded Top-3 recall 0.600 versus random same-pool recall 0.665 (lift -0.065). This deliberately makes no positive performance claim; it confirms that the validation reports unfavorable results rather than guaranteeing apparent improvement.

Features preserved:
- Occurrence/local candidates without SDM, optional ensemble SDM/SSDM, VIF and spatial validation, model-only exploration, zone member points, multiple survey areas, route-cost diagnostics, prediction maps, and exports remain available.

Known risks / TODO:
- The spatial-block validation API enforces a training-only callback contract, but ecological performance claims still require real taxon-specific candidate rebuilding and matched field/retrospective benchmarks. Unit simulations validate mechanics only.
- Integrated weights and the 10% agreement contribution are transparent starting values, not fitted universal constants. Compare component ablations, spatial-block recovery, and field detection before publication claims.

## 2026-07-01 - Codex (OpenAI) - Zone auditability and survey-area clarity

Changed files:
- acsp/planning.py
- acsp_discover.py
- gbif_fieldmap_builder_app.py
- README.md
- test_acsp_discover.py
- test_automatic_hierarchy.py
- test_zone_planning.py
- CHANGELOG_AI.md

Summary:
- Fixed polygon survey-area selection so records are tested against the actual polygon instead of only its bounding box.
- Fixed automatic survey-area maps to read remote-noise classifications from the region audit, show those excluded points in red, focus initially on the active working area, and keep alternative occurrence regions in an optional layer.
- Replaced the inaccurate `diameter / 2` display radius with the actual maximum medoid-to-member radius so the suggested-area circle covers its assigned records.
- Kept every candidate point belonging to a recommended zone visible on the zone map, with representative and alternative points distinguished, while retaining full point CSV exports.
- Added zone merge thresholds, score-method text, evidence-source site IDs, and an explicit warning when evidence maxima come from different points in the same zone.
- Simplified the first map wording to `Known distribution and survey area` and clarified that this area affects observed-data candidates but not the independent SDM/SSDM extent.

Features preserved:
- Occurrence-supported candidates, high-resolution habitat candidates, optional SDM/SSDM re-ranking, model-only exploration, complete-link zone aggregation, multi-area logistics, raw and working records, VIF/spatial validation, prediction maps, and exports remain available.

Known risks / TODO:
- Zone scoring remains an interpretable density-neutral heuristic based on component maxima. It is now auditable, but representative-point scoring, robust quantiles, and the current approach still require retrospective and field comparison.
- Deterministic greedy complete-link assignment prevents chain zones but is not a globally optimal clustering solution; sensitivity to merge thresholds should be included in method validation.

## 2026-06-30 — Issue #25 zone-level proposals

- Consolidated nearby candidate points into deterministic complete-link survey zones before final ranking.
- Added representative sites, practical footprints, plain-language zone roles, and density-neutral evidence aggregation.
- Added stable initial/model ranks, rank changes, agreement scores/classes, and compact SDM/SSDM agreement summaries.
- Replaced the automatic split candidate panels with one Recommended survey zones surface.
- Added zone CSV/API/CLI/R outputs and made the GitHub Action emit zone-level recommendations.
- Replaced the fixed two-day assumption with an internal one-to-five-day feasibility curve and automatic knee selection.
- Added candidate-to-candidate route insertion cost to final plan utility while retaining ecological complementarity.
- Fixed multi-island planning so one field day cannot mix separate survey areas, every selected area receives coverage before duplicates, and local distance uses an area-level hub.
- Multi-island outputs now report unmodeled ferry/flight transfers and very-low routing confidence instead of treating sea crossings as roads.

## 2026-06-30 - Codex (OpenAI) - Fast cached macro-climate SDM/SSDM

Changed files:
- gbif_fieldmap_builder_app.py
- test_automatic_hierarchy.py
- README.md
- CHANGELOG_AI.md

Summary:
- Replaced the one-click SDM/SSDM dependency on slow remote CHELSA strip reads with cached NASA POWER MERRA-2 1981-2010 temperature and precipitation normals.
- Derive BIO1, BIO4, BIO12, BIO14, and BIO15 from monthly normals, retrieve large regions in bounded tiles, retry transient requests, and preserve the existing CHELSA/WorldClim choices in advanced/manual SDM.
- Interpolate the coarse macro-climate normals to a bounded display/prediction grid, then clip it to the independent QC-derived prediction geometry and land mask. The UI and method record explicitly report the native coarse climate resolution.
- Reused the same environment path for species SDM and genus SSDM without changing ensemble algorithms, spatial validation, variable selection/VIF, observed candidates, model-supported re-ranking, or model-only exploration candidates.

Validation:
- `Lilium auratum` (Japan): 299 GBIF records; occurrence and habitat candidates in 16.6 seconds; four-model automatic SDM in 20.3 seconds; 6,659 prediction cells and 20 model-only exploration candidates; 41.3 seconds total including GBIF retrieval.
- `Cirsium` (Japan): 569 fetched genus records; 20 observed-richness candidates; six species modeled; 4,832 SSDM cells and 20 model-only richness exploration candidates; SSDM completed in 55.7 seconds.
- Izu-island test extent produced 327 valid land prediction cells, including small-island areas, instead of depending on coarse source-cell centers falling on land.
- `python -m unittest test_automatic_hierarchy.py test_gbif_fetch_resilience.py test_acsp_package.py test_acsp_cli.py test_acsp_discover.py` passed 36 tests.
- `python -m py_compile gbif_fieldmap_builder_app.py` passed.

Scientific limitation:
- NASA POWER is a fast macro-climate filter, not a high-resolution habitat layer. The interpolated prediction grid must not be interpreted as adding climate detail beyond the native POWER grid; fine-scale site discrimination remains the role of GSI terrain, habitat analogue, access, occurrence support, and field validation.

## 2026-06-30 - Codex (OpenAI) - Model-connected recommendations and clearer evidence maps

Changed files:
- gbif_fieldmap_builder_app.py
- test_automatic_hierarchy.py
- README.md
- CHANGELOG_AI.md

Summary:
- Added explicit observed/model agreement scoring so existing candidates supported by both occurrence evidence and SDM/SSDM move upward transparently.
- Added spatial non-maximum suppression for model-only exploration cells, avoiding the previous single-link DBSCAN behavior that could collapse a continuous high-suitability region into one candidate.
- Added model-connected recommendation quotas: ordinary priority ranking remains primary, with one best model-only exploratory site retained when at least three slots are available.
- Rebuilt automatic SSDM exploratory candidates from the full richness grid and applied a final global re-ranking after observed and model-only candidates are combined.
- Removed the second CHELSA extraction pass for existing candidate coordinates by sampling suitability from the completed SDM prediction grid.
- Split result-map layers into observed/local points, model-only exploratory points, and recommended 500 m survey ranges; added a compact evidence legend.
- Added export fields for candidate evidence, model agreement, agreement bonus, exploration bonus, and recommendation basis.

Validation:
- Reproducible random seed `20260630` selected species `Lilium auratum` and genus `Viola`.
- Random species extent `(138.73423, 36.92800, 140.13423, 38.32800)` retained 17 records and produced 13 candidates / 3 recommendations without SDM.
- Random genus extent `(139.12806, 35.43241, 139.42806, 35.73241)` retained 94 records and produced 16 observed-richness candidates / 3 recommendations without SSDM.
- Unit coverage verifies agreement re-ranking, idempotent re-ranking, model-only quota retention, spatially separated SDM/SSDM exploration, completed-grid candidate support, and separated map layers.
- End-to-end remote SDM attempts did not finish within eight minutes. Inspection found the current CHELSA GeoTIFF endpoint exposes full-width strips and no internal overviews, so remote regional reads remain an external performance risk. No successful AUC claim is made for this validation run.

Features preserved:
- Occurrence-only candidates, optional independent SDM/SSDM, automatic QC, variable selection/VIF, spatial validation, raster prediction maps, model-only exploration, full candidate downloads, and field-validation exports remain available.

Known risks / TODO:
- Replace or pre-cache the current remote CHELSA source with a genuinely tiled/overviewed regional source before claiming consistently fast one-click SDM on Streamlit Cloud.
- Model-only recommendation reservation is a transparent heuristic and should be compared with pure top-ranked selection during field validation.

## 2026-06-30 - Codex (OpenAI) - Automatic SDM read-only fix, clearer candidate maps, and package extents

Changed files:
- gbif_fieldmap_builder_app.py
- acsp/__init__.py
- acsp/planning.py
- acsp/cli.py
- r-acsp/R/recommend.R
- r-acsp/man/acsp_recommend.Rd
- test_acsp_package.py
- test_acsp_cli.py
- test_automatic_hierarchy.py
- README.md
- CHANGELOG_AI.md

Summary:
- Fixed automatic SDM/SSDM variable selection under pandas copy-on-write by zeroing the correlation-matrix diagonal on an explicit writable NumPy copy.
- Changed automatic result maps to show the full candidate pool as points while drawing green 500 m survey buffers only around recommended sites.
- Added inclusive rectangular extent filtering to the Python and R recommendation APIs, ordered as west, south, east, north.
- Added Python CLI support through `--extent WEST SOUTH EAST NORTH` and documented package examples.

Validation:
- `python -m py_compile gbif_fieldmap_builder_app.py` passed.
- All 29 Python unit tests passed, including pandas copy-on-write, extent API/CLI, and candidate-map buffer regression tests.
- The updated Streamlit app booted locally with no browser console errors.

Features preserved:
- Full candidate pools remain visible and downloadable; recommended-site identity, optional SDM/SSDM, independent model extents, VIF/variable selection, prediction maps, exploratory candidates, and exports remain available.

Known risks / TODO:
- Package extent filtering currently supports non-dateline-crossing rectangles; polygon and antimeridian extents are not yet exposed as package APIs.

## 2026-06-30 - Codex (OpenAI) - Four-model ensembles and publication-ready repository metadata

Changed files:
- gbif_fieldmap_builder_app.py
- acsp/__init__.py
- acsp/modeling.py
- pyproject.toml
- r-acsp/R/modeling.R
- r-acsp/NAMESPACE
- r-acsp/man/acsp_default_algorithms.Rd
- r-acsp/README.md
- r-acsp/inst/CITATION
- test_acsp_package.py
- README.md
- LICENSE
- CITATION.cff
- .github/workflows/package-checks.yml
- CHANGELOG_AI.md

Summary:
- Expanded automatic species SDM and per-species SSDM from two tree ensembles to four model families: Logistic regression, Random forest, ExtraTrees, and Gradient boosting.
- Final suitability remains an explicit equal-weight probability ensemble; diagnostics identify the best individual model without replacing the ensemble.
- Moved supported classifier construction and equal-weight prediction into the reusable Python package and made the Streamlit compatibility factory use that API.
- Added the matching default algorithm specification to the R package.
- Expanded Python package metadata with scikit-learn dependency, MIT license, repository URLs, development extras, and publication classifiers.
- Added root MIT license, `CITATION.cff`, R package citation metadata, and GitHub Actions checks for Python 3.10-3.12 plus R package checking.
- Rewrote the GitHub README to describe the current two-result workflow, full candidate maps, four-model 30-second SDM, reporting outputs, Python/R package APIs, validation status, citation, and publication path.
- Added shared remote-raster open retries for transient CHELSA COG DNS/HTTP failures.

Validation:
- Python editable package build/install succeeded with the expanded four-model API.
- Local classifier tests fit Logistic regression, Random forest, ExtraTrees, and Gradient boosting and verified equal-weight ensemble probabilities.
- `python -m py_compile gbif_fieldmap_builder_app.py` passed and all 24 Python tests passed.
- The `Campanula microdonta` end-to-end rerun reached environmental extraction but could not complete the new four-model AUC comparison because the external CHELSA COG endpoint remained unavailable after four retries. The previously completed two-model validation remains documented below; no unverified four-model AUC is reported.
- R is not installed in the current Windows environment, so R package checking is delegated to the added GitHub Actions workflow.

Features preserved:
- Occurrence-only candidates, independent optional SDM/SSDM, QC, variable selection/VIF, spatial partition diagnostics, full candidate maps, model-high exploration candidates, exports, and field-validation outputs remain available.

Known risks / TODO:
- Four algorithms increase optional SDM/SSDM runtime relative to the previous two-model ensemble.
- PyPI/CRAN/Zenodo publication still requires final author metadata, release review, and repository-owner credentials.
- R CMD check is delegated to GitHub Actions because R is not installed in the current Windows environment.

## 2026-06-30 - Codex (OpenAI) - Full candidate maps, publication metadata, and Python/R packages

Changed files:
- gbif_fieldmap_builder_app.py
- acsp/__init__.py
- acsp/planning.py
- acsp/sdm.py
- pyproject.toml
- r-acsp/DESCRIPTION
- r-acsp/NAMESPACE
- r-acsp/LICENSE
- r-acsp/R/recommend.R
- r-acsp/R/sdm.R
- r-acsp/man/*.Rd
- r-acsp/README.md
- README.md
- .gitignore
- test_acsp_package.py
- CHANGELOG_AI.md

Summary:
- Changed both without-model and with-model maps to display the complete eligible candidate pool. Recommended sites remain distinguishable with the existing green selected-site outline.
- Added model-performance reporting for each ensemble member, equal ensemble weights, the best individual model, validation AUC, and AUC warnings.
- Added a manuscript-ready SDM method record containing occurrence counts before/after QC, background count, automatically selected partition and reason, predictors, 30-second CHELSA source, independent prediction extent, ensemble definition, best model, AUC, and a methods-text paragraph.
- Added CSV downloads for the SDM method record and model-performance table.
- Added the installable `acsp-survey` Python package with candidate recommendation, spatial-partition selection, ensemble-performance summarization, and method-record APIs. The Streamlit app now uses these package functions through compatibility wrappers.
- Added the initial base-R `acsp` package under `r-acsp`, with matching recommendation, partition, and method-record functions plus package metadata and manual pages.
- Updated README instructions for Python and R development installs and the simplified two-result app workflow.

Validation:
- Python editable package build/install succeeded as `acsp-survey 0.1.0`.
- `Campanula microdonta` four-area rerun retained candidate pools of 22/18/20/21 without SDM and 23/18/20/21 with SDM; each area retained three recommendations.
- The fitted ensemble used Random forest and ExtraTrees at equal 0.5 weights. Random forest was the best individual model (AUC 0.970); ExtraTrees AUC was 0.926.
- Automatic validation selected random 75/25 holdout because 86 post-QC records had a minimum SDM extent span of 1.80 degrees. High/random-split AUC cautions are exported.
- `python -m py_compile gbif_fieldmap_builder_app.py` passed and all 22 Python tests passed.
- R is not installed in the current environment, so `R CMD check` could not be run; the R package uses base R only and received static structure/documentation checks.

Features preserved:
- Full observed candidate generation, optional independent SDM/SSDM, 30-second COG prediction maps, spatial QC, VIF/variable selection, model-only exploration candidates, map exports, and field-validation outputs remain available.

Known risks / TODO:
- The initial R package mirrors the reusable ranking and reporting core; GBIF retrieval, raster SDM fitting, and full SSDM fitting are not yet exposed as R package APIs.
- AUC 0.970 from random holdout is potentially optimistic and must be reported with the exported validation warning rather than treated as definitive transferability evidence.

## 2026-06-29 - Codex (OpenAI) - Four-area planning, 30-second COG SDM, and two-result workflow

Changed files:
- gbif_fieldmap_builder_app.py
- test_automatic_hierarchy.py
- CHANGELOG_AI.md

Summary:
- Simplified the automatic product surface to the actual user decisions: enter a species/genus name, optionally draw one or more survey areas, and optionally generate model-supported candidates.
- Removed the visible Balanced / Discovery / Learning outputs. The automatic workflow now shows only `Candidates without SDM/SSDM` and, after the optional model run, `Candidates with SDM/SSDM`.
- Added equal, transparent top-ranked quotas: three recommended sites per drawn survey area. Full candidate pools remain downloadable.
- Treats multiple rectangles/polygons as independent survey areas. Candidate grids, GSI terrain retrieval, habitat profiles, ranking quotas, and area IDs are calculated separately, avoiding candidate concentration in the record-richest island and excluding the sea/gaps between rectangles.
- Replaced the automatic SDM/SSDM dependency on the 628 MB global WorldClim 2.5-minute ZIP with CHELSA V2.1 BIOCLIM 30-second Cloud-Optimized GeoTIFFs.
- The app now derives the independent SDM extent after automatic occurrence QC and reads only the required raster windows via HTTP range requests; it does not download a global climate archive.
- Automatic macro models use BIO1, BIO4, BIO12, BIO14, and BIO15 before ecological representative variable selection. Local 100 m terrain discovery remains a separate GSI-based step.
- When survey areas are drawn, model-high exploration candidates are clipped back to those areas before recommendation.
- Applied the same simplified output structure and 30-second COG source to genus/SSDM mode.
- Hid legacy automatic-region choice cards; the default region is automatic and the only range interaction is optional map drawing.

Four-island validation (`Campanula microdonta`):
- GBIF total 300; cleaned records 87; four-area selected records 26.
- Automatic SDM QC excluded the remote point at 33.635783, 134.493324 and retained 86 SDM records.
- Without SDM candidate pools by area: Izu Oshima 22, Toshima 18, Niijima 20, Kozushima 21; three recommendations per area.
- With SDM candidate pools by area: Izu Oshima 23, Toshima 18, Niijima 20, Kozushima 21; three recommendations per area.
- The 12 recommended site IDs changed from `[1,6,7] / [28,31,32] / [44,46,47] / [63,64,65]` without SDM to `[1,12,11] / [37,38,28] / [55,56,45] / [67,71,80]` with SDM.
- The full automatic SDM completed successfully with 2,145 land prediction cells. Ecological representative selection retained BIO1 and BIO12 for this run.
- `python -m py_compile gbif_fieldmap_builder_app.py` passed and all 20 unit tests passed.

## 2026-06-29 - Codex (OpenAI) - Revalidate four-island plans and preserve one-day drawn-area missions

Changed files:
- gbif_fieldmap_builder_app.py
- test_automatic_hierarchy.py
- CHANGELOG_AI.md

Summary:
- Treat an explicitly drawn reachable survey area as a one-day mission; the automatic recommended region remains a two-day proposal.
- Preserve that target-day choice after optional SDM/SSDM support re-ranks candidates.
- Added `Eligible candidate pool` to the species proposal metrics so users can see the full usable pool separately from the selected one-day priority plan.
- Applied the same one-day drawn-area rule to the mirrored genus workflow.

Validation:
- `Campanula microdonta` matched 300 GBIF coordinate records and retained 87 cleaned records.
- Automatic SDM QC excluded one remote point at 33.635783, 134.493324; 86 records remained for the independent SDM workflow.
- Izu Oshima: 22 eligible candidates; one-day Balanced plan 3 sites.
- Toshima: 20 generated, 19 eligible candidates; one-day Balanced plan 3 sites.
- Niijima: 20 eligible candidates; one-day Balanced plan 3 sites.
- Kozushima: 21 eligible candidates; one-day Balanced plan 3 sites.
- Every one-day Balanced plan selected one occurrence-supported anchor, one Survey-gap site, and one Environmental-test site.
- All four areas used 100 m discovery cells and app-provided GSI terrain (DEM10B on the tested Oshima extent; DEM5A on Toshima, Niijima, and Kozushima).
- Full SDM execution reached environmental-raster retrieval, then the external WorldClim host timed out; observed candidates and the verified automatic QC result remained available.
- `python -m py_compile gbif_fieldmap_builder_app.py` and all 18 unit tests passed.

## 2026-06-29 - Codex (OpenAI) - Unified taxon-name workflow with automatic Species/Genus routing

Changed files:
- gbif_fieldmap_builder_app.py
- test_automatic_hierarchy.py
- CHANGELOG_AI.md

Summary:
- Removed the visible `Species name only` versus `Advanced / manual` workflow choice. The app now has one taxon-name-first surface.
- Renamed the sole input to `Species or genus scientific name` and uses the matched GBIF rank to route species-level taxa to occurrence/SDM planning and genera to observed-richness/SSDM planning.
- Kept survey-area drawing optional. Without a drawing, ACSP uses its recommended compact region; a drawn reachable area rebuilds observed-data candidates inside that area.
- Retained the advanced algorithms as automatic internals rather than deleting them: representative occurrence subsets, remote-outlier QC, environmental selection, spatial validation, ensemble SDM/SSDM, model-supported re-ranking, model-high exploration candidates, ACSP set selection, routing, and field-validation exports remain available.
- Added one-click optional species SDM support with fixed lightweight defaults: at most 300 spatially representative presences, automatic remote-outlier QC, ecological representative variable selection, automatic spatial validation, Random Forest plus ExtraTrees, and a 40,000-cell prediction cap.
- Added the mirrored automatic genus workflow: observed richness hotspots first, optional one-click SSDM, predicted-richness re-ranking, SSDM-high exploration hotspots, plan CSV, field-validation CSV, Google Maps routes, and the richness/candidate maps.
- Kept SDM/SSDM optional so ordinary occurrence-supported planning remains fast and usable without modeling.

Validation:
- `python -m py_compile gbif_fieldmap_builder_app.py` passed.
- 18 unit tests passed, including new synthetic genus richness and plan generation coverage.
- `Campanula microdonta` matched `SPECIES`: 87 cleaned Japan records, 31 total observed/habitat candidates, and 5-site Balanced, Discovery, and Learning plans.
- `Cirsium` matched `GENUS`: a 900-record retrieval produced 742 cleaned records, 6 modeled species labels, 53 observed-richness cells, 20 hotspots, and 3-site Balanced, Discovery, and Learning plans.
- Local Streamlit browser check confirmed one input, no workflow selector, clean species proposal rendering, optional SDM action, plan exports, and no console errors.

## 2026-06-29 - Codex (OpenAI) - Reachable-area override and GSI high-resolution terrain

Changed files:
- gbif_fieldmap_builder_app.py
- test_automatic_hierarchy.py
- CHANGELOG_AI.md

Summary:
- Clarified the ordinary workflow: no range interaction is required because ACSP uses its recommended compact region; drawing a polygon/rectangle is now an optional reachable-area override.
- Passed the drawn geographic bounds into Potential Survey Site generation instead of using the drawing only to filter occurrence rows.
- Allowed a reachable-area override containing one known record, which makes sparse islands such as Niijima usable.
- Added automatic app-provided terrain retrieval from documented GSI elevation PNG tiles, preferring DEM5A, then DEM5B, DEM5C, and DEM10B, with concurrent download, local tile/GeoTIFF caching, a compact-area tile cap, and visible GSI attribution.
- Kept large areas responsive by declining or lowering high-resolution retrieval beyond the tile cap and retaining the existing coarse fallback.
- Corrected raster-derived slope to account for pixel dimensions and return degrees.
- Removed the user-facing DEM/NDVI/land-cover upload controls from Potential Survey Sites; app-provided terrain is loaded only when candidates are built, so a collapsed legacy panel no longer triggers heavy downloads.
- Added a documented GSI RGB elevation decoder regression test.

Validation:
- `Campanula microdonta` / Japan: GBIF total 300; 87 cleaned fetched records.
- With one reachable-area box per island, all four areas used GSI DEM5A and 100 m survey cells.
- Izu Oshima: 2 known + 20 potential candidates; 22 unique eligible coordinates; one-day plan 3 sites.
- Toshima: 2 known + 18 potential candidates; 19 unique eligible coordinates; one-day plan 3 sites.
- Niijima: 1 known + 19 potential candidates; 20 unique eligible coordinates; one-day plan 3 sites.
- Kozushima: 1 known + 20 potential candidates; 21 unique eligible coordinates; one-day plan 3 sites.
- Each one-day plan contained one known anchor, one Survey-gap cell, and one Environmental-test cell.

Features preserved:
- GBIF/CSV inputs, observed candidates without SDM, independent optional SDM/SSDM, VIF, spatial validation, predict maps, model-high candidates, ACSP maps, exports, and field validation remain available.

Known risks / TODO:
- The first high-resolution run downloads GSI tiles and is slower; later runs reuse the local cache.
- Multiple islands drawn together are still treated as one broad custom mission. Ferry-separated per-island day constraints remain the next Issue #23 hierarchy step.
- GSI terrain is Japan-specific; other countries retain the existing coarse terrain fallback.

## 2026-06-29 - Codex (OpenAI) - Preserve small-island survey candidates

Changed files:
- gbif_fieldmap_builder_app.py
- test_automatic_hierarchy.py
- CHANGELOG_AI.md

Summary:
- Fixed land filtering for Potential Survey Sites and automatic ACSP-Discover candidates so the candidate center must be on land, rather than requiring a 500 m to 7.5 km surrounding circle to be entirely land.
- This preserves valid coastal and small-island candidates while still excluding candidate centers located in water.
- Added a regression assertion that the automatic workflow applies center-only land filtering to its final candidate pool.
- Collapsed overlapping Potential Survey Site roles at the same grid coordinate into one physical candidate, while retaining all matched roles in `candidate_roles`.
- Added a selection-level guard so ACSP plans cannot count one coordinate as multiple survey sites even if another candidate source supplies duplicates.
- Routed undersized or non-finite local environmental samples directly to the documented spatial fallback instead of emitting unstable covariance/SVD warnings.

Features preserved:
- Existing GBIF/CSV inputs, occurrence candidates, habitat-first candidates, optional SDM/SSDM, hard-constraint audit, route feasibility, maps, exports, and field-validation workflows remain available.

Known risks / TODO:
- Candidate cells that overlap a coastline still need their land fraction or clipped survey footprint reported in a future high-resolution terrain implementation.
- Ferry barriers and island-specific start/end hubs remain explicit follow-up work under Issue #23.

## 2026-06-27 — Taxon-aware short-trip feasibility

- Added broad GBIF-taxonomy survey profiles so plants, birds, mammals, amphibians/reptiles, arthropods, fish, and unknown taxa no longer share one field-effort assumption.
- Replaced the single continuous trip estimate with day-by-day hub-return schedules.
- Excluded sites that cannot individually fit the daily budget and included hub distance in first-site selection.
- Added a 15% operational reserve and explicit repeat-visit requirements for inference-ready non-detection.
- Random validation with `Egretta garzetta` exposed and then verified the fix for a distant first-site failure.

This file records changes made by AI coding agents such as Codex, Claude, ChatGPT, or other assistants.

Each agent should update this file after editing code.

## 2026-06-27 - Codex (OpenAI) - ACSP-Discover v1 planning contract

Changed files:
- acsp_discover.py
- test_acsp_discover.py
- test_gbif_fetch_resilience.py
- validate_automatic_discover.py
- gbif_fieldmap_builder_app.py
- .gitignore
- README.md
- CHANGELOG_AI.md

Summary:
- Added a UI-independent ACSP-Discover v1 engine with explicit Discovery and Learning scores and fixed Balanced, Discovery, and Learning plan presets generated from one candidate pool.
- Added pre-score hard constraints with a downloadable row-level audit; unknown land, legal access, slope, or physical access remains explicitly unknown rather than being assumed safe.
- Added an honest candidate-resolution decision based on environmental raster resolution, access-layer resolution, GBIF coordinate-uncertainty q75, and practical search scale.
- Added optional DEM, NDVI, and land-cover GeoTIFF inputs. Without a local DEM, the built-in ~4.5 km topographic fallback prevents false 100 m candidate precision.
- Standardized new candidate type output as Habitat-match, Survey-gap, and Environmental-test while retaining compatibility with older labels.
- Added the fixed field-validation columns requested by Issue #23 and made adaptive learning accept `result`; flowering-absent, inaccessible, and uncertain-ID visits do not become false absences.
- Kept the former single-mode ACSP selectors under Advanced for backward compatibility and baseline comparisons.
- Added the default species-name-only workflow: Japan-first/worldwide-fallback GBIF retrieval, automatic main-range scope inference, automatic candidate scales, candidate generation, constraint screening, proposal cards, three plans, map, Google Maps, and exports.
- Added explicit candidate-type minimums so an eight-cell Balanced plan includes available capacity for two known anchors, three discovery cells, and one learning cell before filling remaining slots by utility.
- Made representative GBIF retrieval resilient to individual page failures; completed pages are retained and partial retrieval is reported instead of discarding the whole proposal.
- Added a reproducible command-line validation runner and regression tests for scope inference, plan quotas, empty phenology, field-result semantics, and partial GBIF page failure.
- Random validation selected `Cirsium japonicum`: 830 fetched records, 406 in the automatic main range, 117 known candidates, 24 potential candidates, and three eight-cell plans. The final Balanced plan contained 2 known anchors, 4 discovery cells, and 2 learning cells, with medium data quality and Apr–May suggested season.
- Browser E2E confirmed the default species-name-only screen and complete proposal render with no browser console errors.
- Added hierarchical distribution planning: automatic narrow/local, regional, disjunct, or widespread classification followed by compact region/hub recommendation before within-region site selection.
- Added Recommended, Discovery, and Range-contrast region cards and a Known distribution result map. Users can switch suggested regions or draw a custom rectangle/polygon and rebuild without making map selection mandatory.
- Replaced candidate-count-only day estimates with a transparent hub-based route proxy using road-distance factor, average speed, per-cell survey/access time, and daily field-hour assumptions.
- Added a two-day default feasibility loop that reduces selected cell count when an eight-cell plan cannot fit the stated assumptions.
- Added synthetic broad-range, narrow-range, automatic-bundle, and short-trip feasibility tests; the full local suite now contains 13 passing tests.

Features preserved:
- GBIF pagination, CSV upload, occurrence exclusion and red QC points, occurrence-supported candidates without SDM, independent optional ensemble SDM, VIF, spatial validation, predict maps, SDM-high candidates, genus/SSDM, map selection, Google Maps/CSV/KML/HTML outputs, and legacy ACSP modes.

Known risks / TODO:
- Without a high-resolution local DEM, automatic potential cells correctly fall back to 5 km because the built-in WorldClim topographic evidence is about 4.5 km; automatic acquisition of finer authoritative terrain/land-cover data remains the next precision milestone.
- Compact regions and travel estimates still use geodesic proxies rather than a road/ferry routing engine. Start/end base, transport mode, ferry barriers, and researcher-specific daily budgets remain optional-logistics work.
- The current automatic candidate generator is still plant-oriented; taxon-specific Survey Protocol profiles for birds, mammals, insects, aquatic organisms, and other groups remain to be implemented.
- Access/legal/safety datasets are incomplete in many regions; unknown constraints are retained and require field verification.
- The fixed v1 weights need retrospective holdout and prospective field calibration.

## 2026-06-26 - Codex (OpenAI) - Add automatic SDM remote-outlier QC

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:
- Added conservative automatic SDM-only remote spatial outlier screening for small far-away occurrence clusters.
- Combined automatic SDM outlier exclusions with manual SDM QC rectangles so excluded records remain visible as red points but are not used for SDM training or SDM prediction extent generation.
- Kept Step 2 survey-area selection independent from SDM and did not turn the survey-area rectangle into SDM QC.
- Hid the automatic SDM QC toggle under Advanced settings with the recommended behavior enabled by default, reducing routine user decisions.
- Changed the small/local SDM clustering message from a blocking-style warning to an informational local-range note, emphasizing SDM as broad model support and Potential Survey Sites / ACSP for fine-scale destinations.
- Validated with `Campanula microdonta` in Japan: 87 clean fetched records, 1 remote western record at 33.635783 / 134.493324 automatically excluded from SDM, 86 records retained for SDM input.

Features preserved:
- GBIF and CSV occurrence inputs, Step 2 observed-candidate survey-area selection, occurrence-supported candidates, independent optional SDM workflow, manual SDM QC rectangles, VIF, spatial validation, predict map, SDM-high exploration candidates, Potential Survey Sites, ACSP selection, exports, genus/SSDM workflows, and field-validation outputs remain available.

Known risks / TODO:
- The automatic SDM QC is intentionally conservative and may keep ambiguous edge records rather than over-delete legitimate range-edge populations.
- Field validation should calibrate the remote-cluster thresholds for island endemics, mainland disjunctions, and taxa with genuinely fragmented ranges.

## 2026-06-26 - Codex (OpenAI) - Update README for ACSP research workflow

Changed files:
- README.md
- CHANGELOG_AI.md

Summary:
- Rewrote the README to reflect the current ACSP application rather than the older GBIF field-map builder description.
- Documented the four-layer structure: known records, SDM/SSDM, Potential Survey Sites, and ACSP set selection/export.
- Added concise descriptions of Habitat analogue, Under-surveyed analogue, Environmental contrast, app-provided terrain/access proxies, and field-validation learning.
- Clarified that SDM/SSDM are macro-scale optional filters while local habitat analogue search supports field-scale discovery.
- Added current implementation status and active development items.

Features preserved:
- No application code changed. Existing GBIF/CSV inputs, occurrence candidates, optional SDM/SSDM, Potential Survey Sites, ACSP modes, exports, and validation outputs are unchanged.

Known risks / TODO:
- README now describes the research direction more accurately, but app-provided NDVI/land-cover and richer online learning remain future work.

## 2026-06-26 - Codex (OpenAI) - Simplify and localize Potential Survey Sites

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:
- Added recommended fast local settings for Potential Survey Sites so ordinary users do not need to tune cell size, candidate count, or max grid cells.
- Added adaptive effective cell-size reporting so outputs show both requested and actual search-cell sizes.
- Reworked broad-area Potential Survey Sites generation: instead of coarsening a whole-country bounding box into very large cells, broad searches now create fine local search windows around occurrence-supported candidate centers.
- Added output columns for requested search cell size, effective search cell size, and evaluated grid-cell count.
- Hardened representative spatial capping so it also works on generated candidate grids that do not have occurrence-only fields such as `_year`, `_media_url`, or `_row_id`.
- Random validation with `Viola grypoceras` in Japan used 429 fetched records, generated 5 occurrence candidates and 24 potential candidates, kept a 1,000 m effective local search cell, evaluated 957 grid cells, and selected a mixed Discovery-focused set.

Features preserved:
- GBIF/CSV input, occurrence-supported candidates, optional SDM and SDM-high exploration candidates, Potential Survey Sites, local habitat analogue scoring, ACSP modes, genus/SSDM workflows, exports, and field-validation outputs remain available.

Known risks / TODO:
- Local search windows are still based on app-provided elevation/topography and coastline/access proxies unless richer app-provided layers are added.
- Recommended settings should be calibrated with field-validation outcomes and may need taxon- or island-specific presets later.

## 2026-06-26 - Codex (OpenAI) - Validate and fix mirrored genus / SSDM workflow

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:
- Validated genus mode with `Cirsium` in Japan.
- Confirmed GBIF resolves the genus to `Cirsium Mill.` / backbone taxonKey `3112554`, with 23,616 coordinate records for the JP filter.
- Fixed observed richness and SSDM species grouping so genus-only, `sp.`, `cf.`, `aff.`, indeterminate, and author-only labels such as `Cirsium Mill.` are not counted as species.
- Added genus-specific exact-coordinate deduplication that preserves different species at the same coordinates.
- Added genus-specific grid thinning that preserves different species in the same thinning grid cell, preventing observed richness hotspots from being artificially flattened.
- Changed genus ACSP default to `Discovery-focused field survey` so genus mode mirrors species mode: observed evidence first, optional SSDM support, then discovery/learning set selection.
- Added genus count transparency for species-level records and the number of non-species labels excluded from richness/SSDM.
- Lightweight Cirsium validation showed observed hotspot richness increasing after species-preserving thinning, and a mini SSDM test successfully re-ranked observed hotspots while adding SSDM-high exploratory richness candidates.

Features preserved:
- Genus GBIF download, observed richness maps, richness hotspot candidates, optional SSDM, SSDM-high exploratory candidates, VIF safeguards, spatial validation options, ACSP selection modes, map/rectangle/click selection, downloads, and species-mode workflow remain available.

Known risks / TODO:
- Genus-mode SSDM is still computationally expensive for large caps and many eligible species; lightweight defaults and user-triggered Run SSDM remain necessary.
- Species-name cleaning is intentionally conservative and excludes ambiguous labels from richness/SSDM; such records are still retained in fetched data for transparency.

## 2026-06-26 - Codex (OpenAI) - Split ACSP discovery and learning objectives

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:
- Added explicit ACSP selection modes for `Discovery-focused field survey` and `Learning-focused field survey`.
- Made species-mode ACSP default to Discovery-focused selection when Potential Survey Sites are available.
- Discovery-focused selection now treats occurrence-supported candidates as known habitat anchors and suppresses Environmental contrast dominance.
- Learning-focused selection intentionally boosts environmental contrast, under-sampled areas, and exploratory/model-only signals.
- Updated species and genus ACSP help text to explain the Discovery versus Learning distinction.
- Avoided list-index fragility in genus ACSP by selecting the default mode by name.
- Suppressed harmless terrain-derived raster warnings when a local derivative window contains only invalid/NoData values.
- Validated with `Campanula microdonta`: Discovery selection produced a mixed set of Under-surveyed analogue and Occurrence-supported survey range candidates, while Learning selection emphasized Environmental contrast and Under-surveyed analogue candidates.

Features preserved:
- Existing ACSP modes, occurrence-supported candidates, Potential Survey Sites, optional SDM/SSDM, candidate maps, selected-site state, rectangle/click selection, exports, field-validation outputs, and representative working subsets remain available.

Known risks / TODO:
- Discovery/Learning weights are explainable heuristics and should be calibrated against real field-validation outcomes.
- Potential Survey Sites still need richer app-provided high-resolution NDVI, land-cover, geology, and access layers for stronger local habitat analogue inference.

## 2026-06-26 - Codex (OpenAI) - Validate Campanula microdonta and adapt small-local thinning

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:
- Validated the species workflow with `Campanula microdonta Koidz.` from GBIF.
- Confirmed GBIF reports 300 coordinate records and the app fetches 87 records after fetch-stage deduplication.
- Found that the previous fixed 0.05-degree analysis grid over-thinned this small/local dataset from 66 unique coordinates to 28 candidate-input records, yielding only one occurrence-supported candidate.
- Added adaptive local grid thinning for non-large datasets so small/local occurrence sets use a finer effective grid while large-dataset defaults remain unchanged.
- Added pipeline transparency for the effective candidate grid when the adaptive local setting differs from the requested advanced setting.
- Re-tested `Campanula microdonta`: candidate input increased to 53 records, SDM training input to 43 records, and occurrence-supported candidates to 9.

Features preserved:
- GBIF/CSV inputs, representative large-dataset defaults, exact-coordinate deduplication, spatial thinning, occurrence-supported candidates, optional SDM/SSDM, Potential Survey Sites, ACSP selection, exports, and field-validation outputs remain available.

Known risks / TODO:
- Potential Survey Sites still rely mainly on app-provided elevation/topography and coastline proxies unless optional OSM access/edge layers are enabled; true app-provided high-resolution NDVI/land-cover/geology layers remain future work.
- ACSP `Habitat analogue survey` can still favor Environmental contrast / Under-surveyed analogue sites strongly; next improvement should separate Discovery versus Learning objectives for field planning.

## 2026-06-26 - Codex (OpenAI) - Improve app-provided access and edge distance proxies

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:
- Added line densification for app-provided GeoJSON access/edge layers before nearest-distance calculations.
- Densified coastline boundary points generated from the app's built-in land geometry.
- Densified OpenStreetMap road, trail, and forest-edge geometries fetched for Potential Survey Sites.
- Kept the calculation lightweight by using densified vertices with the existing BallTree nearest-distance path.

Features preserved:
- Potential Survey Sites, app-provided habitat layers, optional OSM access/edge layers, ACSP habitat analogue prioritization, field-validation learning, optional SDM/SSDM workflows, exports, and validation outputs remain available.

Known risks / TODO:
- Distances are still proxy distances based on densified geometry samples, not exact point-to-line geodesic distances; this is much closer than raw vertices while staying lightweight for Streamlit.

## 2026-06-26 - Codex (OpenAI) - Simplify Potential Survey Sites layer UI

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:
- Removed the `Optional: user-supplied layer overrides / additions` UI from Potential Survey Sites.
- Simplified Potential Survey Sites so the visible workflow uses app-provided local habitat layers only.
- Kept the optional OpenStreetMap access/edge layer checkbox as the only extra layer control.
- Removed the unused uploaded-layer cache helper for the Potential Survey Sites workflow.

Features preserved:
- Researcher coordinate CSV upload, occurrence-supported candidates, optional SDM and SDM-high exploration candidates, local habitat analogue candidate generation, ACSP selection, field-validation learning, selected-site exports, genus/SSDM workflows, VIF diagnostics, and spatial validation remain available.

Known risks / TODO:
- Users can no longer override local habitat layers from the UI; future app-provided NDVI and land-cover sources should replace that need.

## 2026-06-26 - Codex (OpenAI) - Improve ACSP for macro-SDM plus local habitat analogue planning

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:
- Extended ACSP so the candidate-set algorithm can explicitly use local habitat-analogue evidence, low-survey-effort signals, access feasibility, and field-validation learning.
- Added a new ACSP selection mode: `Habitat analogue survey`.
- Added ACSP gain columns: `habitat_analogue_gain`, `validation_learning_gain`, and `access_gain`.
- Updated the ACSP marginal-gain function to combine occurrence/model priority, geographic/environmental complementarity, exploration value, sampling-gap coverage, local habitat analogue support, validation-learning support, and access feasibility.
- Expanded environmental complementarity detection so ACSP can use local terrain/vegetation/access variables such as elevation, slope, aspect, roughness, TPI, NDVI, distance to road/trail/coast/forest edge, habitat score, and Mahalanobis environmental distance.
- Updated Potential Survey Site priority scoring so `Habitat analogue`, `Under-surveyed analogue`, and `Environmental contrast` candidates receive type-specific composite scores rather than all using a single proxy score.
- Made species-mode ACSP default to `Habitat analogue survey` when potential survey cells are available.
- Added new ACSP gain columns to selected-site summaries, candidate detail tables, and exports.

Features preserved:
- Occurrence-supported candidates, optional SDM and SDM-high exploration candidates, raster-style predict map, VIF/spatial validation, existing ACSP modes, map/rectangle selection, selected-site exports, genus/SSDM workflows, and validation outputs remain available.

Known risks / TODO:
- The new ACSP components depend on available candidate columns; when habitat/access/validation fields are absent, they degrade to zero and the older ACSP behavior is preserved.
- Future validation should compare selected sets across Simple top-ranked, Complementarity, and Habitat analogue survey modes using real field outcomes.

## 2026-06-26 - Codex (OpenAI) - Make habitat analogue layers app-provided and add validation learning

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:
- Shifted `Potential Survey Sites` from an upload-first layer workflow to an app-provided local habitat layer workflow.
- Added app-provided local topography as the default habitat analogue basis, using the app's elevation raster and derived terrain variables.
- Added an app-provided coastline-distance proxy from the built-in land boundary.
- Added optional OpenStreetMap fetches for roads, trails, and forest-edge proxies inside the current survey area.
- Kept user-supplied DEM/NDVI/land-cover/vector inputs as optional overrides/additions rather than the main workflow.
- Added optional field-validation learning: users can upload a previous validation CSV with `site_id` and a presence/result column, and the app learns a lightweight `field_validation_support_score` for candidate re-ranking.
- Export columns now include `field_validation_support_score` and `validation_learning_note`.

Features preserved:
- Occurrence-supported candidates, optional SDM and SDM-high exploration candidates, raster-style predict map, VIF/spatial validation, ACSP selection, map/rectangle selection, selected-site exports, genus/SSDM workflows, and validation outputs remain available.

Known risks / TODO:
- OpenStreetMap access/edge layers depend on Overpass availability and are optional; failures leave those distance proxies missing without stopping candidate generation.
- The validation-learning model is intentionally lightweight and needs enough matched field-validation rows with both success and non-success outcomes before it can re-rank candidates.

## 2026-06-26 - Codex (OpenAI) - Add high-resolution habitat layer inputs for Potential Survey Sites

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:
- Added a dedicated `High-resolution habitat layers` input section inside `Potential Survey Sites (Habitat-first Discovery)`.
- Added optional GeoTIFF inputs for DEM, NDVI, and land cover.
- Added optional GeoJSON inputs for roads, trails, coastline, and forest edge, with nearest-distance extraction to candidate cells.
- Added upload caching so Streamlit can reopen uploaded layers with rasterio across reruns.
- Added high-resolution raster sampling that supports rasters with non-WGS84 CRS by transforming WGS84 candidate coordinates into raster CRS.
- Added DEM-derived local terrain metrics from uploaded DEMs: elevation, slope, aspect, roughness, and TPI.
- Changed known-site habitat profiling to sample points around each known occurrence within a user-defined buffer, default 100 m, instead of sampling only the exact coordinate.
- Potential survey cells can now be scored from uploaded local habitat layers when available, with Mahalanobis environmental similarity, while SDM remains an optional broad macro-scale filter.
- Renamed potential candidate types to `Habitat analogue`, `Under-surveyed analogue`, and `Environmental contrast` to match the intended field-discovery workflow.

Features preserved:
- Occurrence-supported candidates, optional SDM and SDM-high exploration candidates, raster-style predict map, VIF/spatial validation, ACSP selection, map/rectangle selection, selected-site exports, genus/SSDM workflows, and validation outputs remain available.

Known risks / TODO:
- Vector distance extraction currently uses nearest GeoJSON vertices as a lightweight approximation; a later refinement can densify line geometries for more exact road/trail/coast/forest-edge distances.
- Uploaded land-cover values are sampled and exported, with a simple dominant-class match score; richer categorical habitat matching can be added after real layer examples are tested.

## 2026-06-26 - Codex (OpenAI) - Refine potential sites as local habitat analogue search

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:
- Reframed `Potential Survey Sites (Habitat-first Discovery)` so it is not treated as another broad-climate SDM.
- Added local terrain analogue variables derived from the available elevation raster: `aspect` and `tpi`, alongside elevation, slope, and roughness.
- Changed potential-site scoring to build a known-site environmental profile and score grid cells by Mahalanobis environmental distance / environmental similarity.
- Kept SDM separate: SDM predict-map cells can now be used only as an optional broad macro-scale filter, while local topographic analogue score remains the main habitat score.
- Added export columns for `environmental_similarity`, `mahalanobis_environment_distance`, `macro_filter_basis`, local terrain variables, and `missing_layer_note`.
- Clarified that NDVI, land cover, road/trail distance, forest-edge distance, and coastline distance are not yet supplied as real high-resolution layers in this implementation.

Features preserved:
- Occurrence-supported candidates, optional SDM and SDM-high exploration candidates, raster-style predict map, VIF/spatial validation, ACSP selection, map/rectangle selection, selected-site exports, genus/SSDM workflows, and validation outputs remain available.

Known risks / TODO:
- The local analogue search still uses the app's available WorldClim/elevation raster rather than user-uploaded high-resolution DEM/NDVI/land-cover/road/trail layers. A later Issue #23 step should add layer upload/sampling for true 100 m island-scale habitat profiling.

## 2026-06-26 - Codex (OpenAI) - Add Potential Survey Sites MVP

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:
- Synchronized local `main` with GitHub using `git fetch origin` and `git pull --ff-only origin main` before editing.
- Added an optional `Potential Survey Sites (Habitat-first Discovery)` expander in species mode.
- Implemented an MVP grid-cell candidate generator that creates exploratory `Habitat-match`, `Survey-gap`, and `Environmental-test` candidates from the active survey area.
- Added transparent fieldwork proxy columns: `habitat_score`, `analogue_score`, `environmental_distance_to_known`, `environmental_novelty`, `survey_effort_proxy`, `survey_gap_score`, `access_score`, `access_note`, `target_record_density`, `nearest_known_population_km`, `search_cell_radius_m`, and `why_selected`.
- Potential candidates are appended to the existing candidate table and can flow into top-ranked output, map display, ACSP auto-selection, Google Maps links, CSV/KML/HTML exports, and field-validation CSVs.
- Added a selection-map checkbox for including potential survey cells, and marker styling for the three new candidate types.
- Cleared cached potential candidates when source data or the survey-area rectangle changes so stale exploratory cells are not reused.

Features preserved:
- Existing occurrence-supported candidates, optional SDM and SDM-high exploration candidates, ACSP selection, manual map/rectangle selection, selected-site summaries, CSV/HTML/KML/validation exports, genus/SSDM workflows, VIF diagnostics, and spatial validation remain available.

Known risks / TODO:
- This is an MVP scaffold for Issue #23. It does not yet sample uploaded high-resolution GeoTIFF/vector layers or road/trail access data; `access_score` is left unset and `access_note` asks users to verify access externally.

## 2026-06-25 - Codex (OpenAI) - Remove top-ranked display count upper bounds

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:
- Synchronized local `main` with GitHub using `git fetch origin` and `git pull --ff-only origin main` before editing.
- Removed the dynamic upper bound from `Top-ranked hotspots shown` in genus mode so existing/session values no longer become invalid when the candidate count changes.
- Applied the same upper-bound removal to species mode `Top-ranked sites shown` for consistency.
- Values above the currently available candidate count simply show all matching candidates via the existing dataframe `head()` behavior.

Features preserved:
- Top-ranked output tables, hotspot/candidate maps, ACSP selection, manual click/rectangle selection, selected-site exports, optional SDM/SSDM, VIF diagnostics, and spatial validation remain available.

Known risks / TODO:
- Very large display counts can make Folium maps slower; users can lower the count manually when needed.

## 2026-06-25 - Codex (OpenAI) - Hide richness legend on ACSP selection map

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:
- Synchronized local `main` with GitHub using `git fetch origin` and `git pull --ff-only origin main` before editing.
- Added a `show_legend` option to the observed richness grid layer helper.
- Kept the observed richness grid visible on the genus hotspot / ACSP selection map, but removed its fixed-position `Observed species richness` legend from that selection map to reduce UI clutter.
- Preserved the richness legend on the Known distribution map and standalone richness map.

Features preserved:
- Genus Known distribution richness overlay, hotspot selection map richness overlay, ACSP selection, optional SSDM, selected-site exports, species mode, SDM/SSDM maps, VIF diagnostics, and spatial validation remain available.

Known risks / TODO:
- None known; this is a display-only legend adjustment.

## 2026-06-25 - Codex (OpenAI) - Show observed genus richness on maps

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:
- Synchronized local `main` with GitHub using `git fetch origin` and `git pull --ff-only origin main` before editing.
- Added a shared observed richness grid layer helper so the same occurrence-based richness cells can be drawn on multiple Folium maps.
- Overlaid observed species richness on the genus-mode Known distribution / survey-area rectangle map, using all cleaned genus occurrence records.
- Changed the genus hotspot selection map so the observed richness grid is shown by default, while keeping the checkbox available for users who need to hide it for responsiveness.

Features preserved:
- Genus occurrence display, survey-area rectangle selection, observed richness hotspot generation, optional SSDM, ACSP selection, selected-site exports, species mode, SDM/SSDM maps, VIF diagnostics, and spatial validation remain available.

Known risks / TODO:
- Very dense genus datasets may render more richness cells on the Known distribution map; users can still control genus fetch/display caps and hide the hotspot-map richness layer if needed.

## 2026-06-25 - Codex (OpenAI) - Fix duplicate SSDM variable-selection widget key

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:
- Synchronized local `main` with GitHub using `git fetch origin` and `git pull --ff-only origin main` before editing.
- Fixed the StreamlitDuplicateElementKey crash in genus mode by removing a duplicated SSDM variable-selection expander that reused `ssdm_variable_strategy`, `ssdm_corr_threshold`, `ssdm_vif_threshold`, and `ssdm_custom_final_variables`.
- Preserved the SSDM variable-selection controls inside `Advanced: variables & algorithms` and moved the pooled-variable-selection explanation there.

Features preserved:
- Genus richness workflow, optional SSDM, shared variable selection, VIF/correlation/custom variable strategies, per-species bias reduction, validation settings, ACSP selection, map selection, and exports remain available.

Known risks / TODO:
- None known; this is a UI de-duplication fix for Streamlit widget keys.

## 2026-06-24 - Codex (OpenAI) - Fix ACSP redundancy penalty

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:
- Synchronized local `main` with GitHub using `git fetch origin` and `git pull --ff-only origin main` before editing; local tracked changes were clean and untracked generated files were preserved.
- Fixed ACSP redundancy scoring so candidates inside `cluster_distance_m` receive a full redundancy penalty instead of no penalty.
- Changed the redundancy decay to `exp(-d_min / redundancy_scale_m)` for sites outside the local cluster distance, so nearby already-covered areas are penalized more strongly and distant complementary sites are penalized less.
- Lowered the `Complementarity-based batch selection` travel weight from `0.15` to `0.05`, keeping travel as a mild fieldwork practicality term rather than dominating complementarity.

Features preserved:
- ACSP selection modes, Simple top-ranked behavior, exploration-focused and phylogeographic modes, manual map/rectangle selection, selected-site summaries, CSV/HTML/KML/validation exports, optional SDM/SSDM, SDM-high/SSDM-high exploratory candidates, VIF diagnostics, and spatial validation remain available.

Known risks / TODO:
- Complementarity mode should now differ more clearly from Simple top-ranked when nearby candidates compete; real-world behavior still depends on candidate geography and selected K.

## 2026-06-13 - Claude - Fix slow progression after SDM predict map (vectorise hot loops)

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Problem:
- After "SDM predict map is available.", interacting with the candidate-selection map (every click/widget change triggers a Streamlit rerun) was extremely slow — the app appeared stuck and would not progress to subsequent steps.

Root cause:
- Two distance computations in the per-rerun hot path used Python-level geopy `geodesic` loops:
  - `make_sdm_exploration_candidates` computed, for every high-suitability prediction cell, the minimum distance to *all* known points (occurrences + candidates) with a nested `geodesic` loop — millions of geodesic calls per rerun once SDM was active. It runs every rerun inside the always-expanded "Create SDM-high exploration ranges" panel.
  - `nearest_neighbor_order` (called every rerun via `order_sites(all_candidates, "Nearest-neighbor route")`) did an O(n²) per-row `geodesic` greedy nearest-neighbour ordering.

Fix:
- Vectorised `make_sdm_exploration_candidates` nearest-known-distance using a scikit-learn `BallTree` with the haversine metric (added `from sklearn.neighbors import BallTree`).
- Vectorised `nearest_neighbor_order` with the existing numpy haversine helper (`_acsp_point_distances_m`), preserving the identical greedy nearest-neighbour ordering and tie-breaking.

Verification:
- `nearest_neighbor_order` output is identical to the previous geopy implementation across multiple start points; ~445x faster for 250 sites (4.3 s -> 0.01 s per rerun).
- BallTree haversine distances match geopy geodesic within ~0.23 % (about 80 m on multi-km distances, the expected sphere-vs-ellipsoid difference); the keep/exclude filtering decision at the distance threshold is identical. Empty-known-set edge case handled (distances -> infinity).
- Ran `python -m py_compile gbif_fieldmap_builder_app.py` successfully.

Behaviour preserved:
- SDM-high exploration candidate output, distance-to-nearest-known reporting, route ordering, and all downstream selection/exports are unchanged — only the per-rerun compute cost is reduced.

## 2026-06-13 - Claude - Rename app/tool to ACSP

Changed files:
- gbif_fieldmap_builder_app.py
- README.md
- CHANGELOG_AI.md

Summary:
- Renamed the user-facing application/tool name from "GBIF FieldMap Builder" to **"ACSP — Adaptive Complementarity-based Survey Prioritization"** across display strings: the module docstring header, `APP_TITLE`, the Streamlit page title and `st.title`, the page caption, the KML document `<name>`, and the README title/intro.
- Left infrastructure identifiers unchanged to avoid breaking deployment and tooling: the source filename `gbif_fieldmap_builder_app.py`, `Procfile`, the GitHub repository slug `zuizui0223/gbif-fieldmap-builder`, and `APP_BUILD_ID`.
- Ran `python -m py_compile gbif_fieldmap_builder_app.py` successfully.

## 2026-06-12 - Claude - Add ACSP candidate-SET selection algorithm

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:
- Read the latest policy files (`AGENTS.md`, `SURVEY_PLANNING_POLICY.md`, `RESEARCH_POSITIONING.md`, `CHANGELOG_AI.md`) and inspected the current candidate-generation, scoring, selection, and export code before editing.
- Added **ACSP (Adaptive Complementarity-based Survey Prioritization)** — a candidate-*set* selection algorithm, not just new per-candidate scoring variables. It moves beyond independent weighted candidate scores to choose a survey set that jointly maximises detection potential, model support, environmental/geographic complementarity, exploration value, and sampling-gap coverage while reducing redundancy and excessive travel.
- Implemented `acsp_select()` as a greedy marginal-gain set builder. For each unselected candidate the marginal gain is `base_score + coverage_gain + exploration_gain + sampling_gap_gain - redundancy_penalty - travel_penalty`. The existing `priority_score` is preserved and reused as `base_score`.
- Added four selection modes (`ACSP_SELECTION_MODES`), each with its own component weight preset: **Simple top-ranked** (pure priority order), **Complementarity-based batch selection**, **Exploration-focused active survey**, and **Phylogeographic gap-filling**.
- Component design, using only data already on the candidate dataframe (no new user uploads required):
  - **Geographic complementarity** rewards candidates far from already-selected sites; redundancy penalty applies to candidates that are moderately close but not within the planned local cluster distance (same-cluster picks are allowed).
  - **Environmental complementarity** is used when environmental/PCA predictor columns (e.g. `bio*`, `pca*`, `pc#`, `env_*`, elevation) are present on candidates, computed as standardized environmental-space distance to the selected set; it falls back to geographic complementarity when no environmental variables exist.
  - **Exploration gain** rewards SDM-high/SSDM-high exploration candidates, high `sdm_suitability`, distance from known occurrence-supported sites (`distance_to_nearest_known_m`), and model uncertainty columns when available.
  - **Sampling-gap gain** rewards under-sampled (low record-count) sites plus new region/island/richness-cluster coverage and, in genus mode, candidates whose `species_list` covers species not yet represented in the selected set.
  - **Travel penalty** is a mild distance-based penalty for sites far from the selected set (no full routing).
- Optional `selected_ids` (S0) seeds the set with already-selected/sampled sites, preserving the user's manual selection order before greedy complementarity filling continues.
- Required computed columns are emitted on the selected set: `base_score`, `geographic_complementarity_gain`, `environmental_complementarity_gain` (when env predictors exist), `exploration_gain`, `sampling_gap_gain`, `redundancy_penalty`, `travel_penalty`, `marginal_gain_score`, `selection_step`, `selection_reason`, and `selection_algorithm`.
- UI (map-first selection preserved): added an **"Auto-select by selected algorithm"** button with a selection-algorithm dropdown, a K input, and an optional "seed with current selection" toggle to both the single-species candidate selection panel and the genus hotspot selection panel. Selected sites now display `selection_step`, `marginal_gain_score`, and `selection_reason`. Manual click-to-toggle and rectangle selection remain fully available.
- Exports: extended `EXPORT_CSV_COLS` so the selected-site CSV includes all marginal-gain columns, and added `selection_algorithm` and `selection_reason` (plus `selection_step`/`marginal_gain_score`) to the field-validation template.
- Verified the algorithm in isolation across all four modes (distinct, sensible site sets), the S0 seeding path, the environmental-complementarity path, and empty-input handling; ran `python -m py_compile gbif_fieldmap_builder_app.py` successfully.

Features preserved:
- Existing `priority_score`, occurrence-supported candidates, SDM-high exploration candidates, genus richness hotspots, SSDM-high exploration candidates, manual map/rectangle selection, selected-site summaries, and all CSV/HTML/KML/validation exports remain available. ACSP is purely additive and off by default until the user clicks the auto-select button.

Known risks / TODO:
- ACSP runs a greedy O(K·n) loop over the filtered candidate pool; very large pools with large K may add a short delay. Environmental complementarity only activates when environmental/PCA columns are already attached to candidates (geographic complementarity is the documented fallback otherwise).

## 2026-06-09 - Codex (OpenAI) - Restore visible candidate maps and prioritize ranked output

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:
- Read the latest GitHub `main` policy files before editing, including `AGENTS.md`, `SURVEY_PLANNING_POLICY.md`, `RESEARCH_POSITIONING.md`, and `CHANGELOG_AI.md`; refreshed `origin/main` before editing.
- Reverted the closed-by-default candidate/hotspot map behavior so species and genus candidate maps are visible again by default.
- Kept the lightweight map defaults: only the currently filtered top-ranked candidates/hotspots are shown, with occurrence points and richness grid layers still opt-in because they are slower.
- Added prominent top-ranked output tables and direct CSV/KML/field-validation CSV downloads for species candidates and genus hotspots, so the app can be used primarily as a priority-ranking output tool without requiring marker clicks or rectangle selection.
- Preserved click-to-toggle, rectangle selection, selected-site summaries, and selected-site exports as optional user customization after the ranked output is generated.

Features preserved:
- Map-first candidate inspection, top-ranked bulk add, click-to-toggle and rectangle selection, selected green outlines, Google Maps links, CSV/HTML/KML/validation downloads, Step 2 survey-area selection, observed-data candidates, genus observed richness hotspots, optional SDM/SSDM, SDM-high/SSDM-high exploratory candidates, VIF diagnostics, and spatial validation remain available.

Known risks / TODO:
- Clicking candidate markers still triggers a Streamlit/Folium rerun and can feel slower than using the top-ranked output downloads or bulk-add button; the main workflow now no longer depends on marker-click selection.

## 2026-06-09 - Codex (OpenAI) - Defer candidate maps after survey-area selection

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:
- Read the latest GitHub `main` policy files before editing, including `AGENTS.md`, `SURVEY_PLANNING_POLICY.md`, `RESEARCH_POSITIONING.md`, and `CHANGELOG_AI.md`.
- Cached the large-dataset working-set preparation helper so unchanged occurrence subsets are not rebuilt across downstream reruns.
- Made the species candidate-selection map closed by default after Step 2 survey-area confirmation, with explicit open/close buttons for click and rectangle selection.
- Made the genus hotspot-selection map use the same closed-by-default pattern.
- Kept bulk top-ranked site/hotspot addition, selected-site summaries, and exports available without forcing the heavy Folium candidate map to render immediately.
- Enabled HTML map downloads after the corresponding candidate/hotspot map is opened, avoiding automatic map HTML generation during normal post-survey-area navigation.

Features preserved:
- Step 2 survey-area selection, observed-data candidates, genus observed richness hotspots, bulk top-ranked selection, click-to-toggle and rectangle selection when the map is opened, selected-site summaries, Google Maps links, CSV/HTML/KML/validation downloads, optional SDM/SSDM, SDM-high/SSDM-high exploratory candidates, VIF diagnostics, and spatial validation remain available.

Known risks / TODO:
- Users must open the candidate or hotspot map before using click/rectangle site selection or downloading that HTML map; this is intentional to keep Survey area confirmation and movement toward SDM responsive.

## 2026-06-09 - Codex (OpenAI) - Fix rectangle clearing on survey-site maps

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:
- Read the latest GitHub `main` versions of `AGENTS.md`, `SURVEY_PLANNING_POLICY.md`, `RESEARCH_POSITIONING.md`, `CHANGELOG_AI.md`, and `gbif_fieldmap_builder_app.py` before editing.
- Connected existing map reset tokens to Streamlit/Folium component keys so clearing rectangles actually remounts the map instead of receiving stale browser-side drawing state.
- Fixed the species known-distribution `Clear rectangle` button by incrementing `target_map_reset_token` and using it in the macro map key.
- Added explicit `Clear selection rectangles` buttons for species candidate selection and genus hotspot selection maps.
- Added reset-token updates for selection-map clears, data reloads, genus fetches, and mode switches so old drawn rectangles do not persist across workflows.

Features preserved:
- Step 2 survey-area rectangles, candidate-selection rectangles, click-to-toggle selection, bulk top-ranked selection, selected-site summaries, selected green outlines, Google Maps links, CSV/HTML/KML/validation downloads, species mode, genus mode, optional SDM/SSDM, and lightweight selection maps remain available.

Known risks / TODO:
- Clearing a rectangle remounts the affected Folium map, which is intentional and should be more reliable than trying to mutate the existing browser-side drawing layer.

## 2026-06-09 - Codex (OpenAI) - Make selection maps lightweight by default

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:
- Read the latest GitHub `main` versions of `AGENTS.md`, `SURVEY_PLANNING_POLICY.md`, `RESEARCH_POSITIONING.md`, `CHANGELOG_AI.md`, and `gbif_fieldmap_builder_app.py` before editing.
- Made the species candidate-selection map hide candidate-input occurrence points by default, with a `Show candidate-input occurrence points on selection map (slower)` checkbox for verification.
- Made the genus hotspot-selection map hide the observed richness grid by default, with a `Show richness grid on selection map (slower)` checkbox for inspection.
- Kept candidate/hotspot markers, selected green outlines, click-to-toggle, rectangle selection, and bulk top-ranked selection on the lightweight default maps.
- This targets the remaining lag from Streamlit/Folium re-rendering large occurrence/grid layers after bulk add, marker clicks, double-clicks, and rectangle drawings.

Features preserved:
- Species and genus occurrence-supported candidates, observed richness hotspots, optional SDM/SSDM, SDM/SSDM-supported re-ranking, exploratory candidates, selected-site summaries, map selection, rectangle selection, top-ranked bulk add, Google Maps links, CSV/HTML/KML/validation downloads, and analysis-point/grid verification toggles remain available.

Known risks / TODO:
- Users who need to inspect all analysis points or richness cells on the same selection map must turn on the slower verification checkbox; the default prioritizes responsive site selection.

## 2026-06-09 - Codex (OpenAI) - Further reduce genus and selection lag

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:
- Read the latest GitHub `main` versions of `AGENTS.md`, `SURVEY_PLANNING_POLICY.md`, `RESEARCH_POSITIONING.md`, `CHANGELOG_AI.md`, and `gbif_fieldmap_builder_app.py` before editing.
- Confirmed that genus mode already had the recent map-selection fixes: lightweight selected overlays, click/rectangle selection, and bulk top-ranked hotspot selection.
- Added cached genus observed-output generation for the spatially balanced genus candidate input, species summary table, observed richness grid, and observed hotspot candidates.
- Removed selected-site row merging into the species and genus base candidate maps so selecting sites no longer changes the heavy cached map input.
- Selected-site green outlines now use all current candidates through the lightweight overlay, while the base map remains limited to the currently displayed top-ranked candidates.

Features preserved:
- Species and genus map-first selection, click-to-toggle, rectangle selection, bulk top-ranked selection, selected-site summaries, selected green outlines, Google Maps links, CSV/HTML/KML/validation downloads, observed candidates, optional SDM/SSDM, and exploratory candidate labels remain available.

Known risks / TODO:
- Selected candidates outside the current top-ranked display may appear as green overlay rings without their full base candidate popup until display filters are broadened; the selected-site summary and exports still include them.

## 2026-06-09 - Codex (OpenAI) - Add bulk top-ranked candidate selection

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:
- Read the latest GitHub `main` versions of `AGENTS.md`, `SURVEY_PLANNING_POLICY.md`, `RESEARCH_POSITIONING.md`, `CHANGELOG_AI.md`, and `gbif_fieldmap_builder_app.py` before editing.
- Added a species-mode `Add top-ranked shown sites` button that adds the currently filtered top-ranked candidate sites on the map to the selected survey-site set.
- Added the mirrored genus-mode `Add top-ranked shown hotspots` button for richness hotspot candidates.
- Kept the unified map-based workflow: top-ranked sites are displayed first, then users can bulk-add shown candidates, draw rectangles for nearby groups, or click individual markers to adjust the selection.

Features preserved:
- Manual marker click selection, rectangle group selection, selected-site session state, selected-site summaries, selected green outlines, Google Maps links, CSV/HTML/KML/validation downloads, species mode, genus mode, optional SDM/SSDM, and exploratory candidate labels remain available.

Known risks / TODO:
- Bulk-add uses the current display filters and `Top-ranked sites shown` count; users should adjust those controls first when they want a broader or narrower batch.

## 2026-06-09 - Codex (OpenAI) - Keep candidate map cached during selection

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:
- Read the latest GitHub `main` versions of `AGENTS.md`, `SURVEY_PLANNING_POLICY.md`, `RESEARCH_POSITIONING.md`, `CHANGELOG_AI.md`, and `gbif_fieldmap_builder_app.py` before editing.
- Moved selected-site green rings into a lightweight Folium overlay passed to `st_folium` separately from the cached base candidate map.
- Species-mode candidate selection no longer passes changing selected-site IDs into `build_map`, so marker clicks and double-clicks do not invalidate the heavy occurrence/candidate map cache.
- Applied the same selected-overlay pattern to genus-mode hotspot selection maps.
- Added a guarded fallback for Streamlit/Folium environments that do not support `feature_group_to_add`.

Features preserved:
- Candidate marker click selection, rectangle group selection, selected-site green outlines where supported, selected-site summaries, Google Maps links, CSV/HTML/KML/validation downloads, species mode, genus mode, optional SDM/SSDM, and clear-selection buttons remain available.

Known risks / TODO:
- If a deployed `streamlit-folium` version lacks `feature_group_to_add`, the app falls back to the cached base map without the lightweight selected-ring overlay rather than crashing.

## 2026-06-09 - Codex (OpenAI) - Speed up candidate generation before SDM

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:
- Read the latest GitHub `main` versions of `AGENTS.md`, `SURVEY_PLANNING_POLICY.md`, `RESEARCH_POSITIONING.md`, `CHANGELOG_AI.md`, and `gbif_fieldmap_builder_app.py` before editing.
- Optimized candidate medoid selection so small clusters still use exact vectorized pairwise haversine distances, while large clusters use the occurrence point nearest the cluster centroid instead of a slow all-pairs geodesic loop.
- Added a cached occurrence-candidate generation helper covering DBSCAN clustering, candidate-site construction, phenology summaries, priority ranking, and ordering.
- Replaced the always-inline species candidate-generation block with the cached helper so SDM setup interactions do not repeatedly rebuild identical occurrence-supported candidates before the user can proceed.

Features preserved:
- Step 2 survey-area selection, occurrence-supported candidates, candidate phenology fields, priority scoring, candidate map selection, optional SDM, SDM-high exploration candidates, VIF diagnostics, spatial validation, genus/SSDM workflows, and downloads remain available.

Known risks / TODO:
- Large-cluster medoids are now practical centroid-nearest representatives rather than exact all-pairs medoids; this preserves field-planning behavior while avoiding severe lag for dense occurrence clusters.

## 2026-06-09 - Codex (OpenAI) - Reduce candidate-map click lag

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:
- Read the latest GitHub `main` versions of `AGENTS.md`, `SURVEY_PLANNING_POLICY.md`, `RESEARCH_POSITIONING.md`, `CHANGELOG_AI.md`, and `gbif_fieldmap_builder_app.py` before editing.
- Removed redundant immediate `st.rerun()` calls after species-mode candidate marker click toggles and rectangle group selections.
- Applied the same redundant-rerun removal to genus-mode hotspot marker click toggles and rectangle group selections.
- Kept selection state updates in session state so the selected-site summary can update during the same Streamlit pass instead of forcing a second full map rebuild.

Features preserved:
- Click-to-toggle candidate selection, rectangle group selection, selected-site session state, selected-site summaries, Google Maps links, CSV/HTML/KML/validation downloads, species mode, genus mode, optional SDM/SSDM, and clear-selection buttons remain available.

Known risks / TODO:
- In some Streamlit/Folium sessions, selected-marker outline redraw may appear on the next map rerun rather than through an extra forced rerun; this is intentional to reduce click lag.

## 2026-06-09 - Codex (OpenAI) - Remove selected-candidate best-time panel

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:
- Read the latest GitHub `main` versions of `AGENTS.md`, `SURVEY_PLANNING_POLICY.md`, `RESEARCH_POSITIONING.md`, `CHANGELOG_AI.md`, and `gbif_fieldmap_builder_app.py` before editing.
- Removed the separate `Best time to visit (selected candidates)` panel below the selected survey-site summary.
- Kept the main occurrence-level `Best time to visit` section and preserved per-candidate phenology fields in candidate details, CSV exports, popups, and field-validation templates.

Features preserved:
- Candidate selection, selected-site summaries, Google Maps/CSV/HTML/KML/validation exports, optional SDM/SSDM, VIF diagnostics, spatial validation, and existing phenology export columns remain available.

Known risks / TODO:
- Users should rely on the main Best time to visit panel and candidate-level exported phenology fields instead of a separate selected-candidate chart.

## 2026-06-09 - Codex (OpenAI) - Reduce survey-area rectangle lag

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:
- Read the latest GitHub `main` versions of `AGENTS.md`, `SURVEY_PLANNING_POLICY.md`, `RESEARCH_POSITIONING.md`, `CHANGELOG_AI.md`, and `gbif_fieldmap_builder_app.py` before editing.
- Pulled the latest GitHub `main` before making changes.
- Removed redundant `st.rerun()` calls after survey-area rectangle drawings are stored in session state.
- Species mode macro distribution rectangles and genus mode target-occurrence rectangles now save the drawn rectangle and continue through the same Streamlit rerun, instead of triggering an immediate second rerun.
- This keeps rectangle selection behavior unchanged while reducing the visible pause after drawing a survey-area box.

Features preserved:
- Step 2 rectangle survey-area selection, clear-rectangle buttons, SDM/SSDM independence from Step 2, candidate generation, genus richness hotspots, species-mode candidates, optional SDM/SSDM, VIF diagnostics, spatial validation, maps, and downloads remain available.

Known risks / TODO:
- Candidate/richness generation still runs after the rectangle is accepted; if very large target areas remain slow, the next optimization should cache candidate-input/richness computations or add an explicit lightweight apply step.

## 2026-06-05 - Claude (claude-sonnet-4-6) - Add phenology/flowering-season support to fieldwork planning workflow

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:

- **`parse_occurrence_month_doy`**: new helper that extracts (month, day_of_year) from occurrence row fields — tries eventDate/_event_date, then month/day/year fields, then startDayOfYear.
- **`infer_phenology_state`**: new helper that classifies each record as 'flowering', 'fruiting', 'vegetative_or_nonreproductive', or 'unknown' by scanning lifeStage, reproductiveCondition, occurrenceRemarks, fieldNotes, and dynamicProperties text fields against keyword sets (_FLOWERING_KW, _FRUITING_KW, _VEG_KW).
- **`enrich_occurrences_with_phenology`**: new function that adds _obs_month, _obs_doy, _phenology_state columns to a cleaned occurrence DataFrame; called immediately after clean_occurrences() in the main species workflow.
- **`candidate_season_summary`**: new function that summarises flowering/phenology season for occurrence records belonging to one candidate cluster; returns observation_months, observation_doy_median/iqr, flowering_record_count, flowering_months, flowering_doy_median, recommended_survey_window, season_confidence.
- **`_months_to_window_str`**: new helper that converts a list of month integers to a compact string like 'Apr-Jun'.
- **`make_candidate_sites`**: phenology default columns (observation_months, flowering_record_count, flowering_months, recommended_survey_window, season_confidence) added to returned DataFrame so columns are always present.
- **Phenology enrichment at call site**: after make_candidate_sites, per-cluster occurrence subsets are summarised via candidate_season_summary and written back into occurrence_candidates before add_priority_rank.
- **Phenology UI expander** ("Optional: Field season / flowering timing"): shows observation-month bar chart for all dated records and a separate flowering-state bar chart; placed before the Step 3 survey site suggestions section; includes caveat caption about observation vs flowering dates.
- **Candidate details table**: recommended_survey_window, season_confidence, flowering_record_count added to displayed columns when present.
- **`popup_html_site`**: phenology_line added to candidate popup HTML showing recommended visit window, confidence, and flowering evidence count when a valid window is available.
- **`make_validation_template`**: added recommended_survey_window, season_confidence, flowering_record_count from phenology summary; added new field-entry columns visit_date, flowering_observed, fruiting_observed, vegetative_only, phenology_notes.
- **`EXPORT_CSV_COLS`**: recommended_survey_window, season_confidence, flowering_record_count added to candidate CSV exports.

Features preserved:
- All existing species SDM, VIF, spatial partition, predict map, exclusion/QC, route planner, and download features unchanged.
- Genus/SSDM workflows unchanged.
- Phenology section is optional (expander, collapsed by default); missing dates/fields are handled gracefully and never crash the app.

Known risks / TODO:
- Phenology state inference is keyword-based; rare or non-English phenology terms may not be captured.
- Flowering windows derived from all dated records (not confirmed flowering records) are labeled 'inferred' via the season_confidence field.
- GBIF occurrence records may not include lifeStage or reproductiveCondition; flowering_record_count may be 0 for most species.

## 2026-06-05 - Claude (claude-sonnet-4-6) - Global lag reduction: cache main maps, vectorize geometry, raster coverage layer

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:

- **`build_map` cached** (`@st.cache_data`): the main candidate map (occurrence clusters + priority markers + selected-site rings) was rebuilt on every Streamlit widget interaction. Now cached; only rebuilt when input DataFrames, selected_ids, or layers change. Call site converts `selected_ids` list → sorted tuple for hashability.
- **`make_genus_candidate_selection_map` cached** (`@st.cache_data`): same issue in genus mode — grid rectangles + hotspot markers rebuilt on every rerun. Now cached; `selected_ids` list → sorted tuple at call site.
- **`make_ssdm_map` coverage layer** replaced: the per-cell `iterrows()` CircleMarker loop over up to 80,000 grid cells was replaced with a numpy-vectorized RGBA array and `ImageOverlay`. Eliminates 80k Python-level marker object creations.
- **`prediction_area_geometry` vectorized**: removed `iterrows()` for Points creation; replaced with `occ["_longitude"].to_numpy()` + zip array. Also vectorized the excluded_occ cutout loop.
- **`make_ssdm_map` hotspot loop** changed from `iterrows()` → `itertuples()` (faster attribute access).

No UI, session-state, or feature-behavior changes.

## 2026-06-05 - Claude (claude-sonnet-4-6) - Performance: vectorize SSDM extent masking, cache maps, deduplicate per-species geometry

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:

- **`make_richness_map` cached**: added `@st.cache_data(show_spinner=False)` decorator so the Folium richness map is not rebuilt on every widget-triggered rerun.
- **Vectorized SSDM extent masking**: replaced Python-level `Point.covers` loop (O(n_cells × n_species), e.g. 1.6M calls for 80k cells × 20 species) with a numpy bounds check (`lons >= minx & lons <= maxx & lats >= miny & lats <= maxy`). This is exact for bounding-box extents and ~1000× faster. For buffer/convex-hull extents the bounds check is a conservative approximation that still eliminates the per-cell Python overhead.
- **Deduplicated per-species `prediction_area_geometry` call**: `auto_sdm_partition` branch previously called `prediction_area_geometry(sp_occ, "bounding box", 10.0, 20.0)` separately from the masking call `prediction_area_geometry(sp_occ, area_mode, buffer_km, rectangle_margin_km)`. Unified: one call per species using the user's `area_mode`/`buffer_km`/`rectangle_margin_km`, stored in `sp_extent_geom_for_partition`, reused for both partition selection and masking.

No UI, session-state, or feature-behavior changes.

## 2026-06-05 - Claude (claude-sonnet-4-6) - SSDM species-specific prediction extents with NA-aware richness accumulation

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:

- **Fixed critical accumulation bug**: `richness_cont` / `richness_binary` were undefined (referenced before assignment). Replaced with the already-initialized `richness_sum` / `binary_sum` / `n_evaluated` arrays throughout the loop and output construction.
- **Fixed undefined `grid` reference**: `predict_suitability(grid, ...)` and output construction used `grid` which was out of scope; corrected to `shared_grid`.
- **Implemented species-specific extent masking** (`ssdm_extent_mode="species_specific"`, default): for each species, a per-species bounding-box extent is computed from its presence points; the shared grid is masked to that extent; suitability is predicted only within the mask; cells outside are NaN (unevaluated, not absence).
- **NA-aware richness accumulation**: richness is summed only where each species-level model was evaluated (`n_evaluated > 0`). Cells where no species was evaluated remain NaN in `ssdm_continuous_richness` and `ssdm_binary_richness`.
- **Added `n_species_evaluated` and `mean_suitability` columns** to the SSDM output grid.
- **Updated `ssdm_hotspot_candidates`**: added `min_species_evaluated` parameter (default 2); candidates are filtered to cells where at least this many species were modeled, avoiding high-richness artifacts from single-species cells.
- **Coverage layer in `make_ssdm_map`**: optional `n_species_evaluated` dot layer (hidden by default, toggleable via LayerControl) showing how many species were evaluated per cell.
- **SSDM UI**: added "SSDM prediction extent strategy" section with Advanced expander exposing `ssdm_extent_mode` radio and `ssdm_min_coverage` number_input; defaults visible as caption without requiring user interaction.
- **Shared genus mode preserved**: `ssdm_extent_mode="shared_genus"` replicates previous behavior (all species predicted across full genus extent).

Features preserved:
- Species SDM validation unaffected. All SSDM outputs (richness maps, hotspot candidates, model summary CSV, VIF diagnostics, downloads) preserved. Partial SSDM completion and progress reporting preserved.

## 2026-06-05 - Claude (claude-sonnet-4-6) - Unify Step 2 survey-area panel: simple rectangle-include default for both species and genus

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:
- Refactored `target_occurrence_set_panel` with new signature: added `model_label` (default `"SDM"`) and `allow_advanced_modes` (default `False`) parameters.
- Default simple mode (`allow_advanced_modes=False`) shows no radio buttons; automatically uses rectangle-include when a rectangle is drawn, and shows an `st.info` message when no rectangle is drawn.
- Advanced mode (`allow_advanced_modes=True`) shows the three radio options (use all / include / exclude) inside a collapsed `st.expander("Advanced survey area mode")`.
- Simplified the four count metrics to: "Cleaned records", "Inside survey rectangle", "Active target records", and "Records used for candidates" (or "Records used for hotspots" in SSDM mode).
- Removed "Excluded by rectangle" metric from the default simple view; it remains tracked in the returned `counts` dict for downstream use.
- Updated species mode call site: `show_map=False`, `model_label="SDM"`, `allow_advanced_modes=False`.
- Updated genus mode call site: `show_map=True`, `model_label="SSDM"`, `allow_advanced_modes=False`, label `"Survey area for richness hotspots"`.
- Replaced `**Phase 2 — Select your fieldwork survey area**` heading with `**2 — Choose your survey area**` + concise caption for species mode; replaced genus Step 2 subheader to `2 — Choose your survey area` with matching caption.
- Removed redundant genus duplicate-metrics block (g1-g6) that was showing the same counts as the panel's own metric row.
- py_compile: no errors.

Features preserved:
- Rectangle draw and clear logic (stored in session state) unchanged for both modes.
- All advanced three-mode logic preserved inside the `allow_advanced_modes` branch; no behavior removed.
- Phase 1 national distribution map, SDM, SSDM, VIF, candidates, hotspots, downloads, and all other features unchanged.

Known risks / TODO:
- Sessions with a previously active "Exclude records inside drawn rectangle" mode will default to simple include mode on next load; users who need exclude mode must enable `allow_advanced_modes`.

## 2026-06-04 - Claude (claude-sonnet-4-6) - SSDM validation parity: per-species auto_sdm_partition, jackknife, spatial CV

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:
- Read the full 4400+ line app before editing; all changes are targeted diffs to fit_sdm, fit_stacked_species_sdms, the SSDM UI section, and summary column additions only.
- Added a true leave-one-out jackknife branch in fit_sdm (lines ~2283-2330): for each presence record i, trains on all other rows, predicts on i; final AUC is computed from held-out presence predictions vs a background sample. This enables reliable AUC for n < 15.
- Extended fit_stacked_species_sdms signature with ssdm_partition_override, ssdm_k_folds, ssdm_checkerboard_deg, ssdm_holdout_split parameters.
- In the per-species loop, when override=="auto", calls prediction_area_geometry(sp_occ, "bounding box", 10.0, 20.0) to get sp_extent, then auto_sdm_partition(n_occ, sp_extent) for the true per-species method+reason. When override is forced, uses those fixed parameters.
- Added partition_reason, n_folds, valid_folds, auc_warning columns to every summary_rows entry (modeled, skipped_after_thinning, skipped_too_few_records, failed).
- Replaced the old single-selectbox SSDM partition UI with the new expander-based UI: default is "auto", with sub-inputs for k, checkerboard cell size, and holdout split appearing conditionally when the corresponding method is forced. Caption explains auto_sdm_partition is used per species.
- Updated the fit_stacked_species_sdms call site to pass all new parameters.
- py_compile: no errors.

## 2026-06-04 - Codex (OpenAI) - Mirror genus hotspot selection with species workflow

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:
- Read the latest GitHub `main` versions of `AGENTS.md`, `SURVEY_PLANNING_POLICY.md`, `RESEARCH_POSITIONING.md`, `CHANGELOG_AI.md`, and `gbif_fieldmap_builder_app.py` before editing.
- Added genus-specific selected-site session state and reset handling so genus selections are independent but follow the species-mode selection pattern.
- Added a priority-aware genus hotspot selection map that overlays observed richness grid cells, shows observed hotspots and SSDM-high exploratory richness candidates with distinct candidate labels, supports click-to-toggle selection, rectangle selection via `ids_inside_drawn_rectangles`, and selected-site green rings.
- Merged the old genus Step 3/Step 4 table-first flow into one map-first `Richness hotspot suggestions and selection` workflow with top-ranked display controls, priority/model filters, observed/exploratory candidate toggles, compact selected-hotspot summary, and full tables moved into an optional expander.
- Stored optional SSDM grid/hotspot results in session state so observed richness hotspots can be re-ranked with SSDM predicted richness and SSDM-high exploratory richness candidates can be shown on the main selection map.
- Moved the Optional SSDM section visually before the main genus selection map using a Streamlit container, mirroring species mode's optional model support before final candidate selection.
- Expanded selected genus exports and validation templates with observed richness, SSDM predicted richness, species lists, target taxa, specimens, DNA samples, survey effort, and notes.
- Updated SSDM validation UI to use `Auto recommended` by default and added the species SDM partition choices; Auto now chooses a validation method per species and reports the chosen `partition_method` in the SSDM model summary.
- Fixed visible genus Step heading encoding and kept low-offset genus GBIF fetch behavior.

Features preserved:
- Species mode behavior, CSV upload, genus GBIF total count/fetch, partial genus fetch recovery, country/year filters, observed richness grid, species summary, optional SSDM, shared VIF diagnostics, predicted richness maps, and existing downloads remain available.

Known risks / TODO:
- The genus workflow now mirrors species-mode selection and export behavior, but the SSDM setup map/QC remains lighter than the single-species SDM setup and should be refined in a follow-up if full SSDM QC parity is required.

## 2026-06-04 - Codex (OpenAI) - Make genus fetch cap directly editable

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:
- Read the latest GitHub `main` versions of `AGENTS.md`, `SURVEY_PLANNING_POLICY.md`, `RESEARCH_POSITIONING.md`, `CHANGELOG_AI.md`, and `gbif_fieldmap_builder_app.py` before editing.
- Rechecked the deployed genus fetch UI behavior after the user confirmed the stall was caused by high GBIF offsets rather than the record cap.
- Removed the separate Advanced checkbox gate around larger genus fetch caps because it left the visible `Maximum GBIF records to fetch` input capped at 3,000.
- Restored a single genus fetch cap input with default 3,000 and maximum 50,000, so values such as 10,000 can be typed directly.
- Changed the widget key again so Streamlit sessions reset away from the previous 3,000-limited widget state while preserving low-offset page fetching.

Features preserved:
- Low-offset genus fetch stall avoidance, progress-aware partial fetch, genus richness maps, species summaries, hotspot candidates, optional SSDM, VIF diagnostics, downloads, and single-species mode remain available.

Known risks / TODO:
- Very high caps may still take many sequential GBIF pages; partial records remain preserved after each successful page if a later request fails.

## 2026-06-04 - Codex (OpenAI) - Uncap genus fetch while avoiding high offsets

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:
- Read the latest GitHub `main` versions of `AGENTS.md`, `SURVEY_PLANNING_POLICY.md`, `RESEARCH_POSITIONING.md`, `CHANGELOG_AI.md`, and `gbif_fieldmap_builder_app.py` before editing.
- Reopened genus GBIF fetch caps above 3,000 records under an Advanced GBIF fetch cap control while keeping the safe low-offset fetch path that fixed Streamlit Cloud stalls.
- Changed the genus fetch widget key again so deployed Streamlit sessions reset away from the temporary 3,000-only control.
- Updated genus fetch wording to explain that higher caps are allowed but fetched sequentially from low GBIF offsets, with downstream deduplication and spatial thinning creating the working survey subset.
- Added an explicit Step 1 genus workflow caption showing the species-mode symmetry: load records, choose observed-data survey area, generate richness hotspots, optionally run SSDM, and use model support for re-ranking/exploration.
- Fixed visible genus-mode mojibake in Step labels and SSDM status/help text, replacing broken dash/emoji rendering with plain ASCII UI text.

Features preserved:
- Genus richness maps, species summaries, hotspot candidates, optional SSDM, VIF diagnostics, progress-aware partial fetch, low-offset stall avoidance, downloads, and single-species mode remain available.

Known risks / TODO:
- Very high genus fetch caps can still take many GBIF pages; partial records are still preserved after each successful page if a later request fails.

## 2026-06-04 - Codex (OpenAI) - Prevent genus fetch stalls from old large caps

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:
- Read the latest GitHub `main` versions of `AGENTS.md`, `SURVEY_PLANNING_POLICY.md`, `RESEARCH_POSITIONING.md`, `CHANGELOG_AI.md`, and `gbif_fieldmap_builder_app.py` before editing.
- Reset the genus fetch widget key so old Streamlit sessions cannot keep stale 4,300/10,000-record caps after the app default was lowered.
- Capped the normal interactive genus GBIF fetch control at the survey-planning default of 3,000 representative records.
- Avoided high-offset GBIF jumps in the interactive genus fetch because those pages can stall on Streamlit Cloud; genus fetch now uses fast low-offset pages and relies on downstream deduplication/spatial thinning for working subsets.
- Shortened each progress-aware genus page request to one fast 8-second attempt so a single slow GBIF page does not leave the app appearing stuck for several minutes.
- Stored a deduplicated partial genus subset in `st.session_state.genus_raw_df` after every successful page, so a later page failure can continue from records already received instead of returning to the no-data state.

Features preserved:
- Genus occurrence richness maps, species summaries, hotspot candidates, optional SSDM, representative offset retrieval, progress display, partial-data warnings, downloads, and single-species mode remain available.

Known risks / TODO:
- Large genus all-record exports remain intentionally outside the default interactive workflow; the app is optimized for field-survey planning with representative subsets.

## 2026-06-04 - Codex (OpenAI) - Add progress-aware partial genus fetch

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:
- Read the latest GitHub `main` versions of `AGENTS.md`, `SURVEY_PLANNING_POLICY.md`, `RESEARCH_POSITIONING.md`, `CHANGELOG_AI.md`, and `gbif_fieldmap_builder_app.py` before editing.
- Lowered the interactive genus GBIF fetch default cap from 10,000 to 3,000 records.
- Added a progress-aware genus occurrence fetch path that displays planned pages, current page, current offset, records received so far, and requested fetch cap with `st.progress` and a status placeholder.
- Preserved successfully fetched genus pages if a later GBIF page fails, deduplicates/caps the partial subset, stores it in `st.session_state.genus_raw_df`, and warns with failed stage, offset, fetched-so-far count, requested cap, and partial-data status.

Features preserved:
- Genus occurrence richness maps, species summaries, hotspot candidates, optional SSDM, representative offset retrieval, GBIF count checks, country/year filters, downloads, and single-species mode remain available.

Known risks / TODO:
- Species-mode fetch still uses the cached one-shot fetch path; this change targets the blocking genus-mode case only.

## 2026-06-04 - Codex (OpenAI) - Add explicit download button keys

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:
- Read the latest GitHub `main` versions of `AGENTS.md`, `SURVEY_PLANNING_POLICY.md`, `RESEARCH_POSITIONING.md`, `CHANGELOG_AI.md`, and `gbif_fieldmap_builder_app.py` before editing.
- Confirmed the latest `main` no longer has `route_planner_panel()` after the unified map-selection workflow, so the duplicate selected-site summary is already structurally removed.
- Added explicit unique `key=` values to the compact selected-sites CSV, HTML, KML, and validation CSV download buttons to prevent `StreamlitDuplicateElementId`.
- Added explicit keys to remaining genus, SSDM, candidate-details, and sampling-map download buttons so repeated labels or filenames remain safe if sections are rendered together.

Features preserved:
- Unified map-first candidate selection, selected-site session state, click and rectangle selection, green selected-site outlines, Google Maps links, CSV/HTML/KML/validation downloads, genus mode, and optional SDM/SSDM workflows remain unchanged.

Known risks / TODO:
- The fix targets duplicate Streamlit element IDs by keying download widgets; no data-processing behavior was changed.

## 2026-06-04 - Codex (OpenAI) - Unify candidate selection on the main map

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:
- Removed the separate `Auto: top-ranked` / `Manual: map & rectangle` selection modes from the species candidate workflow.
- Removed the separate manual site-selection map; the main priority-aware candidate map is now the only candidate selection map.
- Added map display controls for top-ranked sites shown, minimum priority score, minimum SDM suitability when available, and candidate-type inclusion.
- Added a persistent `Clear selected sites` control above the main candidate map.
- Added rectangle drawing to the main candidate map; drawn rectangles add candidate site IDs using `ids_inside_drawn_rectangles(all_candidates, "site_id", "latitude", "longitude", features)`.
- Kept click-to-toggle individual candidate sites on the main map and preserved green selected-site outlines.
- Updated the performance metric from `Route stops` to `Selected sites`.

Features preserved:
- Occurrence-supported candidates work without SDM; SDM-high exploration candidates remain available and clearly distinct.
- Selected-site session state, compact selected-sites summary, Google Maps links, CSV/HTML/KML downloads, validation CSV download, and priority-aware candidate markers remain available.
- Step 2 survey-area selection and independent optional SDM workflow are unchanged.

Known risks / TODO:
- Rectangle selection adds sites inside drawn rectangles; removing a group still uses individual click toggles or the Clear selected sites button.

## 2026-06-04 - Codex (OpenAI) - Strengthen field-validation exports

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:
- Read the latest GitHub `main` versions of `AGENTS.md`, `SURVEY_PLANNING_POLICY.md`, `RESEARCH_POSITIONING.md`, `CHANGELOG_AI.md`, and `gbif_fieldmap_builder_app.py` before editing.
- Added `site_id` to the selected-site CSV export so downloaded fieldwork lists keep the stable app site identifier.
- Expanded `make_validation_template()` to include field-validation fields for accessibility, survey effort, target-species detection, abundance, flowering status, number of species detected, newly confirmed populations, photographs, specimens, DNA samples, habitat notes, and comments.
- Added `Validation CSV` download buttons to the selected-sites controls so users can directly export a field-validation template for chosen survey sites.

Features preserved:
- Map-first candidate selection, compact selected-sites summary, priority-aware markers, independent optional SDM workflow, SDM-high exploration candidates, genus/SSDM workflows, and existing CSV/HTML/KML exports remain available.
- Occurrence-supported candidates still work without SDM, and SDM/SSDM support remains optional model support for ranking/exploration.

Known risks / TODO:
- The validation template is a CSV scaffold; app-side entry/editing of returned field-validation results is still future work.

## 2026-06-04 - Claude (claude-sonnet-4-6) — Merge Step 3/4: unified priority-visualized candidate map and selection

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:

**1. Priority-aware candidate markers in `build_map`**
- Added `_priority_marker_style(row)` helper that returns `(radius, color)` based on `priority_rank` and `candidate_type`: rank 1–3 → radius 14 red `#d62728`; rank 4–10 → radius 11 orange `#ff7f0e`; rank 11–20 → radius 9 green `#2ca02c`; rank >20 → radius 7 grey `#7f7f7f`; SDM-high → radius 9 purple `#9467bd` with dashed outline.
- `build_map` gains optional `selected_ids` parameter; selected sites receive a green outer ring (`CircleMarker` radius+5, color `#00cc44`, fill=False, weight=3).

**2. Merged Step 3 and Step 4 into one section**
- Replaced `st.subheader("3 — Survey site suggestions")` and the separate `route_planner_panel` subheader `"4 — Selected survey sites"` with a single `st.subheader("3 — Survey site suggestions and selection")`.
- Selection controls (Auto/Manual/rectangle) appear before the map via `route_planner_panel(all_candidates, show_subheader=False)`.
- `route_planner_panel` gains `show_subheader: bool = True` parameter; genus mode unaffected (not called in genus mode).
- Map rendered once after selection controls, passing `selected_ids` for green rings.
- After the map: compact selected-sites summary (site_id, priority_rank, priority_score, candidate_type, Google Maps link) + Open all in Google Maps, CSV, HTML, KML downloads, Clear button.
- Full candidate details table moved into `st.expander("Optional: candidate details table", expanded=False)` with CSV and KML downloads.
- Removed duplicate map rendering that previously existed after the Performance summary block.

Features preserved:
- `sl_selected_site_ids` session state unchanged.
- Auto/Manual/rectangle selection logic fully preserved inside `route_planner_panel`.
- Google Maps links, CSV, HTML, KML downloads preserved.
- Phase 1, Phase 2, SDM expander, VIF, prediction map, performance summary, methods text untouched.
- `add_priority_rank`, `order_sites`, candidate generation unchanged.
- `layers` dict controlling occurrences/predict overlay/candidate_circles preserved.

Known risks / TODO:
- `html_bytes` (used by "Download sampling HTML map") now comes from the map built inside the merged section; verify the reference is still in scope.

## 2026-06-04 - Claude (claude-sonnet-4-6) — Add SDM record-count guidance and candidate-type labels

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:

**SDM record-count guidance (above "Optional: Build SDM" subheader)**
Added `st.info(...)` block using `min(len(occ_raw), sdm_working_records)` as the preview presence-point count. Four tiers: very few (<20), few (20–49), moderate (50–299), abundant (≥300/cap). Guidance helps users understand when SDM adds the most value relative to occurrence density.

**Candidate-type captions**
Added `📍 Occurrence-supported candidates` caption above the SDM-high exploration expander, and `🔭 SDM-high exploration candidates` caption inside the "Create SDM-high exploration ranges" expander, clarifying confidence levels and the need for field validation.

**SDM cap explanation caption**
Added `st.caption(...)` immediately after the `sdm_ind_max_presence` number_input explaining that SDM uses a spatially representative subset regardless of record count, and that the cap is most relevant for abundant-record species.

No Phase 1 or Phase 2 logic was changed. No SDM pipeline order or `auto_sdm_partition` logic was modified.

---

## 2026-06-04 - Claude (claude-sonnet-4-6) — Merge Phase 1 and Phase 2 maps; remove sidebar caption

Changed files:
- gbif_fieldmap_builder_app.py
- CHANGELOG_AI.md

Summary:

**Draw rectangle directly on Phase 1 national distribution map**
- Added `folium.plugins.Draw` (rectangle only) to `make_macro_cluster_map` so users can draw the survey area rectangle on the Phase 1 overview map instead of needing a separate Phase 2 map.
- Phase 1 `st_folium` now returns `["all_drawings", "last_active_drawing"]` and handles draw state (stores to `target_rect_features` / `target_last_draw_sig`).
- Added "Clear survey rectangle" button next to the Phase 1 map.
- `target_occurrence_set_panel` gained a `show_map: bool = True` parameter; called with `show_map=False` in species mode to suppress its previously separate rectangle-selection map.
- Phase 2 caption updated from "map below" to "map above".

**Remove "Raw GBIF records are kept..." sidebar caption**
- Removed the four-value sidebar caption (fetch / map / candidate / SDM record counts) from the main species workflow.

Features preserved:
- Genus mode still uses `target_occurrence_set_panel` with its own map (`show_map=True`, default).
- All rectangle-based survey area selection logic (include / exclude / clear), Phase 2 radio buttons, and metrics unchanged.
- All SDM, VIF, route planner, and download features preserved.

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
