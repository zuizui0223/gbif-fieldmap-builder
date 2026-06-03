"""
GBIF FieldMap Builder

Streamlit app for field-survey planning from GBIF records or a coordinate CSV.

Features:
- GBIF page-by-page download. GBIF returns max 300 records per request; the app repeats requests until the selected cap or endOfRecords.
- Map-click coordinate exclusion. Click an occurrence point to exclude it from clustering, SDM, prediction area, and route planning.
- Candidate survey ranges from occurrence clusters.
- Optional ensemble SDM with VIF stepwise filtering and spatial partition diagnostics.
- Land-only prediction areas: buffer, convex hull, bounding box.
- Raster-like SDM predict map shown with Folium ImageOverlay.
- Day-by-day route planning and downloads.
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
from folium.plugins import Draw, MarkerCluster
from geopy.distance import geodesic
from rasterio.enums import Resampling
from rasterio.windows import Window, from_bounds
from shapely.geometry import MultiPoint, Point, box, shape
from shapely.ops import unary_union
from sklearn.cluster import DBSCAN
from sklearn.ensemble import ExtraTreesClassifier, GradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LinearRegression, LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedKFold, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from streamlit_folium import st_folium

APP_TITLE = "GBIF FieldMap Builder"
APP_BUILD_ID = "hard-exclusion-v2-20260529"
EARTH_RADIUS_M = 6_371_008.8
GBIF_SPECIES_MATCH_URL = "https://api.gbif.org/v1/species/match"
GBIF_OCCURRENCE_SEARCH_URL = "https://api.gbif.org/v1/occurrence/search"
WC_BASE = "https://geodata.ucdavis.edu/climate/worldclim/2_1/base"
LAND_GEOJSON_URL = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_land.geojson"
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

TOPOGRAPHY_VARS = ["elevation", "slope", "roughness"]
CLIMATE_VARS = [f"bio{i}" for i in range(1, 20)]
RESOLUTIONS = ["10m", "5m", "2.5m", "30s"]
RESOLUTION_NOTE = {
    "10m": "10 arc-minutes, about 18 km",
    "5m": "5 arc-minutes, about 9 km",
    "2.5m": "2.5 arc-minutes, about 4.5 km",
    "30s": "30 arc-seconds, about 1 km",
}
ALGORITHMS = ["Logistic regression", "Random forest", "ExtraTrees", "Gradient boosting"]
AREA_MODES = ["buffer", "convex hull", "bounding box"]
PARTITION_METHODS = ["random holdout", "random k-fold", "block", "checkerboard1", "checkerboard2", "jackknife"]
ROUTE_ORDER_METHODS = ["priority then nearest", "nearest from west", "priority only", "north to south", "south to north", "west to east", "east to west"]


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
        "prediction_table": None,
        "prediction_overlay": None,
        "vif_table": None,
        "excluded_row_ids": set(),
        "last_exclude_click_signature": "",
        "restore_excluded_row_ids": [],
        "sdm_occurrence_row_ids": None,
        "selected_route_site_ids": [],
        "last_route_click_signature": "",
        "survey_day_lists": {1: [], 2: []},
        "survey_day_count": 2,
        "sl_selected_site_ids": [],
        "sl_last_draw_sig": "",
        "sl_reset_token": 0,
        "qc_rect_selected_ids": [],
        "qc_last_draw_sig": "",
        "genus_raw_df": None,
        "genus_source_message": "No genus occurrence data loaded yet.",
        "genus_source_key": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def clear_loaded_data() -> None:
    for key in ["raw_df", "source_key", "sdm_result", "sdm_train_table", "prediction_table", "prediction_overlay", "vif_table", "sdm_occurrence_row_ids"]:
        st.session_state[key] = None
    st.session_state.excluded_row_ids = set()
    st.session_state.last_exclude_click_signature = ""
    st.session_state.restore_excluded_row_ids = []
    st.session_state.selected_route_site_ids = []
    st.session_state.last_route_click_signature = ""
    st.session_state.survey_day_lists = {1: [], 2: []}
    st.session_state.survey_day_count = 2
    st.session_state.sl_selected_site_ids = []
    st.session_state.sl_last_draw_sig = ""
    st.session_state.sl_reset_token = st.session_state.get("sl_reset_token", 0) + 1
    st.session_state.qc_rect_selected_ids = []
    st.session_state.qc_last_draw_sig = ""
    st.session_state.source_message = "No occurrence data loaded yet."


def reset_model_outputs() -> None:
    for key in ["sdm_result", "sdm_train_table", "prediction_table", "prediction_overlay", "vif_table", "sdm_occurrence_row_ids"]:
        st.session_state[key] = None


def first_url(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    match = re.search(r"https?://[^\s,;|]+", str(value).strip())
    return match.group(0) if match else ""


def detect_occurrence_columns(df: pd.DataFrame) -> ColumnDetection:
    cols = list(df.columns)
    lat = detect_column(cols, LAT_CANDIDATES)
    lon = detect_column(cols, LON_CANDIDATES)
    if lat is None or lon is None:
        raise ValueError("Latitude/longitude columns could not be detected. Use latitude/longitude, lat/lon, lat/lng, decimalLatitude/decimalLongitude, or 緯度/経度.")
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
    out["_year"] = pd.to_numeric(out[cols.year], errors="coerce") if cols.year and cols.year in out.columns else pd.to_datetime(out["_event_date"], errors="coerce").dt.year
    out["_row_id"] = np.arange(len(out), dtype=int)
    return out.reset_index(drop=True)


def read_uploaded_csv(uploaded: Any) -> pd.DataFrame:
    try:
        return pd.read_csv(uploaded)
    except UnicodeDecodeError:
        uploaded.seek(0)
        return pd.read_csv(uploaded, encoding="latin1")


def extract_media_url_from_gbif_record(rec: dict[str, Any]) -> str:
    media = rec.get("media") or []
    if isinstance(media, list):
        for item in media:
            if isinstance(item, dict):
                url = first_url(item.get("identifier") or item.get("references") or item.get("source"))
                if url:
                    return url
    return first_url(rec.get("associatedMedia"))


@st.cache_data(show_spinner=False, ttl=3600)
def fetch_gbif_occurrences_cached(scientific_name: str, max_records: int, country_code: str, year_from: Optional[int], year_to: Optional[int]) -> tuple[str, pd.DataFrame]:
    match = requests.get(GBIF_SPECIES_MATCH_URL, params={"name": scientific_name.strip()}, timeout=30)
    match.raise_for_status()
    payload = match.json()
    usage_key = payload.get("usageKey")
    if usage_key is None:
        raise ValueError(f"GBIF could not match this scientific name: {scientific_name}")

    params_base: dict[str, Any] = {"taxonKey": usage_key, "hasCoordinate": "true", "hasGeospatialIssue": "false"}
    if country_code.strip():
        params_base["country"] = country_code.strip().upper()
    if year_from is not None and year_to is not None:
        params_base["year"] = f"{int(year_from)},{int(year_to)}"
    elif year_from is not None:
        params_base["year"] = f"{int(year_from)},"
    elif year_to is not None:
        params_base["year"] = f",{int(year_to)}"

    first = requests.get(GBIF_OCCURRENCE_SEARCH_URL, params={**params_base, "limit": 0, "offset": 0}, timeout=60)
    first.raise_for_status()
    total_count = int(first.json().get("count", 0))
    target = min(int(max_records), total_count if total_count > 0 else int(max_records))
    records: list[dict[str, Any]] = []
    offset = 0
    while len(records) < target:
        limit = min(300, target - len(records))
        response = requests.get(GBIF_OCCURRENCE_SEARCH_URL, params={**params_base, "offset": offset, "limit": limit}, timeout=60)
        response.raise_for_status()
        page = response.json()
        batch = page.get("results", [])
        if not batch:
            break
        records.extend(batch)
        offset += len(batch)
        if page.get("endOfRecords"):
            break

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
    msg = f"GBIF match: {payload.get('scientificName', scientific_name)} / usageKey={usage_key} / confidence={payload.get('confidence')}. GBIF total={total_count:,}; fetched={len(rows):,}; cap={int(max_records):,}."
    return msg, pd.DataFrame(rows)



@st.cache_data(show_spinner=False, ttl=3600)
def fetch_gbif_genus_occurrences_cached(genus_name: str, max_records: int, country_code: str, year_from: Optional[int], year_to: Optional[int]) -> tuple[str, pd.DataFrame]:
    match = requests.get(GBIF_SPECIES_MATCH_URL, params={"name": genus_name.strip(), "rank": "GENUS"}, timeout=30)
    match.raise_for_status()
    payload = match.json()
    usage_key = payload.get("usageKey") or payload.get("genusKey")
    if usage_key is None:
        raise ValueError(f"GBIF could not match this genus name: {genus_name}")

    params_base: dict[str, Any] = {"taxonKey": usage_key, "hasCoordinate": "true", "hasGeospatialIssue": "false"}
    if country_code.strip():
        params_base["country"] = country_code.strip().upper()
    if year_from is not None and year_to is not None:
        params_base["year"] = f"{int(year_from)},{int(year_to)}"
    elif year_from is not None:
        params_base["year"] = f"{int(year_from)},"
    elif year_to is not None:
        params_base["year"] = f",{int(year_to)}"

    first = requests.get(GBIF_OCCURRENCE_SEARCH_URL, params={**params_base, "limit": 0, "offset": 0}, timeout=60)
    first.raise_for_status()
    total_count = int(first.json().get("count", 0))
    target = min(int(max_records), total_count if total_count > 0 else int(max_records))
    records: list[dict[str, Any]] = []
    offset = 0
    while len(records) < target:
        limit = min(300, target - len(records))
        response = requests.get(GBIF_OCCURRENCE_SEARCH_URL, params={**params_base, "offset": offset, "limit": limit}, timeout=60)
        response.raise_for_status()
        page = response.json()
        batch = page.get("results", [])
        if not batch:
            break
        records.extend(batch)
        offset += len(batch)
        if page.get("endOfRecords"):
            break

    rows = []
    for rec in records:
        species_name = rec.get("species") or rec.get("acceptedScientificName") or rec.get("scientificName", "")
        rows.append({
            "decimalLatitude": rec.get("decimalLatitude"),
            "decimalLongitude": rec.get("decimalLongitude"),
            "eventDate": rec.get("eventDate", ""),
            "year": rec.get("year"),
            "species": species_name,
            "scientificName": rec.get("scientificName", ""),
            "basisOfRecord": rec.get("basisOfRecord", ""),
            "countryCode": rec.get("countryCode", ""),
            "locality": rec.get("locality", ""),
            "gbifID": rec.get("gbifID") or rec.get("key"),
            "media_url": extract_media_url_from_gbif_record(rec),
        })
    msg = f"GBIF genus match: {payload.get('scientificName', genus_name)} / taxonKey={usage_key} / rank={payload.get('rank', 'GENUS')}. GBIF total={total_count:,}; fetched={len(rows):,}; cap={int(max_records):,}."
    return msg, pd.DataFrame(rows)


def genus_species_summary(occ: pd.DataFrame, min_records: int, grid_deg: float) -> pd.DataFrame:
    if occ.empty:
        return pd.DataFrame(columns=["species", "n_records", "n_unique_grid_cells", "year_min", "year_max", "enough_records_for_sdm"])
    work = occ.copy()
    work["_species_clean"] = work["_species"].astype(str).str.strip()
    work = work[work["_species_clean"].ne("")]
    if work.empty:
        return pd.DataFrame(columns=["species", "n_records", "n_unique_grid_cells", "year_min", "year_max", "enough_records_for_sdm"])
    work["_grid_lon"] = np.floor(work["_longitude"].astype(float) / float(grid_deg)).astype(int)
    work["_grid_lat"] = np.floor(work["_latitude"].astype(float) / float(grid_deg)).astype(int)
    work["_grid_id"] = work["_grid_lat"].astype(str) + ":" + work["_grid_lon"].astype(str)
    work["_year_num"] = pd.to_numeric(work.get("_year"), errors="coerce")
    rows = []
    for species, group in work.groupby("_species_clean", sort=True):
        rows.append({
            "species": species,
            "n_records": int(len(group)),
            "n_unique_grid_cells": int(group["_grid_id"].nunique()),
            "year_min": int(group["_year_num"].min()) if group["_year_num"].notna().any() else np.nan,
            "year_max": int(group["_year_num"].max()) if group["_year_num"].notna().any() else np.nan,
            "enough_records_for_sdm": int(len(group)) >= int(min_records),
        })
    return pd.DataFrame(rows).sort_values(["n_records", "species"], ascending=[False, True]).reset_index(drop=True)


def occurrence_richness_grid(occ: pd.DataFrame, grid_deg: float, min_records_per_species_cell: int) -> pd.DataFrame:
    if occ.empty:
        return pd.DataFrame()
    work = occ.copy()
    work["_species_clean"] = work["_species"].astype(str).str.strip()
    work = work[work["_species_clean"].ne("")]
    if work.empty:
        return pd.DataFrame()
    cell = float(grid_deg)
    work["grid_col"] = np.floor(work["_longitude"].astype(float) / cell).astype(int)
    work["grid_row"] = np.floor(work["_latitude"].astype(float) / cell).astype(int)
    rows = []
    for (grid_row, grid_col), group in work.groupby(["grid_row", "grid_col"], sort=True):
        counts = group.groupby("_species_clean").size().sort_values(ascending=False)
        qualifying = counts[counts >= int(min_records_per_species_cell)]
        lon_min = float(grid_col) * cell
        lat_min = float(grid_row) * cell
        rows.append({
            "grid_row": int(grid_row),
            "grid_col": int(grid_col),
            "latitude": lat_min + cell / 2.0,
            "longitude": lon_min + cell / 2.0,
            "lat_min": lat_min,
            "lat_max": lat_min + cell,
            "lon_min": lon_min,
            "lon_max": lon_min + cell,
            "species_richness": int(len(counts)),
            "record_count": int(len(group)),
            "species_with_min_records": int(len(qualifying)),
            "species_list": "; ".join(list(counts.index)),
        })
    return pd.DataFrame(rows).sort_values(["species_richness", "record_count"], ascending=[False, False]).reset_index(drop=True)


def richness_hotspot_candidates(grid: pd.DataFrame, metric: str, max_candidates: int) -> pd.DataFrame:
    if grid.empty:
        return pd.DataFrame()
    metric_col = {"Species richness": "species_richness", "Record count": "record_count", "Species with minimum records": "species_with_min_records"}.get(metric, "species_richness")
    out = grid.sort_values([metric_col, "species_richness", "record_count"], ascending=False).head(int(max_candidates)).copy()
    out.insert(0, "hotspot_rank", range(1, len(out) + 1))
    out["candidate_type"] = "Occurrence richness hotspot"
    out["google_maps_url"] = [make_google_maps_point_url(float(r["latitude"]), float(r["longitude"])) for _, r in out.iterrows()]
    return out


def richness_color(value: float, max_value: float) -> str:
    if max_value <= 0:
        return "#ffffcc"
    ratio = max(0.0, min(1.0, float(value) / float(max_value)))
    colors = ["#ffffcc", "#c2e699", "#78c679", "#31a354", "#006837"]
    return colors[min(len(colors) - 1, int(ratio * (len(colors) - 1)))]


def make_richness_map(grid: pd.DataFrame, hotspots: pd.DataFrame, metric: str) -> folium.Map:
    center = (float(grid["latitude"].mean()), float(grid["longitude"].mean())) if not grid.empty else (35.5, 135.5)
    fmap = Map(location=center, zoom_start=7, tiles="OpenStreetMap", control_scale=True)
    metric_col = {"Species richness": "species_richness", "Record count": "record_count", "Species with minimum records": "species_with_min_records"}.get(metric, "species_richness")
    max_value = float(grid[metric_col].max()) if not grid.empty else 0.0
    fg_grid = FeatureGroup(name=f"occurrence richness grid: {metric}", show=True)
    for _, row in grid.iterrows():
        value = float(row[metric_col])
        popup = folium.Popup(
            f"<b>Richness grid cell</b><br>{metric}: {value:g}<br>Species richness: {int(row['species_richness'])}<br>Records: {int(row['record_count'])}<br>Species: {row.get('species_list', '')}",
            max_width=520,
        )
        folium.Rectangle(
            bounds=[[row["lat_min"], row["lon_min"]], [row["lat_max"], row["lon_max"]]],
            color=richness_color(value, max_value),
            weight=1,
            fill=True,
            fill_color=richness_color(value, max_value),
            fill_opacity=0.48,
            popup=popup,
            tooltip=f"{metric}: {value:g}",
        ).add_to(fg_grid)
    fg_grid.add_to(fmap)
    if hotspots is not None and not hotspots.empty:
        fg_hot = FeatureGroup(name="richness hotspot candidates", show=True)
        for _, row in hotspots.iterrows():
            folium.CircleMarker(
                (row["latitude"], row["longitude"]),
                radius=7,
                color="#d73027",
                fill=True,
                fill_color="#d73027",
                fill_opacity=0.9,
                popup=folium.Popup(f"Hotspot rank {int(row['hotspot_rank'])}<br>{metric}: {row.get(metric_col, '')}<br><a href='{row['google_maps_url']}' target='_blank'>Open in Google Maps</a>", max_width=360),
                tooltip=f"hotspot {int(row['hotspot_rank'])}",
            ).add_to(fg_hot)
        fg_hot.add_to(fmap)
    LayerControl(collapsed=True).add_to(fmap)
    try:
        fmap.fit_bounds([[grid["lat_min"].min(), grid["lon_min"].min()], [grid["lat_max"].max(), grid["lon_max"].max()]], padding=(30, 30))
    except Exception:
        pass
    return fmap


@st.cache_resource(show_spinner=False)
def load_land_geometry():
    response = requests.get(LAND_GEOJSON_URL, timeout=120)
    response.raise_for_status()
    geojson = response.json()
    return unary_union([shape(feature["geometry"]) for feature in geojson.get("features", [])])


def km_to_deg(km: float) -> float:
    return float(km) / 111.0


def is_land(lon: float, lat: float, land_geom=None) -> bool:
    try:
        land = land_geom if land_geom is not None else load_land_geometry()
        return bool(land.covers(Point(float(lon), float(lat))))
    except Exception:
        return False


def point_at_distance(lat: float, lon: float, meters: float, bearing: float) -> tuple[float, float]:
    p = geodesic(meters=float(meters)).destination((float(lat), float(lon)), bearing)
    return float(p.latitude), float(p.longitude)


def range_fits_land(lat: float, lon: float, radius_m: float, land_geom=None) -> bool:
    if not is_land(lon, lat, land_geom):
        return False
    if radius_m <= 0:
        return True
    for bearing in [0, 45, 90, 135, 180, 225, 270, 315]:
        plat, plon = point_at_distance(lat, lon, radius_m, bearing)
        if not is_land(plon, plat, land_geom):
            return False
    return True


def filter_to_land(df: pd.DataFrame, lat_col: str = "latitude", lon_col: str = "longitude", range_radius_m: float = 0) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    land = load_land_geometry()
    mask = [range_fits_land(row[lat_col], row[lon_col], range_radius_m, land) for _, row in df.iterrows()]
    return df.loc[mask].reset_index(drop=True)


def image_html(url: str, width: int = 220) -> str:
    url = first_url(url)
    if not url:
        return ""
    return f"<br><img src='{url}' style='max-width:{width}px; max-height:180px; border-radius:6px; margin-top:6px;'>"


def extract_drawn_features(draw_data: Any) -> list[dict[str, Any]]:
    """Normalise streamlit-folium all_drawings / last_active_drawing into a flat feature list."""
    if not draw_data:
        return []
    if isinstance(draw_data, dict):
        if draw_data.get("type") == "Feature":
            return [draw_data]
        return [f for f in (draw_data.get("features") or []) if isinstance(f, dict)]
    if isinstance(draw_data, list):
        return [x for x in draw_data if isinstance(x, dict)]
    return []


def ids_inside_drawn_rectangles(df: pd.DataFrame, id_col: str, lat_col: str, lon_col: str, features: list[dict[str, Any]]) -> list[int]:
    """Return sorted list of integer IDs whose lat/lon fall inside any drawn rectangle/polygon."""
    ids: set[int] = set()
    for feat in features:
        geom = feat.get("geometry", {})
        if geom.get("type") not in ("Polygon", "Rectangle"):
            continue
        coords = geom.get("coordinates", [])
        if not coords:
            continue
        ring = coords[0]
        lats = [float(c[1]) for c in ring]
        lngs = [float(c[0]) for c in ring]
        picked = df[df[lat_col].between(min(lats), max(lats)) & df[lon_col].between(min(lngs), max(lngs))][id_col]
        ids.update(map(int, picked.tolist()))
    return sorted(ids)


def make_exclusion_review_map(occ_raw: pd.DataFrame, excluded_ids: set[int], add_draw: bool = False) -> folium.Map:
    center = (float(occ_raw["_latitude"].mean()), float(occ_raw["_longitude"].mean())) if not occ_raw.empty else (35.5, 135.5)
    fmap = Map(location=center, zoom_start=7, tiles="OpenStreetMap", control_scale=True)
    fg_in = FeatureGroup(name="included occurrences", show=True)
    fg_ex = FeatureGroup(name="excluded occurrences", show=True)
    for _, row in occ_raw.iterrows():
        rid = int(row["_row_id"])
        excluded = rid in excluded_ids
        color = "#d62728" if excluded else "#1f77b4"
        html = f"""
        <b>{'Excluded' if excluded else 'Included'} occurrence</b><br>
        row_id: {rid}<br>
        lat/lon: {row['_latitude']:.6f}, {row['_longitude']:.6f}<br>
        locality: {row.get('_locality','')}<br>
        GBIF: {row.get('_gbif_id','')}
        {image_html(row.get('_media_url',''))}
        """
        folium.CircleMarker(
            (row["_latitude"], row["_longitude"]),
            radius=8 if excluded else 5,
            color=color,
            fill=True,
            fill_color=color,
            fill_opacity=0.85,
            weight=2,
            popup=folium.Popup(html, max_width=360),
            tooltip=("excluded" if excluded else "click to exclude") + f" | row {rid}",
        ).add_to(fg_ex if excluded else fg_in)
    fg_in.add_to(fmap)
    fg_ex.add_to(fmap)
    if add_draw:
        Draw(export=False, draw_options={"rectangle": True, "polyline": False, "circle": False, "marker": False, "circlemarker": False, "polygon": False}, edit_options={"edit": False, "remove": True}).add_to(fmap)
    LayerControl(collapsed=True).add_to(fmap)
    try:
        fmap.fit_bounds([[occ_raw["_latitude"].min(), occ_raw["_longitude"].min()], [occ_raw["_latitude"].max(), occ_raw["_longitude"].max()]], padding=(30, 30))
    except Exception:
        pass
    return fmap


def row_id_from_tooltip(tooltip: Any) -> Optional[int]:
    if not tooltip:
        return None
    match = re.search(r"\brow\s+(\d+)\b", str(tooltip))
    return int(match.group(1)) if match else None


def nearest_row_id_from_click(occ_raw: pd.DataFrame, click: dict[str, Any], tooltip: Any = None) -> Optional[int]:
    tooltip_row_id = row_id_from_tooltip(tooltip)
    if tooltip_row_id is not None and tooltip_row_id in set(occ_raw["_row_id"].astype(int)):
        return tooltip_row_id
    if not click or "lat" not in click or "lng" not in click or occ_raw.empty:
        return None
    coord = (float(click["lat"]), float(click["lng"]))
    dists = occ_raw.apply(lambda r: geodesic(coord, (float(r["_latitude"]), float(r["_longitude"]))).km, axis=1)
    return int(occ_raw.loc[int(dists.idxmin()), "_row_id"])


def coordinate_exclusion_panel(occ_raw: pd.DataFrame) -> pd.DataFrame:
    st.subheader("Coordinate quality check")
    with st.expander("Click occurrence points on the map to exclude them", expanded=True):
        if st.button("Clear excluded coordinates"):
            st.session_state.excluded_row_ids = set()
            st.session_state.restore_excluded_row_ids = []
            st.session_state.last_exclude_click_signature = ""
            st.session_state.qc_rect_selected_ids = []
            st.session_state.qc_last_draw_sig = ""
            reset_model_outputs()
            st.rerun()
        click_data = st_folium(
            make_exclusion_review_map(occ_raw, set(st.session_state.excluded_row_ids), add_draw=True),
            width=None, height=520,
            returned_objects=["last_object_clicked", "last_object_clicked_tooltip", "all_drawings", "last_active_drawing"],
            key="coordinate_exclusion_map",
        )
        # ── existing point-click behavior (unchanged) ────────────────────────
        clicked = (click_data or {}).get("last_object_clicked")
        clicked_tooltip = (click_data or {}).get("last_object_clicked_tooltip")
        if clicked:
            sig = f"{clicked.get('lat'):.6f},{clicked.get('lng'):.6f},{clicked_tooltip}"
            if sig != st.session_state.last_exclude_click_signature:
                rid = nearest_row_id_from_click(occ_raw, clicked, clicked_tooltip)
                st.session_state.last_exclude_click_signature = sig
                if rid is not None:
                    if rid in set(st.session_state.excluded_row_ids):
                        st.session_state.excluded_row_ids = set(st.session_state.excluded_row_ids) - {rid}
                        st.success(f"Restored row {rid}.")
                    else:
                        st.session_state.excluded_row_ids = set(st.session_state.excluded_row_ids) | {rid}
                        st.success(f"Excluded row {rid}.")
                    st.session_state.restore_excluded_row_ids = []
                    reset_model_outputs()
                    st.rerun()
        # ── rectangle → immediate exclusion ──────────────────────────────────
        raw_drawings = (click_data or {}).get("all_drawings") or (click_data or {}).get("last_active_drawing")
        qc_features = extract_drawn_features(raw_drawings)
        if qc_features:
            draw_sig = str(qc_features)[:400]
            if draw_sig != st.session_state.get("qc_last_draw_sig", ""):
                st.session_state.qc_last_draw_sig = draw_sig
                rect_ids = ids_inside_drawn_rectangles(occ_raw, "_row_id", "_latitude", "_longitude", qc_features)
                if rect_ids:
                    new_excluded = set(st.session_state.excluded_row_ids) | set(rect_ids)
                    if new_excluded != set(st.session_state.excluded_row_ids):
                        st.session_state.excluded_row_ids = new_excluded
                        reset_model_outputs()
                        st.rerun()
        # ── recover by ID (unchanged) ────────────────────────────────────────
        excluded_options = [x for x in sorted(set(st.session_state.excluded_row_ids)) if x in set(occ_raw["_row_id"].astype(int))]
        recover_ids = st.multiselect("Excluded row IDs", options=excluded_options, default=[], key="restore_excluded_row_ids")
        if recover_ids and st.button("Recover selected excluded rows"):
            st.session_state.excluded_row_ids = set(st.session_state.excluded_row_ids) - set(map(int, recover_ids))
            reset_model_outputs()
            st.rerun()
        filtered = occ_raw[~occ_raw["_row_id"].astype(int).isin(set(st.session_state.excluded_row_ids))].copy()
        st.info(f"Included records: {len(filtered)} / {len(occ_raw)}. Excluded: {len(occ_raw) - len(filtered)}.")
    return filtered.reset_index(drop=True)


def spatial_thin(df: pd.DataFrame, thinning_m: float) -> pd.DataFrame:
    if df.empty or thinning_m <= 0:
        return df.copy().reset_index(drop=True)
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
    return pd.DataFrame(kept_rows).drop(columns=["_year_sort", "_has_photo_sort"], errors="ignore").reset_index(drop=True)


def haversine_dbscan(df: pd.DataFrame, lat_col: str, lon_col: str, threshold_m: float, min_samples: int) -> pd.Series:
    if df.empty:
        return pd.Series(dtype=int, name="cluster_id")
    coords_rad = [[math.radians(lat), math.radians(lon)] for lat, lon in df[[lat_col, lon_col]].to_numpy(dtype=float)]
    eps = float(threshold_m) / EARTH_RADIUS_M
    labels = DBSCAN(eps=eps, min_samples=int(min_samples), metric="haversine").fit_predict(coords_rad)
    return pd.Series(labels, index=df.index, name="cluster_id")


def prediction_area_geometry(occ: pd.DataFrame, mode: str, buffer_km: float, rectangle_margin_km: float, excluded_occ: Optional[pd.DataFrame] = None, exclusion_buffer_km: float = 0.0):
    points = [Point(float(row["_longitude"]), float(row["_latitude"])) for _, row in occ.iterrows()]
    if not points:
        return None
    buffer_deg = max(km_to_deg(buffer_km), 0.0001)
    if mode == "buffer":
        geom = unary_union([p.buffer(buffer_deg) for p in points])
    elif mode == "convex hull":
        geom = points[0].buffer(buffer_deg) if len(points) == 1 else MultiPoint(points).convex_hull.buffer(buffer_deg)
    else:
        margin = km_to_deg(rectangle_margin_km)
        geom = box(float(occ["_longitude"].min()) - margin, float(occ["_latitude"].min()) - margin, float(occ["_longitude"].max()) + margin, float(occ["_latitude"].max()) + margin)
    if excluded_occ is not None and not excluded_occ.empty and exclusion_buffer_km > 0:
        cutout_deg = max(km_to_deg(exclusion_buffer_km), 0.0001)
        cutouts = unary_union([Point(float(row["_longitude"]), float(row["_latitude"])).buffer(cutout_deg) for _, row in excluded_occ.iterrows()])
        geom = geom.difference(cutouts)
    return geom


def excluded_occurrences_from_ids(occ_raw: pd.DataFrame, excluded_ids: set[int]) -> pd.DataFrame:
    if occ_raw.empty or not excluded_ids:
        return occ_raw.iloc[0:0].copy()
    return occ_raw[occ_raw["_row_id"].astype(int).isin(set(map(int, excluded_ids)))].copy()


def make_sdm_extent_preview_map(occ: pd.DataFrame, extent_geom, area_mode: str) -> folium.Map:
    center_df = occ
    center = (float(center_df["_latitude"].mean()), float(center_df["_longitude"].mean())) if not center_df.empty else (35.5, 135.5)
    fmap = Map(location=center, zoom_start=7, tiles="OpenStreetMap", control_scale=True)
    if extent_geom is not None and not extent_geom.is_empty:
        folium.GeoJson(
            extent_geom.__geo_interface__,
            name=f"SDM extent: {area_mode}",
            style_function=lambda _: {
                "color": "#e66101",
                "weight": 3,
                "fillColor": "#fdb863",
                "fillOpacity": 0.22,
            },
            tooltip=f"SDM prediction extent: {area_mode}",
        ).add_to(fmap)
    fg_used = FeatureGroup(name="blue SDM input points", show=True)
    for _, row in occ.iterrows():
        rid = int(row["_row_id"])
        folium.CircleMarker(
            (row["_latitude"], row["_longitude"]),
            radius=5,
            color="#1f77b4",
            fill=True,
            fill_color="#1f77b4",
            fill_opacity=0.85,
            weight=2,
            tooltip=f"SDM input | row {rid}",
        ).add_to(fg_used)
    fg_used.add_to(fmap)
    LayerControl(collapsed=True).add_to(fmap)
    try:
        if extent_geom is not None and not extent_geom.is_empty:
            minx, miny, maxx, maxy = extent_geom.bounds
            fmap.fit_bounds([[miny, minx], [maxy, maxx]], padding=(30, 30))
        elif not center_df.empty:
            fmap.fit_bounds([[center_df["_latitude"].min(), center_df["_longitude"].min()], [center_df["_latitude"].max(), center_df["_longitude"].max()]], padding=(30, 30))
    except Exception:
        pass
    return fmap

def representative_medoid(group: pd.DataFrame) -> pd.Series:
    if len(group) == 1:
        return group.iloc[0]
    coords = [(float(r["_latitude"]), float(r["_longitude"])) for _, r in group.iterrows()]
    scores = [sum(geodesic(coord, other).m for other in coords) for coord in coords]
    return group.iloc[int(np.argmin(scores))]


def make_candidate_sites(df: pd.DataFrame, method: str, occurrence_weight: float) -> pd.DataFrame:
    clustered = df[df["cluster_id"] >= 0].copy()
    rows = []
    max_n = max(1, int(clustered.groupby("cluster_id").size().max())) if not clustered.empty else 1
    for site_id, (cluster_id, group) in enumerate(clustered.groupby("cluster_id", sort=True), start=1):
        rep = representative_medoid(group)
        if method == "Centroid":
            centroid = MultiPoint([Point(float(row["_longitude"]), float(row["_latitude"])) for _, row in group.iterrows()]).centroid
            lat, lon = float(centroid.y), float(centroid.x)
            reason = f"Centroid of occurrence cluster {cluster_id}."
        else:
            lat, lon = float(rep["_latitude"]), float(rep["_longitude"])
            reason = f"Medoid of occurrence cluster {cluster_id}."
        n = int(len(group))
        occurrence_support = round(math.log1p(n) / math.log1p(max_n), 3) if max_n > 1 else 1.0
        year_vals = pd.to_numeric(group.get("_year"), errors="coerce").dropna()
        year_min = int(year_vals.min()) if not year_vals.empty else None
        year_max = int(year_vals.max()) if not year_vals.empty else None
        recent_bonus = 0 if year_max is None else max(0, min(20, year_max - 2000)) / 20
        photo_bonus = 0.15 if str(rep.get("_media_url", "")) else 0
        priority = round(min(1.0, 0.35 + occurrence_weight * occurrence_support + 0.15 * recent_bonus + photo_bonus), 3)
        rows.append({"site_id": site_id, "candidate_type": "Occurrence-supported survey range", "cluster_id": int(cluster_id), "latitude": lat, "longitude": lon, "n_occurrences": n, "occurrence_support_score": occurrence_support, "year_min": year_min, "year_max": year_max, "representative_gbif_id": str(rep.get("_gbif_id", "")), "representative_media_url": str(rep.get("_media_url", "")), "representative_locality": str(rep.get("_locality", "")), "candidate_method": method, "selection_reason": reason, "bias_warning": "Record density is useful but may reflect GBIF observer/access bias.", "priority_score": priority})
    return pd.DataFrame(rows)


def available_sort_cols(df: pd.DataFrame, desired: list[str]) -> list[str]:
    return [c for c in desired if c in df.columns]


def add_priority_rank(sites: pd.DataFrame) -> pd.DataFrame:
    out = sites.copy()
    if out.empty:
        out["priority_rank"] = []
        return out
    sort_cols = available_sort_cols(out, ["priority_score", "sdm_suitability", "occurrence_support_score"])
    if not sort_cols:
        out["priority_rank"] = range(1, len(out) + 1)
        return out
    rank = out.sort_values(sort_cols, ascending=False, na_position="last").reset_index(drop=True)
    rank["priority_rank"] = range(1, len(rank) + 1)
    return out.drop(columns=["priority_rank"], errors="ignore").merge(rank[["site_id", "priority_rank"]], on="site_id", how="left")


def make_google_maps_point_url(latitude: float, longitude: float) -> str:
    return f"https://www.google.com/maps/search/?api=1&query={latitude:.6f}%2C{longitude:.6f}"


def make_google_maps_route_url(sites: pd.DataFrame, travelmode: str = "driving", max_waypoints: int = 8, start_location: str = "") -> str:
    if sites.empty:
        return ""
    ordered = sites.sort_values("route_order") if "route_order" in sites.columns else sites.copy()
    coords = [(float(row["latitude"]), float(row["longitude"])) for _, row in ordered.iterrows()]
    start_location = str(start_location or "").strip()
    if len(coords) == 1 and not start_location:
        return make_google_maps_point_url(coords[0][0], coords[0][1])
    if start_location:
        origin = start_location
        destination = f"{coords[-1][0]:.6f},{coords[-1][1]:.6f}"
        waypoint_coords = coords[:-1]
    else:
        origin = f"{coords[0][0]:.6f},{coords[0][1]:.6f}"
        destination = f"{coords[-1][0]:.6f},{coords[-1][1]:.6f}"
        waypoint_coords = coords[1:-1]
    params = {"api": "1", "origin": origin, "destination": destination, "travelmode": travelmode, "dir_action": "navigate"}
    if travelmode != "transit":
        waypoints = waypoint_coords[:max_waypoints]
        if waypoints:
            params["waypoints"] = "|".join(f"{lat:.6f},{lon:.6f}" for lat, lon in waypoints)
    return "https://www.google.com/maps/dir/?" + urllib.parse.urlencode(params, safe=",|")


def nearest_neighbor_order(sites: pd.DataFrame, start_idx: int = 0) -> pd.DataFrame:
    if sites.empty:
        return sites.copy()
    remaining = sites.copy().reset_index(drop=True)
    start_idx = int(max(0, min(start_idx, len(remaining) - 1)))
    rows = [remaining.loc[start_idx]]
    remaining = remaining.drop(index=start_idx).reset_index(drop=True)
    while not remaining.empty:
        current = rows[-1]
        current_xy = (float(current["latitude"]), float(current["longitude"]))
        distances = remaining.apply(lambda row: geodesic(current_xy, (float(row["latitude"]), float(row["longitude"]))).km, axis=1)
        next_idx = int(distances.idxmin())
        rows.append(remaining.loc[next_idx])
        remaining = remaining.drop(index=next_idx).reset_index(drop=True)
    return pd.DataFrame(rows).reset_index(drop=True)


def order_sites(sites: pd.DataFrame, mode: str) -> pd.DataFrame:
    if sites.empty:
        out = sites.copy(); out["route_order"] = []; return out
    work = sites.copy().reset_index(drop=True)
    if mode in ["Nearest-neighbor route", "nearest from west"]:
        ordered = nearest_neighbor_order(work, int(work["longitude"].idxmin()))
    elif mode in ["Priority score", "priority only"]:
        sort_cols = available_sort_cols(work, ["priority_score", "sdm_suitability", "occurrence_support_score"])
        ordered = work.sort_values(sort_cols, ascending=False, na_position="last") if sort_cols else work
    elif mode == "priority then nearest":
        sort_cols = available_sort_cols(work, ["priority_score", "sdm_suitability", "occurrence_support_score"])
        ranked = work.sort_values(sort_cols, ascending=False, na_position="last").reset_index(drop=True) if sort_cols else work.reset_index(drop=True)
        ordered = nearest_neighbor_order(ranked, 0)
    elif mode in ["North → South", "north to south"]:
        ordered = work.sort_values(["latitude", "longitude"], ascending=[False, True])
    elif mode in ["South → North", "south to north"]:
        ordered = work.sort_values(["latitude", "longitude"], ascending=[True, True])
    elif mode in ["West → East", "west to east"]:
        ordered = work.sort_values(["longitude", "latitude"], ascending=[True, False])
    elif mode in ["East → West", "east to west"]:
        ordered = work.sort_values(["longitude", "latitude"], ascending=[False, False])
    else:
        ordered = work.sort_values([c for c in ["candidate_type", "cluster_id", "site_id"] if c in work.columns])
    ordered = ordered.reset_index(drop=True)
    ordered["route_order"] = range(1, len(ordered) + 1)
    ordered["google_maps_point_url"] = ordered.apply(lambda r: make_google_maps_point_url(float(r["latitude"]), float(r["longitude"])), axis=1)
    return ordered


def split_route_into_days(ordered: pd.DataFrame, survey_days: int, max_sites_per_day: int, max_day_distance_km: float, travelmode: str = "driving", start_location: str = "") -> pd.DataFrame:
    rows = []
    current_day = 1
    day_count = 0
    day_distance = 0.0
    prev_coord = None
    for _, row in ordered.iterrows():
        coord = (float(row["latitude"]), float(row["longitude"]))
        leg = 0.0 if prev_coord is None or day_count == 0 else float(geodesic(prev_coord, coord).km)
        if day_count > 0 and current_day < survey_days and (day_count >= max_sites_per_day or (max_day_distance_km > 0 and day_distance + leg > max_day_distance_km)):
            current_day += 1
            day_count = 0
            day_distance = 0.0
            prev_coord = None
            leg = 0.0
        if current_day > survey_days or day_count >= max_sites_per_day:
            continue
        day_count += 1
        day_distance += leg
        new = row.to_dict()
        new["survey_day"] = current_day
        new["day_route_order"] = day_count
        new["distance_from_previous_km"] = round(leg, 3)
        new["cumulative_day_distance_km"] = round(day_distance, 3)
        rows.append(new)
        prev_coord = coord
    plan = pd.DataFrame(rows)
    if plan.empty:
        return plan
    urls = {}
    for day, group in plan.groupby("survey_day"):
        tmp = group.sort_values("day_route_order").copy()
        tmp["route_order"] = range(1, len(tmp) + 1)
        urls[int(day)] = make_google_maps_route_url(tmp, travelmode=travelmode, start_location=start_location)
    plan["day_google_maps_route_url"] = plan["survey_day"].map(urls)
    return plan.reset_index(drop=True)


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
    var = var.lower(); resolution = resolution.lower()
    if var in {"elevation", "slope", "roughness"}:
        zip_name = f"wc2.1_{resolution}_elev.zip"; tif_name = f"wc2.1_{resolution}_elev.tif"
    elif var.startswith("bio"):
        n = int(var.replace("bio", "")); zip_name = f"wc2.1_{resolution}_bio.zip"; tif_name = f"wc2.1_{resolution}_bio_{n}.tif"
    else:
        raise ValueError(f"Unsupported variable: {var}")
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


def sample_raster_values_fast(points: pd.DataFrame, raster_path: str, lat_col: str, lon_col: str, derived: Optional[str] = None) -> np.ndarray:
    if points.empty:
        return np.array([], dtype=float)
    with rasterio.open(raster_path) as src:
        coords = points[[lon_col, lat_col]].to_numpy(dtype=float)
        rc = np.array([src.index(float(lon), float(lat)) for lon, lat in coords], dtype=int)
        rows, cols = rc[:, 0], rc[:, 1]
        pad = 1 if derived in {"slope", "roughness"} else 0
        r0 = max(0, int(rows.min()) - pad); r1 = min(src.height - 1, int(rows.max()) + pad)
        c0 = max(0, int(cols.min()) - pad); c1 = min(src.width - 1, int(cols.max()) + pad)
        window = Window(c0, r0, c1 - c0 + 1, r1 - r0 + 1)
        arr = src.read(1, window=window, boundless=True, fill_value=np.nan).astype(float)
        if src.nodata is not None:
            arr[arr == src.nodata] = np.nan
        values = np.full(len(points), np.nan, dtype=float)
        for i, (rr, cc) in enumerate(zip(rows - r0, cols - c0)):
            if rr < 0 or cc < 0 or rr >= arr.shape[0] or cc >= arr.shape[1]:
                continue
            if derived is None:
                values[i] = arr[rr, cc]
            else:
                sub = arr[max(0, rr - 1):min(arr.shape[0], rr + 2), max(0, cc - 1):min(arr.shape[1], cc + 2)]
                if np.all(np.isnan(sub)):
                    continue
                values[i] = (np.nanmax(sub) - np.nanmin(sub)) if derived == "roughness" else np.nanmean(np.sqrt(np.gradient(sub)[0] ** 2 + np.gradient(sub)[1] ** 2))
        return values


def extract_environment(points: pd.DataFrame, variables: list[str], lat_col: str, lon_col: str, resolution: str, status=None) -> pd.DataFrame:
    out = points.copy()
    for i, var in enumerate(variables, start=1):
        if status is not None:
            status.write(f"Extracting {var} ({resolution}) [{i}/{len(variables)}]...")
        if var == "slope":
            out[var] = sample_raster_values_fast(out, get_worldclim_raster_path("elevation", resolution), lat_col, lon_col, "slope")
        elif var == "roughness":
            out[var] = sample_raster_values_fast(out, get_worldclim_raster_path("elevation", resolution), lat_col, lon_col, "roughness")
        else:
            out[var] = sample_raster_values_fast(out, get_worldclim_raster_path(var, resolution), lat_col, lon_col)
    return out


def compute_vif_table(df: pd.DataFrame, variables: list[str]) -> pd.DataFrame:
    if len(variables) == 0:
        return pd.DataFrame(columns=["variable", "vif", "vif_warning"])
    if len(variables) == 1:
        return pd.DataFrame({"variable": variables, "vif": [1.0], "vif_warning": [""], "status": ["kept"]})
    X = df[variables].apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan)
    X = pd.DataFrame(SimpleImputer(strategy="median").fit_transform(X), columns=variables)
    rows = []
    for var in variables:
        others = [v for v in variables if v != var]
        try:
            r2 = LinearRegression().fit(X[others].values, X[var].values).score(X[others].values, X[var].values)
            vif = 1.0 / max(1e-12, 1.0 - r2)
        except Exception:
            vif = np.inf
        warning = "unstable / near-perfect collinearity" if (not np.isfinite(vif) or vif >= 1e6) else "very high collinearity" if vif >= 100 else "high collinearity" if vif >= 10 else ""
        rows.append({"variable": var, "vif": round(float(vif), 3) if np.isfinite(vif) else np.inf, "vif_warning": warning})
    return pd.DataFrame(rows).sort_values("vif", ascending=False).reset_index(drop=True)


def vif_step(df: pd.DataFrame, variables: list[str], threshold: float) -> tuple[list[str], pd.DataFrame]:
    kept = list(dict.fromkeys(variables))
    removed = []
    while len(kept) > 1:
        tbl = compute_vif_table(df, kept)
        top = tbl.iloc[0]
        top_vif = float(top["vif"])
        if np.isfinite(top_vif) and top_vif <= threshold:
            break
        var = str(top["variable"])
        removed.append({"variable": var, "vif": top["vif"], "vif_warning": top.get("vif_warning", ""), "status": "removed"})
        kept.remove(var)
    final = compute_vif_table(df, kept) if kept else pd.DataFrame(columns=["variable", "vif", "vif_warning"])
    final["status"] = "kept"
    if removed:
        final = pd.concat([final, pd.DataFrame(removed)], ignore_index=True)
    return kept, final


def generate_land_points(occ: pd.DataFrame, n_points: int, area_mode: str, buffer_km: float, rectangle_margin_km: float, excluded_occ: Optional[pd.DataFrame] = None, exclusion_buffer_km: float = 0.0, random_state: int = 42, status=None) -> pd.DataFrame:
    rng = np.random.default_rng(random_state)
    geom = prediction_area_geometry(occ, area_mode, buffer_km, rectangle_margin_km, excluded_occ, exclusion_buffer_km)
    if geom is None or geom.is_empty:
        return pd.DataFrame(columns=["latitude", "longitude"])
    land = load_land_geometry()
    minx, miny, maxx, maxy = geom.bounds
    rows = []
    attempts = 0
    max_attempts = max(int(n_points) * 1000, 50_000)
    while len(rows) < int(n_points) and attempts < max_attempts:
        lon = float(rng.uniform(minx, maxx)); lat = float(rng.uniform(miny, maxy)); attempts += 1
        p = Point(lon, lat)
        if geom.covers(p) and land.covers(p):
            rows.append({"latitude": lat, "longitude": lon})
        if status is not None and attempts % 3000 == 0:
            status.write(f"Generating background land points: {len(rows):,}/{int(n_points):,}")
    return pd.DataFrame(rows)


def build_presence_background(occ: pd.DataFrame, n_background: int, area_mode: str, buffer_km: float, rectangle_margin_km: float, excluded_occ: Optional[pd.DataFrame] = None, exclusion_buffer_km: float = 0.0, status=None) -> pd.DataFrame:
    pres = occ[["_row_id", "_latitude", "_longitude"]].rename(columns={"_latitude": "latitude", "_longitude": "longitude", "_row_id": "occurrence_row_id"}).copy()
    pres["presence"] = 1
    bg = generate_land_points(occ, n_background, area_mode, buffer_km, rectangle_margin_km, excluded_occ, exclusion_buffer_km, status=status)
    bg["occurrence_row_id"] = np.nan
    bg["presence"] = 0
    return pd.concat([pres, bg[pres.columns]], ignore_index=True)


def make_model(name: str):
    if name == "Logistic regression":
        return Pipeline([("imputer", SimpleImputer(strategy="median")), ("scaler", StandardScaler()), ("model", LogisticRegression(max_iter=1000, class_weight="balanced"))])
    if name == "Random forest":
        return Pipeline([("imputer", SimpleImputer(strategy="median")), ("model", RandomForestClassifier(n_estimators=300, random_state=42, class_weight="balanced_subsample"))])
    if name == "ExtraTrees":
        return Pipeline([("imputer", SimpleImputer(strategy="median")), ("model", ExtraTreesClassifier(n_estimators=300, random_state=42, class_weight="balanced"))])
    if name == "Gradient boosting":
        return Pipeline([("imputer", SimpleImputer(strategy="median")), ("model", GradientBoostingClassifier(random_state=42))])
    raise ValueError(name)


def assign_spatial_folds(data: pd.DataFrame, method: str, k: int, checkerboard_deg: float) -> pd.Series:
    y = data["presence"].astype(int)
    if method == "random k-fold":
        k_eff = max(2, min(int(k), int(y.value_counts().min()) if y.nunique() == 2 else int(k)))
        folds = pd.Series(index=data.index, dtype=int)
        splitter = StratifiedKFold(n_splits=k_eff, shuffle=True, random_state=42)
        for fold_id, (_, test_idx) in enumerate(splitter.split(data, y), start=1):
            folds.iloc[test_idx] = fold_id
        return folds.astype(int)
    if method == "block":
        lat_med = data["latitude"].median(); lon_med = data["longitude"].median()
        return ((data["latitude"] >= lat_med).astype(int) * 2 + (data["longitude"] >= lon_med).astype(int) + 1).astype(int)
    if method in ["checkerboard1", "checkerboard2"]:
        cell = max(float(checkerboard_deg) * (2.0 if method == "checkerboard2" else 1.0), 1e-6)
        ix = np.floor((data["longitude"] - data["longitude"].min()) / cell).astype(int)
        iy = np.floor((data["latitude"] - data["latitude"].min()) / cell).astype(int)
        return ((ix + iy) % 2 + 1).astype(int) if method == "checkerboard1" else ((ix % 2) * 2 + (iy % 2) + 1).astype(int)
    if method == "jackknife":
        pres = data[data["presence"].astype(int) == 1].copy()
        if pres.empty:
            return pd.Series(np.ones(len(data), dtype=int), index=data.index)
        pres["jk_group"] = haversine_dbscan(pres, "latitude", "longitude", 2000.0, 1).values + 1
        pres_coords = pres[["latitude", "longitude", "jk_group"]].reset_index(drop=True)
        folds = []
        for _, row in data.iterrows():
            coord = (float(row["latitude"]), float(row["longitude"]))
            d = pres_coords.apply(lambda r: geodesic(coord, (float(r["latitude"]), float(r["longitude"]))).m, axis=1)
            folds.append(int(pres_coords.loc[d.idxmin(), "jk_group"]))
        return pd.Series(folds, index=data.index).astype(int)
    return pd.Series(np.ones(len(data), dtype=int), index=data.index)


def auc_warning(auc: float, method: str) -> str:
    if not np.isfinite(auc):
        return "not available"
    if auc >= 0.98:
        return "suspiciously high; likely easy background or leakage"
    if auc >= 0.95:
        return "very high; inspect spatial partition and background"
    if method in ["random holdout", "random k-fold"] and auc >= 0.90:
        return "random split may be optimistic"
    return ""


def fit_sdm(train_df: pd.DataFrame, variables: list[str], algorithms: list[str], partition_method: str, k_folds: int, checkerboard_deg: float) -> dict[str, Any]:
    data = train_df.copy()
    X = data[variables].apply(pd.to_numeric, errors="coerce")
    y = data["presence"].astype(int)
    if y.nunique() < 2:
        raise ValueError("Need both presence and background points for SDM.")
    metrics = []; models = {}
    if partition_method == "random holdout":
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.25, random_state=42, stratify=y)
        for alg in algorithms:
            model = make_model(alg); model.fit(X_train, y_train)
            auc = float(roc_auc_score(y_test, model.predict_proba(X_test)[:, 1]))
            metrics.append({"algorithm": alg, "partition_method": partition_method, "fold": "diagnostic", "auc": round(auc, 3), "warning": auc_warning(auc, partition_method)})
            model.fit(X, y); models[alg] = model
    else:
        data["cv_fold"] = assign_spatial_folds(data, partition_method, k_folds, checkerboard_deg).values
        X_all = data[variables].apply(pd.to_numeric, errors="coerce"); y_all = data["presence"].astype(int)
        unique_folds = sorted(data["cv_fold"].dropna().unique())
        for alg in algorithms:
            fold_aucs = []
            for fold in unique_folds:
                test_mask = data["cv_fold"].eq(fold); train_mask = ~test_mask
                if test_mask.sum() < 2 or train_mask.sum() < 2:
                    continue
                if data.loc[test_mask, "presence"].nunique() < 2 or data.loc[train_mask, "presence"].nunique() < 2:
                    continue
                model = make_model(alg); model.fit(X_all.loc[train_mask], y_all.loc[train_mask])
                auc = float(roc_auc_score(y_all.loc[test_mask], model.predict_proba(X_all.loc[test_mask])[:, 1]))
                fold_aucs.append(auc)
                metrics.append({"algorithm": alg, "partition_method": partition_method, "fold": int(fold), "auc": round(auc, 3), "warning": auc_warning(auc, partition_method)})
            mean_auc = float(np.mean(fold_aucs)) if fold_aucs else np.nan
            metrics.append({"algorithm": alg, "partition_method": partition_method, "fold": "mean", "auc": round(mean_auc, 3) if np.isfinite(mean_auc) else np.nan, "warning": auc_warning(mean_auc, partition_method) if np.isfinite(mean_auc) else "no valid folds"})
            final_model = make_model(alg); final_model.fit(X_all, y_all); models[alg] = final_model
    return {"models": models, "metrics": pd.DataFrame(metrics), "variables": variables, "training_table": data if "cv_fold" in data.columns else train_df}


def predict_suitability(table: pd.DataFrame, sdm_result: Optional[dict[str, Any]]) -> pd.DataFrame:
    out = table.copy()
    if not sdm_result or out.empty:
        out["sdm_suitability"] = np.nan
        return out
    variables = sdm_result["variables"]
    X = out[variables].apply(pd.to_numeric, errors="coerce")
    preds = [model.predict_proba(X)[:, 1] for model in sdm_result["models"].values()]
    out["sdm_suitability"] = np.mean(np.vstack(preds), axis=0).round(3)
    return out


def rgba_from_prediction(pred: np.ndarray, alpha: int = 170) -> np.ndarray:
    rgba = np.zeros((pred.shape[0], pred.shape[1], 4), dtype=np.uint8)
    valid = np.isfinite(pred); v = np.clip(pred, 0, 1)
    breaks = np.array([0.0, 0.25, 0.5, 0.75, 1.0])
    colors = np.array([[44, 123, 182], [171, 217, 233], [255, 255, 191], [253, 174, 97], [215, 25, 28]], dtype=float)
    flat = v[valid]; out = np.zeros((flat.size, 3), dtype=float)
    for i in range(len(breaks) - 1):
        m = (flat >= breaks[i]) & (flat <= breaks[i + 1])
        if np.any(m):
            t = (flat[m] - breaks[i]) / max(1e-12, breaks[i + 1] - breaks[i])
            out[m] = colors[i] * (1 - t[:, None]) + colors[i + 1] * t[:, None]
    rgba[..., :3][valid] = out.astype(np.uint8); rgba[..., 3][valid] = alpha
    return rgba


def add_sdm_predict_legend(fmap: folium.Map) -> None:
    legend = """
    <div style="position: fixed; bottom: 28px; left: 28px; z-index: 9999; background: rgba(255,255,255,0.92); padding: 10px 12px; border: 1px solid #999; border-radius: 4px; font-size: 12px; color: #222;">
      <div style="font-weight: 700; margin-bottom: 6px;">SDM predicted suitability</div>
      <div style="width: 180px; height: 12px; background: linear-gradient(90deg, #2c7bb6, #abd9e9, #ffffbf, #fdae61, #d7191c);"></div>
      <div style="display: flex; justify-content: space-between; width: 180px;"><span>0</span><span>0.5</span><span>1</span></div>
    </div>
    """
    fmap.get_root().html.add_child(folium.Element(legend))


def read_window_array(path: str, bounds: tuple[float, float, float, float], out_shape: tuple[int, int]) -> tuple[np.ndarray, tuple[float, float, float, float]]:
    west, south, east, north = bounds
    with rasterio.open(path) as src:
        window = from_bounds(west, south, east, north, transform=src.transform).round_offsets().round_lengths()
        window = Window(max(0, window.col_off), max(0, window.row_off), min(src.width - max(0, window.col_off), window.width), min(src.height - max(0, window.row_off), window.height))
        actual_bounds = src.window_bounds(window)
        arr = src.read(1, window=window, out_shape=out_shape, resampling=Resampling.bilinear, boundless=True, fill_value=np.nan).astype(float)
        if src.nodata is not None:
            arr[arr == src.nodata] = np.nan
    return arr, actual_bounds


def build_predict_map(occ: pd.DataFrame, variables: list[str], resolution: str, sdm_result: dict[str, Any], area_mode: str, buffer_km: float, rectangle_margin_km: float, max_pixels: int, excluded_occ: Optional[pd.DataFrame] = None, exclusion_buffer_km: float = 0.0, status=None) -> tuple[dict[str, Any], pd.DataFrame]:
    geom = prediction_area_geometry(occ, area_mode, buffer_km, rectangle_margin_km, excluded_occ, exclusion_buffer_km)
    if geom is None or geom.is_empty:
        raise RuntimeError("Prediction area could not be generated.")
    land = load_land_geometry(); west, south, east, north = geom.bounds
    ref_var = "elevation" if any(v in {"elevation", "slope", "roughness"} for v in variables) else variables[0]
    with rasterio.open(get_worldclim_raster_path(ref_var, resolution)) as src:
        window = from_bounds(west, south, east, north, transform=src.transform).round_offsets().round_lengths()
        raw_h = max(1, int(window.height)); raw_w = max(1, int(window.width))
    stride = max(1, int(math.ceil(math.sqrt((raw_h * raw_w) / max(1, max_pixels)))))
    out_h = max(1, int(math.ceil(raw_h / stride))); out_w = max(1, int(math.ceil(raw_w / stride)))
    if status is not None:
        status.write(f"Predicting raster map: {out_w:,} × {out_h:,} cells; source stride={stride}")
    arrays = {}; actual_bounds = None; elev_cache = None
    for var in variables:
        if var in {"slope", "roughness"}:
            if elev_cache is None:
                elev_cache, actual_bounds = read_window_array(get_worldclim_raster_path("elevation", resolution), (west, south, east, north), (out_h, out_w))
            gy, gx = np.gradient(elev_cache)
            arrays[var] = np.sqrt(gx**2 + gy**2) if var == "slope" else np.nan_to_num(elev_cache - np.nanmean(elev_cache))
        else:
            arrays[var], actual_bounds = read_window_array(get_worldclim_raster_path(var, resolution), (west, south, east, north), (out_h, out_w))
    west2, south2, east2, north2 = actual_bounds
    lon_centers = np.linspace(west2 + (east2 - west2) / (2 * out_w), east2 - (east2 - west2) / (2 * out_w), out_w)
    lat_centers = np.linspace(north2 - (north2 - south2) / (2 * out_h), south2 + (north2 - south2) / (2 * out_h), out_h)
    lon_grid, lat_grid = np.meshgrid(lon_centers, lat_centers)
    X = pd.DataFrame({v: arrays[v].ravel() for v in variables})
    finite = np.isfinite(X.to_numpy()).all(axis=1)
    spatial = np.array([geom.covers(Point(float(lon), float(lat))) and land.covers(Point(float(lon), float(lat))) for lat, lon in zip(lat_grid.ravel(), lon_grid.ravel())])
    valid = finite & spatial
    pred_flat = np.full(X.shape[0], np.nan, dtype=float)
    if valid.sum() == 0:
        raise RuntimeError("No valid land raster cells were available for prediction.")
    preds = [model.predict_proba(X.loc[valid, variables])[:, 1] for model in sdm_result["models"].values()]
    pred_flat[valid] = np.mean(np.vstack(preds), axis=0)
    pred = pred_flat.reshape(out_h, out_w)
    row_grid, col_grid = np.indices((out_h, out_w))
    overlay = {"image": rgba_from_prediction(pred), "bounds": [[south2, west2], [north2, east2]], "shape": pred.shape, "source_stride": stride, "min": round(float(np.nanmin(pred)), 4), "max": round(float(np.nanmax(pred)), 4), "mean": round(float(np.nanmean(pred)), 4), "method": "Ensemble predict_proba over environmental raster grid"}
    pred_table = pd.DataFrame({"raster_row": row_grid.ravel()[valid].astype(int), "raster_col": col_grid.ravel()[valid].astype(int), "cell_index": np.flatnonzero(valid).astype(int), "x": lon_grid.ravel()[valid], "y": lat_grid.ravel()[valid], "longitude": lon_grid.ravel()[valid], "latitude": lat_grid.ravel()[valid], "sdm_suitability": pred_flat[valid]})
    return overlay, pred_table


def make_sdm_exploration_candidates(pred_table: pd.DataFrame, known_occ: pd.DataFrame, occurrence_candidates: pd.DataFrame, min_suitability: float, quantile_cutoff: float, min_distance_known_m: float, cluster_distance_m: float, max_candidates: int, start_site_id: int) -> pd.DataFrame:
    if pred_table is None or pred_table.empty:
        return pd.DataFrame()
    pred = pred_table.dropna(subset=["sdm_suitability"]).copy()
    cutoff = max(float(min_suitability), float(pred["sdm_suitability"].quantile(float(quantile_cutoff))))
    pred = pred[pred["sdm_suitability"] >= cutoff].copy()
    if pred.empty:
        return pd.DataFrame()
    known = pd.concat([known_occ[["_latitude", "_longitude"]].rename(columns={"_latitude": "latitude", "_longitude": "longitude"}), occurrence_candidates[["latitude", "longitude"]]], ignore_index=True)
    keep = []; dists = []
    for _, row in pred.iterrows():
        coord = (float(row["latitude"]), float(row["longitude"]))
        d = min([geodesic(coord, (float(r["latitude"]), float(r["longitude"]))).m for _, r in known.iterrows()] or [float("inf")])
        keep.append(d >= min_distance_known_m); dists.append(round(d))
    pred["distance_to_nearest_known_m"] = dists
    pred = pred[pd.Series(keep, index=pred.index)].copy()
    if pred.empty:
        return pd.DataFrame()
    pred["exploration_cluster"] = haversine_dbscan(pred, "latitude", "longitude", cluster_distance_m, 1)
    rows = []
    for i, (_, group) in enumerate(pred.groupby("exploration_cluster"), start=0):
        best = group.sort_values("sdm_suitability", ascending=False).iloc[0]
        rows.append({"site_id": start_site_id + i, "candidate_type": "SDM-high exploration survey range", "cluster_id": int(best["exploration_cluster"]), "latitude": float(best["latitude"]), "longitude": float(best["longitude"]), "n_occurrences": 0, "occurrence_support_score": 0.0, "priority_score": round(float(best["sdm_suitability"]), 3), "sdm_suitability": round(float(best["sdm_suitability"]), 3), "distance_to_nearest_known_m": float(best["distance_to_nearest_known_m"]), "candidate_method": "Raster predict-map suitability maximum", "selection_reason": "High SDM suitability and away from known records/candidate ranges.", "bias_warning": "Exploratory SDM candidate. Field validation is required."})
    return pd.DataFrame(rows).sort_values("sdm_suitability", ascending=False).head(int(max_candidates)).reset_index(drop=True)


def popup_html_site(row: pd.Series) -> str:
    return f"""
    <b>Survey range {int(row.get('site_id', 0))}</b><br>
    Type: {row.get('candidate_type', '')}<br>
    Priority rank: {row.get('priority_rank', '')}<br>
    Priority score: {row.get('priority_score', '')}<br>
    Occurrence support: {row.get('occurrence_support_score', '')}<br>
    Occurrence records: {int(row.get('n_occurrences', 0))}<br>
    SDM suitability: {row.get('sdm_suitability', '')}<br>
    Latitude: {float(row['latitude']):.6f}<br>
    Longitude: {float(row['longitude']):.6f}<br>
    Note: {row.get('bias_warning', '')}<br>
    <a href='{make_google_maps_point_url(float(row['latitude']), float(row['longitude']))}' target='_blank'>Open in Google Maps</a>
    {image_html(row.get('representative_media_url', ''))}
    """


def build_map(occ: pd.DataFrame, sites: pd.DataFrame, overlay: Optional[dict[str, Any]], route_plan: Optional[pd.DataFrame], occurrence_buffer_m: float, survey_range_m: float, layers: dict[str, bool]) -> folium.Map:
    center = (float(occ["_latitude"].mean()), float(occ["_longitude"].mean())) if not occ.empty else (35.5, 135.5)
    fmap = Map(location=center, zoom_start=8, tiles="OpenStreetMap", control_scale=True)
    if layers.get("predict") and overlay is not None:
        folium.raster_layers.ImageOverlay(image=overlay["image"], bounds=overlay["bounds"], opacity=0.68, name="SDM predict map", interactive=True).add_to(fmap)
        add_sdm_predict_legend(fmap)
    if layers.get("occ"):
        fg = FeatureGroup(name="occurrences after exclusion", show=True)
        mc = MarkerCluster()
        for _, row in occ.iterrows():
            html = f"Occurrence<br>{row['_latitude']:.6f}, {row['_longitude']:.6f}<br>{row.get('_species','')}<br>GBIF {row.get('_gbif_id','')}<br>{image_html(row.get('_media_url',''))}"
            folium.CircleMarker((row["_latitude"], row["_longitude"]), radius=4, color="#1f77b4", fill=True, popup=folium.Popup(html, max_width=330)).add_to(mc)
        mc.add_to(fg); fg.add_to(fmap)
    if layers.get("candidate_circles") and sites is not None and not sites.empty:
        fg = FeatureGroup(name="candidate circles", show=True)
        for _, row in sites.iterrows():
            color = "#2ca02c" if str(row.get("candidate_type", "")).startswith("SDM-high") else "#d62728"
            folium.Circle((row["latitude"], row["longitude"]), radius=survey_range_m, color=color, fill=True, fill_opacity=0.14, weight=2, popup=folium.Popup(popup_html_site(row), max_width=460)).add_to(fg)
        fg.add_to(fmap)
    LayerControl(collapsed=True).add_to(fmap)
    try:
        fmap.fit_bounds([[occ["_latitude"].min(), occ["_longitude"].min()], [occ["_latitude"].max(), occ["_longitude"].max()]], padding=(30, 30))
    except Exception:
        pass
    return fmap


def load_input_controls() -> None:
    mode = st.sidebar.radio("Input source", ["Upload coordinate CSV", "Search GBIF by scientific name"], index=1, key="input_source_selector")
    if st.sidebar.button("Clear loaded data"):
        clear_loaded_data()
    if mode == "Upload coordinate CSV":
        uploaded = st.sidebar.file_uploader("Upload CSV with latitude/longitude columns", type=["csv"], key="coordinate_csv_uploader")
        if uploaded is not None:
            key = f"upload::{uploaded.name}::{uploaded.size}"
            if st.session_state.source_key != key:
                st.session_state.raw_df = read_uploaded_csv(uploaded)
                st.session_state.source_key = key
                st.session_state.source_message = f"Loaded coordinate CSV: {uploaded.name} ({len(st.session_state.raw_df):,} raw rows)."
                st.session_state.excluded_row_ids = set()
                st.session_state.restore_excluded_row_ids = []
                reset_model_outputs()
        return
    name = st.sidebar.text_input("Taxon scientific name", value="", placeholder="e.g. Campanula punctata", key="gbif_taxon_scientific_name_input")
    country_options = ["", "JP", "US", "GB", "CN", "KR", "TW", "DE", "FR", "IT", "ES", "AU", "NZ", "CA", "BR", "IN", "ID", "TH", "VN"]
    selected_country = st.sidebar.selectbox("Country code filter optional", country_options, index=1, key="gbif_country_code_filter_select")
    custom_country = st.sidebar.text_input("Custom country code optional", value="", max_chars=2, key="gbif_country_code_filter_custom", help="Two-letter ISO country code. Overrides the dropdown when set.")
    country = custom_country.strip().upper() or selected_country
    max_records = st.sidebar.number_input("Maximum GBIF records to fetch", 100, 200_000, 10_000, 1000, help="GBIF returns at most 300 records per request. The app fetches repeated pages until this cap or GBIF endOfRecords.")
    use_year = st.sidebar.checkbox("Filter by year", value=False)
    year_from = year_to = None
    if use_year:
        c1, c2 = st.sidebar.columns(2)
        year_from = int(c1.number_input("From", 1600, 2100, 2000))
        year_to = int(c2.number_input("To", 1600, 2100, 2026))
    if st.sidebar.button("Fetch occurrences from GBIF", type="primary"):
        if not name.strip():
            st.warning("Scientific name is empty.")
            return
        with st.spinner("Fetching GBIF occurrences page by page, 300 records per request..."):
            msg, df = fetch_gbif_occurrences_cached(name.strip(), int(max_records), country.strip().upper(), year_from, year_to)
        st.session_state.raw_df = df
        st.session_state.source_key = f"gbif::{name}::{country}::{max_records}::{year_from}::{year_to}"
        st.session_state.source_message = msg
        st.session_state.excluded_row_ids = set()
        st.session_state.restore_excluded_row_ids = []
        reset_model_outputs()



def genus_diversity_panel() -> None:
    st.sidebar.header("Genus data source")
    genus_name = st.sidebar.text_input("Genus name", value="", placeholder="e.g. Cirsium", key="genus_name_input")
    country_options = ["", "JP", "US", "GB", "CN", "KR", "TW", "DE", "FR", "IT", "ES", "AU", "NZ", "CA", "BR", "IN", "ID", "TH", "VN"]
    selected_country = st.sidebar.selectbox("Country code filter optional", country_options, index=1, key="genus_country_code_filter_select")
    custom_country = st.sidebar.text_input("Custom country code optional", value="", max_chars=2, key="genus_country_code_filter_custom")
    country = custom_country.strip().upper() or selected_country
    max_records = st.sidebar.number_input("Maximum genus GBIF records to fetch", 100, 300_000, 20_000, 1000, help="GBIF returns at most 300 records per request. The app fetches repeated pages until this cap or GBIF endOfRecords.", key="genus_max_records")
    min_records_species = st.sidebar.number_input("Minimum records per species", 1, 500, 10, 1, key="genus_min_records_species")
    use_year = st.sidebar.checkbox("Filter genus records by year", value=False, key="genus_use_year")
    year_from = year_to = None
    if use_year:
        c1, c2 = st.sidebar.columns(2)
        year_from = int(c1.number_input("From", 1600, 2100, 2000, key="genus_year_from"))
        year_to = int(c2.number_input("To", 1600, 2100, 2026, key="genus_year_to"))
    if st.sidebar.button("Fetch genus occurrences from GBIF", type="primary"):
        if not genus_name.strip():
            st.warning("Genus name is empty.")
            return
        with st.spinner("Fetching GBIF genus occurrences page by page, 300 records per request..."):
            msg, df = fetch_gbif_genus_occurrences_cached(genus_name.strip(), int(max_records), country.strip().upper(), year_from, year_to)
        st.session_state.genus_raw_df = df
        st.session_state.genus_source_key = f"genus::{genus_name}::{country}::{max_records}::{year_from}::{year_to}"
        st.session_state.genus_source_message = msg

    st.sidebar.divider()
    st.sidebar.subheader("Occurrence richness")
    grid_deg = st.sidebar.selectbox("Grid cell size (degrees)", [0.05, 0.1, 0.25, 0.5, 1.0], index=1, key="genus_grid_deg")
    richness_metric = st.sidebar.selectbox("Richness metric", ["Species richness", "Record count", "Species with minimum records"], index=0, key="genus_richness_metric")
    min_records_cell = st.sidebar.number_input("Minimum records per species per cell", 1, 100, 1, 1, key="genus_min_records_cell")
    max_hotspots = st.sidebar.number_input("Max hotspot candidates", 1, 500, 30, 1, key="genus_max_hotspots")

    st.subheader("Genus diversity / SSDM")
    st.caption("This first implementation builds occurrence-based richness only. Full SSDM stacking is intentionally not run yet.")
    if st.session_state.genus_raw_df is None:
        st.info(st.session_state.genus_source_message)
        return
    st.success(st.session_state.genus_source_message)

    try:
        detected = detect_occurrence_columns(st.session_state.genus_raw_df)
        occ = clean_occurrences(st.session_state.genus_raw_df, detected)
    except Exception as exc:
        st.error(str(exc))
        return
    occ = occ[occ["_species"].astype(str).str.strip().ne("")].copy().reset_index(drop=True)
    if occ.empty:
        st.error("No valid genus occurrence records with species names and coordinates found.")
        return

    summary = genus_species_summary(occ, int(min_records_species), float(grid_deg))
    grid = occurrence_richness_grid(occ, float(grid_deg), int(min_records_cell))
    hotspots = richness_hotspot_candidates(grid, richness_metric, int(max_hotspots))

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Valid records", f"{len(occ):,}")
    c2.metric("Species", f"{len(summary):,}")
    c3.metric("Richness cells", f"{len(grid):,}")
    c4.metric("Hotspots", f"{len(hotspots):,}")

    st.write("Species summary")
    st.dataframe(summary, width="stretch", hide_index=True)

    if grid.empty:
        st.warning("No richness grid cells could be generated.")
        return

    fmap = make_richness_map(grid, hotspots, richness_metric)
    st_folium(fmap, width=None, height=720, returned_objects=[], key="genus_richness_map")

    st.write("Richness hotspot candidates")
    hotspot_cols = ["hotspot_rank", "candidate_type", "latitude", "longitude", "species_richness", "record_count", "species_with_min_records", "species_list", "google_maps_url"]
    st.dataframe(hotspots[[c for c in hotspot_cols if c in hotspots.columns]], width="stretch", hide_index=True)

    st.subheader("Downloads")
    st.download_button("Download genus species summary CSV", summary.to_csv(index=False).encode("utf-8"), "genus_species_summary.csv", "text/csv", width="stretch")
    st.download_button("Download occurrence richness grid CSV", grid.to_csv(index=False).encode("utf-8"), "occurrence_richness_grid.csv", "text/csv", width="stretch")
    st.download_button("Download richness hotspot candidates CSV", hotspots.to_csv(index=False).encode("utf-8"), "richness_hotspot_candidates.csv", "text/csv", width="stretch")
    st.download_button("Download richness HTML map", fmap.get_root().render().encode("utf-8"), "genus_richness_map.html", "text/html", width="stretch")


def make_route_selection_map(sites: pd.DataFrame, selected_ids: list[int], add_draw: bool = False) -> folium.Map:
    selected = set(map(int, selected_ids))
    center = (float(sites["latitude"].mean()), float(sites["longitude"].mean())) if not sites.empty else (35.5, 135.5)
    fmap = Map(location=center, zoom_start=8, tiles="OpenStreetMap", control_scale=True)
    fg = FeatureGroup(name="candidate survey ranges", show=True)
    for _, row in sites.iterrows():
        sid = int(row["site_id"])
        picked = sid in selected
        color = "#2ca02c" if picked else "#1f77b4"
        html = f"""
        <b>{'Selected' if picked else 'Candidate'} survey site {sid}</b><br>
        type: {row.get('candidate_type', '')}<br>
        priority: {row.get('priority_score', '')}<br>
        SDM: {row.get('sdm_suitability', '')}<br>
        lat/lon: {float(row['latitude']):.6f}, {float(row['longitude']):.6f}<br>
        <a href='{make_google_maps_point_url(float(row['latitude']), float(row['longitude']))}' target='_blank'>Open point in Google Maps</a>
        """
        folium.CircleMarker((row["latitude"], row["longitude"]), radius=9 if picked else 6, color=color, fill=True, fill_color=color, fill_opacity=0.9 if picked else 0.65, weight=3 if picked else 1, popup=folium.Popup(html, max_width=360), tooltip=f"{'selected' if picked else 'click to select'} | site {sid}").add_to(fg)
    fg.add_to(fmap)
    if add_draw:
        Draw(export=False, draw_options={"rectangle": True, "polyline": False, "circle": False, "marker": False, "circlemarker": False, "polygon": False}, edit_options={"edit": False, "remove": True}).add_to(fmap)
    LayerControl(collapsed=True).add_to(fmap)
    try:
        fmap.fit_bounds([[sites["latitude"].min(), sites["longitude"].min()], [sites["latitude"].max(), sites["longitude"].max()]], padding=(30, 30))
    except Exception:
        pass
    return fmap


def nearest_site_id_from_click(sites: pd.DataFrame, click: dict[str, Any]) -> Optional[int]:
    if not click or "lat" not in click or "lng" not in click or sites.empty:
        return None
    coord = (float(click["lat"]), float(click["lng"]))
    dists = sites.apply(lambda r: geodesic(coord, (float(r["latitude"]), float(r["longitude"]))).km, axis=1)
    return int(sites.loc[int(dists.idxmin()), "site_id"])


SURVEY_DAY_CSV_COLS = ["survey_day", "order_within_day", "site_id", "candidate_type", "priority_rank", "priority_score", "sdm_suitability", "occurrence_support_score", "n_occurrences", "latitude", "longitude", "google_maps_url", "access_note"]


def _make_day_gmaps_urls(day_sites: pd.DataFrame, travelmode: str = "driving") -> list[str]:
    """Return Google Maps direction URLs for a day's sites, split into parts when >10 sites."""
    if day_sites.empty:
        return []
    coords = [(float(r["latitude"]), float(r["longitude"])) for _, r in day_sites.iterrows()]
    if len(coords) == 1:
        return [make_google_maps_point_url(coords[0][0], coords[0][1])]
    urls: list[str] = []
    chunk_size = 10  # 1 origin + 8 waypoints + 1 destination
    for i in range(0, len(coords), chunk_size):
        chunk = coords[i:i + chunk_size]
        if len(chunk) == 1:
            urls.append(make_google_maps_point_url(chunk[0][0], chunk[0][1]))
            continue
        params: dict[str, Any] = {"api": "1", "origin": f"{chunk[0][0]:.6f},{chunk[0][1]:.6f}", "destination": f"{chunk[-1][0]:.6f},{chunk[-1][1]:.6f}", "travelmode": travelmode, "dir_action": "navigate"}
        wps = chunk[1:-1]
        if wps and travelmode != "transit":
            params["waypoints"] = "|".join(f"{lat:.6f},{lon:.6f}" for lat, lon in wps)
        urls.append("https://www.google.com/maps/dir/?" + urllib.parse.urlencode(params, safe=",|"))
    return urls


