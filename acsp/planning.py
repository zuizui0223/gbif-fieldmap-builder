"""Transparent candidate recommendation helpers."""

from __future__ import annotations

from collections.abc import Sequence
import math
import re

import numpy as np
import pandas as pd


EARTH_RADIUS_M = 6_371_008.8
DEFAULT_INTEGRATED_WEIGHTS = {
    "observed": 0.35,
    "local_habitat": 0.25,
    "macro_model": 0.15,
    "survey_gap": 0.10,
    "access": 0.10,
    "field_validation": 0.05,
}


def _haversine_m(lat: float, lon: float, lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
    lat1, lon1 = math.radians(float(lat)), math.radians(float(lon))
    lat2, lon2 = np.radians(lats.astype(float)), np.radians(lons.astype(float))
    a = np.sin((lat2 - lat1) / 2.0) ** 2 + math.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2.0) ** 2
    return 2.0 * EARTH_RADIUS_M * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def _unit_series(frame: pd.DataFrame, columns: Sequence[str], default: float = 0.0) -> pd.Series:
    available = [column for column in columns if column in frame.columns]
    if not available:
        return pd.Series(default, index=frame.index, dtype=float)
    values = frame[available].apply(pd.to_numeric, errors="coerce").max(axis=1, skipna=True)
    finite = values[np.isfinite(values)]
    if finite.empty:
        return pd.Series(default, index=frame.index, dtype=float)
    if float(finite.min()) >= 0.0 and float(finite.max()) <= 1.0:
        return values.fillna(default).clip(0.0, 1.0)
    span = float(finite.max() - finite.min())
    if span <= 1e-12:
        return values.notna().astype(float) * 0.5
    return ((values - float(finite.min())) / span).fillna(default).clip(0.0, 1.0)


def _available_unit_component(frame: pd.DataFrame, columns: Sequence[str]) -> tuple[pd.Series, pd.Series]:
    available = [column for column in columns if column in frame.columns]
    if not available:
        return pd.Series(np.nan, index=frame.index, dtype=float), pd.Series(False, index=frame.index)
    values = frame[available].apply(pd.to_numeric, errors="coerce").max(axis=1, skipna=True)
    present = values.notna()
    finite = values[np.isfinite(values)]
    if finite.empty:
        return pd.Series(np.nan, index=frame.index, dtype=float), pd.Series(False, index=frame.index)
    if float(finite.min()) >= 0.0 and float(finite.max()) <= 1.0:
        return values.clip(0.0, 1.0), present
    span = float(finite.max() - finite.min())
    if span <= 1e-12:
        normalized = pd.Series(np.where(present, 0.5, np.nan), index=frame.index, dtype=float)
    else:
        normalized = (values - float(finite.min())) / span
    return normalized.clip(0.0, 1.0), present


