"""
GBIF FieldMap Builder

Bias-aware Streamlit app for field-survey planning from either:
1) any coordinate CSV with latitude/longitude columns, or
2) direct scientific-name searches via the GBIF API.

Core workflow:
- occurrence input
- spatial thinning
- DBSCAN clustering
- medoid/centroid candidate-site selection
- optional environment table upload
- VIF-based variable filtering
- ensemble SDM with selectable algorithms
- field-validation template export

The app stores loaded occurrence data in st.session_state, so changing map layers
or sampling settings does not force another CSV upload or GBIF search.
"""

from __future__ import annotations

import math
import re
import urllib.parse
from dataclasses import dataclass
from typing import Any, Optional

import folium
import numpy as np
import pandas as pd
import requests
import streamlit as st
from folium import FeatureGroup, LayerControl, Map
from folium.plugins import MarkerCluster
from geopy.distance import geodesic
from shapely.geometry import MultiPoint, Point
from sklearn.cluster import DBSCAN
from sklearn.ensemble import ExtraTreesClassifier, GradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LinearRegression, LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from streamlit_folium import st_folium


APP_TITLE = "GBIF FieldMap Builder"
EARTH_RADIUS_M = 6_371_008.8
GBIF_SPECIES_MATCH_URL = "https://api.gbif.org/v1/species/match"
GBIF_OCCURRENCE_SEARCH_URL = "https://api.gbif.org/v1/occurrence/search"

LAT_CANDIDATES = ["decimallatitude", "decimal_latitude", "decimal latitude", "latitude", "lat", "y", "緯度"]
LON_CANDIDATES = ["decimallongitude", "decimal_longitude", "decimal longitude", "longitude", "lon", "lng", "long", "x", "経度"]
DATE_CANDIDATES = ["eventdate", "event_date", "event date", "date", "observedon", "observed_on", "observationdate", "観察日", "日付"]
YEAR_CANDIDATES = ["year", "eventyear", "event_year", "observationyear", "年"]
SPECIES_CANDIDATES = ["species", "scientificname", "scientific_name", "scientific name", "taxonname", "acceptedscientificname", "verbatimscientificname", "種名"]
MEDIA_CANDIDATES = ["mediaurl", "media_url", "imageurl", "image_url", "identifier", "associatedmedia", "associated_media", "photo", "image", "写真", "画像"]
GBIF_ID_CANDIDATES = ["gbifid", "gbif_id", "key", "occurrenceid", "occurrence_id"]
LOCALITY_CANDIDATES = ["locality", "municipality", "county", "stateprovince", "location", "place", "site", "場所", "地点"]
PRESENCE_CANDIDATES = ["presence", "pa", "occurrence", "target_species_found", "found", "label"]
SITE_ID_CANDIDATES = ["site_id", "site", "id", "candidate_id"]

SUGGESTED_ENV_VARS = [
    "elevation", "slope", "roughness",
    "bio1", "bio2", "bio3", "bio4", "bio5", "bio6", "bio7", "bio8", "bio9", "bio10",
    "bio11", "bio12", "bio13", "bio14", "bio15", "bio16", "bio17", "bio18", "bio19",
]
DEFAULT_ENV_VARS = ["elevation", "slope", "roughness", "bio1", "bio4", "bio12", "bio15", "bio19"]


@dataclass(frozen=True)
class ColumnDetection:
    latitude: str
    longitude: str
    event_date: Optional[str] = None
    year: Optional[str] = None
    species: Optional[str] = None
    media_url: Optional[str] = None
    gbif_id: Optional[str] = None
    locality: Optional[str] = None


@dataclass(frozen=True)
class GBIFTaxonMatch:
    input_name: str
    usage_key: Optional[int]
    matched_name: str = ""
    rank: str = ""
    status: str = ""
    confidence: Optional[int] = None


