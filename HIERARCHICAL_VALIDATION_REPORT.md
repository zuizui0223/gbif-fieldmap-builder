# Hierarchical ACSP-Discover validation report

## Scope of the supported claim

Given a species name and occurrence records available through GBIF, the built-in workflow ranks five **regional survey-candidate zones**. Retrospective evidence supports recovery of withheld occurrence records within 10 km better than selection of five random zones from the same generated pool. The representative coordinates are not validated exact field sites. Access, detection probability, abundance, phenology, navigability, and discoveries per field day remain outside this claim.

## Frozen hierarchy

1. GBIF backbone metadata assigns a field protocol and broad taxonomic group automatically.
2. The fraction of training occurrences on the reproducible land mask assigns a terrestrial, coastal, marine, or inland-aquatic candidate surface.
3. Terrestrial candidates use local terrain analogues. Birds additionally use broad climate/elevation gradients. Marine candidates use a training-only distance-to-land-band analogue because terrestrial elevation is undefined offshore.
4. Evidence ranking and geographic complementarity select alternative regional zones. Safety, legal access, and short-trip feasibility are applied afterward and are not allowed to alter the ecological recovery endpoint.
5. Marine and aquatic trip estimates use explicitly low-confidence water-transit proxies rather than road-speed language.

## Retrospective design

- Taxon-region pairs were seeded and balanced by plant/animal group, four Japanese geographic strata, and four regional record-count strata.
- Every fold withheld complete 0.1-degree spatial blocks, rebuilt candidates from training records only, removed known-location candidates, and removed occurrence-distance/density score components.
- The endpoint was Top-5 held-out occurrence recall versus random Top-5 selection from the identical candidate pool. A greedy same-pool oracle measured remaining ranking headroom.
- Missing and failed folds received zero in intention-to-evaluate estimates. Confidence intervals resampled taxon-region pairs, not repeated folds. Pair-level sign flips supplied a randomization test.
- Development taxa and every earlier confirmation taxon were excluded by scientific name from later draws. Failed taxa were not replaced.

## Results

### Development cohort

The hierarchical development cohort contained 24 taxon-region pairs and 120 folds. All folds completed; 117/120 were rankable. The predeclared mixed observation-unit endpoint produced recall 0.0841 versus 0.0543 for random selection: lift 0.0297, pair-clustered 95% CI 0.0103–0.0523, sign-flip p=0.0063.

### Independent mixed confirmation

The final mixed cohort contained 24 previously unseen taxa. It completed 119/120 folds, with 117 rankable. At 10 km, animals achieved recall 0.0981 versus 0.0572: lift 0.0408, 95% CI 0.0031–0.0847. The originally declared mixed 5/10 km endpoint did not pass because plant 5 km recovery was unstable; this negative result is retained rather than relabelled.

### Independent plant extension

A further 24 previously unseen plant taxa were drawn without changing the plant algorithm. It completed 115/120 folds. Plant 10 km recall was 0.1074 versus 0.0859: lift 0.0215, 95% CI 0.0002–0.0481. One failed pair remained in the denominator.

Pooling only the two independent, algorithm-compatible confirmation samples yielded 36 plant pairs and 180 expected folds. Plant 10 km recall was 0.1098 versus 0.0912: lift 0.0186, 95% CI 0.0035–0.0374, sign-flip p=0.0233. The 5 km interval crossed zero and is not a supported exact-site claim.

## Interpretation and remaining uncertainty

The evidence supports a cross-taxon 10 km regional-zone prioritization claim: independently confirmed animal and plant estimates both exceed the same-pool random baseline. It does not establish that every taxonomic class performs equally, nor that a representative point is reachable or occupied during a visit. Rare ecological guilds remain thinly sampled, GBIF observation bias is inherited, land/water masks do not replace hydrography or bathymetry, and retrospective presence recovery cannot estimate false absences. Prospective standardized surveys are still required before claims about exact sites, detection, access, abundance, or field efficiency.
