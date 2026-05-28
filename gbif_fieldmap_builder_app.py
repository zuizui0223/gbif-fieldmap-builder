"""
GBIF FieldMap Builder

Interactive field-survey planning app.

Main workflow:
1. Load occurrence records from a coordinate CSV or GBIF scientific-name search.
2. Build occurrence-supported candidate sites using spatial thinning, DBSCAN, and medoid/centroid selection.
3. Run an ensemble SDM directly from the loaded occurrences:
   - occurrences become presence points,
   - background points are generated automatically,
   - WorldClim rasters are downloaded from the web,
   - raster resolution is user-selectable: 30s, 2.5m, 5m, 10m,
   - default variables are elevation, slope, roughness, and bio19,
   - VIF threshold is user-editable, default 10,
   - algorithms are user-selectable,
   - progress is shown step by step.
4. Suggest both occurrence-supported sites and SDM-high / occurrence-low exploration sites.
5. Export map, candidate table, field-validation template, SDM metrics, VIF table, and SDM training table.
"""

from __future__ import annotations

import math
import os
import re
import urllib.parse
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import folium
import numpy as np
import pandas as pd
import rasterio
import requests
import streamlit as st
from folium import FeatureGroup, LayerControl, Map
from folium.plugins import MarkerCluster
from geopy.distance import geodesic
from rasterio.windows import Window
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
WC_BASE = "https://geodata.ucdavis.edu/climate/worldclim/2_1/base"
CACHE_DIR = Path(os.environ.get("GBIF_FIELDMAP_CACHE", "/tmp/gbif_fieldmap_builder"))
CACHE_DIR.mkdir(parents=True, exist_ok=True)

LAT_CANDIDATES = ["decimallatitude", "decimal_latitude", "decimal latitude", "latitude", "lat", "y", "緯度"]
LON_CANDIDATES = ["decimallongitude", "decimal_longitude", "decimal longitude", "longitude", "lon", "lng", "long", "x", "経度"]
DATE_CANDIDATES = ["eventdate", "event_date", "event date", "date", "observedon", "observed_on", "observationdate", "観察日", "日付"]
YEAR_CANDIDATES = ["year", "eventyear", "event_year", "observationyear", "年"]
SPECIES_CANDIDATES = ["species", "scientificname", "scientific_name", "scientific name", "taxonname", "acceptedscientificname", "verbatimscientificname", "種名"]
MEDIA_CANDIDATES = ["mediaurl", "media_url", "imageurl", "image_url", "identifier", "associatedmedia", "associated_media", "photo", "image", "写真", "画像"]
GBIF_ID_CANDIDATES = ["gbifid", "gbif_id", "key", "occurrenceid", "occurrence_id"]
LOCALITY_CANDIDATES = ["locality", "municipality", "county", "stateprovince", "location", "place", "site", "場所", "地点"]
PRESENCE_CANDIDATES = ["presence", "pa", "occurrence", "target_species_found", "found", "label"]

BIO_VARS = [f"bio{i}" for i in range(1, 20)]
ENV_VARS = ["elevation", "slope", "roughness"] + BIO_VARS
DEFAULT_VARS = ["elevation", "slope", "roughness", "bio19"]
RESOLUTIONS = ["2.5m", "5m", "10m", "30s"]
ALGORITHMS = ["Logistic regression", "Random forest", "ExtraTrees", "Gradient boosting"]


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