def init_session_state() -> None:
    defaults = {
        "raw_df": None,
        "source_message": "No occurrence data loaded yet.",
        "source_kind": None,
        "source_key": None,
        "sdm_result": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def clear_loaded_data() -> None:
    st.session_state.raw_df = None
    st.session_state.source_message = "No occurrence data loaded yet."
    st.session_state.source_kind = None
    st.session_state.source_key = None
    st.session_state.sdm_result = None


def normalize_name(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9一-龥ぁ-んァ-ン]+", "", str(name)).lower()


def detect_column(columns: list[str], candidates: list[str]) -> Optional[str]:
    normalized = {normalize_name(col): col for col in columns}
    for cand in candidates:
        key = normalize_name(cand)
        if key in normalized:
            return normalized[key]
    for cand in candidates:
        key = normalize_name(cand)
        for norm_col, original in normalized.items():
            if key and key in norm_col:
                return original
    return None


def detect_columns(df: pd.DataFrame) -> ColumnDetection:
    cols = list(df.columns)
    lat = detect_column(cols, LAT_CANDIDATES)
    lon = detect_column(cols, LON_CANDIDATES)
    if lat is None or lon is None:
        raise ValueError(
            "Latitude/longitude columns could not be detected. "
            "Use columns such as decimalLatitude/decimalLongitude, latitude/longitude, lat/lon, lat/lng, 緯度/経度."
        )
    return ColumnDetection(
        latitude=lat,
        longitude=lon,
        event_date=detect_column(cols, DATE_CANDIDATES),
        year=detect_column(cols, YEAR_CANDIDATES),
        species=detect_column(cols, SPECIES_CANDIDATES),
        media_url=detect_column(cols, MEDIA_CANDIDATES),
        gbif_id=detect_column(cols, GBIF_ID_CANDIDATES),
        locality=detect_column(cols, LOCALITY_CANDIDATES),
    )


def first_url(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return ""
    match = re.search(r"https?://[^\s,;|]+", text)
    return match.group(0) if match else ""


def extract_media_url_from_gbif_record(rec: dict[str, Any]) -> str:
    media = rec.get("media") or []
    if isinstance(media, list):
        for item in media:
            if isinstance(item, dict):
                url = first_url(item.get("identifier") or item.get("references") or item.get("source"))
                if url:
                    return url
    return first_url(rec.get("associatedMedia"))


def clean_occurrences(df: pd.DataFrame, cols: ColumnDetection) -> pd.DataFrame:
    out = df.copy()
    out[cols.latitude] = pd.to_numeric(out[cols.latitude], errors="coerce")
    out[cols.longitude] = pd.to_numeric(out[cols.longitude], errors="coerce")
    out = out.dropna(subset=[cols.latitude, cols.longitude]).copy()
    out = out[out[cols.latitude].between(-90, 90) & out[cols.longitude].between(-180, 180)].copy()
    out = out.rename(columns={cols.latitude: "_latitude", cols.longitude: "_longitude"})

    out["_event_date"] = out[cols.event_date].astype(str).replace({"nan": ""}) if cols.event_date and cols.event_date in out.columns else ""
    out["_species"] = out[cols.species].astype(str).replace({"nan": ""}) if cols.species and cols.species in out.columns else ""
    out["_media_url"] = out[cols.media_url].apply(first_url) if cols.media_url and cols.media_url in out.columns else ""
    out["_gbif_id"] = out[cols.gbif_id].astype(str).replace({"nan": ""}) if cols.gbif_id and cols.gbif_id in out.columns else ""
    out["_locality"] = out[cols.locality].astype(str).replace({"nan": ""}) if cols.locality and cols.locality in out.columns else ""

    if cols.year and cols.year in out.columns:
        out["_year"] = pd.to_numeric(out[cols.year], errors="coerce")
    else:
        out["_year"] = pd.to_datetime(out["_event_date"], errors="coerce").dt.year

    return out.reset_index(drop=True)


def match_gbif_taxon(scientific_name: str, timeout_s: int = 30) -> GBIFTaxonMatch:
    if not scientific_name.strip():
        raise ValueError("Scientific name is empty.")
    response = requests.get(GBIF_SPECIES_MATCH_URL, params={"name": scientific_name.strip()}, timeout=timeout_s)
    response.raise_for_status()
    payload = response.json()
    usage_key = payload.get("usageKey")
    return GBIFTaxonMatch(
        input_name=scientific_name.strip(),
        usage_key=int(usage_key) if usage_key is not None else None,
        matched_name=payload.get("scientificName", ""),
        rank=payload.get("rank", ""),
        status=payload.get("status", ""),
        confidence=payload.get("confidence"),
    )


def gbif_records_to_dataframe(records: list[dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for rec in records:
        rows.append({
            "decimalLatitude": rec.get("decimalLatitude"),
            "decimalLongitude": rec.get("decimalLongitude"),
            "eventDate": rec.get("eventDate", ""),
            "year": rec.get("year"),
            "species": rec.get("species") or rec.get("scientificName", ""),
            "scientificName": rec.get("scientificName", ""),
            "basisOfRecord": rec.get("basisOfRecord", ""),
            "countryCode": rec.get("countryCode", ""),
            "locality": rec.get("locality", ""),
            "gbifID": rec.get("gbifID") or rec.get("key"),
            "media_url": extract_media_url_from_gbif_record(rec),
        })
    return pd.DataFrame(rows)


@st.cache_data(show_spinner=False, ttl=3600)
def fetch_gbif_occurrences_cached(scientific_name: str, max_records: int, country_code: str, year_from: Optional[int], year_to: Optional[int]) -> tuple[GBIFTaxonMatch, pd.DataFrame]:
    match = match_gbif_taxon(scientific_name)
    if match.usage_key is None:
        raise ValueError(f"GBIF could not match this scientific name: {scientific_name}")

    params_base: dict[str, Any] = {
        "taxonKey": match.usage_key,
        "hasCoordinate": "true",
        "hasGeospatialIssue": "false",
        "limit": 300,
    }
    if country_code.strip():
        params_base["country"] = country_code.strip().upper()
    if year_from is not None and year_to is not None:
        params_base["year"] = f"{int(year_from)},{int(year_to)}"
    elif year_from is not None:
        params_base["year"] = f"{int(year_from)},"
    elif year_to is not None:
        params_base["year"] = f",{int(year_to)}"

    records: list[dict[str, Any]] = []
    offset = 0
    while len(records) < max_records:
        params = dict(params_base)
        params["offset"] = offset
        params["limit"] = min(300, max_records - len(records))
        response = requests.get(GBIF_OCCURRENCE_SEARCH_URL, params=params, timeout=60)
        response.raise_for_status()
        payload = response.json()
        batch = payload.get("results", [])
        if not batch:
            break
        records.extend(batch)
        offset += len(batch)
        if payload.get("endOfRecords") is True:
            break
    return match, gbif_records_to_dataframe(records)


def spatial_thin(df: pd.DataFrame, thinning_m: float) -> pd.DataFrame:
    if df.empty or thinning_m <= 0:
        out = df.copy()
        out["_thinned_in"] = True
        return out

    work = df.copy()
    work["_year_sort"] = pd.to_numeric(work.get("_year"), errors="coerce").fillna(-9999)
    work["_has_photo_sort"] = work.get("_media_url", "").astype(str).str.len() > 0
    work = work.sort_values(["_has_photo_sort", "_year_sort"], ascending=[False, False]).reset_index(drop=True)

    kept_rows = []
    kept_coords: list[tuple[float, float]] = []
    for _, row in work.iterrows():
        coord = (float(row["_latitude"]), float(row["_longitude"]))
        if all(geodesic(coord, kept).m >= thinning_m for kept in kept_coords):
            kept_rows.append(row)
            kept_coords.append(coord)

    out = pd.DataFrame(kept_rows).drop(columns=["_year_sort", "_has_photo_sort"], errors="ignore").reset_index(drop=True)
    out["_thinned_in"] = True
    return out


def haversine_dbscan(df: pd.DataFrame, threshold_m: float, min_samples: int) -> pd.Series:
    if df.empty:
        return pd.Series(dtype=int, name="cluster_id")
    coords_rad = [[math.radians(lat), math.radians(lon)] for lat, lon in df[["_latitude", "_longitude"]].to_numpy(dtype=float)]
    eps = float(threshold_m) / EARTH_RADIUS_M
    labels = DBSCAN(eps=eps, min_samples=int(min_samples), metric="haversine").fit_predict(coords_rad)
    return pd.Series(labels, index=df.index, name="cluster_id")


def summarize_species(values: pd.Series, max_items: int = 3) -> str:
    cleaned = values.dropna().astype(str).str.strip()
    cleaned = cleaned[cleaned.ne("") & cleaned.ne("nan")]
    if cleaned.empty:
        return ""
    counts = cleaned.value_counts().head(max_items)
    parts = [f"{name} ({count})" for name, count in counts.items()]
    more = cleaned.nunique() - len(counts)
    if more > 0:
        parts.append(f"+{more} more")
    return "; ".join(parts)


def representative_medoid(group: pd.DataFrame) -> pd.Series:
    if len(group) == 1:
        return group.iloc[0]
    coords = [(float(r["_latitude"]), float(r["_longitude"])) for _, r in group.iterrows()]
    best_i = 0
    best_score = float("inf")
    for i, coord in enumerate(coords):
        score = sum(geodesic(coord, other).m for other in coords) / max(len(coords) - 1, 1)
        if str(group.iloc[i].get("_media_url", "")):
            score -= 50
        if score < best_score:
            best_score = score
            best_i = i
    return group.iloc[best_i]


def make_candidate_sites(df: pd.DataFrame, method: str, thinning_m: float) -> pd.DataFrame:
    columns = [
        "site_id", "cluster_id", "latitude", "longitude", "n_occurrences",
        "species_summary", "year_min", "year_max", "representative_gbif_id",
        "representative_media_url", "representative_locality", "candidate_method",
        "selection_reason", "bias_warning", "priority_score",
    ]
    clustered = df[df["cluster_id"] >= 0].copy()
    if clustered.empty:
        return pd.DataFrame(columns=columns)

    sites = []
    for site_id, (cluster_id, group) in enumerate(clustered.groupby("cluster_id", sort=True), start=1):
        years = pd.to_numeric(group.get("_year"), errors="coerce").dropna()
        year_min = int(years.min()) if not years.empty else None
        year_max = int(years.max()) if not years.empty else None
        rep = representative_medoid(group)

        if method == "Centroid":
            points = [Point(float(row["_longitude"]), float(row["_latitude"])) for _, row in group.iterrows()]
            centroid = MultiPoint(points).centroid
            lat, lon = float(centroid.y), float(centroid.x)
            reason = f"Geometric centroid of DBSCAN cluster {cluster_id}. Representative occurrence retained as evidence metadata."
        else:
            lat, lon = float(rep["_latitude"]), float(rep["_longitude"])
            reason = f"Medoid of DBSCAN cluster {cluster_id}: an actual occurrence point minimizing mean distance to other records."

        if thinning_m > 0:
            reason += f" Spatial thinning at {int(thinning_m)} m was applied before clustering to reduce observer-density bias."

        n = int(len(group))
        recent_bonus = 0 if year_max is None else max(0, min(20, year_max - 2000)) / 20
        photo_bonus = 0.15 if str(rep.get("_media_url", "")) else 0
        priority = round(min(1.0, 0.35 + min(math.log1p(n) / math.log1p(30), 1) * 0.35 + recent_bonus * 0.15 + photo_bonus), 3)
        warning = (
            "High occurrence density: high-confidence area, but may reflect access/observer bias."
            if n >= 20 else
            "Low occurrence support: useful supplementary site, but field confirmation risk is higher."
            if n <= 2 else
            "Moderate occurrence support. Check road/trail access and habitat manually."
        )
        sites.append({
            "site_id": site_id,
            "cluster_id": int(cluster_id),
            "latitude": lat,
            "longitude": lon,
            "n_occurrences": n,
            "species_summary": summarize_species(group.get("_species", pd.Series(dtype=str))),
            "year_min": year_min,
            "year_max": year_max,
            "representative_gbif_id": str(rep.get("_gbif_id", "")),
            "representative_media_url": str(rep.get("_media_url", "")),
            "representative_locality": str(rep.get("_locality", "")),
            "candidate_method": method,
            "selection_reason": reason,
            "bias_warning": warning,
            "priority_score": priority,
        })
    return pd.DataFrame(sites, columns=columns)


def add_priority_rank(sites: pd.DataFrame) -> pd.DataFrame:
    out = sites.copy()
    if out.empty:
        out["priority_rank"] = []
        return out
    rank = out.sort_values(["priority_score", "n_occurrences"], ascending=[False, False]).reset_index(drop=True)
    rank["priority_rank"] = range(1, len(rank) + 1)
    return out.merge(rank[["site_id", "priority_rank"]], on="site_id", how="left")


def nearest_neighbor_order(sites: pd.DataFrame) -> pd.DataFrame:
    if sites.empty:
        return sites.copy()
    remaining = sites.copy().reset_index(drop=True)
    start_idx = remaining["longitude"].idxmin()
    route_rows = [remaining.loc[start_idx]]
    remaining = remaining.drop(index=start_idx).reset_index(drop=True)
    while not remaining.empty:
        current = route_rows[-1]
        current_xy = (float(current["latitude"]), float(current["longitude"]))
        distances = remaining.apply(lambda row: geodesic(current_xy, (float(row["latitude"]), float(row["longitude"]))).km, axis=1)
        next_idx = distances.idxmin()
        route_rows.append(remaining.loc[next_idx])
        remaining = remaining.drop(index=next_idx).reset_index(drop=True)
    return pd.DataFrame(route_rows)


def order_sites(sites: pd.DataFrame, mode: str) -> pd.DataFrame:
    if sites.empty:
        out = sites.copy()
        out["route_order"] = []
        return out
    if mode == "Cluster ID":
        ordered = sites.sort_values(["cluster_id", "site_id"])
    elif mode == "Priority score":
        ordered = sites.sort_values(["priority_score", "n_occurrences"], ascending=[False, False])
    elif mode == "Nearest-neighbor route":
        ordered = nearest_neighbor_order(sites)
    elif mode == "North → South":
        ordered = sites.sort_values(["latitude", "longitude"], ascending=[False, True])
    elif mode == "South → North":
        ordered = sites.sort_values(["latitude", "longitude"], ascending=[True, True])
    elif mode == "West → East":
        ordered = sites.sort_values(["longitude", "latitude"], ascending=[True, False])
    else:
        ordered = sites.sort_values(["longitude", "latitude"], ascending=[False, False])
    ordered = ordered.reset_index(drop=True)
    ordered["route_order"] = range(1, len(ordered) + 1)
    return ordered


def make_google_maps_point_url(latitude: float, longitude: float) -> str:
    return f"https://www.google.com/maps/search/?api=1&query={latitude:.6f}%2C{longitude:.6f}"


def make_google_maps_route_url(sites: pd.DataFrame, travelmode: str = "driving", max_waypoints: int = 8) -> str:
    if sites.empty:
        return ""
    ordered = sites.sort_values("route_order") if "route_order" in sites.columns else sites.copy()
    coords = [(float(row["latitude"]), float(row["longitude"])) for _, row in ordered.iterrows()]
    if len(coords) == 1:
        return make_google_maps_point_url(coords[0][0], coords[0][1])
    params = {
        "api": "1",
        "origin": f"{coords[0][0]:.6f},{coords[0][1]:.6f}",
        "destination": f"{coords[-1][0]:.6f},{coords[-1][1]:.6f}",
        "travelmode": travelmode,
    }
    if travelmode != "transit":
        waypoints = coords[1:-1][:max_waypoints]
        if waypoints:
            params["waypoints"] = "|".join(f"{lat:.6f},{lon:.6f}" for lat, lon in waypoints)
    return "https://www.google.com/maps/dir/?" + urllib.parse.urlencode(params, safe=",|")


def add_navigation_columns(sites: pd.DataFrame) -> pd.DataFrame:
    out = sites.copy()
    if out.empty:
        out["google_maps_point_url"] = []
        out["next_site_straight_km"] = []
        return out
    out = out.sort_values("route_order").reset_index(drop=True) if "route_order" in out.columns else out
    out["google_maps_point_url"] = out.apply(lambda row: make_google_maps_point_url(float(row["latitude"]), float(row["longitude"])), axis=1)
    next_dist = []
    for i in range(len(out)):
        if i == len(out) - 1:
            next_dist.append(None)
        else:
            a = (float(out.loc[i, "latitude"]), float(out.loc[i, "longitude"]))
            b = (float(out.loc[i + 1, "latitude"]), float(out.loc[i + 1, "longitude"]))
            next_dist.append(round(float(geodesic(a, b).km), 3))
    out["next_site_straight_km"] = pd.Series(next_dist, dtype="float")
    return out


def numeric_columns(df: pd.DataFrame, exclude: Optional[list[str]] = None) -> list[str]:
    exclude_norm = {normalize_name(x) for x in (exclude or [])}
    cols = []
    for col in df.columns:
        if normalize_name(col) in exclude_norm:
            continue
        s = pd.to_numeric(df[col], errors="coerce")
        if s.notna().sum() >= max(5, int(len(df) * 0.2)):
            cols.append(col)
    return cols


def detect_presence_column(df: pd.DataFrame) -> Optional[str]:
    return detect_column(list(df.columns), PRESENCE_CANDIDATES)


def detect_site_id_column(df: pd.DataFrame) -> Optional[str]:
    return detect_column(list(df.columns), SITE_ID_CANDIDATES)


def prepare_env_table(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in out.columns:
        converted = pd.to_numeric(out[col], errors="coerce")
        if converted.notna().sum() >= max(5, int(len(out) * 0.2)):
            out[col] = converted
    return out


def merge_candidate_environment(candidates: pd.DataFrame, env_df: Optional[pd.DataFrame], max_nearest_m: float = 1000) -> pd.DataFrame:
    if env_df is None or env_df.empty or candidates.empty:
        return candidates.copy()
    env = prepare_env_table(env_df)
    out = candidates.copy()
    site_col = detect_site_id_column(env)
    if site_col and "site_id" in out.columns:
        env2 = env.rename(columns={site_col: "site_id"})
        return out.merge(env2, on="site_id", how="left", suffixes=("", "_env"))
    lat_col = detect_column(list(env.columns), LAT_CANDIDATES)
    lon_col = detect_column(list(env.columns), LON_CANDIDATES)
    if not lat_col or not lon_col:
        return out
    env = env.dropna(subset=[lat_col, lon_col]).copy()
    env[lat_col] = pd.to_numeric(env[lat_col], errors="coerce")
    env[lon_col] = pd.to_numeric(env[lon_col], errors="coerce")
    rows = []
    env_coords = list(zip(env[lat_col], env[lon_col]))
    for _, cand in out.iterrows():
        c = (float(cand["latitude"]), float(cand["longitude"]))
        if not env_coords:
            rows.append(pd.Series(dtype=object))
            continue
        dists = [geodesic(c, (float(lat), float(lon))).m for lat, lon in env_coords]
        idx = int(np.argmin(dists))
        if dists[idx] <= max_nearest_m:
            rows.append(env.iloc[idx].drop(labels=[lat_col, lon_col], errors="ignore"))
        else:
            rows.append(pd.Series(dtype=object))
    env_matched = pd.DataFrame(rows).reset_index(drop=True)
    return pd.concat([out.reset_index(drop=True), env_matched.reset_index(drop=True)], axis=1)


def compute_vif_table(df: pd.DataFrame, variables: list[str]) -> pd.DataFrame:
    rows = []
    X = df[variables].apply(pd.to_numeric, errors="coerce")
    X = X.replace([np.inf, -np.inf], np.nan)
    X = pd.DataFrame(SimpleImputer(strategy="median").fit_transform(X), columns=variables)
    for var in variables:
        others = [v for v in variables if v != var]
        if not others:
            rows.append({"variable": var, "vif": 1.0})
            continue
        y = X[var].values
        X_other = X[others].values
        try:
            r2 = LinearRegression().fit(X_other, y).score(X_other, y)
            vif = 1.0 / max(1e-12, 1.0 - r2)
        except Exception:
            vif = np.inf
        rows.append({"variable": var, "vif": round(float(vif), 3) if np.isfinite(vif) else np.inf})
    return pd.DataFrame(rows).sort_values("vif", ascending=False).reset_index(drop=True)


def vif_step(df: pd.DataFrame, variables: list[str], threshold: float = 10.0) -> tuple[list[str], pd.DataFrame]:
    kept = list(dict.fromkeys(variables))
    history = []
    while len(kept) > 1:
        table = compute_vif_table(df, kept)
        top = table.iloc[0]
        for _, row in table.iterrows():
            history.append({"step": len(history) + 1, "variable": row["variable"], "vif": row["vif"], "status": "checked"})
        if float(top["vif"]) <= threshold:
            break
        removed = str(top["variable"])
        history.append({"step": len(history) + 1, "variable": removed, "vif": top["vif"], "status": "removed"})
        kept.remove(removed)
    final_table = compute_vif_table(df, kept) if kept else pd.DataFrame(columns=["variable", "vif"])
    final_table["status"] = "kept"
    if history:
        removed = pd.DataFrame(history)
        removed = removed[removed["status"].eq("removed")][["variable", "vif", "status"]]
        final_table = pd.concat([final_table, removed], ignore_index=True)
    return kept, final_table


def make_model(name: str, random_state: int = 42):
    if name == "Logistic regression":
        return Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            ("model", LogisticRegression(max_iter=1000, class_weight="balanced", random_state=random_state)),
        ])
    if name == "Random forest":
        return Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("model", RandomForestClassifier(n_estimators=300, random_state=random_state, class_weight="balanced_subsample")),
        ])
    if name == "ExtraTrees":
        return Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("model", ExtraTreesClassifier(n_estimators=300, random_state=random_state, class_weight="balanced")),
        ])
    if name == "Gradient boosting":
        return Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("model", GradientBoostingClassifier(random_state=random_state)),
        ])
    raise ValueError(f"Unknown algorithm: {name}")