def integrated_candidate_scores(
    candidates: pd.DataFrame,
    weights: dict[str, float] | None = None,
    exclude_occurrence_derived: bool = False,
) -> pd.DataFrame:
    """Score one candidate pool using every available, non-missing evidence family.

    Missing model support is unavailable rather than zero and therefore does not
    reduce a candidate's score. `exclude_occurrence_derived` is intended for
    retrospective recovery tests and removes direct occurrence support and
    distance/density-derived survey-gap evidence.
    """
    if candidates is None or candidates.empty:
        return pd.DataFrame() if candidates is None else candidates.copy()
    out = candidates.copy().reset_index(drop=True)
    component_columns = {
        "observed": ["observed_base_priority_score", "occurrence_support_score", "observed_species_richness", "species_richness", "record_count"],
        "local_habitat": ["analogue_score", "habitat_score", "environmental_similarity", "landcover_match_score"],
        "macro_model": ["model_support_score", "sdm_suitability", "ssdm_model_support_score", "ssdm_predicted_richness"],
        "survey_gap": ["survey_gap_score", "environmental_novelty", "environmental_distance_to_known"],
        "access": ["access_score", "accessibility_score"],
        "field_validation": ["field_validation_support_score"],
    }
    if exclude_occurrence_derived:
        component_columns["observed"] = []
        component_columns["survey_gap"] = []
    configured = dict(DEFAULT_INTEGRATED_WEIGHTS)
    if weights:
        configured.update({key: max(0.0, float(value)) for key, value in weights.items() if key in configured})
    component_values: dict[str, pd.Series] = {}
    component_available: dict[str, pd.Series] = {}
    numerator = pd.Series(0.0, index=out.index)
    denominator = pd.Series(0.0, index=out.index)
    for name, columns in component_columns.items():
        values, available = _available_unit_component(out, columns)
        if name == "local_habitat" and exclude_occurrence_derived and "occurrence_derived_habitat_score" in out.columns:
            occurrence_derived = out["occurrence_derived_habitat_score"].astype("boolean").fillna(False).astype(bool)
            available &= ~occurrence_derived
            values = values.where(available)
        if name == "macro_model" and "model_support_available" in out.columns:
            explicit = out["model_support_available"].astype("boolean").fillna(False).astype(bool)
            raw_prediction = pd.Series(False, index=out.index)
            for column in ("sdm_suitability", "ssdm_model_support_score", "ssdm_predicted_richness"):
                if column in out.columns:
                    raw_prediction |= pd.to_numeric(out[column], errors="coerce").notna()
            available &= explicit | raw_prediction
            values = values.where(available)
        component_values[name] = values
        component_available[name] = available
        weight = float(configured[name])
        numerator += values.fillna(0.0) * weight
        denominator += available.astype(float) * weight
        out[f"component_{name}_score"] = values.round(4)
        out[f"component_{name}_available"] = available
    base = numerator.div(denominator.where(denominator > 0)).fillna(0.0).clip(0.0, 1.0)
    evidence = pd.DataFrame({
        "observed": component_values["observed"],
        "local_habitat": component_values["local_habitat"],
        "macro_model": component_values["macro_model"],
    })
    evidence_count = evidence.notna().sum(axis=1)
    evidence_mean = evidence.mean(axis=1, skipna=True).fillna(0.0)
    evidence_range = (evidence.max(axis=1, skipna=True) - evidence.min(axis=1, skipna=True)).fillna(0.0)
    agreement = (evidence_mean * (1.0 - evidence_range)).where(evidence_count >= 2, 0.0).clip(0.0, 1.0)
    divergence = evidence_range.where(evidence_count >= 2, 0.0).clip(0.0, 1.0)
    candidate_type = out.get("candidate_type", pd.Series("", index=out.index)).astype(str)
    exploratory = candidate_type.str.contains(
        "model-only|sdm-high|ssdm-high|exploratory|environmental-test|environmental contrast",
        case=False, na=False,
    )
    agreement_bonus = 0.10 * agreement
    divergence_bonus = 0.05 * divergence * exploratory.astype(float)
    integrated = (base + agreement_bonus + divergence_bonus).clip(0.0, 1.0)
    observed = component_values["observed"].fillna(0.0)
    local = component_values["local_habitat"].fillna(0.0)
    macro = component_values["macro_model"].fillna(0.0)
    model_available = component_available["macro_model"]
    evidence_class = np.select(
        [
            model_available & agreement.ge(0.55) & macro.ge(0.5),
            model_available & local.ge(0.5) & macro.lt(0.5),
            model_available & macro.ge(0.5) & local.lt(0.5) & observed.lt(0.5),
            observed.ge(0.5),
            local.ge(0.5),
        ],
        [
            "Cross-scale consensus",
            "Local-habitat support; weak macro support",
            "Macro-model exploration",
            "Known-record anchor",
            "Local-habitat potential",
        ],
        default="Limited evidence",
    )
    out["integrated_base_score"] = base.round(4)
    out["evidence_agreement_score"] = agreement.round(4)
    out["evidence_divergence_score"] = divergence.round(4)
    out["agreement_bonus"] = agreement_bonus.round(4)
    out["divergence_exploration_bonus"] = divergence_bonus.round(4)
    out["integrated_support_score"] = integrated.round(4)
    out["integrated_evidence_class"] = evidence_class
    out["integrated_available_weight"] = denominator.round(4)
    out["distance_excluded_validation_score"] = bool(exclude_occurrence_derived)
    out["integrated_score_explanation"] = [
        f"available-weight-normalized support={base_value:.3f}; agreement={agree:.3f}; divergence={diverge:.3f}; model={'available' if model_ok else 'not available'}"
        for base_value, agree, diverge, model_ok in zip(base, agreement, divergence, model_available)
    ]
    return out


