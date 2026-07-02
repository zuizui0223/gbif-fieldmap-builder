"""Run the species-name-only ACSP-Discover pipeline from the command line."""

from __future__ import annotations

import argparse
import json
import sys

from gbif_fieldmap_builder_app import (
    build_automatic_discover_bundle,
    clean_occurrences,
    detect_occurrence_columns,
    fetch_gbif_occurrences_cached,
    gbif_species_count_cached,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("species")
    parser.add_argument("--cap", type=int, default=1000)
    args = parser.parse_args()

    payload, count, _ = gbif_species_count_cached(args.species, "JP", None, None)
    country_code, country_scope = "JP", "Japan"
    if count == 0:
        payload, count, _ = gbif_species_count_cached(args.species, "", None, None)
        country_code, country_scope = "", "Worldwide fallback"
    message, raw = fetch_gbif_occurrences_cached(args.species, args.cap, country_code, None, None)
    cleaned = clean_occurrences(raw, detect_occurrence_columns(raw))
    bundle = build_automatic_discover_bundle(
        str(payload.get("scientificName") or args.species), cleaned, message, country_scope,
        taxon_metadata=payload,
    )

    plan_sizes = {name: len(plan) for name, plan in bundle["plans"].items()}
    eligible_ids = set(bundle["constraint_audit"].loc[bundle["constraint_audit"]["eligible"], "site_id"].astype(int))
    for name, plan in bundle["plans"].items():
        assert set(plan["site_id"].astype(int)).issubset(eligible_ids), f"{name} contains an ineligible site"
    assert all(size > 0 for size in plan_sizes.values()), "all three plans must contain sites"
    assert bundle["all_candidates"]["site_id"].is_unique, "candidate site IDs must be unique"
    zones = bundle["recommended_zones"]
    assert zones["zone_id"].is_unique, "recommended survey zones must be unique"
    assert zones["representative_site_id"].is_unique, "one representative must not stand for multiple final zones"
    assert bundle["trip_estimate"]["fits_target_days"], "default plan must fit each daily hub-return budget"
    if bundle.get("selected_region"):
        assert float(bundle["selected_region"]["diameter_km"]) <= 80.0, "selected hub is too broad for a short trip"

    result = {
        "requested_species": args.species,
        "matched_species": bundle["scientific_name"],
        "country_scope": country_scope,
        "gbif_coordinate_count": int(count),
        "fetched_records": int(len(cleaned)),
        "scope_summary": bundle["scope_summary"],
        "distribution_summary": bundle["distribution_summary"],
        "region_cards": [
            {key: region[key] for key in ["region_id", "card_role", "record_count", "diameter_km", "center_latitude", "center_longitude"]}
            for region in bundle["region_cards"]
        ],
        "selected_region_id": bundle["selected_region_id"],
        "candidate_grouping_scale_m": bundle["cluster_m"],
        "known_candidates": int(len(bundle["known_candidates"])),
        "potential_candidates": int(len(bundle["potential_candidates"])),
        "potential_cell_sizes_m": sorted(
            bundle["potential_candidates"].get("effective_search_cell_size_m", []).dropna().astype(float).unique().tolist()
        ) if not bundle["potential_candidates"].empty else [],
        "candidate_types": bundle["all_candidates"]["candidate_type"].value_counts().to_dict(),
        "plan_sizes": plan_sizes,
        "recommended_zone_count": int(len(zones)),
        "recommended_zones": zones[[
            "recommended_zone_rank", "zone_id", "primary_zone_role", "zone_score",
            "zone_member_count", "zone_radius_m", "representative_site_id",
            "latitude", "longitude",
        ]].to_dict("records"),
        "automatic_trip_days": int(bundle["target_days"]),
        "reachability_reason": bundle["reachability_reason"],
        "reachability_curve": bundle["reachability_curve"].to_dict("records"),
        "balanced_site_ids": bundle["plans"]["Balanced"]["site_id"].astype(int).tolist(),
        "proposal": bundle["proposal"],
        "trip_estimate": bundle["trip_estimate"],
        "survey_protocol": bundle["survey_protocol"],
        "eligible_with_unknown_constraints": int(
            bundle["constraint_audit"].loc[bundle["constraint_audit"]["eligible"], "unknown_constraints"].astype(str).ne("").sum()
        ),
        "warnings": bundle["warnings"],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str), file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