def fit_ensemble_sdm(train_df: pd.DataFrame, variables: list[str], presence_col: str, algorithms: list[str], test_size: float = 0.25, random_state: int = 42) -> dict[str, Any]:
    data = train_df.copy()
    y = pd.to_numeric(data[presence_col], errors="coerce")
    mask = y.isin([0, 1])
    data = data.loc[mask].copy()
    y = y.loc[mask].astype(int)
    if y.nunique() < 2:
        raise ValueError("SDM training data must contain both presence=1 and absence/background=0 rows.")
    X = data[variables].apply(pd.to_numeric, errors="coerce")
    stratify = y if y.value_counts().min() >= 2 else None
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=test_size, random_state=random_state, stratify=stratify)
    models = {}
    metrics = []
    for alg in algorithms:
        model = make_model(alg, random_state=random_state)
        model.fit(X_train, y_train)
        prob = model.predict_proba(X_test)[:, 1]
        auc = roc_auc_score(y_test, prob) if y_test.nunique() == 2 else np.nan
        models[alg] = model
        metrics.append({"algorithm": alg, "test_auc": round(float(auc), 3) if np.isfinite(auc) else np.nan})
    return {"models": models, "metrics": pd.DataFrame(metrics), "variables": variables, "presence_col": presence_col}


