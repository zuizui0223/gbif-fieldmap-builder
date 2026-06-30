"""Transparent candidate recommendation helpers."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd


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