def make_survey_day_csv(day_lists: dict, sites: pd.DataFrame) -> str:
    rows = []
    for day_num in sorted(day_lists.keys()):
        for order, sid in enumerate(day_lists[day_num], start=1):
            m = sites[sites["site_id"].astype(int) == sid]
            if m.empty:
                continue
            r = m.iloc[0]
            rows.append({"survey_day": day_num, "order_within_day": order, "site_id": int(r.get("site_id", sid)), "candidate_type": r.get("candidate_type", ""), "priority_rank": r.get("priority_rank", ""), "priority_score": r.get("priority_score", ""), "sdm_suitability": r.get("sdm_suitability", ""), "occurrence_support_score": r.get("occurrence_support_score", ""), "n_occurrences": r.get("n_occurrences", ""), "latitude": float(r["latitude"]), "longitude": float(r["longitude"]), "google_maps_url": make_google_maps_point_url(float(r["latitude"]), float(r["longitude"])), "access_note": r.get("access_note", "")})
    return pd.DataFrame(rows).to_csv(index=False) if rows else ",".join(SURVEY_DAY_CSV_COLS) + "\n"


def make_survey_day_html(day_lists: dict, sites: pd.DataFrame) -> str:
    body = ""
    for day_num in sorted(day_lists.keys()):
        if not day_lists[day_num]:
            continue
        body += f"<h3>Day {day_num}</h3><table><thead><tr><th>#</th><th>Site</th><th>Type</th><th>Priority</th><th>SDM suit.</th><th>Lat</th><th>Lon</th><th>Map</th></tr></thead><tbody>"
        for order, sid in enumerate(day_lists[day_num], start=1):
            m = sites[sites["site_id"].astype(int) == sid]
            if m.empty:
                continue
            r = m.iloc[0]
            gmaps = make_google_maps_point_url(float(r["latitude"]), float(r["longitude"]))
            suit = f'{r["sdm_suitability"]:.3f}' if pd.notna(r.get("sdm_suitability")) and str(r.get("sdm_suitability", "")) not in ("", "nan") else "—"
            body += f"<tr><td>{order}</td><td>Site {int(r.get('site_id', sid))}</td><td>{r.get('candidate_type','')}</td><td>{r.get('priority_score','')}</td><td>{suit}</td><td>{float(r['latitude']):.5f}</td><td>{float(r['longitude']):.5f}</td><td><a href='{gmaps}' target='_blank'>📍</a></td></tr>"
        body += "</tbody></table>"
    return ("<!DOCTYPE html><html><head><meta charset='utf-8'><title>Survey Day Site Lists</title><style>body{font-family:sans-serif;margin:24px}h3{margin-top:20px}table{border-collapse:collapse;width:100%;margin-bottom:16px}th,td{border:1px solid #ccc;padding:5px 9px}th{background:#f0f0f0}a{color:#1a73e8}</style></head><body>"
            "<h2>Survey Day Site Lists</h2><p><em>⚠️ Google Maps verification is required. This app does not guarantee road, ferry, mountain, cliff, or restricted-access feasibility.</em></p>"
            f"{body}</body></html>")