def predict_ensemble_suitability(sites: pd.DataFrame, sdm_result: Optional[dict[str, Any]]) -> pd.DataFrame:
    out = sites.copy()
    if not sdm_result or out.empty:
        out["sdm_suitability"] = np.nan
        return out
    variables = sdm_result["variables"]
    missing = [v for v in variables if v not in out.columns]
    if missing:
        out["sdm_suitability"] = np.nan
        out["sdm_note"] = f"Missing candidate environmental variables: {', '.join(missing)}"
        return out
    X = out[variables].apply(pd.to_numeric, errors="coerce")
    preds = []
    for _, model in sdm_result["models"].items():
        preds.append(model.predict_proba(X)[:, 1])
    out["sdm_suitability"] = np.mean(np.vstack(preds), axis=0).round(3) if preds else np.nan
    out["sdm_note"] = "Ensemble mean suitability from selected algorithms."
    return out


def update_priority_with_sdm(sites: pd.DataFrame) -> pd.DataFrame:
    out = sites.copy()
    if "sdm_suitability" not in out.columns or out["sdm_suitability"].isna().all():
        return out
    base = pd.to_numeric(out["priority_score"], errors="coerce").fillna(0.5)
    sdm = pd.to_numeric(out["sdm_suitability"], errors="coerce").fillna(base)
    out["priority_score_pre_sdm"] = base
    out["priority_score"] = (0.65 * base + 0.35 * sdm).clip(0, 1).round(3)
    return out


