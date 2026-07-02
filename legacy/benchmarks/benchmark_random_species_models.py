"""Seeded multi-species spatial validation of the ACSP macro SDM."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import time
from typing import Any

import numpy as np
import pandas as pd
import requests

from acsp import calibrate_model_ensemble_weights, spatial_model_accuracy_benchmark, stratified_random_taxa
from gbif_fieldmap_builder_app import (
    auto_remote_spatial_outlier_qc,
    build_presence_background,
    clean_environment_table,
    clean_occurrences,
    detect_occurrence_columns,
    extract_environment,
    fetch_gbif_records_representative,
    gbif_occurrence_params,
    gbif_record_to_species_row,
    spatially_balanced_cap,
)


GBIF_SEARCH = "https://api.gbif.org/v1/occurrence/search"
GBIF_SPECIES = "https://api.gbif.org/v1/species"
VARIABLES = ["bio1", "bio4", "bio12", "bio15", "bio14"]


def summarize_model_accuracy(metrics: pd.DataFrame, random_state: int, bootstrap_draws: int = 2000) -> pd.DataFrame:
    columns = ["roc_auc", "pr_auc", "brier", "log_loss", "tss", "calibration_slope", "boyce_spearman"]
    per_taxon = metrics.groupby(["algorithm", "benchmark_taxon"], as_index=False)[columns].mean()
    rng = np.random.default_rng(int(random_state))
    rows = []
    for algorithm, group in per_taxon.groupby("algorithm", sort=True):
        row: dict[str, Any] = {
            "algorithm": algorithm, "successful_taxa": int(len(group)),
            "valid_folds": int(metrics[metrics["algorithm"].eq(algorithm)].shape[0]),
        }
        for column in columns:
            values = pd.to_numeric(group[column], errors="coerce").dropna().to_numpy(float)
            row[f"mean_{column}"] = float(values.mean()) if len(values) else float("nan")
            if len(values):
                samples = rng.choice(values, size=(max(1, int(bootstrap_draws)), len(values)), replace=True).mean(axis=1)
                row[f"{column}_ci_low"] = float(np.quantile(samples, 0.025))
                row[f"{column}_ci_high"] = float(np.quantile(samples, 0.975))
        rows.append(row)
    return pd.DataFrame(rows)


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


def japan_plant_sampling_frame(facet_limit: int, minimum_records: int) -> pd.DataFrame:
    payload = _get_json(GBIF_SEARCH, {
        "kingdomKey": 6, "country": "JP", "hasCoordinate": "true", "hasGeospatialIssue": "false",
        "occurrenceStatus": "PRESENT", "limit": 0, "facet": "speciesKey",
        "facetLimit": int(facet_limit), "facetMincount": int(minimum_records),
    })
    counts = payload.get("facets", [{}])[0].get("counts", [])

    def resolve(item: dict[str, Any]) -> dict[str, Any] | None:
        key = int(item["name"])
        try:
            metadata = _get_json(f"{GBIF_SPECIES}/{key}", timeout=30)
        except (requests.RequestException, ValueError):
            return None
        if metadata.get("rank") != "SPECIES" or not metadata.get("scientificName"):
            return None
        return {"speciesKey": key, "scientific_name": metadata["scientificName"], "coordinate_records": int(item["count"])}

    with ThreadPoolExecutor(max_workers=4) as executor:
        rows = list(executor.map(resolve, counts))
    return pd.DataFrame([row for row in rows if row is not None])


def fetch_species_occurrences(species_key: int, total_count: int, cap: int) -> pd.DataFrame:
    params = gbif_occurrence_params(int(species_key), "JP", None, None)
    records, _ = fetch_gbif_records_representative(params, int(cap), int(total_count), timeout=60)
    raw = pd.DataFrame([gbif_record_to_species_row(record) for record in records])
    return clean_occurrences(raw, detect_occurrence_columns(raw))


def prepare_model_table(occurrences: pd.DataFrame, presence_cap: int, background: int) -> tuple[pd.DataFrame, dict[str, int]]:
    capped = spatially_balanced_cap(occurrences, int(presence_cap))
    qc, excluded, _ = auto_remote_spatial_outlier_qc(capped)
    if len(qc) < 20:
        raise ValueError(f"Only {len(qc)} presences remained after spatial QC; 20 are required.")
    table = build_presence_background(qc, int(background), "bounding box", 10.0, 20.0)
    table = extract_environment(table, VARIABLES, "latitude", "longitude", "power-climatology")
    table, dropped = clean_environment_table(table, VARIABLES, "random-species model benchmark")
    return table, {
        "fetched_records": len(occurrences), "presence_cap_records": len(capped),
        "qc_excluded_records": len(excluded), "model_presences": len(qc),
        "environment_rows_dropped": int(dropped), "model_rows": len(table),
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    frame_path = output / "taxon_sampling_frame.csv"
    sample_path = output / "predeclared_taxon_sample.csv"
    frame = pd.read_csv(frame_path) if frame_path.exists() else japan_plant_sampling_frame(args.facet_limit, args.minimum_records)
    if not frame_path.exists():
        frame.to_csv(frame_path, index=False)
    sample = pd.read_csv(sample_path) if sample_path.exists() else stratified_random_taxa(
        frame, args.taxa, strata=args.strata, random_state=args.seed
    )
    if not sample_path.exists():
        sample.to_csv(sample_path, index=False)
    statuses = []
    for index, row in sample.iterrows():
        prefix = output / f"taxon_{index + 1:03d}"
        metric_path = Path(f"{prefix}_metrics.csv")
        prediction_path = Path(f"{prefix}_predictions.csv")
        if metric_path.exists() and prediction_path.exists():
            statuses.append({"benchmark_taxon": row.scientific_name, "status": "checkpoint"})
            continue
        try:
            occurrences = fetch_species_occurrences(int(row.speciesKey), int(row.coordinate_records), args.records_per_taxon)
            table, counts = prepare_model_table(occurrences, args.presence_cap, args.background)
            metrics, predictions = spatial_model_accuracy_benchmark(
                table, VARIABLES, block_degrees=args.block_degrees, repeats=args.repeats,
                holdout_fraction=args.holdout_fraction, random_state=args.seed + index,
            )
            metrics["benchmark_taxon"] = str(row.scientific_name)
            predictions["benchmark_taxon"] = str(row.scientific_name)
            metrics.to_csv(metric_path, index=False)
            predictions.to_csv(prediction_path, index=False)
            statuses.append({"benchmark_taxon": row.scientific_name, "status": "ok", **counts})
        except Exception as exc:
            statuses.append({"benchmark_taxon": row.scientific_name, "status": "failed", "reason": str(exc)})
        pd.DataFrame(statuses).to_csv(output / "taxon_status.csv", index=False)
    metric_files = sorted(output.glob("taxon_*_metrics.csv"))
    prediction_files = sorted(output.glob("taxon_*_predictions.csv"))
    metrics = pd.concat([pd.read_csv(path) for path in metric_files], ignore_index=True) if metric_files else pd.DataFrame()
    predictions = pd.concat([pd.read_csv(path) for path in prediction_files], ignore_index=True) if prediction_files else pd.DataFrame()
    if not metrics.empty:
        metrics.to_csv(output / "all_model_metrics.csv", index=False)
        summary = summarize_model_accuracy(metrics, args.seed)
        summary.to_csv(output / "model_accuracy_summary.csv", index=False)
    else:
        summary = pd.DataFrame()
    ensemble_calibration = {"status": "insufficient_taxa", "recommend_change": False}
    if not predictions.empty and metrics.get("benchmark_taxon", pd.Series(dtype=str)).nunique() >= 10:
        search, ensemble_calibration = calibrate_model_ensemble_weights(
            predictions, metrics, search_draws=args.ensemble_search_draws,
            train_fraction=args.train_fraction, random_state=args.seed,
        )
        search.to_csv(output / "ensemble_weight_search.csv", index=False)
        ensemble_calibration["status"] = "ok"
    result = {
        "protocol": vars(args), "sampled_taxa": int(len(sample)),
        "successful_taxa": int(metrics["benchmark_taxon"].nunique()) if not metrics.empty else 0,
        "failed_or_incomplete_taxa": int(len(sample) - (metrics["benchmark_taxon"].nunique() if not metrics.empty else 0)),
        "model_summary": summary.to_dict("records"),
        "ensemble_calibration": ensemble_calibration,
        "interpretation": "Retrospective discrimination/calibration benchmark; prospective four-island field detection remains the external test.",
    }
    (output / "benchmark_summary.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description="Run seeded random-species spatial SDM validation.")
    command.add_argument("--output", default="benchmark_results/random_species_models")
    command.add_argument("--taxa", type=int, default=20)
    command.add_argument("--repeats", type=int, default=5)
    command.add_argument("--records-per-taxon", type=int, default=200)
    command.add_argument("--presence-cap", type=int, default=150)
    command.add_argument("--background", type=int, default=500)
    command.add_argument("--minimum-records", type=int, default=50)
    command.add_argument("--facet-limit", type=int, default=300)
    command.add_argument("--strata", type=int, default=4)
    command.add_argument("--seed", type=int, default=20260701)
    command.add_argument("--block-degrees", type=float, default=0.5)
    command.add_argument("--holdout-fraction", type=float, default=0.20)
    command.add_argument("--ensemble-search-draws", type=int, default=500)
    command.add_argument("--train-fraction", type=float, default=0.70)
    return command


if __name__ == "__main__":
    print(json.dumps(run(parser().parse_args()), indent=2, ensure_ascii=False))