def select_complementary_candidates(
    candidates: pd.DataFrame,
    k: int,
    *,
    score_col: str = "integrated_support_score",
    evidence_weight: float = 0.25,
    separation_scale_m: float = 25_000.0,
) -> pd.DataFrame:
    """Select alternative survey regions using evidence plus spatial coverage.

    These rows are alternative regional choices, not a claim that every row is
    reachable in one trip. Within-region trip planning remains a separate step.
    """
    if candidates is None or candidates.empty:
        return pd.DataFrame() if candidates is None else candidates.copy()
    work = candidates.dropna(subset=["latitude", "longitude"]).copy().reset_index(drop=True)
    if work.empty:
        return work
    scores = pd.to_numeric(work.get(score_col, pd.Series(0.0, index=work.index)), errors="coerce").fillna(0.0).clip(0, 1).to_numpy(float)
    lats = pd.to_numeric(work["latitude"], errors="coerce").to_numpy(float)
    lons = pd.to_numeric(work["longitude"], errors="coerce").to_numpy(float)
    weight = float(np.clip(evidence_weight, 0.0, 1.0))
    scale = max(1.0, float(separation_scale_m))
    selected: list[int] = []
    utilities: list[float] = []
    while len(selected) < min(max(1, int(k)), len(work)):
        best: tuple[float, float, int] | None = None
        for index in range(len(work)):
            if index in selected:
                continue
            if selected:
                nearest = float(np.min(_haversine_m(lats[index], lons[index], lats[selected], lons[selected])))
                representation = 1.0 - math.exp(-nearest / scale)
            else:
                representation = 0.5
            utility = weight * scores[index] + (1.0 - weight) * representation
            key = (utility, scores[index], -index)
            if best is None or key > best:
                best = key
        assert best is not None
        chosen = -int(best[2])
        selected.append(chosen)
        utilities.append(float(best[0]))
    out = work.iloc[selected].copy().reset_index(drop=True)
    out["complementary_selection_rank"] = range(1, len(out) + 1)
    out["complementary_selection_utility"] = np.round(utilities, 6)
    out["complementary_selection_policy"] = (
        f"{weight:.2f} available-evidence + {1.0 - weight:.2f} geographic complementarity; alternatives, not one route"
    )
    return out


def _plain_role(candidate_type: object) -> str:
    value = str(candidate_type or "").lower()
    if "model-only" in value or "sdm-high" in value or "ssdm-high" in value:
        return "Model-led exploration zone"
    if "environmental-test" in value or "environmental contrast" in value or "boundary" in value:
        return "Range-boundary comparison zone"
    if "survey-gap" in value or "under-surveyed" in value:
        return "Under-sampled verification zone"
    if "habitat" in value or "analogue" in value:
        return "Similar-habitat zone"
    if "occurrence" in value or "known" in value:
        return "Known-location zone"
    return "Survey evidence zone"