def make_field_validation_template(sites: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "site_id", "priority_rank", "route_order", "latitude", "longitude", "priority_score", "sdm_suitability",
        "visited", "survey_date", "observer", "access_success", "target_species_found",
        "abundance_count", "abundance_class", "flowering_status", "population_area_m2",
        "habitat_note", "photo_file", "comments",
    ]
    base = sites.copy()
    for col in cols:
        if col not in base.columns:
            base[col] = ""
    return base[cols]


def image_html(url: str, width: int = 220) -> str:
    url = first_url(url)
    if not url:
        return ""
    return f"<br><img src='{url}' style='max-width:{width}px; max-height:180px; border-radius:6px; margin-top:6px;'>"


def popup_html_occurrence(row: pd.Series) -> str:
    gbif_id = row.get("_gbif_id", "")
    gbif_link = f"<br><a href='https://www.gbif.org/occurrence/{gbif_id}' target='_blank'>Open GBIF record</a>" if gbif_id else ""
    return f"""
    <b>Occurrence</b><br>
    Latitude: {row['_latitude']:.6f}<br>
    Longitude: {row['_longitude']:.6f}<br>
    Cluster: {row.get('cluster_id', '')}<br>
    Species: {row.get('_species', '')}<br>
    Event date: {row.get('_event_date', '')}<br>
    Locality: {row.get('_locality', '')}
    {gbif_link}
    {image_html(row.get('_media_url', ''))}
    """


def popup_html_site(row: pd.Series) -> str:
    point_url = row.get("google_maps_point_url", "")
    nav = f"<br><a href='{point_url}' target='_blank'>Open this site in Google Maps</a>" if point_url else ""
    years = ""
    if pd.notna(row.get("year_min")) and pd.notna(row.get("year_max")):
        years = f"<br>Years: {int(row['year_min'])}–{int(row['year_max'])}"
    sdm_line = f"<br>SDM suitability: {row.get('sdm_suitability', '')}" if "sdm_suitability" in row.index else ""
    return f"""
    <b>Candidate site {int(row['site_id'])}</b><br>
    Priority rank: {row.get('priority_rank', '')}<br>
    Route order: {int(row.get('route_order', row['site_id']))}<br>
    Cluster: {int(row['cluster_id'])}<br>
    Method: {row.get('candidate_method', '')}<br>
    Priority score: {row.get('priority_score', '')}{sdm_line}<br>
    Occurrences: {int(row['n_occurrences'])}<br>
    Latitude: {row['latitude']:.6f}<br>
    Longitude: {row['longitude']:.6f}<br>
    Species: {row.get('species_summary', '') or 'Not detected'}<br>
    Bias note: {row.get('bias_warning', '')}
    {years}
    {nav}
    {image_html(row.get('representative_media_url', ''))}
    """


def midpoint(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float]:
    return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)


