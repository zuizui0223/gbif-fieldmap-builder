# Retrospective validation protocol

## Claim boundary

This protocol can validate reproducible candidate generation and recovery of spatially held-out occurrence records. It cannot establish field detectability, legal or physical access, abundance, phenology, or discoveries per field day without prospective observations. Those components remain unavailable rather than being estimated from GBIF proximity.

## Confirmatory design

- Freeze code and all settings before drawing the confirmatory sample.
- Draw taxon-region pairs with a recorded seed, balanced across plants/animals, four Japanese geographic strata, and four regional occurrence-count strata. Confirmatory draws exclude every taxon used during development, not only exact repeated taxon-region pairs.
- Never replace a failed pair after observing its outcome.
- Rebuild candidates from training spatial blocks only. Remove occurrence-supported candidates and occurrence/distance-derived score components before ranking.
- Primary endpoint: intention-to-evaluate Top-5 held-out occurrence recall within 5 km. Failed and missing folds receive zero recall.
- Sensitivity endpoints: 2 km and 10 km recall. These cannot replace the primary endpoint after results are seen.
- Baselines: same-pool random Top-5 and greedy same-pool recovery ceiling. Candidate-generation completion and rankable-fold rate are separate endpoints.

## Dependence and uncertainty

Repeated folds from one taxon-region pair are not independent samples. Report pair-clustered bootstrap intervals and pair-level sign-flip tests. Report taxon-group and geographic-stratum results even when unfavorable. Do not claim a global improvement from one favorable subgroup.

## Model-change gate

A scoring or weight change is eligible for production consideration only when:

1. it was selected without using the confirmatory pairs;
2. confirmatory candidate completion is at least 90%;
3. at least 80% of expected folds contain more candidates than Top-k;
4. the 5 km intention-to-evaluate lift over same-pool random has a pair-clustered 95% interval entirely above zero;
5. the result is not driven by a single taxon group or geographic stratum;
6. the direction replicates in at least one additional independent seed cohort.

Weights for access, detectability, phenology, and field feedback are outside this retrospective gate. Random occurrence validation can keep them explicitly unvalidated, but cannot identify their numerical values.

## Development versus confirmation

The `20260702_v2` cohort is a development-set evaluation because sparse-pool fallback was motivated by version 1 results on the same pairs. It is useful for debugging and effect-size estimation, not final confirmation. All subsequent confirmatory samples must use unseen taxon-region pairs and remain untouched by model development until the frozen analysis completes.
