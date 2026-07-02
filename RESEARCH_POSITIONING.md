# Research positioning and publication goals

This document defines the scientific purpose, novelty, intended users, and validation strategy of GBIF FieldMap Builder.

It is a design guide for AI coding agents and collaborators. It is not a final literature review or manuscript draft.

## Core scientific purpose

GBIF FieldMap Builder is a field-survey planning tool.

Its main purpose is to convert existing occurrence records into practical, ranked survey-site candidates that researchers can inspect, select, export, visit, and validate in the field.

The app is not primarily a general SDM teaching tool, a full-featured all-record modeling platform, or a replacement for specialist ecological modeling software.

The central question is:

> How can existing occurrence records be converted into the next set of field survey sites, and how can SDM or SSDM help when known records are sparse or incomplete?

## Main workflow

### Single-species workflow

1. Load occurrence records from GBIF or upload a researcher-owned coordinate CSV.
2. Show the known distribution overview.
3. Let the user choose a realistic or hypothesis-driven fieldwork survey area.
4. Generate occurrence-supported survey candidates from known records in that area.
5. Optionally build an SDM using an independent SDM input, QC, bias-reduction, and prediction extent.
6. Use SDM suitability to:
   - re-rank occurrence-supported candidates; and
   - identify exploratory potential sites away from known records when appropriate.
7. Export selected sites and validate them through field survey.

### Genus / multi-species workflow

1. Load genus-level occurrence records from GBIF or a researcher-owned CSV.
2. Show observed species-richness patterns.
3. Generate observed richness hotspot candidates.
4. Optionally run SSDM to estimate predicted richness patterns.
5. Use SSDM predicted richness to re-rank observed hotspot candidates and identify exploratory areas for multi-species sampling.
6. Export sites for biodiversity, taxonomic, phylogeographic, or evolutionary sampling.

## Intended users

The app should support:

- field ecologists selecting survey sites for a focal species;
- researchers studying poorly known, rare, or sparsely recorded species;
- taxonomists and biodiversity researchers planning multi-species or genus-level sampling;
- phylogeographic and phylogenetic researchers deciding which regions, islands, mountains, range edges, or sampling gaps to include;
- researchers using their own unpublished or historical coordinate records rather than GBIF;
- teams that need a transparent, shareable, map-based workflow for fieldwork planning.

## Scientific novelty

### 1. The final output is a field decision, not only a prediction map

Many occurrence-data and SDM workflows end with a distribution or suitability map.

GBIF FieldMap Builder is designed to continue one step further and produce:

- ranked survey-site candidates;
- map-based candidate selection;
- selected-site lists;
- Google Maps links;
- CSV, KML, and HTML outputs;
- field-validation templates.

The app therefore emphasizes fieldwork-oriented decision support rather than prediction alone.

### 2. SDM has different roles depending on occurrence-data availability

SDM should not be mandatory for every species.

When known occurrence records are abundant:

- occurrence-supported candidates may already be sufficient for survey planning;
- SDM is optional model support;
- SDM should use a capped, spatially representative subset rather than all records.

When known occurrence records are sparse or incomplete:

- SDM becomes especially valuable for identifying potential unsampled suitable areas;
- small-sample validation methods such as jackknife may be useful;
- model-only candidates must be clearly labeled exploratory and require field validation.

This adaptive use of SDM is a core feature of the app.

### 3. Known-record candidates and model-only candidates are explicitly separated

The app should distinguish:

- **Occurrence-supported candidates**: based on known records and optionally re-ranked by SDM suitability.
- **SDM-high exploration candidates**: model-only potential sites away from known records, intended for field validation.

This distinction improves scientific transparency and prevents users from treating predicted suitability as confirmed occurrence.

### 4. Single-species and genus-level survey planning share one design logic

Species mode supports focal-species survey planning with optional SDM.

Genus mode supports observed richness hotspots with optional SSDM predicted richness.

This makes the app useful not only for species surveys, but also for:

- multi-species inventory;
- taxonomic revision;
- genus-level diversity surveys;
- phylogeographic sampling;
- evolutionary and phylogenetic studies that require broad spatial representation.

### 5. The app is not limited to GBIF

Researchers can upload their own coordinate CSV files.

This allows the same workflow to be applied to:

- unpublished sampling records;
- herbarium or museum coordinates;
- laboratory databases;
- historical surveys;
- citizen-science exports;
- previous field campaigns.

The app should therefore be described as an occurrence-record-to-fieldwork tool, not only as a GBIF viewer.

### 6. Field validation is part of the research contribution

The app should be tested through real field surveys.

The scientific contribution is stronger when candidate sites are evaluated for:

- accessibility;
- target-species presence or absence;
- abundance or number of flowering individuals;
- number of species detected in genus-level surveys;
- whether the site represents a newly confirmed population;
- time and effort required for detection;
- whether occurrence-supported and model-only candidates differ in success rate.