EXPORT_CSV_COLS = ["name", "latitude", "longitude", "priority_rank", "priority_score", "sdm_suitability", "occurrence_support_score", "n_occurrences", "candidate_type", "candidate_method", "selection_reason", "access_note", "google_maps_url"]


def make_export_csv(sites: pd.DataFrame) -> str:
    out = sites.copy()
    out["name"] = out.apply(lambda r: f"Site {int(r['site_id'])} - {str(r.get('candidate_type', ''))}", axis=1)
    out["google_maps_url"] = out.apply(lambda r: make_google_maps_point_url(float(r["latitude"]), float(r["longitude"])), axis=1)
    for col in EXPORT_CSV_COLS:
        if col not in out.columns:
            out[col] = ""
    return out[EXPORT_CSV_COLS].to_csv(index=False)


def make_export_kml(sites: pd.DataFrame) -> str:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>',
        '  <name>GBIF FieldMap Builder survey sites</name>',
    ]
    for _, r in sites.iterrows():
        name = f"Site {int(r['site_id'])}"
        desc_parts = [f"{col}: {r[col]}" for col in ["candidate_type", "priority_rank", "priority_score", "sdm_suitability", "occurrence_support_score", "n_occurrences", "selection_reason", "access_note"] if col in r and str(r[col]) not in ("", "nan")]
        desc = "\n".join(desc_parts)
        lat, lon = float(r["latitude"]), float(r["longitude"])
        lines += ["  <Placemark>", f"    <name>{name}</name>", f"    <description><![CDATA[{desc}]]></description>", f"    <Point><coordinates>{lon:.6f},{lat:.6f},0</coordinates></Point>", "  </Placemark>"]
    lines += ["</Document></kml>"]
    return "\n".join(lines)


