# Five-kilometre precision limit audit

## Question

Can the name-only ACSP-Discover workflow move from the independently supported 10 km regional-zone claim to a general 5 km exact-location claim by changing the algorithm alone?

## Decomposition

The independent 24-plant extension completed 115/120 folds. At 5 km, Top-5 recall was 0.0493 versus 0.0379 for same-pool random selection; pair-clustered lift was 0.0114 with 95% CI -0.0067 to 0.0298. The greedy same-pool ceiling was 0.0974. Thus candidate generation leaves useful headroom, but the current evidence cannot rank it reproducibly.

The realised plant candidate cell had a median effective width of about 7 km across development and confirmation runs. Its half diagonal is about 5 km before ecological model error, coordinate uncertainty, land-mask error, or GBIF sampling bias. A representative cell centre therefore cannot support a general 5 km exact-location interpretation.

## Improvements tested and rejected

- A pooled candidate-level recovery ranker using ridge regression, random forest, and ExtraTrees was selected only on development taxa. All three were below random under leave-one-species-out evaluation, indicating sparse held-out hits and species-specific overfitting.
- Increasing the practical list from Top-5 to Top-8 improved mean recall, but the combined independent 35-plant lift still crossed zero (about 0.0105; bootstrap interval approximately -0.0015 to 0.0236).
- Adding broad climate variables and using covariance shrinkage did not improve the development 5 km interval over the simpler terrain model.
- Direct fine GSI point-tile terrain extraction avoided the large-mosaic resolution fallback, but one species with three folds did not complete after three minutes. It violated the name-only rapid-response requirement before a stable effect estimate could be obtained and was removed.

## Final model boundary

The final name-only model retains the independently supported 10 km regional candidate-zone output. Every candidate now carries an automatic precision audit based on grid half diagonal, environmental resolution, and coordinate-uncertainty q75. A 5 km claim is marked unsupported whenever the unavoidable input precision floor exceeds 2.5 km. Passing this technical check would still mean only “eligible for validation,” not validated.

General 5 km exact-site performance requires a different data regime: compact preselected regions plus consistently available fine vegetation/land-cover, hydrography or bathymetry, and access layers. Without those inputs, further score tuning primarily increases overfitting or latency rather than transferable precision.