def aggregate_candidates_to_zones(
    candidates: pd.DataFrame,
    merge_distance_m: float | None = None,
    area_col: str = "survey_area_id",
    latitude_col: str = "latitude",
    longitude_col: str = "longitude",
    id_col: str = "site_id",
    score_col: str = "priority_score",
) -> pd.DataFrame:
    """Aggregate nearby candidates using deterministic complete-link zones.

    A point joins a zone only when it lies within the merge threshold of every
    existing member.  This deliberately prevents single-link chain artifacts.
    Zone scores use maxima of independent evidence components, never member
    counts, so dense candidate grids do not gain priority merely by density.
    """
    if candidates is None or candidates.empty:
        return pd.DataFrame()
    required = {latitude_col, longitude_col, id_col, score_col}
    missing = required.difference(candidates.columns)
    if missing:
        raise ValueError(f"Missing zone columns: {', '.join(sorted(missing))}")
    work = candidates.copy().reset_index(drop=True)
    work[latitude_col] = pd.to_numeric(work[latitude_col], errors="coerce")
    work[longitude_col] = pd.to_numeric(work[longitude_col], errors="coerce")
    work = work.dropna(subset=[latitude_col, longitude_col]).reset_index(drop=True)
    if work.empty:
        return pd.DataFrame()
    if area_col not in work.columns:
        work[area_col] = 1
    work["_priority_unit"] = _unit_series(work, [score_col])
    work["_observed_support"] = _unit_series(work, ["component_observed_score", "occurrence_support_score", "observed_base_priority_score"])
    work["_local_support"] = _unit_series(work, ["component_local_habitat_score", "analogue_score", "habitat_score", "environmental_similarity"])
    work["_model_support"] = _unit_series(work, ["component_macro_model_score", "model_support_score", "sdm_suitability", "ssdm_predicted_richness"])
    work["_access_support"] = _unit_series(work, ["component_access_score", "access_score", "accessibility_score"], default=0.5)
    work["_agreement_support"] = _unit_series(work, ["evidence_agreement_score", "observed_model_agreement_score"])
    work["_divergence_support"] = _unit_series(work, ["evidence_divergence_score", "model_analogue_disagreement"])
    work["_representative_score"] = (
        0.80 * work["_priority_unit"] + 0.10 * work["_agreement_support"]
        + 0.10 * work["_access_support"]
    )
    assignments: dict[int, tuple[object, int]] = {}
    zone_members: dict[tuple[object, int], list[int]] = {}
    zone_thresholds: dict[tuple[object, int], float] = {}
    for area, group in work.groupby(area_col, sort=True, dropna=False):
        radius = pd.to_numeric(group.get("search_cell_radius_m", pd.Series(dtype=float)), errors="coerce").dropna()
        threshold = float(merge_distance_m) if merge_distance_m is not None else (
            float(np.clip(2.0 * radius.median(), 250.0, 5_000.0)) if not radius.empty else 1_000.0
        )
        ordered = group.assign(
            _stable_numeric=pd.to_numeric(group[id_col], errors="coerce"),
            _stable_id=group[id_col].astype(str),
        ).sort_values(
            ["_stable_numeric", "_stable_id", latitude_col, longitude_col], kind="mergesort", na_position="last"
        )
        area_zones: list[list[int]] = []
        for index in ordered.index:
            compatible: list[tuple[float, int]] = []
            for zone_index, member_indices in enumerate(area_zones):
                members = work.loc[member_indices]
                distances = _haversine_m(
                    work.at[index, latitude_col], work.at[index, longitude_col],
                    members[latitude_col].to_numpy(float), members[longitude_col].to_numpy(float),
                )
                maximum = float(distances.max()) if len(distances) else 0.0
                if maximum <= threshold:
                    compatible.append((maximum, zone_index))
            if compatible:
                zone_index = min(compatible)[1]
                area_zones[zone_index].append(index)
            else:
                zone_index = len(area_zones)
                area_zones.append([index])
            assignments[index] = (area, zone_index + 1)
        for zone_index, indices in enumerate(area_zones, start=1):
            zone_members[(area, zone_index)] = indices
            zone_thresholds[(area, zone_index)] = threshold

    rows: list[dict[str, object]] = []
    for (area, zone_number), indices in zone_members.items():
        members = work.loc[indices].copy()
        representative = members.sort_values(
            ["_representative_score", "_access_support", "_priority_unit", id_col],
            ascending=[False, False, False, True], kind="mergesort",
        ).iloc[0]
        distances = _haversine_m(
            representative[latitude_col], representative[longitude_col],
            members[latitude_col].to_numpy(float), members[longitude_col].to_numpy(float),
        )
        observed = float(members["_observed_support"].max())
        local = float(members["_local_support"].max())
        model = float(members["_model_support"].max())
        access = float(members["_access_support"].max())
        agreement = float(members["_agreement_support"].max())
        divergence = float(members["_divergence_support"].max())
        priority = float(members["_priority_unit"].max())
        zone_score = 0.90 * priority + 0.10 * agreement
        evidence_sources = {
            "priority": members.loc[members["_priority_unit"].idxmax(), id_col],
            "observed": members.loc[members["_observed_support"].idxmax(), id_col],
            "local": members.loc[members["_local_support"].idxmax(), id_col],
            "model": members.loc[members["_model_support"].idxmax(), id_col],
            "access": members.loc[members["_access_support"].idxmax(), id_col],
        }
        distinct_evidence_sources = {str(value) for value in evidence_sources.values()}
        roles = sorted({_plain_role(value) for value in members.get("candidate_type", pd.Series("", index=members.index))})
        safe_area = re.sub(r"[^A-Za-z0-9_-]+", "-", str(area)).strip("-") or "1"
        row = {
            "zone_id": f"{safe_area}-Z{zone_number:03d}",
            area_col: area,
            "zone_score": round(zone_score, 6),
            "zone_member_count": int(len(members)),
            "zone_radius_m": round(float(distances.max()) if len(distances) else 0.0, 1),
            "zone_merge_threshold_m": round(float(zone_thresholds[(area, zone_number)]), 1),
            "representative_site_id": representative[id_col],
            "latitude": float(representative[latitude_col]),
            "longitude": float(representative[longitude_col]),
            "zone_candidate_roles": "; ".join(roles),
            "primary_zone_role": _plain_role(representative.get("candidate_type", "")),
            "zone_evidence_summary": (
                f"Observed {observed:.2f}; local habitat {local:.2f}; model {model:.2f}; "
                f"access {access:.2f}; {len(members)} candidate point(s)."
            ),
            "zone_evidence_scope": (
                "All diagnostic evidence maxima come from one candidate point."
                if len(distinct_evidence_sources) == 1 else
                f"Diagnostic evidence maxima come from {len(distinct_evidence_sources)} candidate points; they are not independently summed into the zone score."
            ),
            "zone_score_method": "0.90 * best integrated candidate score + 0.10 * strongest cross-evidence agreement; candidate count and diagnostic component maxima are not added.",
            "priority_source_site_id": evidence_sources["priority"],
            "observed_source_site_id": evidence_sources["observed"],
            "local_source_site_id": evidence_sources["local"],
            "model_source_site_id": evidence_sources["model"],
            "access_source_site_id": evidence_sources["access"],
            "observed_support_score": round(observed, 6),
            "local_habitat_support_score": round(local, 6),
            "model_support_score": round(model, 6),
            "access_support_score": round(access, 6),
            "zone_agreement_support_score": round(agreement, 6),
            "zone_divergence_score": round(divergence, 6),
            "zone_member_site_ids": ";".join(members[id_col].astype(str).tolist()),
        }
        rows.append(row)
    zones = pd.DataFrame(rows).sort_values(["zone_score", "zone_id"], ascending=[False, True]).reset_index(drop=True)
    zones["zone_rank"] = range(1, len(zones) + 1)
    zones["initial_rank"] = zones["zone_rank"]
    zones["model_rank"] = pd.NA
    zones["rank_change"] = pd.NA
    zones["agreement_score"] = pd.NA
    zones["agreement_class"] = "Model not run"
    return zones