def fit_bounds_or_default(df: pd.DataFrame) -> tuple[list[list[float]], tuple[float, float], int]:
    if df.empty:
        return [[35.0, 135.0], [36.0, 136.0]], (35.5, 135.5), 6
    min_lat, max_lat = df["_latitude"].min(), df["_latitude"].max()
    min_lon, max_lon = df["_longitude"].min(), df["_longitude"].max()
    return [[min_lat, min_lon], [max_lat, max_lon]], ((min_lat + max_lat) / 2, (min_lon + max_lon) / 2), 8


def build_map(occurrences: pd.DataFrame, sites: pd.DataFrame, buffer_radius_m: float, show_occurrences: bool, show_buffers: bool, show_clusters: bool, show_candidate_sites: bool, show_routes: bool, show_distance_labels: bool) -> folium.Map:
    bounds, center, zoom = fit_bounds_or_default(occurrences)
    fmap = Map(location=center, zoom_start=zoom, tiles="OpenStreetMap", control_scale=True)
    cluster_colors = ["red", "orange", "green", "purple", "cadetblue", "darkred", "darkgreen", "darkblue", "pink", "gray"]

    if show_buffers:
        group = FeatureGroup(name="Buffers", show=True)
        for _, row in occurrences.iterrows():
            folium.Circle(location=(row["_latitude"], row["_longitude"]), radius=float(buffer_radius_m), color="#7aa6ff", weight=1, fill=True, fill_opacity=0.08, opacity=0.35).add_to(group)
        group.add_to(fmap)

    if show_occurrences:
        group = FeatureGroup(name="Occurrences", show=True)
        marker_cluster = MarkerCluster(name="Occurrence marker cluster")
        for _, row in occurrences.iterrows():
            folium.CircleMarker(location=(row["_latitude"], row["_longitude"]), radius=4, color="#1f77b4", fill=True, fill_color="#1f77b4", fill_opacity=0.75, weight=1, popup=folium.Popup(popup_html_occurrence(row), max_width=330)).add_to(marker_cluster)
        marker_cluster.add_to(group)
        group.add_to(fmap)

    if show_clusters:
        group = FeatureGroup(name="Clusters", show=True)
        for _, row in occurrences.iterrows():
            label = int(row["cluster_id"])
            color = "black" if label < 0 else cluster_colors[label % len(cluster_colors)]
            folium.CircleMarker(location=(row["_latitude"], row["_longitude"]), radius=6, color=color, fill=True, fill_color=color, fill_opacity=0.45, weight=2, popup=f"Cluster: {label}").add_to(group)
        group.add_to(fmap)

    if show_routes and len(sites) >= 2:
        group = FeatureGroup(name="Routes", show=True)
        route_coords = list(zip(sites["latitude"], sites["longitude"]))
        folium.PolyLine(route_coords, color="red", weight=3, opacity=0.8).add_to(group)
        group.add_to(fmap)

    if show_distance_labels and len(sites) >= 2:
        group = FeatureGroup(name="Straight-line distance labels", show=True)
        route_coords = list(zip(sites["latitude"], sites["longitude"]))
        for i in range(len(route_coords) - 1):
            a = route_coords[i]
            b = route_coords[i + 1]
            dist_km = geodesic(a, b).km
            mid = midpoint(a, b)
            folium.Marker(location=mid, icon=folium.DivIcon(html=f"<div style='font-size:12px;font-weight:700;background:white;border:1px solid #999;border-radius:4px;padding:2px 5px;white-space:nowrap;'>{dist_km:.1f} km</div>")).add_to(group)
        group.add_to(fmap)

    if show_candidate_sites:
        group = FeatureGroup(name="Candidate survey sites", show=True)
        for _, row in sites.iterrows():
            order = int(row.get("route_order", row["site_id"]))
            folium.Marker(location=(row["latitude"], row["longitude"]), popup=folium.Popup(popup_html_site(row), max_width=390), tooltip=f"Site {int(row['site_id'])} / Priority {row.get('priority_rank', '')}", icon=folium.DivIcon(html="<div style='font-size:22px;line-height:22px;color:red;text-shadow:0 0 2px white,0 0 4px white;'>★</div>")).add_to(group)
            folium.Marker(location=(row["latitude"], row["longitude"]), icon=folium.DivIcon(html=f"<div style='font-size:11px;font-weight:700;background:white;border:1px solid #c00;border-radius:10px;padding:1px 5px;margin-left:14px;'>{order}</div>")).add_to(group)
        group.add_to(fmap)

    LayerControl(collapsed=True).add_to(fmap)
    try:
        fmap.fit_bounds(bounds, padding=(30, 30))
    except Exception:
        pass
    return fmap


def read_uploaded_csv(uploaded: Any) -> pd.DataFrame:
    try:
        return pd.read_csv(uploaded)
    except UnicodeDecodeError:
        uploaded.seek(0)
        return pd.read_csv(uploaded, encoding="latin1")


def load_input_controls() -> None:
    mode = st.sidebar.radio("Input source", ["Upload coordinate CSV", "Search GBIF by scientific name"], index=0, key="input_source_mode")
    if st.sidebar.button("Clear loaded data"):
        clear_loaded_data()
    if mode == "Upload coordinate CSV":
        uploaded = st.sidebar.file_uploader("Upload CSV with latitude/longitude columns", type=["csv"], key="csv_upload", help="GBIF format is not required. Any CSV is OK if it has coordinate columns. Species/date/photo columns are optional.")
        if uploaded is not None:
            file_key = f"upload::{uploaded.name}::{uploaded.size}"
            if st.session_state.source_key != file_key:
                st.session_state.raw_df = read_uploaded_csv(uploaded)
                st.session_state.source_message = f"Loaded coordinate CSV: {uploaded.name} ({len(st.session_state.raw_df):,} raw rows)."
                st.session_state.source_kind = "upload"
                st.session_state.source_key = file_key
        return
    scientific_name = st.sidebar.text_input("Scientific name", value="", placeholder="e.g. Campanula punctata", key="gbif_scientific_name")
    country_code = st.sidebar.text_input("Country code filter optional", value="JP", max_chars=2, key="gbif_country")
    max_records = st.sidebar.number_input("Maximum GBIF records", min_value=100, max_value=100_000, value=5000, step=500, key="gbif_max_records")
    use_year_filter = st.sidebar.checkbox("Filter by year", value=False, key="gbif_use_year")
    year_from = None
    year_to = None
    if use_year_filter:
        c1, c2 = st.sidebar.columns(2)
        with c1:
            year_from = int(st.number_input("From", min_value=1600, max_value=2100, value=2000, step=1, key="gbif_year_from"))
        with c2:
            year_to = int(st.number_input("To", min_value=1600, max_value=2100, value=2026, step=1, key="gbif_year_to"))
    if st.sidebar.button("Fetch occurrences from GBIF", type="primary"):
        if not scientific_name.strip():
            st.warning("Scientific name is empty.")
            return
        with st.spinner("Fetching GBIF occurrences..."):
            match, df = fetch_gbif_occurrences_cached(scientific_name.strip(), int(max_records), country_code.strip().upper(), year_from, year_to)
        st.session_state.raw_df = df.copy()
        st.session_state.source_message = f"GBIF match: {match.matched_name or match.input_name} / usageKey={match.usage_key} / confidence={match.confidence}. Fetched {len(df):,} raw occurrence records."
        st.session_state.source_kind = "gbif"
        st.session_state.source_key = f"gbif::{scientific_name.strip()}::{country_code.strip().upper()}::{int(max_records)}::{year_from}::{year_to}"