## Literature gap to address

Existing research and software commonly address one or more of the following:

- occurrence-data retrieval and visualization;
- SDM or SSDM model construction;
- sampling-bias correction;
- environmental-variable selection;
- spatial validation;
- biodiversity or richness prediction;
- phylogenetic or phylogeographic analysis after samples are collected.

The practical step between prediction and fieldwork is often less integrated:

> Which sites should a researcher visit next, how should those sites be ranked, and how should known-record evidence be distinguished from model-only exploration?

GBIF FieldMap Builder aims to fill this gap by connecting occurrence records, optional SDM/SSDM predictions, map-based site selection, export, and field validation in one workflow.

## Research hypotheses for publication

### H1. Occurrence-supported candidate ranking

Higher-priority occurrence-supported sites will have a higher probability of successful field detection than lower-priority sites.

### H2. SDM value for sparse records

For species with sparse or incomplete occurrence records, SDM-high exploration candidates can identify potential populations that would not be selected from known records alone.

### H3. Integrated scoring

Occurrence-supported candidates with both strong observed support and high SDM suitability will have higher field-detection success than candidates supported by only one source of evidence.

### H4. Genus / SSDM value

Observed richness hotspots re-ranked by SSDM predicted richness will improve multi-species sampling efficiency and may support taxonomic, phylogeographic, and phylogenetic sampling design.

## Recommended field-validation data

Field-validation exports should support recording:

- site ID;
- candidate type;
- priority rank;
- priority score;
- occurrence-support score;
- SDM suitability or SSDM predicted richness;
- accessibility and access mode;
- survey date and observer;
- target-species presence or absence;
- abundance or abundance class;
- flowering status;
- number of species detected;
- whether a newly confirmed population was found;
- habitat notes;
- photographs, specimens, or DNA samples collected;
- survey effort and comments.

## Retrospective distance-excluded validation

To test whether ACSP adds value beyond proximity to known records, hold out complete spatial blocks, islands, or occurrence clusters. Rebuild candidate generation and all environment/SDM profiles from training records only. Exclude known-location candidates, occurrence-support scores, survey-gap scores, environmental novelty, and distance-to-known evidence before ranking. Compare Top-k recovery of held-out occurrences against random Top-k draws from the same candidate pool, as well as distance-only, local-environment-only, SDM-only, and full integrated ablations.

Random point-level train/test splits are not sufficient because duplicated and nearby occurrence records leak spatial information. Report held-out recall within a predeclared radius, nearest-candidate distance, rank-weighted recovery, environmental coverage, and lift over matched random controls.

For weight calibration, predeclare and seed the taxon sample, preferably stratified across occurrence-record abundance. Use nested evaluation: spatial blocks test recovery within each taxon, while entire taxa are held out from weight selection. Report the sampling frame, failed taxa, all searched weight vectors, unchanged-default performance, local-only and SDM-only ablations, and random Top-k from the same candidate pool. Retrospective occurrence recovery must not be presented as validation of access, detection probability, flowering phenology, or field effort; those terms require prospective surveys.

Keep model-accuracy validation separate from candidate-set validation. Model accuracy should use seeded random taxa, repeated spatial-block holdout, probabilistic discrimination and calibration metrics, and taxon-level uncertainty. Candidate-set validation should compare recovery at a fixed candidate budget against matched random and component baselines. Prospective field validation should freeze ACSP and matched-control sites before survey and use equal effort. The superseded four-island protocol is retained in [`legacy/docs/FIELD_VALIDATION_IZU.md`](legacy/docs/FIELD_VALIDATION_IZU.md) for provenance.

## Design implications for AI coding agents

When making implementation decisions, prioritize:

1. clear survey-area selection from the known distribution overview;
2. occurrence-supported candidates that work without SDM;
3. optional SDM that is especially helpful for sparse records;
4. transparent separation of occurrence-supported and model-only candidates;
5. genus / SSDM workflows that support multi-species and evolutionary sampling;
6. CSV upload parity with GBIF workflows;
7. map-first, intuitive candidate selection;
8. field-validation outputs;
9. lightweight SDM/SSDM defaults and representative subsets;
10. scientific transparency over feature quantity.

Do not add complexity merely because a modeling option exists.

A feature should remain prominent only when it helps users decide where to survey, understand why a site is prioritized, or validate the decision in the field.

## Anti-rollback rules

Do not remove or weaken these core concepts:

- occurrence-supported candidates must be available without SDM;
- SDM is optional and especially useful for sparse occurrence data;
- SDM-high exploration candidates must remain available and clearly labeled exploratory;
- Step 2 survey-area selection must not automatically become the SDM extent;
- genus mode and SSDM should support multi-species, taxonomic, phylogeographic, and evolutionary sampling;
- researcher-owned CSV uploads must remain a first-class input;
- field validation must remain part of the intended workflow;
- the main interface should remain map-first and fieldwork-oriented.