def make_shareable_html(sites: pd.DataFrame) -> str:
    rows = ""
    for i, (_, r) in enumerate(sites.iterrows(), start=1):
        gmaps = make_google_maps_point_url(float(r["latitude"]), float(r["longitude"]))
        suit = f'{r["sdm_suitability"]:.3f}' if pd.notna(r.get("sdm_suitability")) and str(r.get("sdm_suitability", "")) not in ("", "nan") else "—"
        rows += (
            f"<tr><td>{int(r.get('site_id', i))}</td>"
            f"<td>{r.get('priority_rank', '')}</td>"
            f"<td>{r.get('priority_score', '')}</td>"
            f"<td>{suit}</td>"
            f"<td>{r.get('occurrence_support_score', '')}</td>"
            f"<td>{r.get('n_occurrences', '')}</td>"
            f"<td>{float(r['latitude']):.5f}</td>"
            f"<td>{float(r['longitude']):.5f}</td>"
            f"<td>{r.get('candidate_type', '')}</td>"
            f"<td><a href='{gmaps}' target='_blank'>Google Maps</a></td></tr>\n"
        )
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        "<title>Survey Site List</title>"
        "<style>body{font-family:sans-serif;margin:24px;color:#222}"
        "h2{margin-bottom:4px}p.warn{color:#b94a00;font-size:.9em;margin-bottom:16px}"
        "table{border-collapse:collapse;width:100%}th,td{border:1px solid #ccc;padding:6px 10px;text-align:left}"
        "th{background:#f0f0f0}tr:nth-child(even){background:#fafafa}"
        "a{color:#1a73e8;text-decoration:none}a:hover{text-decoration:underline}</style></head><body>"
        "<h2>Survey Site List</h2>"
        "<p class='warn'>⚠️ This list does not guarantee road, ferry, mountain, cliff, or restricted-access feasibility. "
        "Please verify each site in Google Maps before fieldwork.</p>"
        "<table><thead><tr>"
        "<th>Site ID</th><th>Priority rank</th><th>Priority score</th><th>SDM suitability</th>"
        "<th>Occ. support</th><th>N occ.</th><th>Latitude</th><th>Longitude</th>"
        "<th>Type</th><th>Google Maps</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></body></html>"
    )


