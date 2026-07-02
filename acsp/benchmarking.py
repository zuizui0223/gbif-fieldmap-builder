"""Shared, current benchmark helpers.

Kept in the package so the national hierarchical benchmark does not depend on
historical, region-specific research runners stored under ``legacy/``.
"""

from __future__ import annotations

import time
from typing import Any

import pandas as pd
import requests


def get_json(
    url: str,
    params: dict[str, Any] | None = None,
    timeout: int = 60,
    attempts: int = 3,
) -> dict[str, Any]:
    """Fetch JSON with bounded retries for transient GBIF failures."""
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


def coverage_at_radius(candidates: pd.DataFrame, radius_km: float) -> pd.DataFrame:
    """Recompute held-out identifiers covered at the requested radius."""
    out = candidates.copy()
    all_ids = out["all_heldout_ids"].astype(str).str.split(";")
    distances = out["heldout_distances_km"].astype(str).str.split(";")
    out["covered_heldout_ids"] = [
        ";".join(
            identifier
            for identifier, distance in zip(ids, values)
            if identifier and float(distance) <= float(radius_km)
        )
        for ids, values in zip(all_ids, distances)
    ]
    return out


def fold_completion(folds: pd.DataFrame, expected_repeats: int) -> dict[str, Any]:
    """Return a failure-inclusive fold completion audit."""
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
        "failed_repeats": max(0, int(expected_repeats) - valid),
    }