def compare_zone_rankings(initial_zones: pd.DataFrame, model_zones: pd.DataFrame) -> pd.DataFrame:
    """Attach before/after rank changes and conservative agreement classes."""
    if model_zones is None or model_zones.empty:
        return initial_zones.copy()
    initial_rank = initial_zones.set_index("zone_id")["zone_rank"] if initial_zones is not None and not initial_zones.empty else pd.Series(dtype=float)
    out = model_zones.copy()
    out["initial_rank"] = out["zone_id"].map(initial_rank)
    out["model_rank"] = out["zone_rank"].astype(int)
    out["rank_change"] = pd.to_numeric(out["initial_rank"], errors="coerce") - out["model_rank"]
    observed = pd.to_numeric(out["observed_support_score"], errors="coerce").fillna(0.0).clip(0, 1)
    local = pd.to_numeric(out["local_habitat_support_score"], errors="coerce").fillna(0.0).clip(0, 1)
    model = pd.to_numeric(out["model_support_score"], errors="coerce").fillna(0.0).clip(0, 1)
    local_evidence = pd.concat([observed, local], axis=1).max(axis=1)
    out["agreement_score"] = np.where(
        local_evidence.add(model).gt(0), 2 * local_evidence * model / (local_evidence + model), 0.0
    ).round(6)
    out["agreement_class"] = np.select(
        [
            local_evidence.ge(0.5) & model.ge(0.5),
            local_evidence.ge(model),
            model.gt(local_evidence),
        ],
        ["Concordant — highest priority", "Local evidence first", "Model-led exploration"],
        default="Local evidence first",
    )
    return out