def init_session_state() -> None:
    defaults = {
        "raw_df": None,
        "source_message": "No occurrence data loaded yet.",
        "source_key": None,
        "sdm_result": None,
        "sdm_train_table": None,
        "prediction_grid": None,
        "vif_table": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def clear_loaded_data() -> None:
    for key in ["raw_df", "source_key", "sdm_result", "sdm_train_table", "prediction_grid", "vif_table"]:
        st.session_state[key] = None
    st.session_state.source_message = "No occurrence data loaded yet."


def detect_occurrence_columns(df: pd.DataFrame) -> ColumnDetection:
    cols = list(df.columns)
    lat = detect_column(cols, LAT_CANDIDATES)
    lon = detect_column(cols, LON_CANDIDATES)
    if lat is None or lon is None:
        raise ValueError("Latitude/longitude columns could not be detected. Use decimalLatitude/decimalLongitude, latitude/longitude, lat/lon, lat/lng, or 緯度/経度.")
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


def read_uploaded_csv(uploaded: Any) -> pd.DataFrame:
    try:
        return pd.read_csv(uploaded)
    except UnicodeDecodeError:
        uploaded.seek(0)
        return pd.read_csv(uploaded, encoding="latin1")


def match_gbif_taxon(scientific_name: str, timeout_s: int = 30) -> GBIFTaxonMatch:
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
    params_base: dict[str, Any] = {"taxonKey": match.usage_key, "hasCoordinate": "true", "hasGeospatialIssue": "false", "limit": 300}
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


def haversine_dbscan(df: pd.DataFrame, lat_col: str, lon_col: str, threshold_m: float, min_samples: int) -> pd.Series:
    if df.empty:
        return pd.Series(dtype=int, name="cluster_id")
    coords_rad = [[math.radians(lat), math.radians(lon)] for lat, lon in df[[lat_col, lon_col]].to_numpy(dtype=float)]
    eps = float(threshold_m) / EARTH_RADIUS_M
    labels = DBSCAN(eps=eps, min_samples=int(min_samples), metric="haversine").fit_predict(coords_rad)
    return pd.Series(labels, index=df.index, name="cluster_id")


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


def make_candidate_sites(df: pd.DataFrame, method: str, thinning_m: float) -> pd.DataFrame:
    columns = ["site_id", "candidate_type", "cluster_id", "latitude", "longitude", "n_occurrences", "species_summary", "year_min", "year_max", "representative_gbif_id", "representative_media_url", "representative_locality", "candidate_method", "selection_reason", "bias_warning", "priority_score"]
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
            reason = f"Geometric centroid of occurrence cluster {cluster_id}."
        else:
            lat, lon = float(rep["_latitude"]), float(rep["_longitude"])
            reason = f"Medoid of occurrence cluster {cluster_id}: an actual occurrence point minimizing mean distance to other records."
        if thinning_m > 0:
            reason += f" Spatial thinning at {int(thinning_m)} m was applied before clustering."
        n = int(len(group))
        recent_bonus = 0 if year_max is None else max(0, min(20, year_max - 2000)) / 20
        photo_bonus = 0.15 if str(rep.get("_media_url", "")) else 0
        priority = round(min(1.0, 0.35 + min(math.log1p(n) / math.log1p(30), 1) * 0.35 + recent_bonus * 0.15 + photo_bonus), 3)
        warning = "High occurrence density: high-confidence area, but may reflect access/observer bias." if n >= 20 else "Low occurrence support: useful supplementary site, but field confirmation risk is higher." if n <= 2 else "Moderate occurrence support. Check road/trail access and habitat manually."
        sites.append({"site_id": site_id, "candidate_type": "Occurrence-supported site", "cluster_id": int(cluster_id), "latitude": lat, "longitude": lon, "n_occurrences": n, "species_summary": summarize_species(group.get("_species", pd.Series(dtype=str))), "year_min": year_min, "year_max": year_max, "representative_gbif_id": str(rep.get("_gbif_id", "")), "representative_media_url": str(rep.get("_media_url", "")), "representative_locality": str(rep.get("_locality", "")), "candidate_method": method, "selection_reason": reason, "bias_warning": warning, "priority_score": priority})
    return pd.DataFrame(sites, columns=columns)


def add_priority_rank(sites: pd.DataFrame) -> pd.DataFrame:
    out = sites.copy()
    if out.empty:
        out["priority_rank"] = []
        return out
    sort_cols = ["priority_score"]
    if "sdm_suitability" in out.columns:
        sort_cols.append("sdm_suitability")
    if "n_occurrences" in out.columns:
        sort_cols.append("n_occurrences")
    rank = out.sort_values(sort_cols, ascending=False).reset_index(drop=True)
    rank["priority_rank"] = range(1, len(rank) + 1)
    out = out.drop(columns=["priority_rank"], errors="ignore")
    return out.merge(rank[["site_id", "priority_rank"]], on="site_id", how="left")


def order_sites(sites: pd.DataFrame, mode: str) -> pd.DataFrame:
    if sites.empty:
        out = sites.copy()
        out["route_order"] = []
        return out
    if mode == "Priority score":
        sort_cols = ["priority_score"]
        if "sdm_suitability" in sites.columns:
            sort_cols.append("sdm_suitability")
        ordered = sites.sort_values(sort_cols, ascending=False)
    elif mode == "Nearest-neighbor route":
        ordered = nearest_neighbor_order(sites)
    elif mode == "North → South":
        ordered = sites.sort_values(["latitude", "longitude"], ascending=[False, True])
    elif mode == "South → North":
        ordered = sites.sort_values(["latitude", "longitude"], ascending=[True, True])
    elif mode == "West → East":
        ordered = sites.sort_values(["longitude", "latitude"], ascending=[True, False])
    elif mode == "East → West":
        ordered = sites.sort_values(["longitude", "latitude"], ascending=[False, False])
    else:
        ordered = sites.sort_values(["candidate_type", "cluster_id", "site_id"])
    ordered = ordered.reset_index(drop=True)
    ordered["route_order"] = range(1, len(ordered) + 1)
    return ordered


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


def make_google_maps_point_url(latitude: float, longitude: float) -> str:
    return f"https://www.google.com/maps/search/?api=1&query={latitude:.6f}%2C{longitude:.6f}"


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


def make_google_maps_route_url(sites: pd.DataFrame, travelmode: str = "driving", max_waypoints: int = 8) -> str:
    if sites.empty:
        return ""
    ordered = sites.sort_values("route_order") if "route_order" in sites.columns else sites.copy()
    coords = [(float(row["latitude"]), float(row["longitude"])) for _, row in ordered.iterrows()]
    if len(coords) == 1:
        return make_google_maps_point_url(coords[0][0], coords[0][1])
    params = {"api": "1", "origin": f"{coords[0][0]:.6f},{coords[0][1]:.6f}", "destination": f"{coords[-1][0]:.6f},{coords[-1][1]:.6f}", "travelmode": travelmode}
    if travelmode != "transit":
        waypoints = coords[1:-1][:max_waypoints]
        if waypoints:
            params["waypoints"] = "|".join(f"{lat:.6f},{lon:.6f}" for lat, lon in waypoints)
    return "https://www.google.com/maps/dir/?" + urllib.parse.urlencode(params, safe=",|")


def download_file(url: str, dest: Path) -> Path:
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    with requests.get(url, stream=True, timeout=180) as response:
        response.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
    tmp.replace(dest)
    return dest


@st.cache_data(show_spinner=False)
def get_worldclim_raster_path(var: str, resolution: str) -> str:
    var = var.lower()
    resolution = resolution.lower()
    if var in {"elevation", "slope", "roughness"}:
        zip_name = f"wc2.1_{resolution}_elev.zip"
        tif_name = f"wc2.1_{resolution}_elev.tif"
    elif var.startswith("bio"):
        n = int(var.replace("bio", ""))
        zip_name = f"wc2.1_{resolution}_bio.zip"
        tif_name = f"wc2.1_{resolution}_bio_{n}.tif"
    else:
        raise ValueError(f"Unsupported web variable: {var}")
    zip_path = CACHE_DIR / zip_name
    extract_dir = CACHE_DIR / zip_name.replace(".zip", "")
    raster_path = extract_dir / tif_name
    if raster_path.exists():
        return str(raster_path)
    extract_dir.mkdir(parents=True, exist_ok=True)
    download_file(f"{WC_BASE}/{zip_name}", zip_path)
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(extract_dir)
    matches = list(extract_dir.rglob(tif_name))
    if not matches:
        raise FileNotFoundError(f"Could not find {tif_name} after extracting {zip_name}")
    return str(matches[0])


def sample_raster_values(points: pd.DataFrame, raster_path: str, lat_col: str, lon_col: str, derived: Optional[str] = None) -> np.ndarray:
    values = []
    with rasterio.open(raster_path) as src:
        nodata = src.nodata
        for _, row in points.iterrows():
            lon = float(row[lon_col])
            lat = float(row[lat_col])
            if derived is None:
                val = next(src.sample([(lon, lat)]))[0]
                if nodata is not None and val == nodata:
                    val = np.nan
                values.append(float(val) if np.isfinite(val) else np.nan)
            else:
                try:
                    r, c = src.index(lon, lat)
                    arr = src.read(1, window=Window(c - 1, r - 1, 3, 3), boundless=True, fill_value=np.nan).astype(float)
                    if nodata is not None:
                        arr[arr == nodata] = np.nan
                    if derived == "roughness":
                        val = np.nanmax(arr) - np.nanmin(arr)
                    elif derived == "slope":
                        gy, gx = np.gradient(arr)
                        val = np.nanmean(np.sqrt(gx**2 + gy**2))
                    else:
                        val = np.nan
                    values.append(float(val) if np.isfinite(val) else np.nan)
                except Exception:
                    values.append(np.nan)
    return np.array(values, dtype=float)


def extract_web_environment(points: pd.DataFrame, variables: list[str], lat_col: str, lon_col: str, resolution: str, status=None, progress=None, start: float = 0.0, span: float = 1.0) -> pd.DataFrame:
    out = points.copy()
    total = max(len(variables), 1)
    for i, var in enumerate(variables, start=1):
        if status is not None:
            status.write(f"Extracting {var} ({resolution}) [{i}/{total}]...")
        if progress is not None:
            progress.progress(min(1.0, start + span * (i - 1) / total))
        if var == "slope":
            elev_path = get_worldclim_raster_path("elevation", resolution)
            out[var] = sample_raster_values(out, elev_path, lat_col, lon_col, derived="slope")
        elif var == "roughness":
            elev_path = get_worldclim_raster_path("elevation", resolution)
            out[var] = sample_raster_values(out, elev_path, lat_col, lon_col, derived="roughness")
        else:
            raster_path = get_worldclim_raster_path(var, resolution)
            out[var] = sample_raster_values(out, raster_path, lat_col, lon_col)
    if progress is not None:
        progress.progress(min(1.0, start + span))
    return out


def generate_background_points(occ: pd.DataFrame, n_background: int, expansion_deg: float, random_state: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(random_state)
    min_lat, max_lat = occ["_latitude"].min() - expansion_deg, occ["_latitude"].max() + expansion_deg
    min_lon, max_lon = occ["_longitude"].min() - expansion_deg, occ["_longitude"].max() + expansion_deg
    lat = rng.uniform(max(-90, min_lat), min(90, max_lat), int(n_background))
    lon = rng.uniform(max(-180, min_lon), min(180, max_lon), int(n_background))
    return pd.DataFrame({"latitude": lat, "longitude": lon, "presence": 0})


def build_presence_background_from_occurrences(occ: pd.DataFrame, n_background: int, expansion_deg: float) -> pd.DataFrame:
    pres = occ[["_latitude", "_longitude"]].rename(columns={"_latitude": "latitude", "_longitude": "longitude"}).copy()
    pres["presence"] = 1
    bg = generate_background_points(occ, n_background, expansion_deg)
    return pd.concat([pres, bg], ignore_index=True)


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


def compute_vif_table(df: pd.DataFrame, variables: list[str]) -> pd.DataFrame:
    rows = []
    X = df[variables].apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan)
    X = pd.DataFrame(SimpleImputer(strategy="median").fit_transform(X), columns=variables)
    for var in variables:
        others = [v for v in variables if v != var]
        if not others:
            rows.append({"variable": var, "vif": 1.0})
            continue
        try:
            r2 = LinearRegression().fit(X[others].values, X[var].values).score(X[others].values, X[var].values)
            vif = 1.0 / max(1e-12, 1.0 - r2)
        except Exception:
            vif = np.inf
        rows.append({"variable": var, "vif": round(float(vif), 3) if np.isfinite(vif) else np.inf})
    return pd.DataFrame(rows).sort_values("vif", ascending=False).reset_index(drop=True)


def vif_step(df: pd.DataFrame, variables: list[str], threshold: float = 10.0, status=None, progress=None, start: float = 0.0, span: float = 0.1) -> tuple[list[str], pd.DataFrame]:
    kept = list(dict.fromkeys(variables))
    removed_rows = []
    iter_n = 0
    while len(kept) > 1:
        iter_n += 1
        if status is not None:
            status.write(f"Running VIF step {iter_n} with threshold {threshold}...")
        if progress is not None:
            progress.progress(min(1.0, start + span * min(iter_n, 10) / 10))
        table = compute_vif_table(df, kept)
        top = table.iloc[0]
        if float(top["vif"]) <= threshold:
            break
        removed = str(top["variable"])
        removed_rows.append({"variable": removed, "vif": top["vif"], "status": "removed"})
        kept.remove(removed)
    final_table = compute_vif_table(df, kept) if kept else pd.DataFrame(columns=["variable", "vif"])
    final_table["status"] = "kept"
    if removed_rows:
        final_table = pd.concat([final_table, pd.DataFrame(removed_rows)], ignore_index=True)
    return kept, final_table


def make_model(name: str, random_state: int = 42):
    if name == "Logistic regression":
        return Pipeline([("imputer", SimpleImputer(strategy="median")), ("scaler", StandardScaler()), ("model", LogisticRegression(max_iter=1000, class_weight="balanced", random_state=random_state))])
    if name == "Random forest":
        return Pipeline([("imputer", SimpleImputer(strategy="median")), ("model", RandomForestClassifier(n_estimators=300, random_state=random_state, class_weight="balanced_subsample"))])
    if name == "ExtraTrees":
        return Pipeline([("imputer", SimpleImputer(strategy="median")), ("model", ExtraTreesClassifier(n_estimators=300, random_state=random_state, class_weight="balanced"))])
    if name == "Gradient boosting":
        return Pipeline([("imputer", SimpleImputer(strategy="median")), ("model", GradientBoostingClassifier(random_state=random_state))])
    raise ValueError(f"Unknown algorithm: {name}")


def fit_ensemble_sdm(train_df: pd.DataFrame, variables: list[str], presence_col: str, algorithms: list[str], test_size: float, status=None, progress=None, start: float = 0.0, span: float = 0.2) -> dict[str, Any]:
    data = train_df.copy()
    y = pd.to_numeric(data[presence_col], errors="coerce")
    mask = y.isin([0, 1])
    data = data.loc[mask].copy()
    y = y.loc[mask].astype(int)
    if y.nunique() < 2:
        raise ValueError("SDM training data must contain both presence=1 and background/absence=0 rows.")
    X = data[variables].apply(pd.to_numeric, errors="coerce")
    stratify = y if y.value_counts().min() >= 2 else None
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=test_size, random_state=42, stratify=stratify)
    models = {}
    metrics = []
    total = max(len(algorithms), 1)
    for i, alg in enumerate(algorithms, start=1):
        if status is not None:
            status.write(f"Fitting {alg} [{i}/{total}]...")
        if progress is not None:
            progress.progress(min(1.0, start + span * (i - 1) / total))
        model = make_model(alg)
        model.fit(X_train, y_train)
        prob = model.predict_proba(X_test)[:, 1]
        auc = roc_auc_score(y_test, prob) if y_test.nunique() == 2 else np.nan
        models[alg] = model
        metrics.append({"algorithm": alg, "test_auc": round(float(auc), 3) if np.isfinite(auc) else np.nan})
    if progress is not None:
        progress.progress(min(1.0, start + span))
    return {"models": models, "metrics": pd.DataFrame(metrics), "variables": variables, "presence_col": presence_col}


