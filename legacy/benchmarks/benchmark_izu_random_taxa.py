"""Predeclared four-island retrospective benchmark for ACSP.

This research runner is intentionally separate from the simple Streamlit UI.
It checkpoints each taxon and never replaces failed sampled taxa.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import time
from typing import Any

import pandas as pd
import requests

from acsp import calibrate_candidate_weights, spatial_block_candidate_benchmark, stratified_random_taxa
from gbif_fieldmap_builder_app import (
    add_automatic_sdm_support,
    build_automatic_discover_bundle,
    clean_occurrences,
    detect_occurrence_columns,
    gbif_record_to_species_row,
)


GBIF_SEARCH = "https://api.gbif.org/v1/occurrence/search"
GBIF_SPECIES = "https://api.gbif.org/v1/species"
ISLAND_BOUNDS = {
    "Izu Oshima": (139.30, 34.64, 139.49, 34.84),
    "Toshima": (139.24, 34.49, 139.30, 34.55),
    "Niijima": (139.20, 34.31, 139.31, 34.48),
    "Kozushima": (139.09, 34.16, 139.23, 34.28),
}


def _polygon(bounds: tuple[float, float, float, float]) -> list[list[float]]:
    west, south, east, north = bounds
    return [[west, south], [east, south], [east, north], [west, north], [west, south]]


def island_features() -> list[dict[str, Any]]:
    return [
        {"type": "Feature", "properties": {"name": name}, "geometry": {"type": "Polygon", "coordinates": [_polygon(bounds)]}}
        for name, bounds in ISLAND_BOUNDS.items()
    ]


def island_wkt() -> str:
    parts = []
    for bounds in ISLAND_BOUNDS.values():
        coordinates = ",".join(f"{lon} {lat}" for lon, lat in _polygon(bounds))
        parts.append(f"(({coordinates}))")
    return f"MULTIPOLYGON({','.join(parts)})"


def _get_json(
    url: str, params: dict[str, Any] | None = None, timeout: int = 60, attempts: int = 3
) -> dict[str, Any]:
    """Fetch JSON while tolerating the short GBIF TLS failures seen in long benchmarks."""
    last_error: Exception | None = None
    for attempt in range(max(1, int(attempts))):
        try:
            response = requests.get(url, params=params, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            if attempt + 1 < max(1, int(attempts)):
                time.sleep(0.5 * (2 ** attempt))
    assert last_error is not None
    raise last_error


def taxon_sampling_frame(facet_limit: int = 300, minimum_records: int = 15) -> pd.DataFrame:
    params = {
        "kingdomKey": 6, "geometry": island_wkt(), "hasCoordinate": "true",
        "hasGeospatialIssue": "false", "occurrenceStatus": "PRESENT", "limit": 0,
        "facet": "speciesKey", "facetLimit": int(facet_limit), "facetMincount": int(minimum_records),
    }
    payload = _get_json(GBIF_SEARCH, params)
    counts = payload.get("facets", [{}])[0].get("counts", [])
    def resolve(item: dict[str, Any]) -> dict[str, Any] | None:
        key = int(item["name"])
        try:
            metadata = _get_json(f"{GBIF_SPECIES}/{key}", timeout=30)
        except (requests.RequestException, ValueError):
            return None
        if metadata.get("rank") == "SPECIES" and metadata.get("scientificName"):
            return {
                "speciesKey": key, "scientific_name": metadata["scientificName"],
                "coordinate_records": int(item["count"]),
            }
        return None
    with ThreadPoolExecutor(max_workers=4) as executor:
        rows = list(executor.map(resolve, counts))
    return pd.DataFrame([row for row in rows if row is not None])


def fetch_occurrences(species_key: int, cap: int) -> pd.DataFrame:
    params = {
        "taxonKey": int(species_key), "geometry": island_wkt(), "hasCoordinate": "true",
        "hasGeospatialIssue": "false", "occurrenceStatus": "PRESENT",
        "limit": min(300, int(cap)), "offset": 0,
    }
    records = _get_json(GBIF_SEARCH, params).get("results", [])
    raw = pd.DataFrame([gbif_record_to_species_row(record) for record in records])
    return clean_occurrences(raw, detect_occurrence_columns(raw))


def _coverage_at_radius(candidates: pd.DataFrame, radius_km: float) -> pd.DataFrame:
    out = candidates.copy()
    all_ids = out["all_heldout_ids"].astype(str).str.split(";")
    distances = out["heldout_distances_km"].astype(str).str.split(";")
    out["covered_heldout_ids"] = [
        ";".join(identifier for identifier, distance in zip(ids, values) if identifier and float(distance) <= radius_km)
        for ids, values in zip(all_ids, distances)
    ]
    return out


def _fold_completion(folds: pd.DataFrame, expected_repeats: int) -> dict[str, Any]:
    valid = int(folds.get("status", pd.Series(dtype=str)).eq("ok").sum())
    if valid == int(expected_repeats):
        status = "ok"
    elif valid > 0:
        status = "partial"
    else:
        status = "failed"
    return {
        "status": status,
        "valid_repeats": valid,
        "attempted_repeats": int(len(folds)),
        "failed_repeats": int(len(folds) - valid),
    }


def _read_candidate_files(paths: list[Path]) -> pd.DataFrame:
    frames = []
    for path in paths:
        try:
            frame = pd.read_csv(path)
        except pd.errors.EmptyDataError:
            continue
        if not frame.empty and "benchmark_taxon" in frame.columns:
            frames.append(frame)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def run(args: argparse.Namespace) -> dict[str, Any]:
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    frame_path = output / "taxon_sampling_frame.csv"
    sample_path = output / "predeclared_taxon_sample.csv"
    frame = pd.read_csv(frame_path) if frame_path.exists() else taxon_sampling_frame(args.facet_limit, args.minimum_records)
    if not frame_path.exists():
        frame.to_csv(frame_path, index=False)
    sample = pd.read_csv(sample_path) if sample_path.exists() else stratified_random_taxa(
        frame, args.taxa, strata=args.strata, random_state=args.seed
    )
    if not sample_path.exists():
        sample.to_csv(sample_path, index=False)

    statuses = []
    for taxon_index, row in sample.iterrows():
        slug = f"taxon_{taxon_index + 1:03d}"
        candidate_path = output / f"{slug}_candidates.csv"
        fold_path = output / f"{slug}_folds.csv"
        if candidate_path.exists() and fold_path.exists():
            folds = pd.read_csv(fold_path)
            statuses.append({
                "benchmark_taxon": row.scientific_name,
                "checkpoint": True,
                **_fold_completion(folds, args.repeats),
            })
            continue
        try:
            occurrences = fetch_occurrences(int(row.speciesKey), args.records_per_taxon)

            def builder(training: pd.DataFrame) -> pd.DataFrame:
                rebuilt = training.copy().reset_index(drop=True)
                rebuilt["_row_id"] = range(len(rebuilt))
                bundle = build_automatic_discover_bundle(
                    str(row.scientific_name), rebuilt, "GBIF four-island benchmark",
                    "predeclared four-island polygons", override_row_ids=rebuilt["_row_id"].tolist(),
                    survey_features=island_features(),
                )
                if args.include_sdm:
                    bundle = add_automatic_sdm_support(bundle)
                return bundle["candidate_pool"]

            candidates, folds, summary = spatial_block_candidate_benchmark(
                occurrences, builder, block_degrees=args.block_degrees, repeats=args.repeats,
                holdout_fraction=args.holdout_fraction, top_k=args.top_k,
                hit_radius_km=max(args.radii), random_draws=args.random_draws,
                random_state=args.seed + taxon_index,
            )
            candidates["benchmark_taxon"] = str(row.scientific_name)
            folds["benchmark_taxon"] = str(row.scientific_name)
            if candidates.empty:
                candidates = pd.DataFrame(columns=["benchmark_taxon"])
            candidates.to_csv(candidate_path, index=False)
            folds.to_csv(fold_path, index=False)
            statuses.append({
                "benchmark_taxon": row.scientific_name,
                **_fold_completion(folds, args.repeats),
                **summary,
            })
        except Exception as exc:
            statuses.append({"benchmark_taxon": row.scientific_name, "status": "failed", "reason": str(exc)})
        pd.DataFrame(statuses).to_csv(output / "taxon_status.csv", index=False)

    # Checkpoint-only taxa use ``continue`` above, so always rewrite the complete audit table.
    pd.DataFrame(statuses).to_csv(output / "taxon_status.csv", index=False)

    candidate_files = sorted(output.glob("taxon_*_candidates.csv"))
    all_candidates = _read_candidate_files(candidate_files)
    radius_summaries = []
    for radius in args.radii:
        if all_candidates.empty:
            radius_summaries.append({"radius_km": radius, "status": "insufficient_taxa"})
            continue
        radius_candidates = _coverage_at_radius(all_candidates, radius)
        radius_candidates.to_csv(output / f"candidate_benchmark_{radius:g}km.csv", index=False)
        if radius_candidates["benchmark_taxon"].nunique() < 4:
            radius_summaries.append({"radius_km": radius, "status": "insufficient_taxa"})
            continue
        search, summary = calibrate_candidate_weights(
            radius_candidates, top_k=args.top_k, search_draws=args.search_draws,
            train_fraction=args.train_fraction, random_state=args.seed,
        )
        search.to_csv(output / f"weight_search_{radius:g}km.csv", index=False)
        summary["radius_km"] = radius
        radius_summaries.append(summary)
    result = {
        "protocol": vars(args), "island_bounds": ISLAND_BOUNDS,
        "sampled_taxa": int(len(sample)),
        "fully_completed_taxa": int(sum(item.get("status") == "ok" for item in statuses)),
        "partially_completed_taxa": int(sum(item.get("status") == "partial" for item in statuses)),
        "failed_taxa": int(sum(item.get("status") == "failed" for item in statuses)),
        "evaluable_taxa": int(all_candidates.get("benchmark_taxon", pd.Series(dtype=str)).nunique()),
        "radius_results": radius_summaries,
    }
    (output / "benchmark_summary.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description="Run the predeclared four-Izu-island ACSP benchmark.")
    command.add_argument("--output", default="benchmark_results/izu_random_taxa")
    command.add_argument("--taxa", type=int, default=20)
    command.add_argument("--repeats", type=int, default=5)
    command.add_argument("--records-per-taxon", type=int, default=150)
    command.add_argument("--minimum-records", type=int, default=15)
    command.add_argument("--facet-limit", type=int, default=300)
    command.add_argument("--strata", type=int, default=4)
    command.add_argument("--seed", type=int, default=20260701)
    command.add_argument("--block-degrees", type=float, default=0.03)
    command.add_argument("--holdout-fraction", type=float, default=0.20)
    command.add_argument("--top-k", type=int, default=5)
    command.add_argument("--radii", type=float, nargs="+", default=[2.0, 5.0, 10.0])
    command.add_argument("--random-draws", type=int, default=200)
    command.add_argument("--search-draws", type=int, default=2000)
    command.add_argument("--train-fraction", type=float, default=0.70)
    command.add_argument("--include-sdm", action="store_true")
    return command


if __name__ == "__main__":
    print(json.dumps(run(parser().parse_args()), indent=2, ensure_ascii=False))