def environment_sdm_panel(candidates: pd.DataFrame) -> tuple[pd.DataFrame, Optional[dict[str, Any]], Optional[pd.DataFrame], Optional[pd.DataFrame]]:
    st.subheader("Environment variables and ensemble SDM")
    st.caption("Use 30 arc-sec raster-derived values prepared outside the app, or any additional environmental table. Recommended variables include elevation, slope, roughness, and bio1–bio19.")
    with st.expander("Suggested 30 arc-sec variables", expanded=False):
        st.write(SUGGESTED_ENV_VARS)
        st.markdown("Expected SDM training CSV: one row per presence/background point, a `presence` column with 1/0, and environmental variable columns such as `elevation`, `slope`, `roughness`, `bio1` ... `bio19`.")
        st.markdown("Candidate environment CSV can be joined by `site_id`, or nearest latitude/longitude within the selected matching distance.")

    c1, c2 = st.columns(2)
    with c1:
        sdm_file = st.file_uploader("Upload SDM training table CSV", type=["csv"], key="sdm_training_csv")
    with c2:
        cand_env_file = st.file_uploader("Upload candidate/site environment CSV optional", type=["csv"], key="candidate_env_csv")

    env_train = read_uploaded_csv(sdm_file) if sdm_file is not None else None
    cand_env = read_uploaded_csv(cand_env_file) if cand_env_file is not None else None
    max_match_m = st.number_input("Nearest coordinate match distance for candidate env table (m)", min_value=10, max_value=100_000, value=1000, step=100)
    candidates_env = merge_candidate_environment(candidates, cand_env, max_nearest_m=float(max_match_m)) if cand_env is not None else candidates.copy()

    if env_train is None:
        st.info("Upload an SDM training table to run VIF and ensemble SDM. Candidate selection still works without SDM.")
        return candidates_env, None, None, None

    env_train = prepare_env_table(env_train)
    presence_col = detect_presence_column(env_train)
    if presence_col is None:
        st.warning("Could not detect a presence column. Add a column named presence, pa, found, or label with 1/0.")
        return candidates_env, None, env_train, None

    excluded = [presence_col] + LAT_CANDIDATES + LON_CANDIDATES + SITE_ID_CANDIDATES
    available_vars = numeric_columns(env_train, exclude=excluded)
    if not available_vars:
        st.warning("No numeric environmental variables were detected in the SDM training table.")
        return candidates_env, None, env_train, None

    default_vars = [v for v in DEFAULT_ENV_VARS if v in available_vars]
    if not default_vars:
        default_vars = available_vars[: min(8, len(available_vars))]
    selected_vars = st.multiselect("Select environmental variables for SDM", options=available_vars, default=default_vars)
    if not selected_vars:
        st.warning("Select at least one environmental variable.")
        return candidates_env, None, env_train, None

    use_vif = st.checkbox("Apply VIF filtering", value=True)
    vif_threshold = st.number_input("VIF threshold", min_value=1.0, max_value=100.0, value=10.0, step=1.0)
    if use_vif and len(selected_vars) > 1:
        kept_vars, vif_table = vif_step(env_train, selected_vars, threshold=float(vif_threshold))
    else:
        kept_vars = selected_vars
        vif_table = compute_vif_table(env_train, selected_vars) if len(selected_vars) > 1 else pd.DataFrame({"variable": selected_vars, "vif": [1.0] * len(selected_vars), "status": ["kept"] * len(selected_vars)})
    st.write("Variables after VIF filtering:", kept_vars)
    st.dataframe(vif_table, width="stretch", hide_index=True)

    algorithms = st.multiselect("Select SDM algorithms for ensemble", ["Logistic regression", "Random forest", "ExtraTrees", "Gradient boosting"], default=["Logistic regression", "Random forest", "ExtraTrees"])
    test_size = st.slider("Test split proportion", min_value=0.1, max_value=0.5, value=0.25, step=0.05)
    if st.button("Run ensemble SDM", type="primary"):
        if not algorithms:
            st.warning("Select at least one algorithm.")
        else:
            with st.spinner("Fitting ensemble SDM..."):
                st.session_state.sdm_result = fit_ensemble_sdm(env_train, kept_vars, presence_col, algorithms, float(test_size))
    sdm_result = st.session_state.sdm_result
    if sdm_result:
        st.success("Ensemble SDM is available for candidate suitability prediction.")
        st.dataframe(sdm_result["metrics"], width="stretch", hide_index=True)
        candidates_env = predict_ensemble_suitability(candidates_env, sdm_result)
        candidates_env = update_priority_with_sdm(candidates_env)
    else:
        candidates_env = predict_ensemble_suitability(candidates_env, None)
    return candidates_env, sdm_result, env_train, vif_table