def predict_ensemble_suitability(table: pd.DataFrame, sdm_result: Optional[dict[str, Any]]) -> pd.DataFrame:
    out = table.copy()
    if not sdm_result or out.empty:
        out["sdm_suitability"] = np.nan
        return out
    variables = sdm_result["variables"]
    missing = [v for v in variables if v not in out.columns]
    if missing:
        out["sdm_suitability"] = np.nan
        out["sdm_note"] = f"Missing environmental variables: {', '.join(missing)}"
        return out
    X = out[variables].apply(pd.to_numeric, errors="coerce")
    preds = [model.predict_proba(X)[:, 1] for model in sdm_result["models"].values()]
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


def min_distance_to_points(coord: tuple[float, float], point_df: pd.DataFrame, lat_col: str, lon_col: str) -> float:
    if point_df is None or point_df.empty:
        return float("inf")
    return min(geodesic(coord, (float(r[lat_col]), float(r[lon_col]))).m for _, r in point_df.iterrows())


def make_sdm_exploration_candidates(prediction_grid: pd.DataFrame, sdm_result: Optional[dict[str, Any]], known_occ: pd.DataFrame, occurrence_candidates: pd.DataFrame, min_suitability: float, quantile_cutoff: float, min_distance_known_m: float, cluster_distance_m: float, max_candidates: int, start_site_id: int, status=None, progress=None, start: float = 0.9, span: float = 0.08) -> pd.DataFrame:
    columns = list(occurrence_candidates.columns)
    if not sdm_result or prediction_grid is None or prediction_grid.empty:
        return pd.DataFrame(columns=columns)
    if status is not None:
        status.write("Predicting SDM suitability across exploration grid...")
    if progress is not None:
        progress.progress(start)
    grid = prediction_grid.copy()
    pred = predict_ensemble_suitability(grid, sdm_result).dropna(subset=["sdm_suitability"]).copy()
    if pred.empty:
        return pd.DataFrame(columns=columns)
    q = pred["sdm_suitability"].quantile(float(quantile_cutoff))
    pred = pred[pred["sdm_suitability"] >= max(float(min_suitability), float(q))].copy()
    if pred.empty:
        return pd.DataFrame(columns=columns)
    occ_points = known_occ[["_latitude", "_longitude"]].dropna().copy()
    cand_points = occurrence_candidates[["latitude", "longitude"]].dropna().copy() if not occurrence_candidates.empty else pd.DataFrame(columns=["latitude", "longitude"])
    keep = []
    min_dists = []
    for _, row in pred.iterrows():
        coord = (float(row["latitude"]), float(row["longitude"]))
        d = min(min_distance_to_points(coord, occ_points, "_latitude", "_longitude"), min_distance_to_points(coord, cand_points, "latitude", "longitude"))
        keep.append(d >= float(min_distance_known_m))
        min_dists.append(round(d))
    pred["distance_to_nearest_known_m"] = min_dists
    pred = pred[pd.Series(keep, index=pred.index)].copy()
    if pred.empty:
        return pd.DataFrame(columns=columns)
    if status is not None:
        status.write("Clustering high-suitability exploration grid points...")
    pred["exploration_cluster"] = haversine_dbscan(pred, "latitude", "longitude", cluster_distance_m, 1)
    rows = []
    for i, (_, group) in enumerate(pred.groupby("exploration_cluster", sort=True), start=0):
        best = group.sort_values("sdm_suitability", ascending=False).iloc[0]
        site_id = start_site_id + i
        rows.append({
            "site_id": site_id,
            "candidate_type": "SDM-high / occurrence-low exploration site",
            "cluster_id": int(best["exploration_cluster"]),
            "latitude": float(best["latitude"]),
            "longitude": float(best["longitude"]),
            "n_occurrences": 0,
            "species_summary": "",
            "year_min": None,
            "year_max": None,
            "representative_gbif_id": "",
            "representative_media_url": "",
            "representative_locality": "",
            "candidate_method": "SDM exploration grid maximum",
            "selection_reason": f"Selected because ensemble SDM suitability is high ({float(best['sdm_suitability']):.3f}) and no known occurrence/candidate exists within {int(min_distance_known_m)} m.",
            "bias_warning": "New exploration candidate: high SDM suitability but no nearby occurrence evidence. Important for validation/discovery, but field confirmation risk is higher.",
            "priority_score": round(float(best["sdm_suitability"]), 3),
            "sdm_suitability": round(float(best["sdm_suitability"]), 3),
            "distance_to_nearest_known_m": float(best["distance_to_nearest_known_m"]),
        })
    out = pd.DataFrame(rows).sort_values("sdm_suitability", ascending=False).head(int(max_candidates)).reset_index(drop=True)
    for col in columns:
        if col not in out.columns:
            out[col] = np.nan
    if progress is not None:
        progress.progress(min(1.0, start + span))
    return out


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
    sdm_line = f"<br>SDM suitability: {row.get('sdm_suitability', '')}" if "sdm_suitability" in row.index else ""
    return f"""
    <b>Candidate site {int(row['site_id'])}</b><br>
    Type: {row.get('candidate_type', '')}<br>
    Priority rank: {row.get('priority_rank', '')}<br>
    Route order: {int(row.get('route_order', row['site_id']))}<br>
    Method: {row.get('candidate_method', '')}<br>
    Priority score: {row.get('priority_score', '')}{sdm_line}<br>
    Occurrences: {int(row.get('n_occurrences', 0))}<br>
    Latitude: {row['latitude']:.6f}<br>
    Longitude: {row['longitude']:.6f}<br>
    Bias note: {row.get('bias_warning', '')}<br>
    Reason: {row.get('selection_reason', '')}
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
    colors = ["red", "orange", "green", "purple", "cadetblue", "darkred", "darkgreen", "darkblue", "pink", "gray"]
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
        group = FeatureGroup(name="Occurrence clusters", show=True)
        for _, row in occurrences.iterrows():
            label = int(row["cluster_id"])
            color = "black" if label < 0 else colors[label % len(colors)]
            folium.CircleMarker(location=(row["_latitude"], row["_longitude"]), radius=6, color=color, fill=True, fill_color=color, fill_opacity=0.45, weight=2, popup=f"Cluster: {label}").add_to(group)
        group.add_to(fmap)
    if show_routes and len(sites) >= 2:
        group = FeatureGroup(name="Routes", show=True)
        folium.PolyLine(list(zip(sites["latitude"], sites["longitude"])), color="red", weight=3, opacity=0.8).add_to(group)
        group.add_to(fmap)
    if show_distance_labels and len(sites) >= 2:
        group = FeatureGroup(name="Straight-line distance labels", show=True)
        route_coords = list(zip(sites["latitude"], sites["longitude"]))
        for i in range(len(route_coords) - 1):
            a, b = route_coords[i], route_coords[i + 1]
            folium.Marker(location=midpoint(a, b), icon=folium.DivIcon(html=f"<div style='font-size:12px;font-weight:700;background:white;border:1px solid #999;border-radius:4px;padding:2px 5px;white-space:nowrap;'>{geodesic(a, b).km:.1f} km</div>")).add_to(group)
        group.add_to(fmap)
    if show_candidate_sites:
        group = FeatureGroup(name="Candidate survey sites", show=True)
        for _, row in sites.iterrows():
            order = int(row.get("route_order", row["site_id"]))
            is_explore = str(row.get("candidate_type", "")).startswith("SDM-high")
            star_color = "green" if is_explore else "red"
            border_color = "#080" if is_explore else "#c00"
            folium.Marker(location=(row["latitude"], row["longitude"]), popup=folium.Popup(popup_html_site(row), max_width=420), tooltip=f"Site {int(row['site_id'])} / {row.get('candidate_type', '')}", icon=folium.DivIcon(html=f"<div style='font-size:22px;line-height:22px;color:{star_color};text-shadow:0 0 2px white,0 0 4px white;'>★</div>")).add_to(group)
            folium.Marker(location=(row["latitude"], row["longitude"]), icon=folium.DivIcon(html=f"<div style='font-size:11px;font-weight:700;background:white;border:1px solid {border_color};border-radius:10px;padding:1px 5px;margin-left:14px;'>{order}</div>")).add_to(group)
        group.add_to(fmap)
    LayerControl(collapsed=True).add_to(fmap)
    try:
        fmap.fit_bounds(bounds, padding=(30, 30))
    except Exception:
        pass
    return fmap


def load_input_controls() -> None:
    mode = st.sidebar.radio("Input source", ["Upload coordinate CSV", "Search GBIF by scientific name"], index=1, key="input_source_mode")
    if st.sidebar.button("Clear loaded data"):
        clear_loaded_data()
    if mode == "Upload coordinate CSV":
        uploaded = st.sidebar.file_uploader("Upload CSV with latitude/longitude columns", type=["csv"], key="csv_upload")
        if uploaded is not None:
            file_key = f"upload::{uploaded.name}::{uploaded.size}"
            if st.session_state.source_key != file_key:
                st.session_state.raw_df = read_uploaded_csv(uploaded)
                st.session_state.source_message = f"Loaded coordinate CSV: {uploaded.name} ({len(st.session_state.raw_df):,} raw rows)."
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
        st.session_state.source_key = f"gbif::{scientific_name.strip()}::{country_code.strip().upper()}::{int(max_records)}::{year_from}::{year_to}"


def environment_sdm_panel(occ: pd.DataFrame, occurrence_candidates: pd.DataFrame) -> tuple[pd.DataFrame, Optional[dict[str, Any]], Optional[pd.DataFrame], Optional[pd.DataFrame]]:
    st.subheader("Environment variables and ensemble SDM")
    st.caption("Loaded occurrences are used directly as presences. Background points and exploration grid are generated automatically.")

    with st.expander("SDM settings", expanded=True):
        resolution = st.selectbox("WorldClim raster resolution", RESOLUTIONS, index=0, help="30s is finest but slowest. 2.5m is the default balance for app use.")
        selected_web_vars = st.multiselect("Environmental variables", ENV_VARS, default=DEFAULT_VARS)
        algorithms = st.multiselect("Ensemble algorithms", ALGORITHMS, default=["Logistic regression", "Random forest", "ExtraTrees"])
        vif_threshold = st.number_input("VIF threshold", min_value=1.0, max_value=100.0, value=10.0, step=1.0, help="Default = 10. Variables are removed stepwise until all remaining VIF values are below this threshold.")
        use_vif = st.checkbox("Apply VIF stepwise filtering", value=True)
        n_background = st.number_input("Number of background points", min_value=100, max_value=20000, value=min(5000, max(500, len(occ) * 3)), step=100)
        pred_n = st.number_input("Prediction/exploration grid random points", min_value=100, max_value=50000, value=3000, step=500)
        bbox_expansion = st.number_input("Background/grid bounding-box expansion in degrees", min_value=0.0, max_value=5.0, value=0.2, step=0.1)
        test_size = st.slider("Test split proportion", min_value=0.1, max_value=0.5, value=0.25, step=0.05)

    if not selected_web_vars:
        st.warning("Select at least one environmental variable.")
        return occurrence_candidates.copy(), None, None, None
    if not algorithms:
        st.warning("Select at least one SDM algorithm.")
        return occurrence_candidates.copy(), None, None, None

    progress = st.progress(0.0)
    status = st.empty()

    if st.button("Build environment table and run ensemble SDM", type="primary"):
        try:
            status.write("Step 1/7: generating presence/background table...")
            progress.progress(0.05)
            pb = build_presence_background_from_occurrences(occ, int(n_background), float(bbox_expansion))
            status.write("Step 2/7: downloading/extracting raster values for training data...")
            env_train = extract_web_environment(pb, selected_web_vars, "latitude", "longitude", resolution, status=status, progress=progress, start=0.10, span=0.30)
            status.write("Step 3/7: generating exploration grid...")
            progress.progress(0.42)
            pred_grid = generate_background_points(occ, int(pred_n), float(bbox_expansion)).drop(columns=["presence"], errors="ignore")
            status.write("Step 4/7: extracting raster values for exploration grid...")
            pred_grid = extract_web_environment(pred_grid, selected_web_vars, "latitude", "longitude", resolution, status=status, progress=progress, start=0.45, span=0.20)
            status.write(f"Step 5/7: running VIF stepwise filtering; threshold = {vif_threshold}...")
            if use_vif and len(selected_web_vars) > 1:
                kept_vars, vif_table = vif_step(env_train, selected_web_vars, threshold=float(vif_threshold), status=status, progress=progress, start=0.67, span=0.08)
            else:
                kept_vars = selected_web_vars
                vif_table = compute_vif_table(env_train, selected_web_vars) if len(selected_web_vars) > 1 else pd.DataFrame({"variable": selected_web_vars, "vif": [1.0], "status": ["kept"]})
            status.write("Step 6/7: fitting selected ensemble SDM algorithms...")
            sdm_result = fit_ensemble_sdm(env_train, kept_vars, "presence", algorithms, float(test_size), status=status, progress=progress, start=0.76, span=0.16)
            st.session_state.sdm_train_table = env_train
            st.session_state.prediction_grid = pred_grid
            st.session_state.sdm_result = sdm_result
            st.session_state.vif_table = vif_table
            status.write("Step 7/7: SDM complete.")
            progress.progress(1.0)
        except Exception as exc:
            status.write("SDM failed.")
            st.error(f"SDM failed: {exc}")

    env_train = st.session_state.get("sdm_train_table")
    pred_grid = st.session_state.get("prediction_grid")
    sdm_result = st.session_state.get("sdm_result")
    vif_table = st.session_state.get("vif_table")

    if vif_table is not None:
        st.write("VIF table")
        st.dataframe(vif_table, width="stretch", hide_index=True)
    if sdm_result is None:
        st.info("Run the SDM to re-rank occurrence-supported sites and generate SDM-high / occurrence-low exploration sites.")
        return occurrence_candidates.copy(), None, env_train, vif_table

    st.success("Ensemble SDM is available.")
    st.dataframe(sdm_result["metrics"], width="stretch", hide_index=True)

    candidates_env = occurrence_candidates.copy()
    try:
        status.write("Extracting environment for candidate sites...")
        tmp = candidates_env.rename(columns={"latitude": "lat_tmp", "longitude": "lon_tmp"})
        tmp = extract_web_environment(tmp, sdm_result["variables"], "lat_tmp", "lon_tmp", resolution, status=status, progress=progress, start=0.0, span=0.2)
        candidates_env = tmp.rename(columns={"lat_tmp": "latitude", "lon_tmp": "longitude"})
    except Exception as exc:
        st.warning(f"Could not extract web environment for occurrence-supported candidate sites: {exc}")

    candidates_env = predict_ensemble_suitability(candidates_env, sdm_result)
    candidates_env = update_priority_with_sdm(candidates_env)

    st.markdown("### SDM-high / occurrence-low exploration candidates")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        min_suitability = st.number_input("Minimum suitability", min_value=0.0, max_value=1.0, value=0.60, step=0.05)
    with c2:
        quantile_cutoff = st.number_input("Grid suitability quantile", min_value=0.0, max_value=0.99, value=0.90, step=0.01)
    with c3:
        min_dist_known = st.number_input("Minimum distance from known records/sites (m)", min_value=0, max_value=200_000, value=3000, step=500)
    with c4:
        max_new = st.number_input("Max new exploration candidates", min_value=1, max_value=200, value=20, step=1)
    cluster_m = st.number_input("Exploration clustering distance (m)", min_value=100, max_value=200_000, value=3000, step=500)

    exploration = pd.DataFrame()
    if pred_grid is not None:
        exploration = make_sdm_exploration_candidates(pred_grid, sdm_result, occ, candidates_env, float(min_suitability), float(quantile_cutoff), float(min_dist_known), float(cluster_m), int(max_new), int(candidates_env["site_id"].max()) + 1 if not candidates_env.empty else 1, status=status, progress=progress, start=0.88, span=0.10)
    if exploration.empty:
        st.info("No new exploration candidates were generated with current thresholds.")
    else:
        st.success(f"Generated {len(exploration)} SDM-high / occurrence-low exploration candidates.")
        st.dataframe(exploration.sort_values("sdm_suitability", ascending=False), width="stretch", hide_index=True)
        candidates_env = pd.concat([candidates_env, exploration], ignore_index=True, sort=False)

    return candidates_env, sdm_result, env_train, vif_table


def make_field_validation_template(sites: pd.DataFrame) -> pd.DataFrame:
    cols = ["site_id", "candidate_type", "priority_rank", "route_order", "latitude", "longitude", "priority_score", "sdm_suitability", "visited", "survey_date", "observer", "access_success", "target_species_found", "abundance_count", "abundance_class", "flowering_status", "population_area_m2", "habitat_note", "photo_file", "comments"]
    base = sites.copy()
    for col in cols:
        if col not in base.columns:
            base[col] = ""
    return base[cols]


def main() -> None:
    st.set_page_config(page_title=APP_TITLE, page_icon="🗺️", layout="wide")
    init_session_state()
    st.title("🗺️ GBIF FieldMap Builder")
    st.caption("Survey planning from GBIF/coordinate occurrences, web environmental rasters, ensemble SDM, and validation templates.")

    st.sidebar.header("Data source")
    load_input_controls()
    st.sidebar.divider()
    st.sidebar.subheader("Sampling design")
    thinning_m = st.sidebar.number_input("Spatial thinning distance before clustering (m)", min_value=0, max_value=50_000, value=1000, step=500)
    candidate_method = st.sidebar.selectbox("Candidate site method", ["Medoid", "Centroid"], index=0)
    buffer_radius_m = st.sidebar.number_input("Buffer radius around occurrences (m)", 0, 100_000, 500, 100)
    dbscan_threshold_m = st.sidebar.number_input("DBSCAN cluster distance threshold (m)", 1, 500_000, 2000, 500)
    min_samples = st.sidebar.number_input("Minimum occurrences per cluster", 1, 50, 1, 1)
    route_order_mode = st.sidebar.selectbox("Candidate site order", ["Cluster ID", "Priority score", "Nearest-neighbor route", "North → South", "South → North", "West → East", "East → West"], index=2)
    priority_top_n = st.sidebar.number_input("Show top N priority candidates", min_value=1, max_value=100, value=10, step=1)
    st.sidebar.divider()
    st.sidebar.subheader("Layers")
    show_occurrences = st.sidebar.checkbox("Occurrences", value=True)
    show_buffers = st.sidebar.checkbox("Buffers", value=True)
    show_clusters = st.sidebar.checkbox("Occurrence clusters", value=False)
    show_candidate_sites = st.sidebar.checkbox("Candidate survey sites", value=True)
    show_routes = st.sidebar.checkbox("Routes", value=True)
    show_distance_labels = st.sidebar.checkbox("Straight-line distance labels", value=True)

    raw_df = st.session_state.raw_df
    if raw_df is None:
        st.info(st.session_state.source_message)
        st.markdown("Start by searching GBIF by scientific name, or upload any coordinate CSV. Then run the SDM module to generate occurrence-supported and SDM-high / occurrence-low candidates.")
        return

    st.success(st.session_state.source_message)
    try:
        detected = detect_occurrence_columns(raw_df)
        occ_raw = clean_occurrences(raw_df, detected)
    except Exception as exc:
        st.error(str(exc))
        return
    if occ_raw.empty:
        st.error("No valid coordinate records were found after cleaning.")
        return

    occ = spatial_thin(occ_raw, float(thinning_m))
    occ["cluster_id"] = haversine_dbscan(occ, "_latitude", "_longitude", float(dbscan_threshold_m), int(min_samples))
    occurrence_candidates = make_candidate_sites(occ, candidate_method, float(thinning_m))
    occurrence_candidates = add_priority_rank(occurrence_candidates)
    occurrence_candidates = add_navigation_columns(order_sites(occurrence_candidates, route_order_mode))

    all_candidates, sdm_result, env_train, vif_table = environment_sdm_panel(occ, occurrence_candidates)
    all_candidates = add_priority_rank(all_candidates)
    all_candidates = add_navigation_columns(order_sites(all_candidates, route_order_mode))

    route_url = make_google_maps_route_url(all_candidates, travelmode="driving")
    transit_route_url = make_google_maps_route_url(all_candidates, travelmode="transit")
    total_clusters = int(occ.loc[occ["cluster_id"] >= 0, "cluster_id"].nunique()) if not occ.empty else 0
    noise_points = int((occ["cluster_id"] < 0).sum()) if not occ.empty else 0
    n_explore = int(all_candidates.get("candidate_type", pd.Series(dtype=str)).astype(str).str.startswith("SDM-high").sum()) if not all_candidates.empty else 0

    col1, col2, col3, col4, col5, col6 = st.columns(6)
    col1.metric("Raw valid records", f"{len(occ_raw):,}")
    col2.metric("After thinning", f"{len(occ):,}")
    col3.metric("Occurrence clusters", f"{total_clusters:,}")
    col4.metric("Occurrence candidates", f"{len(occurrence_candidates):,}")
    col5.metric("SDM exploration", f"{n_explore:,}")
    col6.metric("Noise points", f"{noise_points:,}")

    if route_url:
        c1, c2 = st.columns(2)
        with c1:
            st.link_button("Open driving route in Google Maps", route_url, width="stretch")
        with c2:
            st.link_button("Open public-transit route in Google Maps", transit_route_url, width="stretch")

    with st.expander("Detected input columns", expanded=False):
        st.write(detected.__dict__)

    fmap = build_map(occ, all_candidates, float(buffer_radius_m), show_occurrences, show_buffers, show_clusters, show_candidate_sites, show_routes, show_distance_labels)
    st_folium(fmap, width=None, height=720, returned_objects=[])

    st.subheader("Priority candidate sites")
    priority_cols = ["priority_rank", "site_id", "candidate_type", "route_order", "priority_score", "sdm_suitability", "distance_to_nearest_known_m", "n_occurrences", "latitude", "longitude", "bias_warning", "selection_reason"]
    priority_cols = [c for c in priority_cols if c in all_candidates.columns]
    priority_sites = all_candidates.sort_values(["priority_rank"]).head(int(priority_top_n)) if not all_candidates.empty else all_candidates
    if not priority_sites.empty:
        st.dataframe(priority_sites[priority_cols], width="stretch", hide_index=True)

    st.subheader("All candidate survey sites")
    st.dataframe(all_candidates, width="stretch", hide_index=True)

    validation_template = make_field_validation_template(all_candidates)
    html_bytes = fmap.get_root().render().encode("utf-8")
    candidates_csv = all_candidates.to_csv(index=False).encode("utf-8-sig")
    validation_csv = validation_template.to_csv(index=False).encode("utf-8-sig")
    sdm_metrics_csv = sdm_result["metrics"].to_csv(index=False).encode("utf-8-sig") if sdm_result else b"algorithm,test_auc\n"
    vif_csv = vif_table.to_csv(index=False).encode("utf-8-sig") if vif_table is not None else b"variable,vif,status\n"
    train_csv = env_train.to_csv(index=False).encode("utf-8-sig") if env_train is not None else b""

    dl1, dl2, dl3, dl4, dl5, dl6 = st.columns(6)
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
    with dl6:
        st.download_button("Download SDM training table", train_csv, "sdm_training_table.csv", "text/csv", width="stretch")


if __name__ == "__main__":
    main()