def zone_agreement_summary(zones: pd.DataFrame, top_n: int = 8) -> dict[str, object]:
    """Return compact model-agreement counts and rank correlation."""
    if zones is None or zones.empty or "agreement_class" not in zones.columns:
        return {"model_run": False, "zone_count": 0}
    top = zones.sort_values("model_rank", na_position="last").head(int(top_n))
    counts = top["agreement_class"].value_counts().to_dict()
    common = zones.dropna(subset=["initial_rank", "model_rank"])
    correlation = common["initial_rank"].corr(common["model_rank"], method="spearman") if len(common) >= 2 else np.nan
    return {
        "model_run": not top["agreement_class"].eq("Model not run").all(),
        "zone_count": int(len(zones)),
        "top_zone_count": int(len(top)),
        "concordant_top_zones": int(counts.get("Concordant — highest priority", 0)),
        "local_evidence_first_top_zones": int(counts.get("Local evidence first", 0)),
        "model_led_top_zones": int(counts.get("Model-led exploration", 0)),
        "initial_model_rank_spearman": None if pd.isna(correlation) else round(float(correlation), 4),
    }


def recommend_survey_zones(
    candidates: pd.DataFrame,
    per_area: int = 3,
    default_total: int = 8,
    merge_distance_m: float | None = None,
    area_col: str = "survey_area_id",
    latitude_col: str = "latitude",
    longitude_col: str = "longitude",
    id_col: str = "site_id",
    score_col: str = "priority_score",
) -> pd.DataFrame:
    """Aggregate candidates, then apply recommendation quotas to survey zones."""
    zones = aggregate_candidates_to_zones(
        candidates, merge_distance_m=merge_distance_m, area_col=area_col,
        latitude_col=latitude_col, longitude_col=longitude_col,
        id_col=id_col, score_col=score_col,
    )
    if zones.empty:
        return zones
    selected = recommend_candidates(
        zones, per_area=per_area, default_total=default_total, area_col=area_col,
        score_col="zone_score", id_col="zone_id",
    )
    return selected.rename(columns={"recommendation_rank": "recommended_zone_rank"})


def normalize_extent(extent: Sequence[float]) -> tuple[float, float, float, float]:
    """Validate an extent ordered as west, south, east, north."""
    if len(extent) != 4:
        raise ValueError("Extent must contain west, south, east, north.")
    west, south, east, north = (float(value) for value in extent)
    if not np.isfinite([west, south, east, north]).all():
        raise ValueError("Extent coordinates must be finite numbers.")
    if west >= east or south >= north:
        raise ValueError("Extent must satisfy west < east and south < north.")
    return west, south, east, north


def filter_candidates_to_extent(
    candidates: pd.DataFrame,
    extent: Sequence[float],
    latitude_col: str = "latitude",
    longitude_col: str = "longitude",
) -> pd.DataFrame:
    """Keep candidate points inside an inclusive rectangular extent."""
    missing = {latitude_col, longitude_col}.difference(candidates.columns)
    if missing:
        raise ValueError(f"Missing coordinate columns: {', '.join(sorted(missing))}")
    west, south, east, north = normalize_extent(extent)
    latitude = pd.to_numeric(candidates[latitude_col], errors="coerce")
    longitude = pd.to_numeric(candidates[longitude_col], errors="coerce")
    inside = latitude.between(south, north) & longitude.between(west, east)
    return candidates.loc[inside].copy().reset_index(drop=True)


def recommend_candidates(
    candidates: pd.DataFrame,
    per_area: int = 3,
    default_total: int = 8,
    area_col: str = "survey_area_id",
    score_col: str = "priority_score",
    id_col: str = "site_id",
    extent: Sequence[float] | None = None,
    latitude_col: str = "latitude",
    longitude_col: str = "longitude",
) -> pd.DataFrame:
    """Select top-ranked candidates, with an equal quota across multiple areas."""
    if candidates is None or candidates.empty:
        return pd.DataFrame()
    required = {score_col, id_col}
    missing = required.difference(candidates.columns)
    if missing:
        raise ValueError(f"Missing candidate columns: {', '.join(sorted(missing))}")
    if extent is not None:
        candidates = filter_candidates_to_extent(candidates, extent, latitude_col, longitude_col)
    ranked = candidates.sort_values([score_col, id_col], ascending=[False, True]).copy()
    if area_col in ranked.columns and ranked[area_col].nunique() > 1:
        selected = ranked.groupby(area_col, group_keys=False).head(int(per_area)).copy()
        selected = selected.sort_values([area_col, score_col], ascending=[True, False])
    else:
        selected = ranked.head(int(default_total)).copy()
    selected["recommendation_rank"] = range(1, len(selected) + 1)
    return selected.reset_index(drop=True)
