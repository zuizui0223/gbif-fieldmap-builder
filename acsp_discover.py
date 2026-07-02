"""Core, UI-independent ACSP-Discover v1 planning primitives.

The functions in this module turn an already generated candidate table into
three transparent survey plans.  SDM values are optional evidence; they are
never required to produce a plan.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Mapping, Optional

import numpy as np
import pandas as pd

from acsp.planning import integrated_candidate_scores


EARTH_RADIUS_M = 6_371_008.8
PLAN_ORDER = ("Balanced", "Discovery", "Learning")
SURFACE_DOMAINS = ("terrestrial", "inland_aquatic", "coastal", "marine")


def infer_surface_domain(
    taxon_metadata: Optional[Mapping[str, object]] = None,
    *,
    occurrence_land_fraction: Optional[float] = None,
) -> str:
    """Infer the candidate surface without requiring a second user input.

    Taxonomy supplies a conservative prior; the observed fraction of records
    falling on the land mask overrides it for marine/coastal species.  This is
    a candidate-surface decision, not a claim about species ecology.
    """
    metadata = {str(key).lower(): str(value or "").strip().lower() for key, value in (taxon_metadata or {}).items()}
    kingdom = metadata.get("kingdom", "")
    clazz = metadata.get("class", "")
    fraction = None if occurrence_land_fraction is None else float(np.clip(occurrence_land_fraction, 0.0, 1.0))
    if kingdom in {"plantae", "viridiplantae"}:
        return "terrestrial"
    aquatic_classes = {"actinopterygii", "chondrichthyes", "myxini", "cephalaspidomorphi"}
    if fraction is not None:
        if fraction <= 0.20:
            return "marine"
        if fraction <= 0.65:
            return "coastal"
    if clazz in aquatic_classes:
        return "inland_aquatic"
    return "terrestrial"


def primary_recovery_radius_km(
    taxon_metadata: Optional[Mapping[str, object]] = None,
    *,
    surface_domain: str = "terrestrial",
) -> float:
    """Predeclared retrospective scale for unlike biological observation units."""
    metadata = {str(key).lower(): str(value or "").strip().lower() for key, value in (taxon_metadata or {}).items()}
    if str(surface_domain) in {"marine", "coastal", "inland_aquatic"}:
        return 10.0
    if metadata.get("class", "") in {"aves", "mammalia"}:
        return 10.0
    return 5.0


def spatial_precision_audit(
    effective_cell_size_m: float,
    *,
    environmental_resolution_m: Optional[float] = None,
    coordinate_uncertainty_q75_m: Optional[float] = None,
    target_radius_km: float = 5.0,
) -> dict[str, object]:
    """State whether a grid can technically support a fine-radius claim.

    The half diagonal is the worst-case centre quantisation error before any
    ecological ranking error. A fine claim needs at least half of the target
    radius left for model error; this is a technical eligibility check, not a
    validation result.
    """
    cell_m = max(0.0, float(effective_cell_size_m))
    target_m = max(1.0, float(target_radius_km) * 1000.0)
    quantisation_m = cell_m / math.sqrt(2.0)
    environment_m = max(0.0, float(environmental_resolution_m or 0.0))
    uncertainty_m = max(0.0, float(coordinate_uncertainty_q75_m or 0.0))
    precision_floor_m = max(quantisation_m, environment_m, uncertainty_m)
    eligible = precision_floor_m <= target_m / 2.0
    limiting = max(
        (("grid half-diagonal", quantisation_m), ("environmental resolution", environment_m), ("coordinate uncertainty q75", uncertainty_m)),
        key=lambda item: item[1],
    )[0]
    return {
        "target_radius_km": float(target_radius_km),
        "precision_floor_km": round(precision_floor_m / 1000.0, 3),
        "technical_eligibility": bool(eligible),
        "status": "technically eligible but not retrospectively validated" if eligible else "unsupported at current input resolution",
        "limiting_factor": limiting,
        "reason": (
            f"{limiting} implies a {precision_floor_m / 1000.0:.2f} km precision floor; "
            f"the {target_radius_km:.1f} km target reserves only {target_radius_km / 2.0:.2f} km for input quantisation."
        ),
    }


@dataclass(frozen=True)
class ResolutionDecision:
    cell_size_m: int
    required_resolution_m: float
    search_radius_m: int
    data_quality: str
    reason: str


@dataclass(frozen=True)
class SurveyProtocol:
    """Conservative field-effort defaults inferred from coarse taxonomy."""

    protocol_id: str
    taxon_group: str
    method: str
    observation_unit: str
    daily_window: str
    daily_field_hours: float
    search_minutes_per_cell: int
    access_buffer_minutes_per_cell: int
    minimum_repeat_visits: int
    movement_caution: str
    weather_caution: str
    confidence: str

    def as_dict(self) -> dict[str, object]:
        return {
            "protocol_id": self.protocol_id,
            "taxon_group": self.taxon_group,
            "method": self.method,
            "observation_unit": self.observation_unit,
            "daily_window": self.daily_window,
            "daily_field_hours": self.daily_field_hours,
            "search_minutes_per_cell": self.search_minutes_per_cell,
            "access_buffer_minutes_per_cell": self.access_buffer_minutes_per_cell,
            "minimum_repeat_visits": self.minimum_repeat_visits,
            "movement_caution": self.movement_caution,
            "weather_caution": self.weather_caution,
            "confidence": self.confidence,
        }


def infer_survey_protocol(taxon_metadata: Optional[Mapping[str, object]] = None) -> SurveyProtocol:
    """Infer a transparent broad protocol; never pretend it is species-specific.

    GBIF backbone fields are sufficient to avoid treating a plant, bird, fish,
    and amphibian as the same field object.  They are not sufficient to choose
    a publication-ready method, so every profile retains an explicit caution.
    """
    metadata = {str(key).lower(): str(value or "").strip().lower() for key, value in (taxon_metadata or {}).items()}
    kingdom = metadata.get("kingdom", "")
    clazz = metadata.get("class", "")

    common = {
        "observation_unit": "candidate cell",
        "weather_caution": "Verify local weather, season, detectability, permissions, and safety before departure.",
    }
    if kingdom in {"plantae", "viridiplantae"}:
        return SurveyProtocol(
            "vascular-plant-reconnaissance", "plant", "slow visual search with voucher-quality photographs",
            daily_window="daylight; match flowering or fruiting period", daily_field_hours=8.0,
            search_minutes_per_cell=90, access_buffer_minutes_per_cell=20, minimum_repeat_visits=1,
            movement_caution="Records represent stationary individuals, but coordinates may be generalized or cultivated.",
            confidence="medium", **common,
        )
    if clazz == "aves":
        return SurveyProtocol(
            "bird-point-count-reconnaissance", "bird", "stationary point count plus habitat notes",
            daily_window="dawn-focused detection window", daily_field_hours=5.5,
            search_minutes_per_cell=30, access_buffer_minutes_per_cell=15, minimum_repeat_visits=2,
            movement_caution="Mobile detections are not population locations; avoid interpreting one record as a stationary colony.",
            weather_caution="Avoid strong wind and rain; repeated visits are normally needed for non-detection inference.",
            observation_unit="point-count station", confidence="medium",
        )
    if clazz in {"amphibia", "reptilia"}:
        group = "amphibian" if clazz == "amphibia" else "reptile"
        return SurveyProtocol(
            f"{group}-active-search-reconnaissance", group, "standardized timed active search",
            daily_window="evening/night for amphibians; suitable thermal window for reptiles", daily_field_hours=6.0,
            search_minutes_per_cell=60, access_buffer_minutes_per_cell=25, minimum_repeat_visits=2,
            movement_caution="Detection is strongly conditional on microhabitat and activity period.",
            weather_caution="Rainfall, temperature, and recent weather must be checked; a single non-detection is weak evidence.",
            observation_unit="timed search reach", confidence="low",
        )
    if clazz in {"insecta", "arachnida"}:
        return SurveyProtocol(
            "terrestrial-arthropod-reconnaissance", "terrestrial arthropod", "standardized timed visual/net/trap reconnaissance",
            daily_window="species activity window; often weather-limited", daily_field_hours=7.0,
            search_minutes_per_cell=60, access_buffer_minutes_per_cell=20, minimum_repeat_visits=2,
            movement_caution="Life stage, host association, and short activity periods can dominate apparent distribution.",
            weather_caution="Wind, rain, temperature, and time of day can invalidate comparisons between sites.",
            observation_unit="standardized search station", confidence="low",
        )
    if clazz == "mammalia":
        return SurveyProtocol(
            "mammal-sign-reconnaissance", "mammal", "timed sign/transect reconnaissance; camera design requires a separate deployment plan",
            daily_window="species-dependent; many taxa require nocturnal or multi-day sampling", daily_field_hours=7.0,
            search_minutes_per_cell=75, access_buffer_minutes_per_cell=25, minimum_repeat_visits=2,
            movement_caution="Mobile detections and signs may represent large home ranges rather than local populations.",
            weather_caution="Survey method, latency, and repeat effort must be set from the focal species ecology.",
            observation_unit="sign/transect station", confidence="low",
        )
    if clazz in {"actinopterygii", "chondrichthyes", "myxini", "cephalaspidomorphi"}:
        return SurveyProtocol(
            "aquatic-fish-reconnaissance", "fish", "waterbody/reach reconnaissance before gear-specific sampling",
            daily_window="daylight access window unless species protocol says otherwise", daily_field_hours=7.0,
            search_minutes_per_cell=120, access_buffer_minutes_per_cell=35, minimum_repeat_visits=2,
            movement_caution="Road distance is a poor proxy for connected aquatic distance; barriers and catchments must be verified.",
            weather_caution="Flow, tide, water level, permits, biosecurity, and gear requirements can dominate feasibility.",
            observation_unit="waterbody or stream reach", confidence="low",
        )
    if kingdom == "animalia":
        return SurveyProtocol(
            "animal-reconnaissance-generic", "other animal", "taxon-appropriate timed reconnaissance",
            daily_window="species activity window", daily_field_hours=7.0,
            search_minutes_per_cell=60, access_buffer_minutes_per_cell=20, minimum_repeat_visits=2,
            movement_caution="Mobility and detectability are unknown at this taxonomic resolution.",
            weather_caution="Choose a species-specific detection method before treating non-detection as absence.",
            observation_unit="survey station", confidence="low",
        )
    return SurveyProtocol(
        "unknown-taxon-reconnaissance", "unknown", "generic timed reconnaissance",
        daily_window="verify from focal-species ecology", daily_field_hours=7.0,
        search_minutes_per_cell=75, access_buffer_minutes_per_cell=25, minimum_repeat_visits=2,
        movement_caution="Taxonomic metadata were insufficient to infer mobility or spatial independence.",
        weather_caution="A species-specific method must be selected before interpreting non-detections.",
        observation_unit="candidate station", confidence="low",
    )


PLAN_WEIGHTS: dict[str, dict[str, float]] = {
    "Balanced": {
        "discovery": 0.30, "learning": 0.15, "representation": 0.20,
        "survey_gap": 0.10, "accessibility": 0.15, "travel": 0.05,
        "redundancy": 0.10,
    },
    "Discovery": {
        "discovery": 0.55, "learning": 0.05, "representation": 0.10,
        "survey_gap": 0.10, "accessibility": 0.20, "travel": 0.05,
        "redundancy": 0.05,
    },
    "Learning": {
        "discovery": 0.10, "learning": 0.45, "representation": 0.25,
        "survey_gap": 0.10, "accessibility": 0.10, "travel": 0.05,
        "redundancy": 0.10,
    },
}

PLAN_MINIMUM_TYPE_COUNTS: dict[str, dict[str, int]] = {
    "Balanced": {"known": 2, "discovery": 3, "learning": 1},
    "Discovery": {"known": 1, "discovery": 4, "learning": 0},
    "Learning": {"known": 1, "discovery": 1, "learning": 3},
}


def _pairwise_haversine_m(coords: np.ndarray) -> np.ndarray:
    lat = np.radians(coords[:, 0])
    lon = np.radians(coords[:, 1])
    dlat = lat[:, None] - lat[None, :]
    dlon = lon[:, None] - lon[None, :]
    a = np.sin(dlat / 2.0) ** 2 + np.cos(lat[:, None]) * np.cos(lat[None, :]) * np.sin(dlon / 2.0) ** 2
    return 2.0 * EARTH_RADIUS_M * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def _connected_cluster_labels(distances_m: np.ndarray, threshold_m: float) -> np.ndarray:
    """Single-link connected components; singleton components are noise (-1)."""
    n = distances_m.shape[0]
    adjacency = distances_m <= float(threshold_m)
    np.fill_diagonal(adjacency, False)
    labels = np.full(n, -1, dtype=int)
    unseen = set(range(n))
    next_label = 0
    while unseen:
        seed = unseen.pop()
        component = {seed}
        frontier = [seed]
        while frontier:
            current = frontier.pop()
            neighbours = set(np.flatnonzero(adjacency[current]).tolist()) & unseen
            unseen -= neighbours
            component |= neighbours
            frontier.extend(neighbours)
        if len(component) >= 2:
            labels[list(component)] = next_label
            next_label += 1
    return labels


def parse_field_results(validation: pd.DataFrame, target_col: str) -> pd.DataFrame:
    """Return determinate presence labels; non-detections caused by other states are omitted."""
    if validation is None or validation.empty or "site_id" not in validation.columns or target_col not in validation.columns:
        return pd.DataFrame(columns=["site_id", "_field_success"])
    labels = validation[["site_id", target_col]].copy()
    labels["site_id"] = pd.to_numeric(labels["site_id"], errors="coerce")
    truth = labels[target_col].astype(str).str.lower().str.strip()
    success_values = {"1", "true", "yes", "y", "present", "found", "detected", "success"}
    absence_values = {"0", "false", "no", "n", "absent", "not_found", "not found", "failure"}
    usable = truth.isin(success_values | absence_values)
    labels = labels.loc[usable].copy()
    labels["_field_success"] = truth.loc[usable].isin(success_values)
    return labels[["site_id", "_field_success"]].dropna(subset=["site_id"]).drop_duplicates("site_id")


def preferred_survey_window(values: object) -> str:
    """Return the most frequent determinate phenology window or an honest fallback."""
    series = pd.Series(values, dtype=object).dropna().astype(str).str.strip()
    series = series[~series.str.lower().isin({"", "nan", "none", "<na>", "unknown"})]
    modes = series.mode(dropna=True)
    return str(modes.iloc[0]) if not modes.empty else "Unknown; verify phenology locally"


def infer_default_survey_scope(
    occurrences: pd.DataFrame,
    *,
    latitude_col: str = "_latitude",
    longitude_col: str = "_longitude",
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, object]]:
    """Select one coherent default field region and classify remote records.

    The largest density-connected range becomes the ordinary survey frame.
    Other stable clusters are retained in the audit as disjunct ranges; isolated
    points are possible remote noise. Nothing is deleted from the audit.
    """
    if occurrences is None or occurrences.empty:
        empty = pd.DataFrame() if occurrences is None else occurrences.copy()
        return empty, empty, {"scope_status": "empty", "cluster_eps_m": None, "main_records": 0}
    work = occurrences.dropna(subset=[latitude_col, longitude_col]).copy().reset_index(drop=True)
    if len(work) < 5:
        audit = work[[c for c in ("_row_id", latitude_col, longitude_col) if c in work.columns]].copy()
        audit["scope_class"] = "main_range"
        return work, audit, {
            "scope_status": "all_records_small_sample", "cluster_eps_m": None,
            "main_records": int(len(work)), "disjunct_records": 0, "possible_noise_records": 0,
        }

    coords = work[[latitude_col, longitude_col]].to_numpy(dtype=float)
    pairwise_m = _pairwise_haversine_m(coords)
    np.fill_diagonal(pairwise_m, np.inf)
    nearest_m = np.min(pairwise_m, axis=1)
    positive_nearest = nearest_m[np.isfinite(nearest_m) & (nearest_m > 0)]
    q75 = float(np.quantile(positive_nearest, 0.75)) if positive_nearest.size else 5_000.0
    cluster_eps_m = float(np.clip(q75 * 3.0, 10_000.0, 120_000.0))
    labels = _connected_cluster_labels(pairwise_m, cluster_eps_m)
    work["_auto_scope_cluster"] = labels
    counts = work.loc[work["_auto_scope_cluster"] >= 0, "_auto_scope_cluster"].value_counts()
    if counts.empty:
        audit = work[[c for c in ("_row_id", latitude_col, longitude_col) if c in work.columns]].copy()
        audit["scope_class"] = "main_range"
        return work.drop(columns=["_auto_scope_cluster"]), audit, {
            "scope_status": "no_stable_cluster_all_records", "cluster_eps_m": round(cluster_eps_m, 1),
            "main_records": int(len(work)), "disjunct_records": 0, "possible_noise_records": 0,
        }

    main_cluster = int(counts.index[0])
    stable_threshold = max(3, int(math.ceil(len(work) * 0.01)))
    stable_disjuncts = {int(label) for label, count in counts.items() if int(label) != main_cluster and int(count) >= stable_threshold}
    scope_class = np.full(len(work), "possible_remote_noise", dtype=object)
    scope_class[labels == main_cluster] = "main_range"
    if stable_disjuncts:
        scope_class[np.isin(labels, list(stable_disjuncts))] = "disjunct_range"
    work["_scope_class"] = scope_class
    selected = work[work["_scope_class"].eq("main_range")].drop(columns=["_auto_scope_cluster"]).reset_index(drop=True)
    audit_cols = [c for c in ("_row_id", latitude_col, longitude_col, "_auto_scope_cluster", "_scope_class") if c in work.columns]
    audit = work[audit_cols].rename(columns={"_scope_class": "scope_class"}).copy()
    return selected, audit, {
        "scope_status": "main_cluster_selected",
        "cluster_eps_m": round(cluster_eps_m, 1),
        "main_cluster": main_cluster,
        "main_records": int((scope_class == "main_range").sum()),
        "disjunct_records": int((scope_class == "disjunct_range").sum()),
        "possible_noise_records": int((scope_class == "possible_remote_noise").sum()),
        "main_fraction": round(float((scope_class == "main_range").mean()), 4),
    }


def recommend_survey_regions(
    occurrences: pd.DataFrame,
    scope_audit: Optional[pd.DataFrame] = None,
    *,
    latitude_col: str = "_latitude",
    longitude_col: str = "_longitude",
    trip_radius_m: float = 40_000.0,
    max_cards: int = 3,
) -> tuple[list[dict[str, object]], pd.DataFrame, dict[str, object]]:
    """Create compact region/hub cards before within-region site selection.

    Each occurrence is assigned to at most one radius-bounded hub. Possible
    remote-noise records from scope QC remain in the audit but do not seed the
    default region recommendations.
    """
    if occurrences is None or occurrences.empty:
        return [], pd.DataFrame(), {"distribution_regime": "empty", "stable_regions": 0}
    work = occurrences.dropna(subset=[latitude_col, longitude_col]).copy().reset_index(drop=True)
    if "_row_id" not in work.columns:
        work["_row_id"] = np.arange(len(work), dtype=int)
    work["_region_eligible"] = True
    if scope_audit is not None and not scope_audit.empty and {"_row_id", "scope_class"}.issubset(scope_audit.columns):
        scope_lookup = scope_audit.set_index("_row_id")["scope_class"]
        work["scope_class"] = work["_row_id"].map(scope_lookup).fillna("unclassified")
        work["_region_eligible"] = ~work["scope_class"].eq("possible_remote_noise")
    else:
        work["scope_class"] = "unclassified"
    eligible = work[work["_region_eligible"]].copy().reset_index(drop=True)
    if eligible.empty:
        eligible = work.copy().reset_index(drop=True)

    coords = eligible[[latitude_col, longitude_col]].to_numpy(dtype=float)
    pairwise = _pairwise_haversine_m(coords)
    unassigned = set(range(len(eligible)))
    raw_regions: list[dict[str, object]] = []
    assignment: dict[int, int] = {}
    radius = max(5_000.0, float(trip_radius_m))
    while unassigned:
        indices = np.array(sorted(unassigned), dtype=int)
        neighbour_counts = (pairwise[np.ix_(indices, indices)] <= radius).sum(axis=1)
        seed = int(indices[int(np.argmax(neighbour_counts))])
        members = sorted(i for i in unassigned if pairwise[seed, i] <= radius)
        region_id = len(raw_regions) + 1
        for member in members:
            assignment[member] = region_id
        unassigned -= set(members)
        sub = pairwise[np.ix_(members, members)]
        medoid_local = int(np.argmin(sub.sum(axis=1))) if len(members) > 1 else 0
        medoid_index = members[medoid_local]
        member_rows = eligible.iloc[members]
        center_radius_m = float(sub[medoid_local].max()) if sub.size else 0.0
        raw_regions.append({
            "region_id": region_id,
            "center_latitude": float(eligible.iloc[medoid_index][latitude_col]),
            "center_longitude": float(eligible.iloc[medoid_index][longitude_col]),
            "record_count": int(len(members)),
            "record_share": round(len(members) / max(1, len(eligible)), 4),
            "diameter_km": round(float(np.max(sub)) / 1000.0, 1) if sub.size else 0.0,
            "center_radius_km": round(center_radius_m / 1000.0, 1),
            "member_row_ids": member_rows["_row_id"].astype(int).tolist(),
            "lat_min": float(member_rows[latitude_col].min()),
            "lat_max": float(member_rows[latitude_col].max()),
            "lon_min": float(member_rows[longitude_col].min()),
            "lon_max": float(member_rows[longitude_col].max()),
        })

    eligible["region_id"] = [assignment[i] for i in range(len(eligible))]
    region_id_by_row = eligible.set_index("_row_id")["region_id"]
    audit = work[["_row_id", latitude_col, longitude_col, "scope_class", "_region_eligible"]].copy()
    audit["region_id"] = audit["_row_id"].map(region_id_by_row).astype("Int64")

    stable = [region for region in raw_regions if int(region["record_count"]) >= 3]
    candidate_regions = stable or raw_regions
    best = max(candidate_regions, key=lambda region: (int(region["record_count"]), -int(region["region_id"])))
    selected: list[dict[str, object]] = [dict(best)]
    remaining = [region for region in candidate_regions if region["region_id"] != best["region_id"]]

    def center_distance(region_a: Mapping[str, object], region_b: Mapping[str, object]) -> float:
        return float(_distances_m(
            float(region_a["center_latitude"]), float(region_a["center_longitude"]),
            np.array([float(region_b["center_latitude"])]), np.array([float(region_b["center_longitude"])]),
        )[0])

    if remaining and len(selected) < int(max_cards):
        n_max = max(int(region["record_count"]) for region in candidate_regions)
        distance_max = max(center_distance(best, region) for region in remaining) or 1.0
        discovery = max(
            remaining,
            key=lambda region: (
                0.45 * int(region["record_count"]) / max(1, n_max)
                + 0.55 * center_distance(best, region) / distance_max
            ),
        )
        selected.append(dict(discovery))
        remaining = [region for region in remaining if region["region_id"] != discovery["region_id"]]
    if remaining and len(selected) < int(max_cards):
        contrast = max(
            remaining,
            key=lambda region: min(center_distance(region, chosen) for chosen in selected),
        )
        selected.append(dict(contrast))

    roles = [
        ("Recommended", "Best-supported compact region; default for an immediate field proposal."),
        ("Discovery", "Alternative region balancing record support with geographic separation from the default."),
        ("Range contrast", "Geographically complementary region for population comparison or range-boundary learning."),
    ]
    for rank, region in enumerate(selected):
        role, reason = roles[min(rank, len(roles) - 1)]
        region["card_role"] = role
        region["card_reason"] = reason
        region["recommended"] = rank == 0
        region["card_rank"] = rank + 1

    stable_regions = len(stable)
    eligible_pairwise = _pairwise_haversine_m(coords)
    total_span_km = float(np.max(eligible_pairwise)) / 1000.0 if eligible_pairwise.size else 0.0
    if total_span_km <= 80.0:
        regime = "narrow/local"
        regime_reason = "Eligible records fit within an approximately 80 km maximum span."
    elif total_span_km <= 300.0:
        regime = "regional"
        regime_reason = "Eligible records span multiple short-trip hubs within one broad region."
    elif stable_regions <= 3:
        regime = "disjunct"
        regime_reason = "A small number of stable regions are separated by long distances."
    else:
        regime = "widespread"
        regime_reason = "Records require several compact trip hubs across a broad range."
    return selected, audit, {
        "distribution_regime": regime,
        "distribution_regime_reason": regime_reason,
        "eligible_records": int(len(eligible)),
        "stable_regions": int(stable_regions),
        "total_span_km": round(total_span_km, 1),
        "trip_radius_km": round(radius / 1000.0, 1),
    }


def choose_candidate_resolution(
    environmental_resolution_m: Optional[float] = None,
    access_resolution_m: Optional[float] = None,
    coordinate_uncertainty_q75_m: Optional[float] = None,
    minimum_practical_search_m: float = 100.0,
    allowed_cell_sizes_m: Iterable[int] = (100, 250, 500, 1000, 2000, 5000),
) -> ResolutionDecision:
    """Choose the first allowed cell size that does not overstate input precision."""
    evidence = {
        "environment": environmental_resolution_m,
        "access": access_resolution_m,
        "coordinate uncertainty q75": coordinate_uncertainty_q75_m,
        "practical field scale": minimum_practical_search_m,
    }
    finite = {
        label: float(value) for label, value in evidence.items()
        if value is not None and np.isfinite(float(value)) and float(value) > 0
    }
    required = max(finite.values(), default=float(minimum_practical_search_m))
    allowed = sorted({int(v) for v in allowed_cell_sizes_m if int(v) > 0})
    if not allowed:
        raise ValueError("allowed_cell_sizes_m must contain at least one positive size")
    chosen = next((value for value in allowed if value >= required), int(math.ceil(required / 100.0) * 100))
    measured_inputs = sum(key != "practical field scale" for key in finite)
    quality = "high" if measured_inputs >= 3 and required <= 250 else "medium" if measured_inputs >= 1 else "low"
    limiting = max(finite, key=finite.get) if finite else "practical field scale"
    reason = f"{chosen:,} m cell: limited by {limiting} ({required:,.0f} m); finer output would overstate precision."
    return ResolutionDecision(chosen, required, int(math.ceil(chosen * 0.6)), quality, reason)


def _unit(values: object, *, default: float = 0.0) -> pd.Series:
    series = pd.to_numeric(pd.Series(values), errors="coerce").astype(float)
    finite = series[np.isfinite(series)]
    out = pd.Series(default, index=series.index, dtype=float)
    if finite.empty:
        return out
    lo, hi = float(finite.min()), float(finite.max())
    if lo >= 0.0 and hi <= 1.0:
        out.loc[finite.index] = finite.clip(0.0, 1.0)
    elif hi - lo > 1e-12:
        out.loc[finite.index] = (finite - lo) / (hi - lo)
    else:
        out.loc[finite.index] = 0.5
    return out.clip(0.0, 1.0)


def _weighted_available(df: pd.DataFrame, weights: Mapping[str, float], default: float) -> tuple[pd.Series, pd.Series]:
    numerator = pd.Series(0.0, index=df.index)
    denominator = pd.Series(0.0, index=df.index)
    count = pd.Series(0, index=df.index, dtype=int)
    for column, weight in weights.items():
        if column not in df.columns:
            continue
        raw = pd.to_numeric(df[column], errors="coerce")
        available = raw.notna()
        values = _unit(raw, default=default)
        numerator += values * float(weight) * available.astype(float)
        denominator += float(weight) * available.astype(float)
        count += available.astype(int)
    score = numerator.div(denominator.where(denominator > 0)).fillna(float(default)).clip(0.0, 1.0)
    return score, count


def apply_hard_constraints(
    candidates: pd.DataFrame,
    *,
    minimum_supported_resolution_m: Optional[float] = None,
    maximum_slope_deg: float = 45.0,
    maximum_access_distance_m: float = 500.0,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Exclude known-invalid cells and return a row-level audit table.

    Unknown land/access/restriction values are retained and flagged, rather
    than silently treated as safe or inaccessible.
    """
    if candidates is None or candidates.empty:
        empty = pd.DataFrame() if candidates is None else candidates.copy()
        return empty, empty
    out = candidates.copy().reset_index(drop=True)
    reasons: list[list[str]] = [[] for _ in range(len(out))]
    unknowns: list[list[str]] = [[] for _ in range(len(out))]

    lat = pd.to_numeric(out.get("latitude"), errors="coerce")
    lon = pd.to_numeric(out.get("longitude"), errors="coerce")
    invalid_coordinate = lat.isna() | lon.isna() | ~lat.between(-90, 90) | ~lon.between(-180, 180)
    for i in np.flatnonzero(invalid_coordinate.to_numpy()):
        reasons[i].append("invalid_coordinate")

    land_col = next((c for c in ("is_land", "land_mask") if c in out.columns), None)
    if land_col:
        values = out[land_col]
        false_mask = values.astype(str).str.lower().isin({"false", "0", "no", "water"})
        for i in np.flatnonzero(false_mask.to_numpy()):
            reasons[i].append("water")
        unknown_land = values.isna() | values.astype(str).str.lower().isin({"", "nan", "none", "unknown"})
        for i in np.flatnonzero(unknown_land.to_numpy()):
            unknowns[i].append("land")
    else:
        for row in unknowns:
            row.append("land")

    for restricted_col in ("access_restricted", "restricted_access", "is_restricted"):
        if restricted_col in out.columns:
            restriction_values = out[restricted_col]
            restricted = restriction_values.astype(str).str.lower().isin({"true", "1", "yes", "restricted"})
            for i in np.flatnonzero(restricted.to_numpy()):
                reasons[i].append("restricted_access")
            unknown_restriction = restriction_values.isna() | restriction_values.astype(str).str.lower().isin({"", "nan", "none", "unknown"})
            for i in np.flatnonzero(unknown_restriction.to_numpy()):
                unknowns[i].append("legal_access")
            break
    else:
        for row in unknowns:
            row.append("legal_access")

    if "slope" in out.columns:
        steep = pd.to_numeric(out["slope"], errors="coerce") > float(maximum_slope_deg)
        for i in np.flatnonzero(steep.fillna(False).to_numpy()):
            reasons[i].append("dangerous_slope")
    else:
        for row in unknowns:
            row.append("slope")

    distance_columns = [c for c in ("distance_to_road_m", "distance_to_trail_m") if c in out.columns]
    if distance_columns:
        distances = out[distance_columns].apply(pd.to_numeric, errors="coerce")
        nearest = distances.min(axis=1, skipna=True)
        too_far = nearest.notna() & (nearest > float(maximum_access_distance_m))
        for i in np.flatnonzero(too_far.to_numpy()):
            reasons[i].append("beyond_access_distance")
        for i in np.flatnonzero(nearest.isna().to_numpy()):
            unknowns[i].append("physical_access")
    else:
        for row in unknowns:
            row.append("physical_access")

    if minimum_supported_resolution_m is not None:
        resolution_col = next((c for c in ("effective_search_cell_size_m", "search_cell_size_m") if c in out.columns), None)
        if resolution_col:
            resolution = pd.to_numeric(out[resolution_col], errors="coerce")
            overprecise = resolution.notna() & (resolution < float(minimum_supported_resolution_m))
            for i in np.flatnonzero(overprecise.to_numpy()):
                reasons[i].append("over_precision")

    audit = out[[c for c in ("site_id", "candidate_type", "latitude", "longitude") if c in out.columns]].copy()
    audit["eligible"] = [not row for row in reasons]
    audit["exclusion_reason"] = [";".join(row) for row in reasons]
    audit["unknown_constraints"] = [";".join(row) for row in unknowns]
    eligible = out.loc[audit["eligible"].to_numpy()].copy().reset_index(drop=True)
    eligible["constraint_status"] = audit.loc[audit["eligible"], "unknown_constraints"].replace("", "checked").to_numpy()
    return eligible, audit