def _make_shareable_text(sites: pd.DataFrame) -> str:
    lines = ["Survey Site List", "=" * 60]
    for _, r in sites.iterrows():
        gmaps = make_google_maps_point_url(float(r["latitude"]), float(r["longitude"]))
        suit = f'{r["sdm_suitability"]:.3f}' if pd.notna(r.get("sdm_suitability")) and str(r.get("sdm_suitability", "")) not in ("", "nan") else "—"
        lines.append(
            f"Site {int(r.get('site_id', '?'))} | Rank {r.get('priority_rank', '?')} | "
            f"Priority {r.get('priority_score', '?')} | SDM {suit} | "
            f"{float(r['latitude']):.5f}, {float(r['longitude']):.5f} | {gmaps}"
        )
    lines += ["", "⚠️ Verify each site in Google Maps before fieldwork."]
    return "\n".join(lines)


def _make_gmaps_url_with_end(ordered: pd.DataFrame, travelmode: str, start_location: str, end_location: str) -> str:
    """Build a Google Maps directions URL with an explicit end_location destination."""
    if ordered.empty:
        return ""
    coords = [(float(r["latitude"]), float(r["longitude"])) for _, r in ordered.iterrows()]
    origin = start_location.strip() if start_location.strip() else f"{coords[0][0]:.6f},{coords[0][1]:.6f}"
    destination = end_location.strip()
    waypoint_coords = coords if start_location.strip() else coords[:-1]
    params: dict[str, Any] = {"api": "1", "origin": origin, "destination": destination, "travelmode": travelmode, "dir_action": "navigate"}
    if travelmode != "transit":
        wps = waypoint_coords[:8]
        if wps:
            params["waypoints"] = "|".join(f"{lat:.6f},{lon:.6f}" for lat, lon in wps)
    return "https://www.google.com/maps/dir/?" + urllib.parse.urlencode(params, safe=",|")


