"""Seeded general-performance benchmark across random Japanese taxa and regions."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests

from acsp import clustered_recovery_inference, spatial_block_candidate_benchmark
from acsp.benchmarking import coverage_at_radius, fold_completion, get_json
from gbif_fieldmap_builder_app import (
    build_automatic_discover_bundle,
    clean_occurrences,
    detect_occurrence_columns,
    gbif_record_to_species_row,
)
from acsp_discover import primary_recovery_radius_km


GBIF_SEARCH = "https://api.gbif.org/v1/occurrence/search"
GBIF_SPECIES = "https://api.gbif.org/v1/species"
TAXON_GROUPS = {"plant": 6, "animal": 1}

# Fixed cells are declared before outcomes and span major geographic contexts.
REGION_CELLS = [
    ("north", "Hokkaido west", 140.0, 42.5, 142.0, 44.5),
    ("north", "Hokkaido east", 143.0, 42.5, 145.5, 44.5),
    ("north", "Tohoku", 139.5, 38.0, 141.5, 40.5),
    ("east", "Kanto", 138.5, 35.0, 140.5, 36.5),
    ("east", "Izu", 138.8, 34.0, 139.8, 35.0),
    ("east", "Chubu mountains", 136.5, 35.0, 138.5, 37.0),
    ("west", "Kinki", 134.5, 33.5, 136.5, 35.5),
    ("west", "Chugoku", 131.5, 34.0, 134.0, 35.5),
    ("west", "Shikoku", 132.5, 32.7, 134.5, 34.5),
    ("south", "Northern Kyushu", 129.5, 32.5, 131.5, 34.0),
    ("south", "Southern Kyushu", 130.0, 30.8, 131.8, 32.5),
    ("south", "Ryukyu", 126.0, 24.0, 130.0, 28.5),
]


def rectangle_wkt(bounds: tuple[float, float, float, float]) -> str:
    west, south, east, north = bounds
    return f"POLYGON(({west} {south},{east} {south},{east} {north},{west} {north},{west} {south}))"


def rectangle_feature(bounds: tuple[float, float, float, float], name: str) -> dict[str, Any]:
    west, south, east, north = bounds
    return {
        "type": "Feature", "properties": {"name": name},
        "geometry": {"type": "Polygon", "coordinates": [[
            [west, south], [east, south], [east, north], [west, north], [west, south],
        ]]},
    }


@lru_cache(maxsize=4096)
def _species_metadata(key: int) -> dict[str, Any] | None:
    try:
        return get_json(f"{GBIF_SPECIES}/{int(key)}", timeout=30)
    except (requests.RequestException, ValueError):
        return None


def taxon_frame(bounds: tuple[float, float, float, float], kingdom_key: int, facet_limit: int, minimum_records: int) -> pd.DataFrame:
    payload = get_json(GBIF_SEARCH, {
        "kingdomKey": int(kingdom_key), "geometry": rectangle_wkt(bounds),
        "hasCoordinate": "true", "hasGeospatialIssue": "false", "occurrenceStatus": "PRESENT",
        "limit": 0, "facet": "speciesKey", "facetLimit": int(facet_limit),
        "facetMincount": int(minimum_records),
    })
    counts = payload.get("facets", [{}])[0].get("counts", [])

    def resolve(item: dict[str, Any]) -> dict[str, Any] | None:
        key = int(item["name"])
        metadata = _species_metadata(key)
        if metadata is None:
            return None
        if metadata.get("rank") != "SPECIES" or not metadata.get("scientificName"):
            return None
        return {
            "speciesKey": key, "scientific_name": metadata["scientificName"],
            "coordinate_records": int(item["count"]),
        }

    with ThreadPoolExecutor(max_workers=8) as executor:
        rows = list(executor.map(resolve, counts))
    return pd.DataFrame([row for row in rows if row is not None])


def predeclare_pairs(
    pair_count: int,
    seed: int,
    facet_limit: int,
    minimum_records: int,
    excluded_taxa: set[str] | None = None,
    taxon_groups: list[str] | None = None,
) -> pd.DataFrame:
    rng = np.random.default_rng(int(seed))
    cells = pd.DataFrame(REGION_CELLS, columns=["geographic_stratum", "region_name", "west", "south", "east", "north"])
    selected_rows = []
    used_taxa: set[str] = set(map(str, excluded_taxa or set()))
    strata = list(dict.fromkeys(cells["geographic_stratum"]))
    groups = list(taxon_groups or TAXON_GROUPS)
    invalid_groups = set(groups).difference(TAXON_GROUPS)
    if invalid_groups:
        raise ValueError(f"Unknown taxon groups: {', '.join(sorted(invalid_groups))}")
    frame_cache: dict[tuple[str, str], pd.DataFrame] = {}
    for index in range(int(pair_count)):
        geographic = strata[index % len(strata)]
        choices = cells[cells["geographic_stratum"].eq(geographic)]
        cell = choices.iloc[int(rng.integers(0, len(choices)))]
        group = groups[(index // len(strata)) % len(groups)]
        bounds = (float(cell.west), float(cell.south), float(cell.east), float(cell.north))
        cache_key = (str(cell.region_name), group)
        if cache_key not in frame_cache:
            frame_cache[cache_key] = taxon_frame(bounds, TAXON_GROUPS[group], facet_limit, minimum_records)
        frame = frame_cache[cache_key].copy()
        if frame.empty:
            selected_rows.append({"pair_id": index + 1, "status": "empty_sampling_frame"})
            continue
        frame = frame[~frame["scientific_name"].astype(str).isin(used_taxa)].copy()
        if frame.empty:
            selected_rows.append({"pair_id": index + 1, "status": "no_unused_taxon"})
            continue
        bins = min(4, frame["coordinate_records"].nunique(), len(frame))
        frame["record_count_stratum"] = pd.qcut(
            frame["coordinate_records"].rank(method="first"), bins, labels=False
        )
        desired = index % bins
        pool = frame[frame["record_count_stratum"].eq(desired)]
        chosen = pool.iloc[int(rng.integers(0, len(pool)))]
        used_taxa.add(str(chosen.scientific_name))
        selected_rows.append({
            "pair_id": index + 1, "status": "predeclared", "taxon_group": group,
            "kingdomKey": TAXON_GROUPS[group], "geographic_stratum": geographic,
            "region_name": str(cell.region_name), "west": bounds[0], "south": bounds[1],
            "east": bounds[2], "north": bounds[3], "speciesKey": int(chosen.speciesKey),
            "scientific_name": str(chosen.scientific_name),
            "coordinate_records": int(chosen.coordinate_records),
            "record_count_stratum": int(chosen.record_count_stratum),
        })
    return pd.DataFrame(selected_rows)


def fetch_occurrences(row: pd.Series, cap: int) -> pd.DataFrame:
    bounds = (float(row.west), float(row.south), float(row.east), float(row.north))
    payload = get_json(GBIF_SEARCH, {
        "taxonKey": int(row.speciesKey), "geometry": rectangle_wkt(bounds),
        "hasCoordinate": "true", "hasGeospatialIssue": "false", "occurrenceStatus": "PRESENT",
        "limit": min(300, int(cap)), "offset": 0,
    })
    raw = pd.DataFrame([gbif_record_to_species_row(record) for record in payload.get("results", [])])
    return clean_occurrences(raw, detect_occurrence_columns(raw))


def summarize_recovery(candidates: pd.DataFrame, radius: float, top_k: int, seed: int) -> list[dict[str, Any]]:
    work = coverage_at_radius(candidates, radius)
    rng = np.random.default_rng(int(seed))
    rows = []
    group_columns = ["benchmark_taxon", "benchmark_region", "taxon_group", "geographic_stratum"]
    group_columns.extend(
        column for column in ("taxon_class", "surface_domain", "primary_radius_km")
        if column in work.columns
    )
    group_columns.append("repeat")
    for keys, fold in work.groupby(group_columns, sort=False):
        all_ids = set(filter(None, str(fold["all_heldout_ids"].iloc[0]).split(";")))
        if not all_ids:
            continue
        k = min(int(top_k), len(fold))
        if "validation_selection_rank" in fold.columns and pd.to_numeric(fold["validation_selection_rank"], errors="coerce").notna().any():
            chosen = fold[pd.to_numeric(fold["validation_selection_rank"], errors="coerce").notna()].sort_values(
                "validation_selection_rank"
            ).head(k)
        else:
            chosen = fold.nlargest(k, "integrated_support_score")
        default_ids = set(filter(None, ";".join(chosen["covered_heldout_ids"].astype(str)).split(";")))
        random_values = []
        for _ in range(200):
            indices = rng.choice(len(fold), size=k, replace=False)
            ids = set(filter(None, ";".join(fold.iloc[indices]["covered_heldout_ids"].astype(str)).split(";")))
            random_values.append(len(ids) / len(all_ids))
        remaining = [set(filter(None, str(value).split(";"))) for value in fold["covered_heldout_ids"]]
        oracle: set[str] = set()
        for _ in range(k):
            best = max(range(len(remaining)), key=lambda i: len(remaining[i] - oracle))
            oracle.update(remaining.pop(best))
        rows.append({
            **dict(zip(group_columns, keys)), "radius_km": float(radius),
            "candidate_pool": int(len(fold)), "effective_top_k": int(k),
            "rankable_fold": bool(len(fold) > int(top_k)),
            "default_recall": len(default_ids) / len(all_ids),
            "random_recall": float(np.mean(random_values)),
            "greedy_oracle_recall": len(oracle) / len(all_ids),
        })
    return rows


def run(args: argparse.Namespace) -> dict[str, Any]:
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    sample_path = output / "predeclared_taxon_region_pairs.csv"
    excluded_taxa: set[str] = set()
    for exclusion_path in args.exclude_sample or []:
        exclusion = pd.read_csv(exclusion_path)
        if "scientific_name" not in exclusion.columns:
            raise ValueError("Exclusion sample requires a scientific_name column.")
        excluded_taxa.update(exclusion["scientific_name"].dropna().astype(str))
    if sample_path.exists():
        sample = pd.read_csv(sample_path)
    elif args.sample_file:
        sample = pd.read_csv(args.sample_file).head(int(args.pairs)).copy()
    else:
        sample = predeclare_pairs(
            args.pairs, args.seed, args.facet_limit, args.minimum_records, excluded_taxa,
            list(args.taxon_groups),
        )
    if not sample_path.exists():
        sample.to_csv(sample_path, index=False)
    statuses = []
    for _, row in sample[sample["status"].eq("predeclared")].iterrows():
        slug = f"pair_{int(row.pair_id):03d}"
        candidate_path, fold_path = output / f"{slug}_candidates.csv", output / f"{slug}_folds.csv"
        if candidate_path.exists() and fold_path.exists():
            folds = pd.read_csv(fold_path)
            statuses.append({"pair_id": int(row.pair_id), "scientific_name": row.scientific_name, "checkpoint": True, **fold_completion(folds, args.repeats)})
            continue
        try:
            occurrences = fetch_occurrences(row, args.records_per_pair)
            bounds = (float(row.west), float(row.south), float(row.east), float(row.north))

            def builder(training: pd.DataFrame) -> pd.DataFrame:
                rebuilt = training.copy().reset_index(drop=True)
                rebuilt["_row_id"] = range(len(rebuilt))
                metadata = _species_metadata(int(row.speciesKey)) or {}
                metadata.setdefault("kingdom", "Plantae" if row.taxon_group == "plant" else "Animalia")
                bundle = build_automatic_discover_bundle(
                    str(row.scientific_name), rebuilt, "general benchmark",
                    str(row.region_name), override_row_ids=rebuilt["_row_id"].tolist(),
                    taxon_metadata=metadata,
                    survey_bounds=bounds, survey_features=[rectangle_feature(bounds, str(row.region_name))],
                    candidate_generation_only=True,
                )
                # Measure ecological candidate generation/ranking before the
                # separate logistics and safety screen.  Using candidate_pool
                # here mixed dangerous-slope/access exclusions into a habitat
                # recovery endpoint and often left <= top_k cells, making the
                # ranking statistically unidentifiable.  The production bundle
                # still applies hard constraints before making a field plan.
                potential = bundle["potential_candidates"].copy()
                taxon_class = str(metadata.get("class") or "unknown").lower()
                surface_domain = str(bundle.get("surface_domain") or "terrestrial")
                potential["taxon_class"] = taxon_class
                potential["primary_radius_km"] = primary_recovery_radius_km(
                    metadata, surface_domain=surface_domain
                )
                return potential

            candidates, folds, _ = spatial_block_candidate_benchmark(
                occurrences, builder, block_degrees=args.block_degrees, repeats=args.repeats,
                holdout_fraction=args.holdout_fraction, top_k=args.top_k,
                hit_radius_km=max(args.radii), random_draws=args.random_draws,
                random_state=args.seed + int(row.pair_id),
                # Development-only sensitivity analysis selected stronger local
                # habitat evidence for both groups. Animals retain 25%
                # geographic complementarity; plants use pure habitat ordering
                # at this candidate-screening stage.
                selection_evidence_weight=1.0 if str(row.taxon_group) == "plant" else 0.75,
                selection_score_col="component_local_habitat_score",
            )
            for frame in (candidates, folds):
                frame["benchmark_taxon"] = str(row.scientific_name)
                frame["benchmark_region"] = str(row.region_name)
                frame["taxon_group"] = str(row.taxon_group)
                frame["geographic_stratum"] = str(row.geographic_stratum)
            (candidates if not candidates.empty else pd.DataFrame(columns=["benchmark_taxon"])).to_csv(candidate_path, index=False)
            folds.to_csv(fold_path, index=False)
            statuses.append({"pair_id": int(row.pair_id), "scientific_name": row.scientific_name, **fold_completion(folds, args.repeats)})
        except Exception as exc:
            statuses.append({"pair_id": int(row.pair_id), "scientific_name": row.scientific_name, "status": "failed", "reason": str(exc)})
        pd.DataFrame(statuses).to_csv(output / "pair_status.csv", index=False)
    pd.DataFrame(statuses).to_csv(output / "pair_status.csv", index=False)
    frames = []
    for path in sorted(output.glob("pair_*_candidates.csv")):
        try:
            frame = pd.read_csv(path)
        except pd.errors.EmptyDataError:
            continue
        if not frame.empty and set(["benchmark_taxon", "benchmark_region"]).issubset(frame.columns):
            frames.append(frame)
    candidates = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    recovery_rows = []
    if not candidates.empty:
        for radius in args.radii:
            recovery_rows.extend(summarize_recovery(candidates, radius, args.top_k, args.seed))
    recovery = pd.DataFrame(recovery_rows)
    recovery.to_csv(output / "fold_recovery.csv", index=False)
    primary = pd.DataFrame()
    if not recovery.empty and "primary_radius_km" in recovery.columns:
        primary = recovery[
            np.isclose(
                pd.to_numeric(recovery["radius_km"], errors="coerce"),
                pd.to_numeric(recovery["primary_radius_km"], errors="coerce"),
            )
        ].copy()
        primary.to_csv(output / "primary_endpoint_recovery.csv", index=False)
    cohort = pd.DataFrame()
    if not recovery.empty:
        cohort = recovery.groupby(["radius_km", "taxon_group", "geographic_stratum"], as_index=False).agg(
            folds=("repeat", "size"), default_recall=("default_recall", "mean"),
            random_recall=("random_recall", "mean"), greedy_oracle_recall=("greedy_oracle_recall", "mean"),
            rankable_folds=("rankable_fold", "sum"), median_candidate_pool=("candidate_pool", "median"),
        )
        cohort["lift_over_random"] = cohort["default_recall"] - cohort["random_recall"]
        rankable = recovery[recovery["rankable_fold"]].groupby(
            ["radius_km", "taxon_group", "geographic_stratum"], as_index=False
        ).agg(
            rankable_default_recall=("default_recall", "mean"),
            rankable_random_recall=("random_recall", "mean"),
            rankable_oracle_recall=("greedy_oracle_recall", "mean"),
        )
        cohort = cohort.merge(rankable, on=["radius_km", "taxon_group", "geographic_stratum"], how="left")
    cohort.to_csv(output / "cohort_summary.csv", index=False)
    robust = pd.DataFrame()
    if not recovery.empty:
        declared = sample[sample["status"].eq("predeclared")].rename(
            columns={"scientific_name": "benchmark_taxon"}
        )
        robust = clustered_recovery_inference(
            recovery, declared, repeats=args.repeats,
            bootstrap_draws=args.bootstrap_draws, permutation_draws=args.permutation_draws,
            random_state=args.seed,
        )
    robust.to_csv(output / "robust_inference.csv", index=False)
    primary_inference = pd.DataFrame()
    if not primary.empty:
        endpoint = primary.copy()
        endpoint["radius_km"] = 0.0
        endpoint["primary_endpoint_group"] = "all_taxa"
        declared_endpoint = sample[sample["status"].eq("predeclared")].rename(
            columns={"scientific_name": "benchmark_taxon"}
        ).copy()
        declared_endpoint["primary_endpoint_group"] = "all_taxa"
        primary_inference = clustered_recovery_inference(
            endpoint, declared_endpoint, repeats=args.repeats,
            group_col="primary_endpoint_group",
            bootstrap_draws=args.bootstrap_draws,
            permutation_draws=args.permutation_draws,
            random_state=args.seed,
        ).rename(columns={"radius_km": "mixed_primary_endpoint"})
    primary_inference.to_csv(output / "primary_endpoint_inference.csv", index=False)
    result = {
        "protocol": vars(args), "predeclared_pairs": int(len(sample)),
        "evaluable_pairs": int(candidates[["benchmark_taxon", "benchmark_region"]].drop_duplicates().shape[0]) if not candidates.empty else 0,
        "status_counts": pd.Series([item.get("status", "unknown") for item in statuses]).value_counts().to_dict(),
        "cohort_summary": cohort.to_dict("records"),
        "robust_inference": json.loads(robust.to_json(orient="records")),
        "primary_endpoint_inference": json.loads(primary_inference.to_json(orient="records")),
        "interpretation": "General performance across predeclared taxon-group, record-count, and geographic strata. Robust inference assigns zero recovery to missing/failed folds and clusters uncertainty by taxon-region pair.",
    }
    (output / "benchmark_summary.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description="Run stratified random taxon-by-region ACSP validation.")
    command.add_argument("--output", default="benchmark_results/general_random_taxa_regions")
    command.add_argument("--pairs", type=int, default=24)
    command.add_argument("--repeats", type=int, default=5)
    command.add_argument("--records-per-pair", type=int, default=150)
    command.add_argument("--minimum-records", type=int, default=20)
    command.add_argument("--facet-limit", type=int, default=160)
    command.add_argument(
        "--taxon-groups", nargs="+", choices=sorted(TAXON_GROUPS),
        default=list(TAXON_GROUPS),
        help="Taxon groups included in a newly drawn cohort.",
    )
    command.add_argument("--seed", type=int, default=20260702)
    command.add_argument(
        "--exclude-sample", action="append", default=[],
        help="CSV whose scientific_name taxa are excluded; repeat for multiple development/confirmation cohorts.",
    )
    command.add_argument("--sample-file", default="", help="Reuse a frozen sample CSV; --pairs limits it for development runs.")
    command.add_argument("--block-degrees", type=float, default=0.10)
    command.add_argument("--holdout-fraction", type=float, default=0.20)
    command.add_argument("--top-k", type=int, default=5)
    command.add_argument("--radii", type=float, nargs="+", default=[2.0, 5.0, 10.0])
    command.add_argument("--random-draws", type=int, default=200)
    command.add_argument("--bootstrap-draws", type=int, default=5000)
    command.add_argument("--permutation-draws", type=int, default=20000)
    return command


if __name__ == "__main__":
    print(json.dumps(run(parser().parse_args()), indent=2, ensure_ascii=False))