def score_discovery_learning(candidates: pd.DataFrame) -> pd.DataFrame:
    """Add explicit Discovery, Learning, access and evidence-quality scores."""
    if candidates is None or candidates.empty:
        return pd.DataFrame() if candidates is None else candidates.copy()
    out = integrated_candidate_scores(candidates).reset_index(drop=True)
    habitat, habitat_n = _weighted_available(out, {
        "analogue_score": 0.35, "habitat_score": 0.25, "environmental_similarity": 0.15,
        "landcover_match_score": 0.25,
    }, 0.0)
    detectability, detect_n = _weighted_available(out, {
        "detectability": 0.60, "flowering_probability": 0.25, "season_confidence": 0.15,
    }, 0.5)
    access, access_n = _weighted_available(out, {"access_score": 1.0}, 0.5)
    if access_n.eq(0).all():
        distance_columns = [c for c in ("distance_to_road_m", "distance_to_trail_m") if c in out.columns]
        if distance_columns:
            nearest = out[distance_columns].apply(pd.to_numeric, errors="coerce").min(axis=1, skipna=True)
            access = np.exp(-nearest.fillna(500.0).clip(lower=0.0) / 500.0).clip(0.0, 1.0)
            access_n = nearest.notna().astype(int)

    uncertainty, uncertainty_n = _weighted_available(out, {
        "model_uncertainty": 0.5, "prediction_sd": 0.3, "ensemble_sd": 0.2,
    }, 0.0)
    boundary, boundary_n = _weighted_available(out, {
        "environmental_novelty": 0.55, "survey_gap_score": 0.25,
        "environmental_distance_to_known": 0.20,
    }, 0.0)
    analogue = _unit(out.get("analogue_score", pd.Series(np.nan, index=out.index)))
    sdm = _unit(out.get("sdm_suitability", pd.Series(np.nan, index=out.index)))
    disagreement_available = (
        pd.to_numeric(out.get("analogue_score", pd.Series(np.nan, index=out.index)), errors="coerce").notna()
        & pd.to_numeric(out.get("sdm_suitability", pd.Series(np.nan, index=out.index)), errors="coerce").notna()
    )
    disagreement = (analogue - sdm).abs().where(disagreement_available, 0.0)
    learning_denominator = 0.45 * disagreement_available.astype(float) + 0.30 * uncertainty_n.gt(0) + 0.25 * boundary_n.gt(0)
    learning = (
        0.45 * disagreement + 0.30 * uncertainty + 0.25 * boundary
    ).div(learning_denominator.where(learning_denominator > 0)).fillna(0.0).clip(0.0, 1.0)

    out["habitat_likelihood"] = habitat.round(4)
    out["detectability_score"] = detectability.round(4)
    out["accessibility_score"] = pd.Series(access).round(4)
    integrated = pd.to_numeric(out["integrated_support_score"], errors="coerce").fillna(habitat).clip(0.0, 1.0)
    out["discovery_value"] = (integrated * detectability * pd.Series(access)).clip(0.0, 1.0).round(4)
    out["learning_value"] = learning.round(4)
    out["model_analogue_disagreement"] = disagreement.round(4)
    evidence_count = habitat_n + detect_n + access_n + uncertainty_n + boundary_n
    out["evidence_count"] = evidence_count.astype(int)
    out["data_quality"] = np.select([evidence_count >= 5, evidence_count >= 2], ["high", "medium"], default="low")
    return out