def route_planner_panel(sites: pd.DataFrame) -> pd.DataFrame:
    st.subheader("Survey site list")
    st.caption(
        "⚠️ Google Maps verification is required. "
        "This app does not guarantee road, ferry, mountain, cliff, or restricted-access feasibility."
    )
    if sites.empty:
        return pd.DataFrame()

    sort_cols = available_sort_cols(sites, ["priority_score", "sdm_suitability", "occurrence_support_score"])
    ranked_sites = sites.sort_values(sort_cols, ascending=False, na_position="last") if sort_cols else sites
    options = sites["site_id"].astype(int).tolist()
    has_suit = "sdm_suitability" in sites.columns and sites["sdm_suitability"].notna().any()
    has_sdm_high = "candidate_type" in sites.columns and sites["candidate_type"].str.startswith("SDM-high").any()

    # ── Initialise / prune state ─────────────────────────────────────────────
    if not isinstance(st.session_state.get("survey_day_lists"), dict):
        st.session_state.survey_day_lists = {1: [], 2: []}
    valid_ids = set(options)
    for k in list(st.session_state.survey_day_lists.keys()):
        st.session_state.survey_day_lists[k] = [s for s in st.session_state.survey_day_lists[k] if s in valid_ids]
    st.session_state.sl_selected_site_ids = [s for s in st.session_state.get("sl_selected_site_ids", []) if s in valid_ids]

    travelmode = st.selectbox("Travel mode for Google Maps links", ["driving", "walking", "bicycling", "transit"], index=0, key="sl_travelmode")

    # ── Selection area (auto / manual+rectangle — unchanged logic) ───────────
    st.markdown("#### Select candidate sites")
    sel_mode = st.radio("Selection mode", ["Auto: top-ranked", "Manual: map & rectangle"], horizontal=True, key="sl_sel_mode")

    if sel_mode.startswith("Auto"):
        ac1, ac2, ac3 = st.columns(3)
        top_n = ac1.number_input("Top N sites", 1, max(1, len(sites)), min(10, len(sites)), 1, key="sl_top_n")
        min_priority = ac2.number_input("Min priority score", 0.0, 1.0, 0.0, 0.05, format="%.2f", key="sl_min_priority")
        min_suit = ac3.number_input("Min SDM suitability", 0.0, 1.0, 0.0, 0.05, format="%.2f", key="sl_min_suit",
                                    help="SDM not built yet." if not has_suit else "Filter by SDM suitability.")
        ic1, ic2 = st.columns(2)
        incl_occ = ic1.checkbox("Occurrence-supported sites", value=True, key="sl_incl_occ")
        incl_sdm = ic2.checkbox("SDM-high exploration sites", value=True, key="sl_incl_sdm", disabled=not has_sdm_high)

        filtered = ranked_sites.copy()
        type_mask = pd.Series(False, index=filtered.index)
        if incl_occ:
            type_mask |= filtered.get("candidate_type", pd.Series("", index=filtered.index)).str.startswith("Occurrence")
        if incl_sdm and has_sdm_high:
            type_mask |= filtered.get("candidate_type", pd.Series("", index=filtered.index)).str.startswith("SDM-high")
        if incl_occ or (incl_sdm and has_sdm_high):
            filtered = filtered[type_mask]
        if "priority_score" in filtered.columns:
            filtered = filtered[pd.to_numeric(filtered["priority_score"], errors="coerce").fillna(0.0) >= float(min_priority)]
        if has_suit:
            filtered = filtered[pd.to_numeric(filtered["sdm_suitability"], errors="coerce").fillna(0.0) >= float(min_suit)]
        auto_ids = filtered.head(int(top_n))["site_id"].astype(int).tolist()

        show_cols = [c for c in ["site_id", "priority_rank", "priority_score", "sdm_suitability", "candidate_type"] if c in filtered.columns]
        if auto_ids:
            st.dataframe(filtered.head(int(top_n))[show_cols], width="stretch", hide_index=True)
        if not filtered.iloc[int(top_n):].empty:
            with st.expander(f"Lower-priority sites not included ({len(filtered) - int(top_n)})", expanded=False):
                st.dataframe(filtered.iloc[int(top_n):][show_cols], width="stretch", hide_index=True)
        if st.button("Use these as selected sites", key="sl_auto_apply") and auto_ids:
            st.session_state.sl_selected_site_ids = auto_ids
            st.rerun()

    else:
        # Manual: map click + rectangle Draw (logic unchanged)
        st.caption("Click sites to toggle. Draw a rectangle to add all sites inside to the selection. 🟢 = selected, 🔵 = not selected.")
        click_data = st_folium(
            make_route_selection_map(sites, st.session_state.sl_selected_site_ids, add_draw=True),
            width=None, height=480,
            returned_objects=["last_object_clicked", "all_drawings", "last_active_drawing"],
            key="sl_manual_map",
        )
        clicked = (click_data or {}).get("last_object_clicked")
        if clicked:
            sig = f"{clicked.get('lat'):.6f},{clicked.get('lng'):.6f}"
            if sig != st.session_state.last_route_click_signature:
                sid = nearest_site_id_from_click(sites, clicked)
                st.session_state.last_route_click_signature = sig
                if sid is not None:
                    sel = list(st.session_state.sl_selected_site_ids)
                    if sid in sel:
                        sel.remove(sid)
                    else:
                        sel.append(sid)
                    st.session_state.sl_selected_site_ids = sel
                    st.rerun()
        raw_sl_drawings = (click_data or {}).get("all_drawings") or (click_data or {}).get("last_active_drawing")
        sl_features = extract_drawn_features(raw_sl_drawings)
        if sl_features:
            draw_sig = str(sl_features)[:400]
            if draw_sig != st.session_state.get("sl_last_draw_sig", ""):
                st.session_state.sl_last_draw_sig = draw_sig
                rect_ids = ids_inside_drawn_rectangles(sites, "site_id", "latitude", "longitude", sl_features)
                if rect_ids:
                    existing = set(st.session_state.sl_selected_site_ids)
                    st.session_state.sl_selected_site_ids = list(existing | set(rect_ids))
                    st.rerun()
        _tok = st.session_state.get("sl_reset_token", 0)
        manual_ids = st.multiselect("Selected site IDs", options=options, default=st.session_state.sl_selected_site_ids, key=f"sl_manual_ids_{_tok}")
        st.session_state.sl_selected_site_ids = [int(x) for x in manual_ids]
        b1, b2 = st.columns(2)
        if b1.button("Use top ranked", key="sl_top_btn"):
            st.session_state.sl_selected_site_ids = ranked_sites["site_id"].astype(int).head(min(10, len(ranked_sites))).tolist()
            st.rerun()
        if b2.button("Clear selected sites", key="sl_clear_btn"):
            st.session_state.sl_selected_site_ids = []
            st.session_state.sl_reset_token = st.session_state.get("sl_reset_token", 0) + 1
            st.session_state.last_route_click_signature = ""
            st.session_state.sl_last_draw_sig = ""
            st.rerun()

    # ── Selected survey sites (main output) ──────────────────────────────────
    selected_ids = st.session_state.sl_selected_site_ids
    sel_df = sites[sites["site_id"].astype(int).isin(selected_ids)].copy()
    if not sel_df.empty and selected_ids:
        sid_order = {sid: i for i, sid in enumerate(selected_ids)}
        sel_df = sel_df.assign(_ord=sel_df["site_id"].astype(int).map(sid_order)).sort_values("_ord").drop(columns=["_ord"])

    st.markdown(f"#### Selected survey sites ({len(sel_df)})")
    if sel_df.empty:
        st.info("No sites selected yet. Use Auto or Manual mode above.")
    else:
        sel_df["google_maps_point_url"] = sel_df.apply(
            lambda r: make_google_maps_point_url(float(r["latitude"]), float(r["longitude"])), axis=1
        )
        show_scols = [c for c in ["site_id", "priority_rank", "priority_score", "sdm_suitability",
                                   "occurrence_support_score", "n_occurrences", "candidate_type",
                                   "latitude", "longitude", "google_maps_point_url"] if c in sel_df.columns]
        scol_cfg: dict[str, Any] = {}
        if "google_maps_point_url" in show_scols:
            scol_cfg["google_maps_point_url"] = st.column_config.LinkColumn("Google Maps", display_text="📍")
        st.dataframe(sel_df[show_scols], column_config=scol_cfg, width="stretch", hide_index=True)

        gmaps_all_url = make_google_maps_route_url(sel_df, travelmode=travelmode, max_waypoints=8)
        ab1, ab2, ab3, ab4 = st.columns(4)
        ab1.link_button("🗺️ Open all in Google Maps", gmaps_all_url, use_container_width=True)
        ab2.download_button("⬇ CSV", make_export_csv(sel_df), "survey_site_list.csv", "text/csv", use_container_width=True)
        ab3.download_button("⬇ HTML", make_shareable_html(sel_df), "survey_site_list.html", "text/html", use_container_width=True)
        if ab4.button("Clear selected sites", key="sl_clear_main"):
            st.session_state.sl_selected_site_ids = []
            st.session_state.sl_reset_token = st.session_state.get("sl_reset_token", 0) + 1
            st.session_state.last_route_click_signature = ""
            st.session_state.sl_last_draw_sig = ""
            st.rerun()

    # ── Return selected sites for map route layer (survey_day=1) ─────────────
    if sel_df.empty:
        return pd.DataFrame()
    gurl = make_google_maps_route_url(sel_df, travelmode=travelmode, max_waypoints=8)
    all_rows: list[dict] = []
    for order, (_, row) in enumerate(sel_df.iterrows(), start=1):
        r = row.to_dict()
        r.update({"survey_day": 1, "day_route_order": order, "distance_from_previous_km": 0.0, "cumulative_day_distance_km": 0.0, "day_google_maps_route_url": gurl})
        all_rows.append(r)
    return pd.DataFrame(all_rows)