def main() -> None:
    st.set_page_config(page_title=APP_TITLE, page_icon="🗺️", layout="wide")
    init_session_state()
    st.title("🗺️ GBIF FieldMap Builder")
    st.caption("Bias-aware field survey planning from coordinate data, environmental variables, ensemble SDM, and field validation.")

    st.sidebar.header("Data source")
    load_input_controls()
    st.sidebar.divider()
    st.sidebar.subheader("Sampling design")
    thinning_m = st.sidebar.number_input("Spatial thinning distance before clustering (m)", min_value=0, max_value=50_000, value=1000, step=500)
    candidate_method = st.sidebar.selectbox("Candidate site method", ["Medoid", "Centroid"], index=0, help="Medoid is recommended: it selects an actual occurrence point.")
    buffer_radius_m = st.sidebar.number_input("Buffer radius around occurrences (m)", 0, 100_000, 500, 100)
    dbscan_threshold_m = st.sidebar.number_input("DBSCAN cluster distance threshold (m)", 1, 500_000, 2000, 500)
    min_samples = st.sidebar.number_input("Minimum occurrences per cluster", 1, 50, 1, 1)
    route_order_mode = st.sidebar.selectbox("Candidate site order", ["Cluster ID", "Priority score", "Nearest-neighbor route", "North → South", "South → North", "West → East", "East → West"], index=2)
    priority_top_n = st.sidebar.number_input("Show top N priority candidates", min_value=1, max_value=100, value=10, step=1)
    st.sidebar.divider()
    st.sidebar.subheader("Layers")
    show_occurrences = st.sidebar.checkbox("Occurrences", value=True)
    show_buffers = st.sidebar.checkbox("Buffers", value=True)
    show_clusters = st.sidebar.checkbox("Clusters", value=False)
    show_candidate_sites = st.sidebar.checkbox("Candidate survey sites", value=True)
    show_routes = st.sidebar.checkbox("Routes", value=True)
    show_distance_labels = st.sidebar.checkbox("Straight-line distance labels", value=True)

    raw_df = st.session_state.raw_df
    if raw_df is None:
        st.info(st.session_state.source_message)
        st.markdown("""
        **Two ways to start:**
        1. Upload any CSV with latitude/longitude columns. GBIF format is not required.
        2. Enter a scientific name and fetch occurrences directly from GBIF.

        Optional columns such as species/scientificName, eventDate/year, locality, gbifID, and image/media URL will be detected automatically.
        """)
        return

    st.success(st.session_state.source_message)
    try:
        detected = detect_columns(raw_df)
        occ_raw = clean_occurrences(raw_df, detected)
    except Exception as exc:
        st.error(str(exc))
        return
    if occ_raw.empty:
        st.error("No valid coordinate records were found after cleaning.")
        return

    occ = spatial_thin(occ_raw, float(thinning_m))
    try:
        occ["cluster_id"] = haversine_dbscan(occ, float(dbscan_threshold_m), int(min_samples))
    except Exception as exc:
        st.error(f"Clustering failed: {exc}")
        return

    candidate_sites = make_candidate_sites(occ, candidate_method, float(thinning_m))
    candidate_sites = add_priority_rank(candidate_sites)
    ordered_sites_base = add_navigation_columns(order_sites(candidate_sites, route_order_mode))

    ordered_sites, sdm_result, env_train, vif_table = environment_sdm_panel(ordered_sites_base)
    ordered_sites = add_priority_rank(ordered_sites)
    ordered_sites = add_navigation_columns(order_sites(ordered_sites, route_order_mode))

    route_url = make_google_maps_route_url(ordered_sites, travelmode="driving")
    transit_route_url = make_google_maps_route_url(ordered_sites, travelmode="transit")
    clustered_mask = occ["cluster_id"] >= 0
    total_clusters = int(occ.loc[clustered_mask, "cluster_id"].nunique()) if clustered_mask.any() else 0
    noise_points = int((occ["cluster_id"] < 0).sum())

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Raw valid records", f"{len(occ_raw):,}")
    col2.metric("After thinning", f"{len(occ):,}")
    col3.metric("Clusters", f"{total_clusters:,}")
    col4.metric("Candidate sites", f"{len(ordered_sites):,}")
    col5.metric("Noise points", f"{noise_points:,}")

    if route_url:
        c1, c2 = st.columns(2)
        with c1:
            st.link_button("Open driving route in Google Maps", route_url, width="stretch")
        with c2:
            st.link_button("Open public-transit route in Google Maps", transit_route_url, width="stretch")

    with st.expander("Detected input columns", expanded=False):
        st.write(detected.__dict__)

    fmap = build_map(occ, ordered_sites, float(buffer_radius_m), show_occurrences, show_buffers, show_clusters, show_candidate_sites, show_routes, show_distance_labels)
    st_folium(fmap, width=None, height=720, returned_objects=[])

    st.subheader("Priority candidate sites")
    priority_cols = ["priority_rank", "site_id", "route_order", "priority_score", "sdm_suitability", "n_occurrences", "latitude", "longitude", "year_min", "year_max", "bias_warning", "selection_reason", "representative_media_url"]
    priority_cols = [c for c in priority_cols if c in ordered_sites.columns]
    priority_sites = ordered_sites.sort_values(["priority_rank"]).head(int(priority_top_n)) if not ordered_sites.empty else ordered_sites
    if priority_sites.empty:
        st.warning("No priority candidates were generated. Try changing DBSCAN settings.")
    else:
        st.dataframe(priority_sites[priority_cols], width="stretch", hide_index=True)

    st.subheader("All candidate survey sites")
    if ordered_sites.empty:
        st.warning("No candidate sites were generated. Try changing DBSCAN settings.")
    else:
        st.dataframe(ordered_sites, width="stretch", hide_index=True)

    validation_template = make_field_validation_template(ordered_sites)
    html_bytes = fmap.get_root().render().encode("utf-8")
    candidates_csv = ordered_sites.to_csv(index=False).encode("utf-8-sig")
    validation_csv = validation_template.to_csv(index=False).encode("utf-8-sig")
    sdm_metrics_csv = sdm_result["metrics"].to_csv(index=False).encode("utf-8-sig") if sdm_result else b"algorithm,test_auc\n"
    vif_csv = vif_table.to_csv(index=False).encode("utf-8-sig") if vif_table is not None else b"variable,vif,status\n"

    dl1, dl2, dl3, dl4, dl5 = st.columns(5)
    with dl1:
        st.download_button("Download HTML map", html_bytes, "fieldmap.html", "text/html", width="stretch")
    with dl2:
        st.download_button("Download candidate CSV", candidates_csv, "candidate_survey_sites.csv", "text/csv", width="stretch")
    with dl3:
        st.download_button("Download validation template", validation_csv, "field_validation_template.csv", "text/csv", width="stretch")
    with dl4:
        st.download_button("Download SDM metrics", sdm_metrics_csv, "sdm_metrics.csv", "text/csv", width="stretch")
    with dl5:
        st.download_button("Download VIF table", vif_csv, "vif_table.csv", "text/csv", width="stretch")


if __name__ == "__main__":
    main()