def _distances_m(lat: float, lon: float, lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
    lat1, lon1 = math.radians(lat), math.radians(lon)
    lat2, lon2 = np.radians(lats), np.radians(lons)
    a = np.sin((lat2 - lat1) / 2.0) ** 2 + math.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2.0) ** 2
    return 2.0 * EARTH_RADIUS_M * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def _label(value: float) -> str:
    return "high" if value >= 0.67 else "medium" if value >= 0.34 else "low"


def build_acsp_discover_plans(
    candidates: pd.DataFrame,
    k: int = 8,
    hub_latitude: Optional[float] = None,
    hub_longitude: Optional[float] = None,
) -> dict[str, pd.DataFrame]:
    """Greedily build Balanced, Discovery and Learning plans from one pool."""
    scored = score_discovery_learning(candidates)
    if scored.empty or int(k) <= 0:
        return {name: scored.head(0).copy() for name in PLAN_ORDER}
    required = {"site_id", "latitude", "longitude"}
    missing = required - set(scored.columns)
    if missing:
        raise ValueError(f"candidate table is missing required columns: {', '.join(sorted(missing))}")
    lats = pd.to_numeric(scored["latitude"], errors="coerce").to_numpy(float)
    lons = pd.to_numeric(scored["longitude"], errors="coerce").to_numpy(float)
    gap = _unit(scored.get("survey_gap_score", pd.Series(0.0, index=scored.index)))
    candidate_types = scored.get("candidate_type", pd.Series("", index=scored.index)).astype(str).str.lower()
    type_masks = {
        "known": candidate_types.str.contains("occurrence|known").to_numpy(bool),
        "discovery": candidate_types.str.contains("habitat|analogue|survey-gap|under-surveyed").to_numpy(bool),
        "learning": candidate_types.str.contains("environmental-test|environmental contrast|sdm-high|ssdm-high").to_numpy(bool),
    }
    area_values = scored.get("survey_area_id", pd.Series(1, index=scored.index)).astype(str).to_numpy()
    distinct_areas = list(dict.fromkeys(area_values.tolist()))
    plans: dict[str, pd.DataFrame] = {}
    for plan_name in PLAN_ORDER:
        weights = PLAN_WEIGHTS[plan_name]
        requested_minimums = PLAN_MINIMUM_TYPE_COUNTS[plan_name]
        minimums = {
            category: min(int(requested), int(type_masks[category].sum()))
            for category, requested in requested_minimums.items()
        }
        while sum(minimums.values()) > min(int(k), len(scored)):
            reducible = max(minimums, key=minimums.get)
            minimums[reducible] = max(0, minimums[reducible] - 1)
        selected: list[int] = []
        route_order: list[int] = []
        records: list[dict[str, object]] = []
        while len(selected) < min(int(k), len(scored)):
            selected_counts = {
                category: sum(bool(mask[position]) for position in selected)
                for category, mask in type_masks.items()
            }
            unmet = {
                category for category, minimum in minimums.items()
                if selected_counts[category] < minimum
                and any(type_masks[category][i] for i in range(len(scored)) if i not in selected)
            }
            selected_areas = {area_values[position] for position in selected}
            unmet_areas = set(distinct_areas) - selected_areas if int(k) >= len(distinct_areas) else set()
            best: Optional[tuple[float, int, dict[str, float]]] = None
            for i in range(len(scored)):
                if i in selected:
                    continue
                if unmet_areas and area_values[i] not in unmet_areas:
                    continue
                if unmet and not any(type_masks[category][i] for category in unmet):
                    same_area_type_available = any(
                        j not in selected
                        and (not unmet_areas or area_values[j] in unmet_areas)
                        and any(type_masks[category][j] for category in unmet)
                        for j in range(len(scored))
                    )
                    if same_area_type_available:
                        continue
                same_area_selected = [position for position in selected if area_values[position] == area_values[i]]
                if same_area_selected:
                    distances = _distances_m(lats[i], lons[i], lats[same_area_selected], lons[same_area_selected])
                    nearest = float(np.min(distances))
                    if nearest < 1.0:
                        continue
                    representation = 1.0 - math.exp(-nearest / 25_000.0)
                    redundancy = math.exp(-nearest / 5_000.0)
                    travel = min(1.0, nearest / 100_000.0)
                else:
                    representation, redundancy = 0.5, 0.0
                    hub_distance = pd.to_numeric(
                        pd.Series([scored.at[i, "distance_to_hub_m"]])
                        if "distance_to_hub_m" in scored.columns else pd.Series([0.0]),
                        errors="coerce",
                    ).fillna(0.0).iloc[0]
                    travel = min(1.0, float(hub_distance) / 50_000.0)
                insertion_index = len(route_order)
                marginal_route_m = travel * 100_000.0
                if hub_latitude is not None and hub_longitude is not None:
                    route_nodes = [(float(hub_latitude), float(hub_longitude))]
                    route_nodes.extend((float(lats[position]), float(lons[position])) for position in route_order)
                    route_nodes.append((float(hub_latitude), float(hub_longitude)))
                    insertion_options: list[tuple[float, int]] = []
                    for edge_index in range(len(route_nodes) - 1):
                        start_lat, start_lon = route_nodes[edge_index]
                        end_lat, end_lon = route_nodes[edge_index + 1]
                        start_to_candidate = float(_distances_m(start_lat, start_lon, np.array([lats[i]]), np.array([lons[i]]))[0])
                        candidate_to_end = float(_distances_m(lats[i], lons[i], np.array([end_lat]), np.array([end_lon]))[0])
                        direct = float(_distances_m(start_lat, start_lon, np.array([end_lat]), np.array([end_lon]))[0])
                        insertion_options.append((max(0.0, start_to_candidate + candidate_to_end - direct), edge_index))
                    marginal_route_m, insertion_index = min(insertion_options)
                    travel = min(1.0, marginal_route_m / 50_000.0)
                components = {
                    "discovery": float(scored.at[i, "discovery_value"]),
                    "learning": float(scored.at[i, "learning_value"]),
                    "representation": representation,
                    "survey_gap": float(gap.iloc[i]),
                    "accessibility": float(scored.at[i, "accessibility_score"]),
                    "travel": travel,
                    "redundancy": redundancy,
                    "marginal_route_m": marginal_route_m,
                    "insertion_index": float(insertion_index),
                }
                utility = sum(weights[key] * components[key] for key in ("discovery", "learning", "representation", "survey_gap", "accessibility"))
                utility -= weights["travel"] * travel + weights["redundancy"] * redundancy
                candidate = (utility, i, components)
                if best is None or candidate[:2] > best[:2]:
                    best = candidate
            if best is None:
                break
            utility, i, components = best
            selected.append(i)
            route_order.insert(int(components["insertion_index"]), i)
            positive = {
                key: weights[key] * components[key]
                for key in ("discovery", "learning", "representation", "survey_gap", "accessibility")
            }
            drivers = [key.replace("_", " ") for key, value in sorted(positive.items(), key=lambda item: item[1], reverse=True) if value > 0][:2]
            records.append({
                "_position": i,
                "plan_name": plan_name,
                "plan_rank": len(selected),
                "discover_utility": round(float(utility), 4),
                "representation_value": round(components["representation"], 4),
                "travel_cost": round(components["travel"], 4),
                "marginal_route_km": round(components["marginal_route_m"] / 1000.0, 3),
                "redundancy_penalty_v1": round(components["redundancy"], 4),
                "discovery_label": _label(components["discovery"]),
                "learning_label": _label(components["learning"]),
                "access_label": _label(components["accessibility"]),
                "quota_category": next((category for category, mask in type_masks.items() if mask[i]), "other"),
                "why_selected": f"Selected for {', '.join(drivers) if drivers else plan_name.lower()}; field presence and access remain unverified.",
            })
        rows = []
        for record in records:
            row = scored.iloc[int(record.pop("_position"))].to_dict()
            row.update(record)
            rows.append(row)
        plans[plan_name] = pd.DataFrame(rows).reset_index(drop=True)
    return plans


def summarize_plan(plan: pd.DataFrame) -> dict[str, object]:
    """Return fields for a compact proposal card."""
    if plan is None or plan.empty:
        return {"priority_cells": 0, "known_anchors": 0, "discovery_cells": 0, "learning_cells": 0, "data_quality": "low"}
    types = plan.get("candidate_type", pd.Series("", index=plan.index)).astype(str).str.lower()
    qualities = plan.get("data_quality", pd.Series("low", index=plan.index)).astype(str)
    quality_rank = {"low": 0, "medium": 1, "high": 2}
    median_quality = sorted(qualities, key=lambda value: quality_rank.get(value, 0))[len(qualities) // 2]
    return {
        "priority_cells": int(len(plan)),
        "known_anchors": int(types.str.contains("occurrence|known").sum()),
        "discovery_cells": int(types.str.contains("habitat|analogue|survey-gap|under-surveyed").sum()),
        "learning_cells": int(types.str.contains("contrast|environmental-test|sdm-high").sum()),
        "data_quality": median_quality,
    }