def make_validation_template(sites: pd.DataFrame) -> pd.DataFrame:
    cols = ["site_id", "candidate_type", "priority_rank", "latitude", "longitude", "priority_score", "occurrence_support_score", "sdm_suitability", "google_maps_checked", "accessible", "access_mode", "access_note", "visited", "survey_date", "observer", "access_success", "target_species_found", "abundance_count", "abundance_class", "flowering_status", "habitat_note", "photo_file", "comments"]
    base = sites.copy()
    for col in cols:
        if col not in base.columns:
            base[col] = ""
    return base[cols]


def main() -> None:
    st.set_page_config(page_title=APP_TITLE, page_icon="🗺️", layout="wide")
    init_session_state()
    st.title("🗺️ GBIF FieldMap Builder")
    st.caption("Occurrence-based survey ranges, map-click coordinate exclusion, raster-style SDM predict maps, VIF filtering, spatial partition diagnostics, and route planning.")

    st.sidebar.caption(f"Build: {APP_BUILD_ID}")
    analysis_mode = st.sidebar.radio("Analysis mode", ["Single species survey planning", "Genus diversity / SSDM"], index=0, key="analysis_mode")
    if analysis_mode == "Genus diversity / SSDM":
        genus_diversity_panel()
        return

    st.sidebar.header("Data source")
    load_input_controls()
    st.sidebar.divider()
    st.sidebar.subheader("Sampling design")
    thinning_m = st.sidebar.number_input("Spatial thinning before clustering (m)", 0, 50_000, 1000, 500)
    center_method = st.sidebar.selectbox("Candidate center method", ["Medoid", "Centroid"], index=0)
    survey_range_m = st.sidebar.number_input("Survey range radius around candidate centers (m)", 50, 50_000, 500, 50)
    cluster_m = st.sidebar.number_input("DBSCAN cluster distance (m)", 1, 500_000, 2000, 500)
    min_samples = st.sidebar.number_input("Minimum records per cluster", 1, 50, 1, 1)
    occurrence_weight = st.sidebar.slider("Occurrence record-count weight", 0.0, 0.60, 0.35, 0.05)
    st.sidebar.divider()
    st.sidebar.subheader("Layers")
    layers = {"predict": st.sidebar.checkbox("SDM predict map", True), "occ": st.sidebar.checkbox("Occurrences", True), "candidate_circles": st.sidebar.checkbox("Candidate circles", True)}

    if st.session_state.raw_df is None:
        st.info(st.session_state.source_message)
        return
    st.success(st.session_state.source_message)
    try:
        detected = detect_occurrence_columns(st.session_state.raw_df)
        occ_raw = clean_occurrences(st.session_state.raw_df, detected)
    except Exception as exc:
        st.error(str(exc))
        return
    if occ_raw.empty:
        st.error("No valid coordinate records found.")
        return

    occ_checked = coordinate_exclusion_panel(occ_raw)
    active_excluded_ids = set(map(int, st.session_state.excluded_row_ids))
    occ_checked = occ_raw[~occ_raw["_row_id"].astype(int).isin(active_excluded_ids)].copy().reset_index(drop=True)
    leaked_checked_ids = sorted(set(occ_checked["_row_id"].astype(int)).intersection(active_excluded_ids))
    if leaked_checked_ids:
        st.error(f"Excluded rows leaked into the included occurrence set: {leaked_checked_ids[:20]}. SDM was stopped.")
        return
    if occ_checked.empty:
        st.error("All occurrence records were excluded. Clear excluded coordinates.")
        return

    occ = spatial_thin(occ_checked, float(thinning_m))
    leaked_occ_ids = sorted(set(occ["_row_id"].astype(int)).intersection(active_excluded_ids))
    if leaked_occ_ids:
        st.error(f"Excluded rows leaked into the thinned SDM occurrence set: {leaked_occ_ids[:20]}. SDM was stopped.")
        return
    occ["cluster_id"] = haversine_dbscan(occ, "_latitude", "_longitude", float(cluster_m), int(min_samples))
    current_sdm_occurrence_row_ids = tuple(sorted(occ["_row_id"].astype(int).tolist()))
    if st.session_state.sdm_occurrence_row_ids is not None and st.session_state.sdm_occurrence_row_ids != current_sdm_occurrence_row_ids:
        reset_model_outputs()
        st.info("Coordinate exclusions or thinning changed. Previous SDM and predict map were cleared; rebuild SDM to use the current occurrence set.")
    occurrence_candidates = make_candidate_sites(occ, center_method, float(occurrence_weight))
    occurrence_candidates = add_priority_rank(occurrence_candidates)
    occurrence_candidates = order_sites(occurrence_candidates, "Nearest-neighbor route")

    st.subheader("SDM prediction extent")
    st.caption("Choose the prediction area before building SDM. Only blue included points are used below; excluded rows are removed from the analysis view and hard-masked from prediction.")
    area_mode = st.selectbox("Area to predict", AREA_MODES, index=2, help="All three modes are land-only: buffer, convex hull, or bounding box.", key="sdm_area_mode")
    c1, c2, c3 = st.columns(3)
    buffer_km = c1.number_input("Buffer radius for buffer / convex hull (km)", min_value=0.1, max_value=500.0, value=10.0, step=1.0, key="sdm_buffer_km")
    rectangle_margin_km = c2.number_input("Margin around bounding box (km)", min_value=0.0, max_value=500.0, value=20.0, step=5.0, key="sdm_rectangle_margin_km")
    exclusion_buffer_km = c3.number_input("Hard exclusion radius (km)", min_value=0.1, max_value=100.0, value=10.0, step=1.0, key="sdm_exclusion_cutout_km", help="Excluded records are removed from training and their surrounding area is physically cut out of the prediction extent.")
    excluded_occ = excluded_occurrences_from_ids(occ_raw, active_excluded_ids)
    extent_geom = prediction_area_geometry(occ, area_mode, float(buffer_km), float(rectangle_margin_km), excluded_occ, float(exclusion_buffer_km))
    if extent_geom is not None and not extent_geom.is_empty:
        minx, miny, maxx, maxy = extent_geom.bounds
        st.caption(f"Current SDM input: {len(occ):,} blue included records after thinning; {len(active_excluded_ids):,} excluded records removed and hard-masked. Extent bounds: lon {minx:.4f} to {maxx:.4f}, lat {miny:.4f} to {maxy:.4f}.")
        st_folium(
            make_sdm_extent_preview_map(occ, extent_geom, area_mode),
            width=None,
            height=460,
            returned_objects=[],
            key=f"sdm_extent_preview_map_{area_mode}",
        )

    st.subheader("SDM settings")
    with st.expander("Build SDM and predict map", expanded=True):
        resolution = st.selectbox("WorldClim raster resolution", RESOLUTIONS, index=2)
        st.caption(f"Selected resolution: {RESOLUTION_NOTE[resolution]}")
        st.markdown("<span style='color:#8c510a;font-weight:700'>Topography variables</span>", unsafe_allow_html=True)
        topo_vars = st.multiselect("Topography variables", TOPOGRAPHY_VARS, default=[])
        st.markdown("<span style='color:#2166ac;font-weight:700'>Climate variables</span>", unsafe_allow_html=True)
        climate_vars = st.multiselect("Climate variables", CLIMATE_VARS, default=[])
        variables = topo_vars + climate_vars
        use_vif = st.checkbox("Apply VIF stepwise filtering", value=True)
        vif_threshold = st.number_input("VIF threshold", min_value=1.0, max_value=100.0, value=10.0, step=1.0)
        st.caption("VIF filtering is vifstep-like: repeatedly calculate VIF, remove the variable with the highest VIF above the threshold, and refit until all remaining variables pass.")
        algorithms = st.multiselect("Ensemble algorithms", ALGORITHMS, default=[])
        partition_method = st.selectbox("Spatial partition method for AUC", PARTITION_METHODS, index=2)
        k_folds = st.number_input("k for random k-fold", min_value=2, max_value=20, value=5, step=1)
        checkerboard_deg = st.number_input("Checkerboard cell size (degrees)", min_value=0.001, max_value=5.0, value=0.05, step=0.01, format="%.3f")
        n_background = st.number_input("Number of land-only background points", 100, 20_000, 500, 100)
        max_pixels = st.number_input("Maximum predict-map pixels", 2_000, 500_000, 80_000, 10_000)
        st.caption("buffer = around each occurrence point; convex hull = polygon around records; bounding box = latitude/longitude rectangle around records. All are clipped to land.")
        run_sdm = st.button("Build SDM and predict map", type="primary")

    status = st.empty()
    if run_sdm:
        if not variables:
            st.warning("Select at least one environmental variable.")
        elif not algorithms:
            st.warning("Select at least one algorithm.")
        elif extent_geom is None or extent_geom.is_empty:
            st.error("The SDM prediction extent is empty after red-point cutouts. SDM was stopped.")
        elif set(occ["_row_id"].astype(int)).intersection(active_excluded_ids):
            st.error("Excluded row IDs are still present in the SDM input. SDM was stopped to prevent using excluded occurrences.")
        else:
            try:
                progress = st.progress(0.0)
                status.write("Generating presence/background data...")
                pb = build_presence_background(occ, int(n_background), area_mode, float(buffer_km), float(rectangle_margin_km), excluded_occ, float(exclusion_buffer_km), status)
                progress.progress(0.15)
                status.write("Extracting environmental variables for training data...")
                train = extract_environment(pb, variables, "latitude", "longitude", resolution, status)
                if "occurrence_row_id" in train.columns:
                    train_presence_ids = set(pd.to_numeric(train.loc[train["presence"].eq(1), "occurrence_row_id"], errors="coerce").dropna().astype(int))
                    leaked_train_ids = sorted(train_presence_ids.intersection(active_excluded_ids))
                    if leaked_train_ids:
                        raise RuntimeError(f"Excluded rows reached the SDM training table: {leaked_train_ids[:20]}")
                progress.progress(0.35)
                if use_vif:
                    status.write(f"Running VIF stepwise filtering with threshold {vif_threshold}...")
                    kept_vars, vif_tbl = vif_step(train, variables, float(vif_threshold))
                else:
                    kept_vars = variables
                    vif_tbl = compute_vif_table(train, variables)
                    if "status" not in vif_tbl.columns:
                        vif_tbl["status"] = "kept"
                if not kept_vars:
                    raise RuntimeError("No environmental variables remained after VIF filtering.")
                progress.progress(0.50)
                status.write(f"Fitting ensemble SDM with {partition_method} partition...")
                sdm_result = fit_sdm(train, kept_vars, algorithms, partition_method, int(k_folds), float(checkerboard_deg))
                progress.progress(0.70)
                status.write("Predicting raster-style suitability map...")
                overlay, pred_table = build_predict_map(occ, kept_vars, resolution, sdm_result, area_mode, float(buffer_km), float(rectangle_margin_km), int(max_pixels), excluded_occ, float(exclusion_buffer_km), status)
                st.session_state.sdm_result = sdm_result
                st.session_state.sdm_train_table = sdm_result.get("training_table", train)
                st.session_state.prediction_overlay = overlay
                st.session_state.prediction_table = pred_table
                st.session_state.vif_table = vif_tbl
                st.session_state.sdm_occurrence_row_ids = current_sdm_occurrence_row_ids
                progress.progress(1.0)
                status.write("SDM complete.")
            except Exception as exc:
                st.error(f"SDM failed: {exc}")

    all_candidates = occurrence_candidates.copy()
    sdm_result = st.session_state.sdm_result
    pred_table = st.session_state.prediction_table
    overlay = st.session_state.prediction_overlay
    env_train = st.session_state.sdm_train_table
    vif_table = st.session_state.vif_table

    if sdm_result is not None and st.session_state.sdm_occurrence_row_ids != current_sdm_occurrence_row_ids:
        reset_model_outputs()
        sdm_result = pred_table = overlay = env_train = vif_table = None
        st.warning("Stored SDM did not match the currently included occurrence row IDs, so it was discarded. Rebuild SDM to use only the remaining non-excluded points.")

    if vif_table is not None:
        st.write("VIF table")
        st.dataframe(vif_table, width="stretch", hide_index=True)

    if sdm_result is not None:
        st.success("SDM predict map is available.")
        st.caption(f"SDM training presence rows: {len(current_sdm_occurrence_row_ids)} included occurrence records; excluded row IDs are not used.")
        if overlay is not None:
            st.caption(f"Predict map: R/terra-style raster grid prediction using {overlay.get('method', 'ensemble raster prediction')}; array={overlay.get('shape')} cells; stride={overlay.get('source_stride')}; suitability min/mean/max={overlay.get('min')}/{overlay.get('mean')}/{overlay.get('max')}")
        st.write("SDM metrics")
        st.dataframe(sdm_result["metrics"], width="stretch", hide_index=True)
        try:
            tmp = all_candidates.rename(columns={"latitude": "lat_tmp", "longitude": "lon_tmp"})
            tmp = extract_environment(tmp, sdm_result["variables"], "lat_tmp", "lon_tmp", resolution, status)
            all_candidates = tmp.rename(columns={"lat_tmp": "latitude", "lon_tmp": "longitude"})
            all_candidates = predict_suitability(all_candidates, sdm_result)
        except Exception as exc:
            st.warning(f"Could not predict suitability for occurrence-supported ranges: {exc}")
        with st.expander("Create SDM-high exploration ranges", expanded=True):
            c1, c2, c3, c4 = st.columns(4)
            min_suit = c1.number_input("Minimum suitability", 0.0, 1.0, 0.60, 0.05)
            q = c2.number_input("Predict-map quantile", 0.0, 0.99, 0.90, 0.01)
            min_dist = c3.number_input("Min distance from known records/ranges (m)", 0, 200_000, 3000, 500)
            max_new = c4.number_input("Max new ranges", 1, 200, 20, 1)
            explore_cluster_m = st.number_input("Exploration clustering distance (m)", 100, 200_000, 3000, 500)
            exploration = make_sdm_exploration_candidates(pred_table, occ, all_candidates, float(min_suit), float(q), float(min_dist), float(explore_cluster_m), int(max_new), int(all_candidates["site_id"].max()) + 1 if not all_candidates.empty else 1)
        if not exploration.empty:
            all_candidates = pd.concat([all_candidates, exploration], ignore_index=True, sort=False)

    all_candidates = filter_to_land(all_candidates, "latitude", "longitude", float(survey_range_m)) if not all_candidates.empty else all_candidates
    all_candidates = add_priority_rank(all_candidates)
    all_candidates = order_sites(all_candidates, "Nearest-neighbor route")
    route_plan = route_planner_panel(all_candidates)

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Raw valid records", f"{len(occ_raw):,}")
    c2.metric("After exclusion", f"{len(occ_checked):,}")
    c3.metric("After thinning", f"{len(occ):,}")
    c4.metric("Occurrence clusters", f"{int((occ['cluster_id'] >= 0).sum()):,}")
    c5.metric("Survey ranges", f"{len(all_candidates):,}")
    c6.metric("Route stops", f"{len(route_plan):,}" if route_plan is not None else "0")

    fmap = build_map(occ, all_candidates, overlay, route_plan, 0.0, float(survey_range_m), layers)
    st_folium(fmap, width=None, height=720, returned_objects=[], key="main_map")

    html_bytes = fmap.get_root().render().encode("utf-8")

    st.subheader("Downloads")
    st.download_button("Download sampling HTML map", html_bytes, "fieldmap.html", "text/html", width="stretch")


if __name__ == "__main__":
    main()
