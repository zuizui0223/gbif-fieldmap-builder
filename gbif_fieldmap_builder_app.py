"""
ACSP — Adaptive Complementarity-based Survey Prioritization

Streamlit app for field-survey planning from GBIF records or a coordinate CSV.

Features:
- GBIF page-by-page download. GBIF returns max 300 records per request; the app repeats requests until the selected cap or endOfRecords.
- Rectangle-based coordinate QC exclusion before candidate generation and optional SDM/SSDM.
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
import time
import urllib.parse
import zipfile
import hashlib
import json
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
from rasterio.warp import transform as rio_transform
from shapely.geometry import MultiPoint, Point, box, shape
from shapely.ops import unary_union
from sklearn.cluster import DBSCAN
from sklearn.ensemble import ExtraTreesClassifier, GradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LinearRegression, LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedKFold, train_test_split
from sklearn.neighbors import BallTree
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from streamlit_folium import st_folium

from acsp_discover import (
    PLAN_ORDER as ACSP_DISCOVER_PLAN_ORDER,
    apply_hard_constraints as apply_discover_hard_constraints,
    build_acsp_discover_plans,
    choose_candidate_resolution,
    infer_default_survey_scope,
    infer_survey_protocol,
    parse_field_results,
    preferred_survey_window,
    recommend_survey_regions,
    summarize_plan as summarize_discover_plan,
)

APP_TITLE = "ACSP — Adaptive Complementarity-based Survey Prioritization"
APP_BUILD_ID = "acsp-discover-hierarchy-v1-20260627"
EARTH_RADIUS_M = 6_371_008.8
ENV_SENTINEL_ABS = 1e20
GBIF_SPECIES_MATCH_URL = "https://api.gbif.org/v1/species/match"
GBIF_SPECIES_SEARCH_URL = "https://api.gbif.org/v1/species/search"
GBIF_OCCURRENCE_SEARCH_URL = "https://api.gbif.org/v1/occurrence/search"
GBIF_REQUEST_HEADERS = {"User-Agent": "GBIF-FieldMap-Builder/1.0"}
WC_BASE = "https://geodata.ucdavis.edu/climate/worldclim/2_1/base"
LAND_GEOJSON_URL = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_land.geojson"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
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

def gbif_get_json(url: str, params: dict[str, Any], timeout: int, attempts: int = 4) -> dict[str, Any]:
    last_error: Optional[Exception] = None
    total_attempts = max(1, int(attempts))
    for attempt in range(total_attempts):
        try:
            response = requests.get(url, params=params, timeout=timeout, headers=GBIF_REQUEST_HEADERS)
            if response.status_code in {429, 500, 502, 503, 504} and attempt < total_attempts - 1:
                last_error = requests.HTTPError(f"GBIF temporary HTTP {response.status_code}", response=response)
            else:
                response.raise_for_status()
                return response.json()
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
        if attempt < total_attempts - 1:
            time.sleep(min(8.0, 1.5 * (2 ** attempt)))
    raise RuntimeError(f"GBIF request failed after {total_attempts} attempts: {last_error}")


TOPOGRAPHY_VARS = ["elevation", "slope", "aspect", "roughness", "tpi"]
CLIMATE_VARS = [f"bio{i}" for i in range(1, 20)]
SUPPORTED_ENV_VARS = TOPOGRAPHY_VARS + CLIMATE_VARS
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
ECOLOGICAL_PRESET_VARS = ["elevation", "slope", "roughness", "bio1", "bio4", "bio12", "bio15"]
# Balanced ecology preset: 6 interpretable variables covering key ecological gradients.
# bio1 = Annual Mean Temperature (temperature level)
# bio4 = Temperature Seasonality (temperature variation)
# bio12 = Annual Precipitation (precipitation amount)
# bio15 = Precipitation Seasonality (precipitation variation)
# bio14 = Precipitation of Driest Month (dryness / dry-month limitation)
# elevation = terrain (topography)
BALANCED_ECOLOGY_PRESET = ["bio1", "bio4", "bio12", "bio15", "bio14", "elevation"]
POTENTIAL_ANALOGUE_PRESET = ["elevation", "slope", "aspect", "roughness", "tpi"]
FAST_MAP_RECORDS = 500
FAST_CANDIDATE_RECORDS = 800
FAST_SDM_RECORDS = 300
FAST_SSDM_RECORDS_PER_SPECIES = 150
FAST_SPECIES_GBIF_FETCH_CAP = 10_000   # fetch all records for most species (GBIF paginates 300/request)
FAST_GENUS_GBIF_FETCH_CAP = 3_000


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


# ── Phenology / flowering-season helpers ──────────────────────────────────────

def parse_occurrence_month_doy(row: dict) -> tuple[Optional[int], Optional[int]]:
    """Return (month, day_of_year) from occurrence row fields. Returns (None, None) if unparseable."""
    # Try eventDate first
    for date_field in ["eventDate", "_event_date", "event_date"]:
        val = row.get(date_field)
        if val and str(val) not in ("", "nan", "NaT"):
            try:
                dt = pd.to_datetime(str(val), errors="coerce")
                if pd.notna(dt):
                    return int(dt.month), int(dt.day_of_year)
            except Exception:
                pass
    # Fallback: year/month/day fields
    try:
        m = row.get("month") or row.get("_month")
        if m and str(m) not in ("", "nan"):
            month = int(float(str(m)))
            if 1 <= month <= 12:
                d = row.get("day") or row.get("_day")
                if d and str(d) not in ("", "nan"):
                    try:
                        import datetime
                        day = int(float(str(d)))
                        y = int(row.get("year") or row.get("_year") or 2000)
                        doy = datetime.date(y, month, day).timetuple().tm_yday
                        return month, doy
                    except Exception:
                        pass
                # month known, day unknown: estimate mid-month
                return month, (month - 1) * 30 + 15
    except Exception:
        pass
    # startDayOfYear
    try:
        sdoy = row.get("startDayOfYear")
        if sdoy and str(sdoy) not in ("", "nan"):
            doy = int(float(str(sdoy)))
            if 1 <= doy <= 366:
                import datetime
                dt2 = datetime.datetime(2000, 1, 1) + datetime.timedelta(days=doy - 1)
                return dt2.month, doy
    except Exception:
        pass
    return None, None


_FLOWERING_KW = {"flowering", "flower", "in bloom", "bloom", "floral", "anthesis", "開花", "花"}
_FRUITING_KW = {"fruiting", "fruit-bearing", "fruit", "seed", "結実", "果実"}
_VEG_KW = {"vegetative", "sterile", "non-reproductive", "seedling"}


def infer_phenology_state(row: dict) -> str:
    """Return 'flowering' | 'fruiting' | 'vegetative_or_nonreproductive' | 'unknown'."""
    text_fields = ["lifeStage", "reproductiveCondition", "occurrenceRemarks",
                   "fieldNotes", "dynamicProperties"]
    combined = " ".join(str(row.get(f, "")) for f in text_fields).lower()
    if not combined.strip():
        return "unknown"
    for kw in _FLOWERING_KW:
        if kw in combined:
            return "flowering"
    for kw in _FRUITING_KW:
        if kw in combined:
            return "fruiting"
    for kw in _VEG_KW:
        if kw in combined:
            return "vegetative_or_nonreproductive"
    return "unknown"


def enrich_occurrences_with_phenology(occ: pd.DataFrame) -> pd.DataFrame:
    """Add _month, _doy, _phenology_state columns to occurrence DataFrame in-place copy."""
    if occ.empty:
        return occ.copy()
    out = occ.copy()
    months, doys, states = [], [], []
    for row in out.to_dict("records"):
        m, d = parse_occurrence_month_doy(row)
        months.append(m)
        doys.append(d)
        states.append(infer_phenology_state(row))
    out["_obs_month"] = months
    out["_obs_doy"] = doys
    out["_phenology_state"] = states
    return out


def candidate_season_summary(candidate_occ: pd.DataFrame) -> dict:
    """Summarise flowering/phenology season for occurrences belonging to one candidate cluster.

    candidate_occ must have _obs_month, _obs_doy, _phenology_state columns.
    Returns a dict of summary fields.
    """
    result = {
        "observation_months": "",
        "observation_doy_median": np.nan,
        "observation_doy_iqr": np.nan,
        "flowering_record_count": 0,
        "flowering_months": "",
        "flowering_doy_median": np.nan,
        "recommended_survey_window": "unknown",
        "season_confidence": "low",
    }
    if candidate_occ.empty:
        return result
    # All records with known month
    dated = candidate_occ.dropna(subset=["_obs_month"])
    if dated.empty:
        return result
    months = sorted(dated["_obs_month"].dropna().astype(int).unique().tolist())
    result["observation_months"] = ", ".join(str(m) for m in months)
    doys = dated["_obs_doy"].dropna().astype(float).tolist()
    if doys:
        result["observation_doy_median"] = round(float(np.median(doys)), 1)
        result["observation_doy_iqr"] = round(float(np.percentile(doys, 75) - np.percentile(doys, 25)), 1)
    # Flowering records
    fl = dated[dated["_phenology_state"] == "flowering"]
    fl_count = len(fl)
    result["flowering_record_count"] = fl_count
    if fl_count > 0:
        fl_months = sorted(fl["_obs_month"].dropna().astype(int).unique().tolist())
        result["flowering_months"] = ", ".join(str(m) for m in fl_months)
        fl_doys = fl["_obs_doy"].dropna().astype(float).tolist()
        if fl_doys:
            result["flowering_doy_median"] = round(float(np.median(fl_doys)), 1)
        window_months = fl_months
        window_counts = fl["_obs_month"].value_counts().to_dict()
        confidence = "high" if fl_count >= 5 else "medium" if fl_count >= 2 else "low"
    else:
        window_months = months
        window_counts = dated["_obs_month"].value_counts().to_dict()
        confidence = "medium" if len(dated) >= 5 else "low"
        result["flowering_months"] = ""
    if window_months:
        result["recommended_survey_window"] = _months_to_window_str(window_months, counts=window_counts)
    result["season_confidence"] = confidence
    return result


def _months_to_window_str(months: list, counts: Optional[dict] = None) -> str:
    """Convert month list to a compact human-readable peak window like 'May–Aug'.

    When counts (month → n_records) are provided, the window is derived from the
    central 80 % of observations (10th–90th percentile by cumulative record count),
    so outlier months with very few records do not widen the window artificially.
    Without counts, falls back to first–last month.
    """
    _MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    if not months:
        return "unknown"
    months_s = sorted(set(int(m) for m in months if 1 <= int(m) <= 12))
    if len(months_s) == 1:
        return _MONTH_ABBR[months_s[0] - 1]
    if counts:
        max_count = max((counts.get(m, 0) for m in months_s), default=0)
        if max_count > 0:
            # Include months where record count is ≥ 15 % of the peak month
            threshold = max_count * 0.15
            peak_months = [m for m in months_s if counts.get(m, 0) >= threshold]
            if peak_months:
                return f"{_MONTH_ABBR[peak_months[0] - 1]}–{_MONTH_ABBR[peak_months[-1] - 1]}"
    return f"{_MONTH_ABBR[months_s[0] - 1]}–{_MONTH_ABBR[months_s[-1] - 1]}"


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
        "sdm_excluded_row_ids": set(),           # SDM-training-only suspicious-record exclusions
        "sdm_qc_click_sig": "",
        "sdm_occurrence_row_ids": None,
        "selected_route_site_ids": [],
        "last_route_click_signature": "",
        "survey_day_lists": {1: [], 2: []},
        "survey_day_count": 2,
        "sl_selected_site_ids": [],
        "sl_last_draw_sig": "",
        "sl_reset_token": 0,
        "target_map_reset_token": 0,
        "qc_rect_selected_ids": [],
        "qc_rect_features": [],
        "qc_last_draw_sig": "",
        "qc_map_reset_token": 0,
        "target_rect_features": [],
        "target_last_draw_sig": "",
        "genus_target_rect_features": [],
        "genus_target_last_draw_sig": "",
        "genus_target_map_reset_token": 0,
        "genus_raw_df": None,
        "genus_source_key": None,
        "genus_source_message": "No genus occurrence data loaded yet.",
        "genus_selected_site_ids": [],
        "genus_last_click_signature": "",
        "genus_last_draw_sig": "",
        "genus_selection_map_reset_token": 0,
        "genus_ssdm_grid": None,
        "genus_ssdm_hotspots": None,
        "genus_ssdm_shape": None,
        "genus_ssdm_bounds": None,
        "genus_ssdm_model_summary": None,
        "_last_analysis_mode": None,
        "acsp_result_species": None,
        "acsp_result_genus": None,
        "acsp_discover_plans": None,
        "acsp_discover_constraint_audit": None,
        "acsp_discover_pool_signature": None,
        "potential_survey_candidates": None,
        "automatic_discover_bundle": None,
        "automatic_discover_query": None,
        "automatic_region_draw_features": [],
        "automatic_region_map_reset_token": 0,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def clear_loaded_data() -> None:
    for key in ["raw_df", "source_key", "sdm_result", "sdm_train_table", "prediction_table", "prediction_overlay", "vif_table", "sdm_occurrence_row_ids"]:
        st.session_state[key] = None
    st.session_state.excluded_row_ids = set()
    st.session_state.last_exclude_click_signature = ""
    st.session_state.selected_route_site_ids = []
    st.session_state.last_route_click_signature = ""
    st.session_state.survey_day_lists = {1: [], 2: []}
    st.session_state.survey_day_count = 2
    st.session_state.sl_selected_site_ids = []
    st.session_state.sl_last_draw_sig = ""
    st.session_state.sl_reset_token = st.session_state.get("sl_reset_token", 0) + 1
    st.session_state.qc_rect_selected_ids = []
    st.session_state.qc_rect_features = []
    st.session_state.qc_last_draw_sig = ""
    st.session_state.target_rect_features = []
    st.session_state.target_last_draw_sig = ""
    st.session_state.target_map_reset_token = st.session_state.get("target_map_reset_token", 0) + 1
    st.session_state.potential_survey_candidates = None
    st.session_state.acsp_discover_plans = None
    st.session_state.acsp_discover_constraint_audit = None
    st.session_state.acsp_discover_pool_signature = None
    st.session_state.acsp_result_species = None
    st.session_state.source_message = "No occurrence data loaded yet."


def clear_genus_data() -> None:
    st.session_state.genus_raw_df = None
    st.session_state.genus_source_key = None
    st.session_state.genus_source_message = "No genus occurrence data loaded yet."
    st.session_state.genus_selected_site_ids = []
    st.session_state.genus_last_click_signature = ""
    st.session_state.genus_last_draw_sig = ""
    st.session_state.genus_selection_map_reset_token = st.session_state.get("genus_selection_map_reset_token", 0) + 1
    st.session_state.genus_target_map_reset_token = st.session_state.get("genus_target_map_reset_token", 0) + 1
    st.session_state.genus_ssdm_grid = None
    st.session_state.genus_ssdm_hotspots = None
    st.session_state.genus_ssdm_shape = None
    st.session_state.genus_ssdm_bounds = None
    st.session_state.excluded_row_ids = set()
    st.session_state.qc_rect_selected_ids = []
    st.session_state.qc_rect_features = []
    st.session_state.qc_last_draw_sig = ""
    st.session_state.genus_target_rect_features = []
    st.session_state.genus_target_last_draw_sig = ""


def reset_model_outputs() -> None:
    for key in ["sdm_result", "sdm_train_table", "prediction_table", "prediction_overlay", "vif_table", "sdm_occurrence_row_ids"]:
        st.session_state[key] = None
    st.session_state.acsp_discover_plans = None
    st.session_state.acsp_discover_constraint_audit = None
    st.session_state.acsp_discover_pool_signature = None


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
    uncertainty_col = detect_column(
        list(out.columns),
        ["coordinateUncertaintyInMeters", "coordinate_uncertainty_m", "coordinate uncertainty meters", "座標精度m"],
    )
    out["_coordinate_uncertainty_m"] = pd.to_numeric(out[uncertainty_col], errors="coerce") if uncertainty_col else np.nan
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


def gbif_occurrence_params(taxon_key: int, country_code: str, year_from: Optional[int], year_to: Optional[int]) -> dict[str, Any]:
    params_base: dict[str, Any] = {"taxonKey": taxon_key, "hasCoordinate": "true", "hasGeospatialIssue": "false"}
    if country_code.strip():
        params_base["country"] = country_code.strip().upper()
    if year_from is not None and year_to is not None:
        params_base["year"] = f"{int(year_from)},{int(year_to)}"
    elif year_from is not None:
        params_base["year"] = f"{int(year_from)},"
    elif year_to is not None:
        params_base["year"] = f",{int(year_to)}"

    return params_base


def gbif_representative_offsets(total_count: int, target: int, page_size: int = 300) -> list[int]:
    if total_count <= 0 or target <= 0:
        return []
    n_pages = max(1, int(math.ceil(target / page_size)))
    if total_count <= target:
        return [i * page_size for i in range(n_pages)]
    max_offset = max(0, total_count - page_size)
    offsets = np.linspace(0, max_offset, n_pages)
    out = sorted({int(round(float(offset) / page_size) * page_size) for offset in offsets})
    return [min(offset, max_offset) for offset in out]


def gbif_record_to_species_row(rec: dict[str, Any]) -> dict[str, Any]:
    return {
        "decimalLatitude": rec.get("decimalLatitude"),
        "decimalLongitude": rec.get("decimalLongitude"),
        "eventDate": rec.get("eventDate", ""),
        "year": rec.get("year"),
        "species": rec.get("species") or rec.get("scientificName", ""),
        "scientificName": rec.get("scientificName", ""),
        "basisOfRecord": rec.get("basisOfRecord", ""),
        "countryCode": rec.get("countryCode", ""),
        "locality": rec.get("locality", ""),
        "coordinateUncertaintyInMeters": rec.get("coordinateUncertaintyInMeters"),
        "gbifID": rec.get("gbifID") or rec.get("key"),
        "media_url": extract_media_url_from_gbif_record(rec),
    }


def gbif_record_to_genus_row(rec: dict[str, Any]) -> dict[str, Any]:
    return {
        "decimalLatitude": rec.get("decimalLatitude"),
        "decimalLongitude": rec.get("decimalLongitude"),
        "eventDate": rec.get("eventDate", ""),
        "year": rec.get("year"),
        "species": _species_name_from_genus_record(rec),
        "scientificName": rec.get("scientificName", ""),
        "genus": rec.get("genus", ""),
        "basisOfRecord": rec.get("basisOfRecord", ""),
        "countryCode": rec.get("countryCode", ""),
        "locality": rec.get("locality", ""),
        "coordinateUncertaintyInMeters": rec.get("coordinateUncertaintyInMeters"),
        "gbifID": rec.get("gbifID") or rec.get("key"),
        "media_url": extract_media_url_from_gbif_record(rec),
    }


def representative_row_cap(df: pd.DataFrame, target: int) -> pd.DataFrame:
    if df.empty or len(df) <= target:
        return df.reset_index(drop=True)
    work = df.copy()
    work["_latitude"] = pd.to_numeric(work["decimalLatitude"], errors="coerce")
    work["_longitude"] = pd.to_numeric(work["decimalLongitude"], errors="coerce")
    work["_year"] = pd.to_numeric(work.get("year"), errors="coerce")
    work["_row_id"] = np.arange(len(work), dtype=int)
    work = work.dropna(subset=["_latitude", "_longitude"]).copy()
    capped = spatially_balanced_cap(work, int(target))
    keep_ids = set(capped["_row_id"].astype(int))
    return df.iloc[[i for i in range(len(df)) if i in keep_ids]].reset_index(drop=True)


def fetch_gbif_records_representative(params_base: dict[str, Any], max_records: int, total_count: int, timeout: int) -> tuple[list[dict[str, Any]], str]:
    target = min(int(max_records), int(total_count) if total_count > 0 else int(max_records))
    records: list[dict[str, Any]] = []
    offsets = gbif_representative_offsets(total_count, target, 300)
    retrieval = "sequential pages" if total_count <= target else "representative evenly spaced GBIF offsets"
    completed_pages = 0
    failed_pages = 0
    last_error: Optional[Exception] = None
    for offset in offsets:
        if len(records) >= target:
            break
        limit = min(300, target - len(records))
        try:
            page = gbif_get_json(GBIF_OCCURRENCE_SEARCH_URL, {**params_base, "offset": offset, "limit": limit}, timeout=timeout)
            completed_pages += 1
        except Exception as exc:
            failed_pages += 1
            last_error = exc
            continue
        batch = page.get("results", [])
        if not batch:
            continue
        records.extend(batch)
        if page.get("endOfRecords") and total_count <= target:
            break
    if not records and last_error is not None:
        raise last_error
    if failed_pages:
        retrieval += f"; partial resilient retrieval ({completed_pages} pages completed, {failed_pages} failed)"
    return records[:target], retrieval


@st.cache_data(show_spinner=False, ttl=3600)
def gbif_species_count_cached(scientific_name: str, country_code: str, year_from: Optional[int], year_to: Optional[int]) -> tuple[dict[str, Any], int, dict[str, Any]]:
    payload = gbif_get_json(GBIF_SPECIES_MATCH_URL, {"name": scientific_name.strip()}, timeout=30)
    usage_key = payload.get("usageKey")
    if usage_key is None:
        raise ValueError(f"GBIF could not match this scientific name: {scientific_name}")
    params_base = gbif_occurrence_params(int(usage_key), country_code, year_from, year_to)
    first = gbif_get_json(GBIF_OCCURRENCE_SEARCH_URL, {**params_base, "limit": 0, "offset": 0}, timeout=60)
    return payload, int(first.get("count", 0)), params_base


@st.cache_data(show_spinner=False, ttl=3600)
def fetch_gbif_occurrences_cached(scientific_name: str, max_records: int, country_code: str, year_from: Optional[int], year_to: Optional[int]) -> tuple[str, pd.DataFrame]:
    payload, total_count, params_base = gbif_species_count_cached(scientific_name, country_code, year_from, year_to)
    usage_key = payload.get("usageKey")
    records, retrieval = fetch_gbif_records_representative(params_base, int(max_records), int(total_count), timeout=60)

    df = _dedup_and_cap(pd.DataFrame([gbif_record_to_species_row(rec) for rec in records]), int(max_records))
    msg = f"GBIF match: {payload.get('scientificName', scientific_name)} / usageKey={usage_key} / confidence={payload.get('confidence')}. GBIF total coordinate records={total_count:,}; requested fetch cap={int(max_records):,}; actual fetched records={len(df):,}; retrieval={retrieval}."
    rows = df.to_dict("records") if not df.empty else []
    return msg, pd.DataFrame(rows)


def _dedup_and_cap(df: pd.DataFrame, max_records: int, extra_dedup_keys: Optional[list[str]] = None) -> pd.DataFrame:
    """Shared post-fetch deduplication and representative cap for GBIF DataFrames."""
    if df.empty:
        return df
    with_id = df[df["gbifID"].notna() & df["gbifID"].astype(str).ne("")]
    without_id = df[~(df["gbifID"].notna() & df["gbifID"].astype(str).ne(""))]
    df = pd.concat([with_id.drop_duplicates(subset=["gbifID"], keep="first"), without_id], ignore_index=True, sort=False)
    coord_keys = ["decimalLatitude", "decimalLongitude", "year"] + (extra_dedup_keys or [])
    df = df.drop_duplicates(subset=coord_keys, keep="first")
    return representative_row_cap(df, int(max_records))


def _species_name_from_genus_record(rec: dict[str, Any]) -> str:
    species = rec.get("species") or rec.get("acceptedScientificName") or ""
    species = str(species).strip()
    if species:
        return species
    genus = str(rec.get("genus") or "").strip()
    epithet = str(rec.get("specificEpithet") or "").strip()
    if genus and epithet:
        return f"{genus} {epithet}"
    return str(rec.get("scientificName") or "").strip()


def _resolve_gbif_genus_key(genus_name: str) -> tuple[Optional[int], dict[str, Any]]:
    genus = genus_name.strip()
    if not genus:
        return None, {}
    payload = gbif_get_json(GBIF_SPECIES_MATCH_URL, {"name": genus, "rank": "GENUS"}, timeout=20)
    canonical = str(payload.get("canonicalName") or payload.get("genus") or "").strip()
    if payload.get("rank") == "GENUS" and payload.get("usageKey") and canonical.lower() == genus.lower():
        return int(payload["usageKey"]), payload

    search_payload = gbif_get_json(GBIF_SPECIES_SEARCH_URL, {"q": genus, "rank": "GENUS", "limit": 10}, timeout=20)
    for candidate in search_payload.get("results", []):
        canonical = str(candidate.get("canonicalName") or candidate.get("scientificName") or "").strip()
        if canonical.lower() == genus.lower() and candidate.get("rank") == "GENUS" and (candidate.get("nubKey") or candidate.get("key")):
            payload = dict(candidate)
            payload.setdefault("scientificName", canonical)
            payload.setdefault("rank", "GENUS")
            payload["gbifBackboneKey"] = candidate.get("nubKey") or candidate.get("key")
            return int(payload["gbifBackboneKey"]), payload
    for candidate in search_payload.get("results", []):
        if candidate.get("rank") == "GENUS" and (candidate.get("nubKey") or candidate.get("key")):
            payload = dict(candidate)
            payload.setdefault("rank", "GENUS")
            payload["gbifBackboneKey"] = candidate.get("nubKey") or candidate.get("key")
            return int(payload["gbifBackboneKey"]), payload
    return None, {}


@st.cache_data(show_spinner=False, ttl=3600)
def gbif_genus_count_cached(genus_name: str, country_code: str, year_from: Optional[int], year_to: Optional[int]) -> tuple[dict[str, Any], int, dict[str, Any], int]:
    usage_key, payload = _resolve_gbif_genus_key(genus_name)
    if usage_key is None:
        raise ValueError(f"GBIF could not match this genus name: {genus_name}")
    params_base = gbif_occurrence_params(int(usage_key), country_code, year_from, year_to)
    first = gbif_get_json(GBIF_OCCURRENCE_SEARCH_URL, {**params_base, "limit": 0, "offset": 0}, timeout=45)
    return payload, int(first.get("count", 0)), params_base, int(usage_key)


GENUS_OCCURRENCE_COLUMNS = [
    "decimalLatitude",
    "decimalLongitude",
    "eventDate",
    "year",
    "species",
    "scientificName",
    "genus",
    "basisOfRecord",
    "countryCode",
    "locality",
    "gbifID",
    "media_url",
]


def genus_records_to_dataframe(records: list[dict[str, Any]], max_records: int) -> pd.DataFrame:
    raw_df = pd.DataFrame([gbif_record_to_genus_row(rec) for rec in records], columns=GENUS_OCCURRENCE_COLUMNS)
    df = _dedup_and_cap(raw_df, int(max_records), extra_dedup_keys=["species"])
    return pd.DataFrame(df.to_dict("records") if not df.empty else [], columns=GENUS_OCCURRENCE_COLUMNS)


@st.cache_data(show_spinner=False, ttl=3600)
def fetch_gbif_genus_occurrences_cached(genus_name: str, max_records: int, country_code: str, year_from: Optional[int], year_to: Optional[int]) -> tuple[str, pd.DataFrame]:
    payload, total_count, params_base, usage_key = gbif_genus_count_cached(genus_name, country_code, year_from, year_to)
    records, retrieval = fetch_gbif_records_representative(params_base, int(max_records), int(total_count), timeout=45)

    df = genus_records_to_dataframe(records, int(max_records))
    matched_name = payload.get("scientificName") or payload.get("canonicalName") or genus_name
    msg = f"GBIF genus match: {matched_name} / GBIF backbone taxonKey={usage_key} / rank={payload.get('rank', 'GENUS')}. GBIF total coordinate records={total_count:,}; requested fetch cap={int(max_records):,}; actual fetched records={len(df):,}; retrieval={retrieval}."
    return msg, df


def fetch_gbif_genus_occurrences_with_progress(genus_name: str, max_records: int, country_code: str, year_from: Optional[int], year_to: Optional[int]) -> tuple[str, pd.DataFrame, Optional[str]]:
    payload, total_count, params_base, usage_key = gbif_genus_count_cached(genus_name, country_code, year_from, year_to)
    target = min(int(max_records), int(total_count) if total_count > 0 else int(max_records))
    # High GBIF offsets can stall on Streamlit Cloud. For interactive genus planning,
    # keep downloads on low-offset pages, then rely on downstream spatial thinning.
    offsets = list(range(0, target, 300))
    planned_pages = len(offsets)
    retrieval = "fast low-offset interactive subset with downstream deduplication and spatial thinning"
    records: list[dict[str, Any]] = []
    warning: Optional[str] = None

    progress_bar = st.progress(0.0)
    status = st.empty()
    status.write(
        f"Fetching genus records: planned pages {planned_pages:,}; requested fetch cap {int(max_records):,}; received 0 records"
    )
    completed_pages = 0
    failed_offset: Optional[int] = None
    failed_stage = "initializing"
    for page_num, offset in enumerate(offsets, start=1):
        if len(records) >= target:
            break
        limit = min(300, target - len(records))
        failed_stage = f"page {page_num} / {planned_pages}"
        status.write(
            f"Fetching genus records: page {page_num:,} / {planned_pages:,}, "
            f"offset {offset:,}, received {len(records):,} records, requested fetch cap {int(max_records):,}"
        )
        try:
            page = gbif_get_json(
                GBIF_OCCURRENCE_SEARCH_URL,
                {**params_base, "offset": int(offset), "limit": int(limit)},
                timeout=8,
                attempts=1,
            )
        except Exception as exc:
            failed_offset = int(offset)
            warning = (
                f"GBIF genus download stopped during {failed_stage}; failed offset={failed_offset:,}; "
                f"records fetched so far={len(records):,}; requested fetch cap={int(max_records):,}; "
                f"partial data are being used. Error: {exc}"
            )
            break
        batch = page.get("results", [])
        if batch:
            records.extend(batch)
        completed_pages = page_num
        partial_df = genus_records_to_dataframe(records, int(max_records))
        st.session_state.genus_raw_df = partial_df
        st.session_state.genus_source_key = f"genus::{genus_name}::{country_code}::{max_records}::{year_from}::{year_to}::partial"
        st.session_state.genus_source_message = (
            f"Partial GBIF genus fetch in progress: pages completed={completed_pages:,}/{planned_pages:,}; "
            f"raw records received={len(records):,}; actual fetched records after deduplication={len(partial_df):,}; "
            f"requested fetch cap={int(max_records):,}."
        )
        progress_bar.progress(min(1.0, completed_pages / max(1, planned_pages)))
        status.write(
            f"Fetching genus records: page {page_num:,} / {planned_pages:,}, "
            f"offset {offset:,}, received {len(records):,} records, requested fetch cap {int(max_records):,}"
        )
        if page.get("endOfRecords") and total_count <= target:
            break

    df = genus_records_to_dataframe(records, int(max_records))
    matched_name = payload.get("scientificName") or payload.get("canonicalName") or genus_name
    partial_note = "; partial subset used after page failure" if warning else ""
    msg = (
        f"GBIF genus match: {matched_name} / GBIF backbone taxonKey={usage_key} / "
        f"rank={payload.get('rank', 'GENUS')}. GBIF total coordinate records={total_count:,}; "
        f"requested fetch cap={int(max_records):,}; pages completed={completed_pages:,}/{planned_pages:,}; "
        f"raw records received={len(records):,}; actual fetched records after deduplication={len(df):,}; "
        f"retrieval={retrieval}{partial_note}."
    )
    if warning:
        progress_bar.progress(min(1.0, completed_pages / max(1, planned_pages)))
        status.warning(warning)
    else:
        progress_bar.progress(1.0)
        status.success(
            f"Genus fetch complete: completed {completed_pages:,} / {planned_pages:,} pages; "
            f"received {len(records):,} records; stored {len(df):,} records after deduplication."
        )
    return msg, df, warning


def genus_species_summary(occ: pd.DataFrame, min_records_for_sdm: int, grid_deg: float) -> pd.DataFrame:
    columns = ["species", "n_records", "n_unique_grid_cells", "year_min", "year_max", "enough_records_for_future_sdm"]
    if occ.empty:
        return pd.DataFrame(columns=columns)
    work = occ.copy()
    work["_species_clean"] = work["_species"].apply(clean_species_label_for_genus_richness)
    work = work[work["_species_clean"].ne("")]
    if work.empty:
        return pd.DataFrame(columns=columns)
    cell = float(grid_deg)
    work["_grid_lon"] = np.floor(work["_longitude"].astype(float) / cell).astype(int)
    work["_grid_lat"] = np.floor(work["_latitude"].astype(float) / cell).astype(int)
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
            "enough_records_for_future_sdm": int(len(group)) >= int(min_records_for_sdm),
        })
    return pd.DataFrame(rows).sort_values(["n_records", "species"], ascending=[False, True]).reset_index(drop=True)


def occurrence_richness_grid(occ: pd.DataFrame, grid_deg: float, min_records_per_species_cell: int) -> pd.DataFrame:
    if occ.empty:
        return pd.DataFrame()
    work = occ.copy()
    work["_species_clean"] = work["_species"].apply(clean_species_label_for_genus_richness)
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
    max_metric = float(out[metric_col].max()) if not out.empty and float(out[metric_col].max()) > 0 else 1.0
    out.insert(0, "hotspot_rank", range(1, len(out) + 1))
    out["site_id"] = out["hotspot_rank"].astype(int)
    out["candidate_type"] = "Occurrence richness hotspot"
    out["n_occurrences"] = pd.to_numeric(out["record_count"], errors="coerce").fillna(0).astype(int)
    out["observed_species_richness"] = pd.to_numeric(out["species_richness"], errors="coerce").fillna(0).astype(int)
    out["ssdm_predicted_richness"] = np.nan
    out["occurrence_support_score"] = (pd.to_numeric(out[metric_col], errors="coerce").fillna(0.0) / max_metric).clip(0, 1).round(3)
    out["model_support_score"] = 0.0
    out["candidate_method"] = "Observed occurrence richness grid"
    out["selection_reason"] = f"High observed {metric_col.replace('_', ' ')} in the selected Step 2 survey area."
    out["bias_warning"] = "Occurrence-supported hotspot. Field validation is still required."
    out["google_maps_url"] = [make_google_maps_point_url(float(r["latitude"]), float(r["longitude"])) for _, r in out.iterrows()]
    return out.reset_index(drop=True)


@st.cache_data(show_spinner=False)
def build_genus_observed_outputs_cached(
    occ: pd.DataFrame,
    genus_candidate_records: int,
    min_records_for_sdm: int,
    grid_deg: float,
    min_records_cell: int,
    richness_metric: str,
    max_hotspots: int,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if occ.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    genus_base = genus_species_deduplicate(occ)
    candidate_input = spatially_balanced_cap(genus_species_grid_thin(genus_base, 0.05), int(genus_candidate_records))
    summary = genus_species_summary(occ, int(min_records_for_sdm), float(grid_deg))
    grid = occurrence_richness_grid(candidate_input, float(grid_deg), int(min_records_cell))
    hotspots = richness_hotspot_candidates(grid, richness_metric, int(max_hotspots)) if not grid.empty else pd.DataFrame()
    return candidate_input, summary, grid, hotspots


def richness_color(value: float, max_value: float) -> str:
    if max_value <= 0:
        return "#ffffcc"
    ratio = max(0.0, min(1.0, float(value) / float(max_value)))
    colors = ["#ffffcc", "#c2e699", "#78c679", "#31a354", "#006837"]
    return colors[min(len(colors) - 1, int(ratio * (len(colors) - 1)))]


def add_richness_legend(fmap: folium.Map, metric: str, max_value: float) -> None:
    """Add a yellow-green gradient legend for occurrence richness maps."""
    titles = {
        "Species richness": "Observed species richness",
        "Record count": "Occurrence record count",
        "Species with minimum records": "Species meeting min. records threshold",
    }
    title = titles.get(metric, "Observed species richness")
    note = "Based on GBIF occurrence records — not modeled suitability"
    legend = f"""
    <div style="position:fixed;bottom:28px;left:28px;z-index:9999;background:rgba(255,255,255,0.92);padding:10px 12px;border:1px solid #999;border-radius:4px;font-size:12px;color:#222;">
      <div style="font-weight:700;margin-bottom:6px;">{title}</div>
      <div style="width:180px;height:12px;background:linear-gradient(90deg,#ffffcc,#c2e699,#78c679,#31a354,#006837);"></div>
      <div style="display:flex;justify-content:space-between;width:180px;"><span>1</span><span>{max_value:.0f}</span></div>
      <div style="margin-top:5px;font-size:10px;color:#555;">{note}</div>
    </div>
    """
    fmap.get_root().html.add_child(folium.Element(legend))


def add_ssdm_richness_legend(fmap: folium.Map, value_col: str, min_val: float, max_val: float) -> None:
    """Add a legend for SSDM continuous or binary richness maps."""
    if value_col == "ssdm_binary_richness":
        title = "Predicted species richness"
        lo_label = "0"
        hi_label = f"{int(round(max_val))}"
        note = "Number of species with suitability above threshold"
    else:
        title = "Predicted richness (suitability sum)"
        lo_label = f"{min_val:.2f}"
        hi_label = f"{max_val:.2f}"
        note = "Sum of per-species suitability — not an integer species count"
    legend = f"""
    <div style="position:fixed;bottom:28px;left:28px;z-index:9999;background:rgba(255,255,255,0.92);padding:10px 12px;border:1px solid #999;border-radius:4px;font-size:12px;color:#222;">
      <div style="font-weight:700;margin-bottom:6px;">{title}</div>
      <div style="width:180px;height:12px;background:linear-gradient(90deg,#2c7bb6,#abd9e9,#ffffbf,#fdae61,#d7191c);"></div>
      <div style="display:flex;justify-content:space-between;width:180px;"><span>{lo_label}</span><span>{hi_label}</span></div>
      <div style="margin-top:5px;font-size:10px;color:#555;">{note}</div>
    </div>
    """
    fmap.get_root().html.add_child(folium.Element(legend))


def add_observed_richness_grid_layer(fmap: folium.Map, grid: pd.DataFrame, metric: str, *, name: Optional[str] = None, opacity: float = 0.38, show_legend: bool = True) -> None:
    """Add an observed occurrence-richness grid layer to an existing Folium map."""
    if grid is None or grid.empty:
        return
    metric_col = {"Species richness": "species_richness", "Record count": "record_count", "Species with minimum records": "species_with_min_records"}.get(metric, "species_richness")
    if metric_col not in grid.columns:
        return
    max_value = float(pd.to_numeric(grid[metric_col], errors="coerce").max()) if not grid.empty else 0.0
    fg_grid = FeatureGroup(name=name or f"observed richness grid: {metric}", show=True)
    for _, row in grid.iterrows():
        value = float(row.get(metric_col, 0.0))
        folium.Rectangle(
            bounds=[[row["lat_min"], row["lon_min"]], [row["lat_max"], row["lon_max"]]],
            color=richness_color(value, max_value),
            weight=1,
            fill=True,
            fill_color=richness_color(value, max_value),
            fill_opacity=opacity,
            popup=folium.Popup(
                f"<b>Observed richness grid cell</b><br>{metric}: {value:g}<br>Species richness: {int(row.get('species_richness', 0))}<br>Records: {int(row.get('record_count', 0))}<br>Species: {row.get('species_list', '')}",
                max_width=520,
            ),
            tooltip=f"{metric}: {value:g}",
        ).add_to(fg_grid)
    fg_grid.add_to(fmap)
    if show_legend:
        add_richness_legend(fmap, metric, max_value)


@st.cache_data(show_spinner=False)
def make_richness_map(grid: pd.DataFrame, hotspots: pd.DataFrame, metric: str) -> folium.Map:
    center = (float(grid["latitude"].mean()), float(grid["longitude"].mean())) if not grid.empty else (35.5, 135.5)
    fmap = Map(location=center, zoom_start=7, tiles="OpenStreetMap", control_scale=True)
    metric_col = {"Species richness": "species_richness", "Record count": "record_count", "Species with minimum records": "species_with_min_records"}.get(metric, "species_richness")
    max_value = float(grid[metric_col].max()) if not grid.empty else 0.0
    add_observed_richness_grid_layer(fmap, grid, metric, name=f"occurrence richness grid: {metric}", opacity=0.48)
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


@st.cache_data(show_spinner=False)
def make_genus_candidate_selection_map(grid: pd.DataFrame, candidates: pd.DataFrame, metric: str, selected_ids: Optional[tuple] = None, add_draw: bool = True, show_grid: bool = True) -> folium.Map:
    center = (float(grid["latitude"].mean()), float(grid["longitude"].mean())) if grid is not None and not grid.empty else (35.5, 135.5)
    fmap = Map(location=center, zoom_start=7, tiles="OpenStreetMap", control_scale=True)
    metric_col = {"Species richness": "species_richness", "Record count": "record_count", "Species with minimum records": "species_with_min_records"}.get(metric, "species_richness")
    max_value = float(grid[metric_col].max()) if grid is not None and not grid.empty and metric_col in grid.columns else 0.0
    if show_grid and grid is not None and not grid.empty:
        add_observed_richness_grid_layer(fmap, grid, metric, opacity=0.38, show_legend=False)
    selected_set = set(int(s) for s in (selected_ids or []))
    if candidates is not None and not candidates.empty:
        fg_hot = FeatureGroup(name="richness hotspot candidates", show=True)
        for _, row in candidates.iterrows():
            sid = int(row["site_id"])
            marker_radius, color = _priority_marker_style(row)
            ctype = str(row.get("candidate_type", ""))
            rank = row.get("priority_rank", "")
            rank_label = f"Rank {rank} | " if str(rank).strip() not in ("", "nan") else ""
            is_exploratory = ctype.lower().startswith("ssdm-high")
            tooltip_text = f"{rank_label}{ctype} | site {sid}"
            kwargs: dict[str, Any] = dict(
                radius=marker_radius,
                color=color,
                fill=True,
                fill_color=color,
                fill_opacity=0.88,
                weight=2,
                tooltip=tooltip_text,
                popup=folium.Popup(popup_html_site(row), max_width=460),
            )
            if is_exploratory:
                kwargs["dash_array"] = "10 5"
            loc = (float(row["latitude"]), float(row["longitude"]))
            folium.CircleMarker(loc, **kwargs).add_to(fg_hot)
            if sid in selected_set:
                folium.CircleMarker(loc, radius=marker_radius + 5, color="#00cc44", fill=False, weight=3, tooltip=f"SELECTED | site {sid}").add_to(fg_hot)
        fg_hot.add_to(fmap)
    if add_draw:
        Draw(export=False, draw_options={"rectangle": True, "polyline": False, "circle": False, "marker": False, "circlemarker": False, "polygon": False}, edit_options={"edit": False, "remove": True}).add_to(fmap)
    LayerControl(collapsed=True).add_to(fmap)
    try:
        lat_values: list[float] = []
        lon_values: list[float] = []
        if grid is not None and not grid.empty:
            lat_values.extend(pd.to_numeric(grid["latitude"], errors="coerce").dropna().tolist())
            lon_values.extend(pd.to_numeric(grid["longitude"], errors="coerce").dropna().tolist())
        if candidates is not None and not candidates.empty:
            lat_values.extend(pd.to_numeric(candidates["latitude"], errors="coerce").dropna().tolist())
            lon_values.extend(pd.to_numeric(candidates["longitude"], errors="coerce").dropna().tolist())
        if lat_values and lon_values:
            fmap.fit_bounds([[min(lat_values), min(lon_values)], [max(lat_values), max(lon_values)]], padding=(30, 30))
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


@st.cache_data(show_spinner=False)
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


def make_exclusion_review_map(occ_map_display: pd.DataFrame, excluded_ids: set[int], add_draw: bool = False, show_images: bool = True) -> folium.Map:
    center = (float(occ_map_display["_latitude"].mean()), float(occ_map_display["_longitude"].mean())) if not occ_map_display.empty else (35.5, 135.5)
    fmap = Map(location=center, zoom_start=7, tiles="OpenStreetMap", control_scale=True)
    fg_in = FeatureGroup(name="included occurrences", show=True)
    fg_ex = FeatureGroup(name="excluded occurrences", show=True)
    for _, row in occ_map_display.iterrows():
        rid = int(row["_row_id"])
        excluded = rid in excluded_ids
        color = "#d62728" if excluded else "#1f77b4"
        media_html = image_html(row.get("_media_url", "")) if show_images else ""
        html = f"""
        <b>{'Excluded' if excluded else 'Included'} occurrence</b><br>
        row_id: {rid}<br>
        lat/lon: {row['_latitude']:.6f}, {row['_longitude']:.6f}<br>
        locality: {row.get('_locality','')}<br>
        GBIF: {row.get('_gbif_id','')}
        {media_html}
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
        fmap.fit_bounds([[occ_map_display["_latitude"].min(), occ_map_display["_longitude"].min()], [occ_map_display["_latitude"].max(), occ_map_display["_longitude"].max()]], padding=(30, 30))
    except Exception:
        pass
    return fmap


def make_target_selection_map(occ_map_display: pd.DataFrame, richness_grid: Optional[pd.DataFrame] = None, richness_metric: str = "Species richness") -> folium.Map:
    center = (float(occ_map_display["_latitude"].mean()), float(occ_map_display["_longitude"].mean())) if not occ_map_display.empty else (35.5, 135.5)
    fmap = Map(location=center, zoom_start=7, tiles="OpenStreetMap", control_scale=True)
    if richness_grid is not None and not richness_grid.empty:
        add_observed_richness_grid_layer(
            fmap,
            richness_grid,
            richness_metric,
            name=f"observed richness grid: {richness_metric}",
            opacity=0.34,
        )
    fg = FeatureGroup(name="target selection occurrences", show=True)
    for _, row in occ_map_display.iterrows():
        rid = int(row["_row_id"])
        folium.CircleMarker(
            (row["_latitude"], row["_longitude"]),
            radius=4,
            color="#1f77b4",
            fill=True,
            fill_color="#1f77b4",
            fill_opacity=0.65,
            weight=1,
            tooltip=f"row {rid}",
        ).add_to(fg)
    fg.add_to(fmap)
    Draw(
        export=False,
        draw_options={"rectangle": True, "polyline": False, "circle": False, "marker": False, "circlemarker": False, "polygon": False},
        edit_options={"edit": False, "remove": True},
    ).add_to(fmap)
    LayerControl(collapsed=True).add_to(fmap)
    try:
        fmap.fit_bounds([[occ_map_display["_latitude"].min(), occ_map_display["_longitude"].min()], [occ_map_display["_latitude"].max(), occ_map_display["_longitude"].max()]], padding=(30, 30))
    except Exception:
        pass
    return fmap


def target_occurrence_set_panel(
    occ_base: pd.DataFrame,
    occ_map_display: pd.DataFrame,
    raw_record_count: int,
    key_prefix: str,
    label: str = "Survey area selection",
    show_map: bool = True,
    model_label: str = "SDM",
    allow_advanced_modes: bool = False,
    richness_grid: Optional[pd.DataFrame] = None,
    richness_metric: str = "Species richness",
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Survey area selection panel.

    Default behaviour (allow_advanced_modes=False):
    - No radio buttons shown.
    - Mode is always 'include rectangle' when a rectangle has been drawn.
    - When no rectangle is drawn, all cleaned records are used with an info message.

    Advanced mode (allow_advanced_modes=True):
    - Three radio options inside a collapsed expander: use all / include / exclude.
    """
    build_or_run = "Run" if model_label != "SDM" else "Build"
    caption_text = (
        f"{model_label} can predict across a wider macro-scale extent — "
        f"set that separately inside Optional: {build_or_run} {model_label}."
    )

    # ── Map (genus mode only; species mode reuses the Phase 1 map) ─────────────
    if show_map:
        if len(occ_map_display) < len(occ_base):
            st.caption(f"Showing {len(occ_map_display):,} of {len(occ_base):,} cleaned records on this map.")
        col_map, col_clear = st.columns([4, 1])
        with col_clear:
            if st.button("Clear target rectangle", key=f"{key_prefix}_clear_target_rect"):
                st.session_state[f"{key_prefix}_rect_features"] = []
                st.session_state[f"{key_prefix}_last_draw_sig"] = ""
                st.session_state[f"{key_prefix}_map_reset_token"] = st.session_state.get(f"{key_prefix}_map_reset_token", 0) + 1
                st.session_state.potential_survey_candidates = None
                reset_model_outputs()
                st.rerun()
        with col_map:
            draw_data = st_folium(
                make_target_selection_map(occ_map_display, richness_grid, richness_metric),
                width=None,
                height=420,
                returned_objects=["all_drawings", "last_active_drawing"],
                key=f"{key_prefix}_target_occurrence_map_{st.session_state.get(f'{key_prefix}_map_reset_token', 0)}",
            )
        raw_drawings = (draw_data or {}).get("all_drawings") or (draw_data or {}).get("last_active_drawing")
        features = extract_drawn_features(raw_drawings)
        if features:
            draw_sig = str(features)[:800]
            if draw_sig != st.session_state.get(f"{key_prefix}_last_draw_sig", ""):
                st.session_state[f"{key_prefix}_last_draw_sig"] = draw_sig
                st.session_state[f"{key_prefix}_rect_features"] = features
                st.session_state.potential_survey_candidates = None
                reset_model_outputs()

    # ── Retrieve stored rectangle ──────────────────────────────────────────────
    stored_features = st.session_state.get(f"{key_prefix}_rect_features", []) or []
    inside_ids = set(ids_inside_drawn_rectangles(occ_base, "_row_id", "_latitude", "_longitude", stored_features)) if stored_features else set()
    has_rectangle = bool(stored_features)

    # ── Mode determination ─────────────────────────────────────────────────────
    if allow_advanced_modes:
        survey_area_options = [
            "Use all remaining cleaned records",
            "Use only records inside drawn rectangle",
            "Exclude records inside drawn rectangle",
        ]
        survey_area_key = f"{key_prefix}_target_occurrence_mode"
        if st.session_state.get(survey_area_key) not in (None, *survey_area_options):
            st.session_state[survey_area_key] = survey_area_options[0]
        with st.expander("Advanced survey area mode", expanded=False):
            mode = st.radio(
                "Survey area",
                survey_area_options,
                index=0,
                horizontal=True,
                key=survey_area_key,
            )
    else:
        # Simple default: rectangle-include when drawn, all records otherwise
        if has_rectangle:
            mode = "Use only records inside drawn rectangle"
        else:
            mode = "Use all remaining cleaned records"
            st.info(
                "Draw a rectangle on the map above to set your survey area. "
                "Until then, all cleaned records are used."
            )

    # ── Apply mode ─────────────────────────────────────────────────────────────
    rectangle_excluded = 0
    if mode in ("Use all cleaned records", "Use all records", "Use all remaining cleaned records"):
        selected = occ_base.copy()
        rectangle_excluded = 0
    elif not has_rectangle:
        selected = occ_base.copy()
        rectangle_excluded = 0
    elif mode == "Use only records inside drawn rectangle":
        selected = occ_base[occ_base["_row_id"].astype(int).isin(inside_ids)].copy()
        rectangle_excluded = len(occ_base) - len(selected)
    else:
        selected = occ_base[~occ_base["_row_id"].astype(int).isin(inside_ids)].copy()
        rectangle_excluded = len(inside_ids)

    counts = {
        "raw_records": int(raw_record_count),
        "records_inside_rectangle": int(len(inside_ids)),
        "records_excluded_by_rectangle": int(rectangle_excluded),
        "active_target_records": int(len(selected)),
    }

    # ── Metrics ────────────────────────────────────────────────────────────────
    candidates_label = "Records used for hotspots" if model_label == "SSDM" else "Records used for candidates"
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Cleaned records", f"{counts['raw_records']:,}")
    m2.metric("Inside survey rectangle", f"{counts['records_inside_rectangle']:,}")
    m3.metric("Active target records", f"{counts['active_target_records']:,}")
    m4.metric(candidates_label, f"{len(selected):,}")

    st.caption(caption_text)
    return selected.reset_index(drop=True), counts


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


def coordinate_exclusion_panel(occ_raw: pd.DataFrame, occ_map_display: pd.DataFrame, show_images: bool) -> pd.DataFrame:
    """Click-to-exclude individual suspicious records.

    Rectangle-based geographic filtering is handled by the Target occurrence set
    selector (Use only inside rectangle / Exclude inside rectangle) and is NOT
    duplicated here.  This panel only supports point-click exclusion of
    individual records with clearly wrong coordinates (e.g. sea points,
    misidentified localities).
    """
    n_excl = len(set(st.session_state.excluded_row_ids))
    expander_label = (
        f"Advanced: exclude individual suspicious records — {n_excl} excluded"
        if n_excl > 0
        else "Advanced: exclude individual suspicious records (click on map)"
    )
    with st.expander(expander_label, expanded=False):
        st.caption(
            "Click an occurrence point on the map to mark it as excluded (turns red). "
            "Click it again to restore. Excluded records are removed from all downstream analysis "
            "and shown as red points. "
            "To filter by geographic area use the target occurrence options above."
        )
        if len(occ_map_display) < len(occ_raw):
            st.caption(
                f"Showing {len(occ_map_display):,} of {len(occ_raw):,} records. "
                "Adjust 'Max occurrence points shown on map' in Advanced sampling settings to inspect more."
            )
        if st.button("Clear all excluded records", key="qc_clear_btn"):
            st.session_state.excluded_row_ids = set()
            st.session_state.last_exclude_click_signature = ""
            reset_model_outputs()
            st.rerun()
        click_data = st_folium(
            make_exclusion_review_map(occ_map_display, set(st.session_state.excluded_row_ids), add_draw=False, show_images=show_images),
            width=None, height=440,
            returned_objects=["last_object_clicked", "last_object_clicked_tooltip"],
            key="coordinate_exclusion_map",
        )
        clicked = (click_data or {}).get("last_object_clicked")
        clicked_tooltip = (click_data or {}).get("last_object_clicked_tooltip")
        if clicked:
            sig = f"{clicked.get('lat'):.6f},{clicked.get('lng'):.6f},{clicked_tooltip}"
            if sig != st.session_state.last_exclude_click_signature:
                rid = nearest_row_id_from_click(occ_map_display, clicked, clicked_tooltip)
                st.session_state.last_exclude_click_signature = sig
                if rid is not None:
                    if rid in set(st.session_state.excluded_row_ids):
                        st.session_state.excluded_row_ids = set(st.session_state.excluded_row_ids) - {rid}
                        st.success(f"Restored record {rid}.")
                    else:
                        st.session_state.excluded_row_ids = set(st.session_state.excluded_row_ids) | {rid}
                        st.success(f"Excluded record {rid}.")
                    reset_model_outputs()
                    st.rerun()
        filtered = occ_raw[~occ_raw["_row_id"].astype(int).isin(set(st.session_state.excluded_row_ids))].copy()
        st.info(f"Included: {len(filtered):,} / {len(occ_raw):,} records. Excluded: {len(occ_raw) - len(filtered):,}.")
    return filtered.reset_index(drop=True)


def rectangle_qc_exclusion_panel(occ_raw: pd.DataFrame, occ_map_display: pd.DataFrame, show_images: bool) -> pd.DataFrame:
    """Rectangle-only QC exclusion for suspicious coordinate regions."""
    n_excl = len(set(st.session_state.excluded_row_ids))
    expander_label = f"Optional rectangle-based coordinate QC - {n_excl} excluded" if n_excl else "Optional rectangle-based coordinate QC"
    with st.expander(expander_label, expanded=False):
        st.caption(
            "Draw one or more rectangles around suspicious coordinate regions. "
            "Records inside the QC rectangle are shown in red and removed from candidate generation, SDM/SSDM, prediction extents, and survey-site lists. "
            "Use the separate survey-area rectangle below to choose which remaining records define the fieldwork target area."
        )
        if len(occ_map_display) < len(occ_raw):
            st.caption(f"Showing {len(occ_map_display):,} of {len(occ_raw):,} records. Raw records remain preserved for summary/download.")
        if st.button("Clear QC rectangles / restore excluded records", key="qc_clear_rectangles_btn"):
            st.session_state.excluded_row_ids = set()
            st.session_state.qc_rect_selected_ids = []
            st.session_state.qc_rect_features = []
            st.session_state.qc_last_draw_sig = ""
            reset_model_outputs()
            st.rerun()
        draw_data = st_folium(
            make_exclusion_review_map(occ_map_display, set(st.session_state.excluded_row_ids), add_draw=True, show_images=show_images),
            width=None,
            height=440,
            returned_objects=["all_drawings", "last_active_drawing"],
            key="rectangle_qc_exclusion_map",
        )
        raw_drawings = (draw_data or {}).get("all_drawings") or (draw_data or {}).get("last_active_drawing")
        features = extract_drawn_features(raw_drawings)
        if features:
            draw_sig = str(features)[:800]
            if draw_sig != st.session_state.get("qc_last_draw_sig", ""):
                excluded_ids = set(ids_inside_drawn_rectangles(occ_raw, "_row_id", "_latitude", "_longitude", features))
                st.session_state.qc_last_draw_sig = draw_sig
                st.session_state.qc_rect_features = features
                st.session_state.qc_rect_selected_ids = sorted(excluded_ids)
                st.session_state.excluded_row_ids = excluded_ids
                reset_model_outputs()
                st.rerun()
        filtered = occ_raw[~occ_raw["_row_id"].astype(int).isin(set(st.session_state.excluded_row_ids))].copy()
        st.info(f"Included: {len(filtered):,} / {len(occ_raw):,} records. Excluded by QC rectangle: {len(occ_raw) - len(filtered):,}.")
    return filtered.reset_index(drop=True)


def sdm_rectangle_qc_panel(occ_raw: pd.DataFrame, occ_map_display: pd.DataFrame) -> pd.DataFrame:
    """SDM-only rectangle QC; independent from the Step 2 survey-area selection."""
    n_excl = len(set(st.session_state.sdm_excluded_row_ids))
    st.markdown("**SDM coordinate QC**")
    st.caption(
        "Optional SDM-only QC. Draw rectangles around suspicious coordinate regions to exclude them from SDM training and SDM extent generation. "
        "This does not change the Step 2 observed-data survey candidates."
    )
    if len(occ_map_display) < len(occ_raw):
        st.caption(f"Showing {len(occ_map_display):,} of {len(occ_raw):,} fetched records for SDM QC.")
    if st.button("Clear SDM QC rectangles / restore SDM records", key="sdm_qc_clear_rectangles"):
        st.session_state.sdm_excluded_row_ids = set()
        st.session_state.sdm_qc_click_sig = ""
        reset_model_outputs()
        st.rerun()
    draw_data = st_folium(
        make_exclusion_review_map(occ_map_display, set(st.session_state.sdm_excluded_row_ids), add_draw=True, show_images=False),
        width=None,
        height=380,
        returned_objects=["all_drawings", "last_active_drawing"],
        key="sdm_rectangle_qc_map",
    )
    raw_drawings = (draw_data or {}).get("all_drawings") or (draw_data or {}).get("last_active_drawing")
    features = extract_drawn_features(raw_drawings)
    if features:
        draw_sig = str(features)[:800]
        if draw_sig != st.session_state.get("sdm_qc_click_sig", ""):
            excluded_ids = set(ids_inside_drawn_rectangles(occ_raw, "_row_id", "_latitude", "_longitude", features))
            st.session_state.sdm_qc_click_sig = draw_sig
            st.session_state.sdm_excluded_row_ids = excluded_ids
            reset_model_outputs()
            st.rerun()
    filtered = occ_raw[~occ_raw["_row_id"].astype(int).isin(set(st.session_state.sdm_excluded_row_ids))].copy()
    st.info(f"SDM included: {len(filtered):,} / {len(occ_raw):,}. SDM QC excluded: {n_excl:,}.")
    return filtered.reset_index(drop=True)


def occurrence_sort_for_representative(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    work = df.copy()
    if "_year" in work.columns:
        work["_year_sort"] = pd.to_numeric(work["_year"], errors="coerce").fillna(-9999)
    else:
        work["_year_sort"] = -9999
    if "_media_url" in work.columns:
        work["_has_photo_sort"] = work["_media_url"].astype(str).str.len() > 0
    else:
        work["_has_photo_sort"] = False
    if "_row_id" not in work.columns:
        work["_row_id"] = np.arange(len(work), dtype=int)
    return work.sort_values(["_has_photo_sort", "_year_sort", "_row_id"], ascending=[False, False, True]).reset_index(drop=True)


def exact_coordinate_deduplicate(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy().reset_index(drop=True)
    work = occurrence_sort_for_representative(df)
    return work.drop_duplicates(subset=["_latitude", "_longitude"], keep="first").drop(columns=[c for c in ["_year_sort", "_has_photo_sort"] if c in work.columns]).reset_index(drop=True)


def genus_species_deduplicate(df: pd.DataFrame) -> pd.DataFrame:
    """For genus richness, keep distinct species even when they share coordinates."""
    if df.empty:
        return df.copy().reset_index(drop=True)
    work = occurrence_sort_for_representative(df)
    species = work.get("_species", pd.Series("", index=work.index)).astype(str).str.strip()
    work["_species_dedup_key"] = species
    out = work.drop_duplicates(subset=["_latitude", "_longitude", "_species_dedup_key"], keep="first")
    drop_cols = [c for c in ["_species_dedup_key", "_year_sort", "_has_photo_sort"] if c in out.columns]
    return out.drop(columns=drop_cols).reset_index(drop=True)


def clean_species_label_for_genus_richness(value: Any) -> str:
    """Return a binomial species label; exclude genus-only, sp./cf./aff., and author-only labels."""
    raw = str(value or "").strip()
    if not raw or raw.lower() in {"nan", "none"}:
        return ""
    parts = raw.replace("×", " ").split()
    if len(parts) < 2:
        return ""
    genus, epithet = parts[0], parts[1]
    bad_epithets = {"sp", "sp.", "spp", "spp.", "cf", "cf.", "aff", "aff.", "indet", "indet.", "hybrid"}
    if epithet.lower() in bad_epithets:
        return ""
    if not re.match(r"^[A-Z][A-Za-z-]+$", genus):
        return ""
    if not re.match(r"^[a-z][a-z-]+$", epithet):
        return ""
    return f"{genus} {epithet}"


def grid_thin(df: pd.DataFrame, grid_degrees: float) -> pd.DataFrame:
    if df.empty or float(grid_degrees) <= 0:
        return df.copy().reset_index(drop=True)
    work = occurrence_sort_for_representative(df)
    cell = float(grid_degrees)
    work["_grid_lon"] = np.floor(work["_longitude"].astype(float) / cell).astype(int)
    work["_grid_lat"] = np.floor(work["_latitude"].astype(float) / cell).astype(int)
    work = work.drop_duplicates(subset=["_grid_lat", "_grid_lon"], keep="first")
    drop_cols = [c for c in ["_grid_lon", "_grid_lat", "_year_sort", "_has_photo_sort"] if c in work.columns]
    return work.drop(columns=drop_cols).reset_index(drop=True)


def genus_species_grid_thin(df: pd.DataFrame, grid_degrees: float) -> pd.DataFrame:
    """Grid-thin genus data without collapsing different species in the same cell."""
    if df.empty or float(grid_degrees) <= 0:
        return df.copy().reset_index(drop=True)
    work = occurrence_sort_for_representative(df)
    cell = float(grid_degrees)
    work["_species_grid_key"] = work.get("_species", pd.Series("", index=work.index)).apply(clean_species_label_for_genus_richness)
    work = work[work["_species_grid_key"].ne("")]
    if work.empty:
        return work.drop(columns=[c for c in ["_species_grid_key", "_year_sort", "_has_photo_sort"] if c in work.columns], errors="ignore").reset_index(drop=True)
    work["_grid_lon"] = np.floor(work["_longitude"].astype(float) / cell).astype(int)
    work["_grid_lat"] = np.floor(work["_latitude"].astype(float) / cell).astype(int)
    work = work.drop_duplicates(subset=["_grid_lat", "_grid_lon", "_species_grid_key"], keep="first")
    drop_cols = [c for c in ["_grid_lon", "_grid_lat", "_species_grid_key", "_year_sort", "_has_photo_sort"] if c in work.columns]
    return work.drop(columns=drop_cols).reset_index(drop=True)


def adaptive_grid_thinning_degrees(df: pd.DataFrame, requested_grid_deg: float, large_mode: bool) -> float:
    """Keep large-dataset defaults, but avoid over-thinning small island/local taxa."""
    try:
        requested = max(0.0, float(requested_grid_deg))
    except Exception:
        requested = 0.0
    if requested <= 0 or df.empty or bool(large_mode):
        return requested
    n = len(df)
    lat_span = float(pd.to_numeric(df["_latitude"], errors="coerce").max() - pd.to_numeric(df["_latitude"], errors="coerce").min())
    lon_span = float(pd.to_numeric(df["_longitude"], errors="coerce").max() - pd.to_numeric(df["_longitude"], errors="coerce").min())
    max_span = max(lat_span, lon_span)
    if n <= 150:
        return min(requested, 0.01)
    if n <= 500 and max_span <= 2.0:
        return min(requested, 0.02)
    return requested


def limit_occurrence_display(occ_raw: pd.DataFrame, excluded_ids: set[int], max_points: int) -> pd.DataFrame:
    if occ_raw.empty:
        return occ_raw.copy()
    cap = max(1, int(max_points))
    if len(occ_raw) <= cap:
        return occ_raw.copy().reset_index(drop=True)
    work = occ_raw.copy()
    work["_display_priority"] = work["_row_id"].astype(int).isin(excluded_ids).astype(int)
    work = occurrence_sort_for_representative(work).sort_values(["_display_priority", "_row_id"], ascending=[False, True]).reset_index(drop=True)
    excluded = work[work["_display_priority"].eq(1)]
    included = work[work["_display_priority"].eq(0)]
    if len(excluded) >= cap:
        out = excluded.head(cap)
    else:
        remain = cap - len(excluded)
        if len(included) <= remain:
            sampled = included
        else:
            positions = np.linspace(0, len(included) - 1, remain).round().astype(int)
            sampled = included.iloc[np.unique(positions)]
        out = pd.concat([excluded, sampled], ignore_index=True, sort=False)
    drop_cols = [c for c in ["_display_priority", "_year_sort", "_has_photo_sort"] if c in out.columns]
    return out.drop(columns=drop_cols).reset_index(drop=True)


def spatially_balanced_cap(df: pd.DataFrame, max_points: int) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    cap = max(1, int(max_points))
    if len(df) <= cap:
        return df.copy().reset_index(drop=True)
    work = occurrence_sort_for_representative(df)
    target_cells = max(4, int(math.sqrt(cap)))
    lat_span = max(1e-9, float(work["_latitude"].max() - work["_latitude"].min()))
    lon_span = max(1e-9, float(work["_longitude"].max() - work["_longitude"].min()))
    work["_bal_lat"] = np.floor((work["_latitude"] - work["_latitude"].min()) / lat_span * target_cells).astype(int)
    work["_bal_lon"] = np.floor((work["_longitude"] - work["_longitude"].min()) / lon_span * target_cells).astype(int)
    balanced = work.drop_duplicates(subset=["_bal_lat", "_bal_lon"], keep="first").copy()
    if len(balanced) > cap:
        positions = np.linspace(0, len(balanced) - 1, cap).round().astype(int)
        balanced = balanced.iloc[np.unique(positions)].copy()
    elif len(balanced) < cap:
        remaining = work[~work["_row_id"].astype(int).isin(set(balanced["_row_id"].astype(int)))]
        need = cap - len(balanced)
        if len(remaining) > need:
            positions = np.linspace(0, len(remaining) - 1, need).round().astype(int)
            remaining = remaining.iloc[np.unique(positions)]
        balanced = pd.concat([balanced, remaining], ignore_index=True, sort=False)
    drop_cols = [c for c in ["_bal_lat", "_bal_lon", "_year_sort", "_has_photo_sort"] if c in balanced.columns]
    return balanced.drop(columns=drop_cols).reset_index(drop=True)


@st.cache_data(show_spinner=False)
def prepare_large_dataset_inputs(
    occ_after_exclusion: pd.DataFrame,
    use_exact_dedup: bool,
    manual_grid_deg: float,
    manual_distance_m: float,
    large_mode: bool,
    candidate_target: int = FAST_CANDIDATE_RECORDS,
    sdm_target: int = FAST_SDM_RECORDS,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, int]]:
    candidate_target = max(1, int(candidate_target))
    sdm_target = max(1, int(sdm_target))
    base = exact_coordinate_deduplicate(occ_after_exclusion) if use_exact_dedup else occ_after_exclusion.copy().reset_index(drop=True)
    effective_grid_deg = adaptive_grid_thinning_degrees(base, float(manual_grid_deg), bool(large_mode))
    candidate_grid = grid_thin(base, effective_grid_deg)
    candidate = spatially_balanced_cap(candidate_grid, candidate_target)
    sdm_grid_deg = adaptive_grid_thinning_degrees(base, float(manual_grid_deg), bool(large_mode))
    sdm_train = grid_thin(base, sdm_grid_deg)
    if float(manual_distance_m) > 0:
        sdm_train = spatial_thin(sdm_train, float(manual_distance_m))
    sdm_train = spatially_balanced_cap(sdm_train, sdm_target)
    summary = {
        "candidate_target": int(candidate_target),
        "sdm_target": int(sdm_target),
        "after_exact_dedup": int(len(base)),
        "candidate_grid_deg": float(effective_grid_deg),
        "sdm_grid_deg": float(sdm_grid_deg),
        "after_grid_thin": int(len(candidate_grid)),
        "candidate_input": int(len(candidate)),
        "sdm_train": int(len(sdm_train)),
    }
    return candidate.reset_index(drop=True), sdm_train.reset_index(drop=True), summary


def spatial_thin(df: pd.DataFrame, thinning_m: float) -> pd.DataFrame:
    """Greedy minimum-distance thinning using vectorised haversine (replaces O(n²) geopy loop)."""
    if df.empty or thinning_m <= 0:
        return df.copy().reset_index(drop=True)
    work = df.copy()
    work["_year_sort"] = pd.to_numeric(work.get("_year"), errors="coerce").fillna(-9999)
    work["_has_photo_sort"] = work.get("_media_url", "").astype(str).str.len() > 0
    work = work.sort_values(["_has_photo_sort", "_year_sort"], ascending=[False, False]).reset_index(drop=True)
    lats = work["_latitude"].to_numpy(dtype=float)
    lons = work["_longitude"].to_numpy(dtype=float)
    kept_mask = np.zeros(len(work), dtype=bool)
    kept_lats: list[float] = []
    kept_lons: list[float] = []
    for i in range(len(work)):
        if kept_lats:
            kl = np.radians(np.array(kept_lats))
            ko = np.radians(np.array(kept_lons))
            dlat = kl - math.radians(lats[i])
            dlon = ko - math.radians(lons[i])
            a = np.sin(dlat / 2) ** 2 + math.cos(math.radians(lats[i])) * np.cos(kl) * np.sin(dlon / 2) ** 2
            if (2 * EARTH_RADIUS_M * np.arcsin(np.sqrt(a.clip(0, 1)))).min() < thinning_m:
                continue
        kept_mask[i] = True
        kept_lats.append(lats[i])
        kept_lons.append(lons[i])
    return work.loc[kept_mask].drop(columns=["_year_sort", "_has_photo_sort"], errors="ignore").reset_index(drop=True)


def haversine_dbscan(df: pd.DataFrame, lat_col: str, lon_col: str, threshold_m: float, min_samples: int) -> pd.Series:
    if df.empty:
        return pd.Series(dtype=int, name="cluster_id")
    coords_rad = [[math.radians(lat), math.radians(lon)] for lat, lon in df[[lat_col, lon_col]].to_numpy(dtype=float)]
    eps = float(threshold_m) / EARTH_RADIUS_M
    labels = DBSCAN(eps=eps, min_samples=int(min_samples), metric="haversine").fit_predict(coords_rad)
    return pd.Series(labels, index=df.index, name="cluster_id")


def auto_remote_spatial_outlier_qc(
    occ: pd.DataFrame,
    cluster_eps_m: float = 120_000.0,
    min_records: int = 20,
    min_samples: int = 3,
    keep_fraction: float = 0.90,
    min_remote_distance_m: float = 250_000.0,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Conservatively remove remote minor clusters from SDM input only.

    This catches cases such as an island endemic with a few mainland noise
    records, while avoiding aggressive trimming of legitimate range-edge
    records. Step 2 observed-candidate selection remains independent.
    """
    empty = occ.iloc[0:0].copy()
    report: dict[str, Any] = {
        "enabled": True,
        "input_records": int(len(occ)),
        "excluded_records": 0,
        "cluster_eps_km": round(float(cluster_eps_m) / 1000.0, 1),
        "min_remote_distance_km": round(float(min_remote_distance_m) / 1000.0, 1),
        "reason": "not enough records for automatic outlier screening",
    }
    if occ.empty or len(occ) < int(min_records) or "_row_id" not in occ.columns:
        return occ.copy().reset_index(drop=True), empty, report

    work = occ.dropna(subset=["_latitude", "_longitude"]).copy().reset_index(drop=True)
    if len(work) < int(min_records):
        return occ.copy().reset_index(drop=True), empty, report

    labels = haversine_dbscan(work, "_latitude", "_longitude", float(cluster_eps_m), int(min_samples))
    work["_auto_sdm_cluster"] = labels.values
    cluster_counts = work.loc[work["_auto_sdm_cluster"] >= 0, "_auto_sdm_cluster"].value_counts()
    if cluster_counts.empty:
        report["reason"] = "no stable spatial cluster detected"
        return occ.copy().reset_index(drop=True), empty, report

    clustered_total = int(cluster_counts.sum())
    keep_target = max(1, int(math.ceil(clustered_total * float(keep_fraction))))
    keep_clusters: set[int] = set()
    cumulative = 0
    for cluster_id, count in cluster_counts.sort_values(ascending=False).items():
        keep_clusters.add(int(cluster_id))
        cumulative += int(count)
        if cumulative >= keep_target:
            break

    kept = work[work["_auto_sdm_cluster"].isin(keep_clusters)].copy()
    if kept.empty:
        report["reason"] = "no primary cluster retained"
        return occ.copy().reset_index(drop=True), empty, report

    tree = BallTree(np.radians(kept[["_latitude", "_longitude"]].to_numpy(dtype=float)), metric="haversine")
    dist_rad, _ = tree.query(np.radians(work[["_latitude", "_longitude"]].to_numpy(dtype=float)), k=1)
    work["_auto_nearest_kept_m"] = dist_rad[:, 0] * EARTH_RADIUS_M

    cluster_size = work["_auto_sdm_cluster"].map(cluster_counts).fillna(1).astype(int)
    minor_cluster_limit = max(3, int(math.ceil(len(work) * 0.08)))
    remote_minor = (
        (~work["_auto_sdm_cluster"].isin(keep_clusters))
        & (cluster_size <= minor_cluster_limit)
        & (work["_auto_nearest_kept_m"] >= float(min_remote_distance_m))
    )
    excluded_ids = set(work.loc[remote_minor, "_row_id"].astype(int))
    if not excluded_ids:
        report["reason"] = "no remote minor cluster detected"
        report["kept_clusters"] = sorted(keep_clusters)
        return occ.copy().reset_index(drop=True), empty, report

    included = occ[~occ["_row_id"].astype(int).isin(excluded_ids)].copy().reset_index(drop=True)
    excluded = occ[occ["_row_id"].astype(int).isin(excluded_ids)].copy().reset_index(drop=True)
    excl_meta = work.loc[work["_row_id"].astype(int).isin(excluded_ids), ["_row_id", "_auto_sdm_cluster", "_auto_nearest_kept_m"]].copy()
    excluded = excluded.merge(excl_meta, on="_row_id", how="left")
    excluded["sdm_qc_reason"] = "Auto remote spatial outlier"
    report.update({
        "input_records": int(len(occ)),
        "included_records": int(len(included)),
        "excluded_records": int(len(excluded)),
        "kept_clusters": sorted(keep_clusters),
        "reason": "remote minor cluster excluded from SDM input",
    })
    return included, excluded, report


def prediction_area_geometry(occ: pd.DataFrame, mode: str, buffer_km: float, rectangle_margin_km: float, excluded_occ: Optional[pd.DataFrame] = None, exclusion_buffer_km: float = 0.0):
    if occ.empty:
        return None
    lons = occ["_longitude"].to_numpy(dtype=float)
    lats = occ["_latitude"].to_numpy(dtype=float)
    buffer_deg = max(km_to_deg(buffer_km), 0.0001)
    if mode == "buffer":
        points = [Point(lo, la) for lo, la in zip(lons, lats)]
        geom = unary_union([p.buffer(buffer_deg) for p in points])
    elif mode == "convex hull":
        if len(lons) == 1:
            geom = Point(lons[0], lats[0]).buffer(buffer_deg)
        else:
            geom = MultiPoint(list(zip(lons, lats))).convex_hull.buffer(buffer_deg)
    else:
        margin = km_to_deg(rectangle_margin_km)
        geom = box(lons.min() - margin, lats.min() - margin, lons.max() + margin, lats.max() + margin)
    if excluded_occ is not None and not excluded_occ.empty and exclusion_buffer_km > 0:
        cutout_deg = max(km_to_deg(exclusion_buffer_km), 0.0001)
        exc_lons = excluded_occ["_longitude"].to_numpy(dtype=float)
        exc_lats = excluded_occ["_latitude"].to_numpy(dtype=float)
        cutouts = unary_union([Point(lo, la).buffer(cutout_deg) for lo, la in zip(exc_lons, exc_lats)])
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

def make_sdm_setup_map(
    occ_sdm_final: pd.DataFrame,
    excluded_raw: pd.DataFrame,
    extent_geom=None,
    area_mode: str = "bounding box",
) -> folium.Map:
    """Consolidated SDM setup map: extent outline + all analysis points + excluded QC points + rectangle draw.

    occ_sdm_final — final SDM presence points after QC + bias reduction; shown in blue, NOT capped.
    excluded_raw  — raw records excluded by SDM QC rectangles; shown in red (capped at 500 for performance).
    extent_geom   — SDM prediction extent polygon; shown as orange outline.
    """
    all_pts = pd.concat([occ_sdm_final, excluded_raw], ignore_index=True, sort=False) if not excluded_raw.empty else occ_sdm_final
    center = (float(all_pts["_latitude"].mean()), float(all_pts["_longitude"].mean())) if not all_pts.empty else (35.5, 135.5)
    fmap = Map(location=center, zoom_start=7, tiles="OpenStreetMap", control_scale=True)

    # Extent polygon
    if extent_geom is not None and not extent_geom.is_empty:
        folium.GeoJson(
            extent_geom.__geo_interface__,
            name=f"SDM prediction extent ({area_mode})",
            style_function=lambda _: {"color": "#e66101", "weight": 2, "fillColor": "#fdb863", "fillOpacity": 0.12},
            tooltip=f"SDM prediction extent: {area_mode}",
        ).add_to(fmap)

    # Included SDM analysis points (blue) — show all, no cap
    fg_inc = FeatureGroup(name=f"SDM analysis points ({len(occ_sdm_final):,} included)", show=True)
    for _, row in occ_sdm_final.iterrows():
        folium.CircleMarker(
            (row["_latitude"], row["_longitude"]),
            radius=4, color="#1f77b4", fill=True, fill_color="#1f77b4", fill_opacity=0.85, weight=1,
            tooltip=f"SDM analysis point | row {int(row['_row_id'])}",
        ).add_to(fg_inc)
    fg_inc.add_to(fmap)

    # Excluded QC points (red) — capped at 500 for performance since they are not analysis points
    if not excluded_raw.empty:
        show_excl = excluded_raw if len(excluded_raw) <= 500 else excluded_raw.sample(500, random_state=42)
        fg_exc = FeatureGroup(name=f"SDM QC excluded ({len(excluded_raw):,} excluded)", show=True)
        for _, row in show_excl.iterrows():
            folium.CircleMarker(
                (row["_latitude"], row["_longitude"]),
                radius=5, color="#d62728", fill=True, fill_color="#d62728", fill_opacity=0.85, weight=1,
                tooltip=f"Excluded by SDM QC | row {int(row['_row_id'])}",
            ).add_to(fg_exc)
        fg_exc.add_to(fmap)

    # Rectangle draw for SDM QC exclusion
    Draw(
        export=False,
        draw_options={"rectangle": True, "polyline": False, "circle": False, "marker": False, "circlemarker": False, "polygon": False},
        edit_options={"edit": False, "remove": True},
    ).add_to(fmap)

    LayerControl(collapsed=True).add_to(fmap)
    try:
        if extent_geom is not None and not extent_geom.is_empty:
            minx, miny, maxx, maxy = extent_geom.bounds
            fmap.fit_bounds([[miny, minx], [maxy, maxx]], padding=(20, 20))
        elif not all_pts.empty:
            fmap.fit_bounds([[all_pts["_latitude"].min(), all_pts["_longitude"].min()], [all_pts["_latitude"].max(), all_pts["_longitude"].max()]], padding=(30, 30))
    except Exception:
        pass
    return fmap


@st.cache_data(show_spinner=False)
def make_macro_cluster_map(occ: pd.DataFrame) -> folium.Map:
    """National-scale MarkerCluster map for macro distribution overview.

    All fetched records are shown as auto-clustering circles that expand/contract
    with zoom level.  Users can see where species are concentrated without the
    app being slow — MarkerCluster handles thousands of points efficiently.
    """
    if occ.empty:
        return Map(location=(35.5, 135.5), zoom_start=6, tiles="OpenStreetMap")
    center = (float(occ["_latitude"].mean()), float(occ["_longitude"].mean()))
    fmap = Map(location=center, zoom_start=6, tiles="OpenStreetMap", control_scale=True)
    mc = MarkerCluster(name=f"All occurrences ({len(occ):,} records)", show=True,
                       options={"maxClusterRadius": 40, "disableClusteringAtZoom": 10})
    for _, row in occ.iterrows():
        year_str = f" ({int(row['_year'])})" if pd.notna(row.get("_year")) and str(row.get("_year", "")) not in ("", "nan") else ""
        folium.CircleMarker(
            (row["_latitude"], row["_longitude"]),
            radius=3,
            color="#1f77b4",
            fill=True,
            fill_color="#1f77b4",
            fill_opacity=0.75,
            weight=0,
            popup=folium.Popup(f"{row.get('_species', '')}{year_str}", max_width=250),
        ).add_to(mc)
    mc.add_to(fmap)
    Draw(
        export=False,
        draw_options={"rectangle": True, "polyline": False, "circle": False, "marker": False, "circlemarker": False, "polygon": False},
        edit_options={"edit": False, "remove": True},
    ).add_to(fmap)
    LayerControl(collapsed=True).add_to(fmap)
    try:
        fmap.fit_bounds([
            [occ["_latitude"].min(), occ["_longitude"].min()],
            [occ["_latitude"].max(), occ["_longitude"].max()],
        ], padding=(40, 40))
    except Exception:
        pass
    return fmap


def representative_medoid(group: pd.DataFrame) -> pd.Series:
    if len(group) == 1:
        return group.iloc[0]
    lats = group["_latitude"].to_numpy(dtype=float)
    lons = group["_longitude"].to_numpy(dtype=float)
    if len(group) <= 75:
        lat_rad = np.radians(lats)
        lon_rad = np.radians(lons)
        dlat = lat_rad[:, None] - lat_rad[None, :]
        dlon = lon_rad[:, None] - lon_rad[None, :]
        a = np.sin(dlat / 2) ** 2 + np.cos(lat_rad[:, None]) * np.cos(lat_rad[None, :]) * np.sin(dlon / 2) ** 2
        d = 2 * EARTH_RADIUS_M * np.arcsin(np.sqrt(a.clip(0, 1)))
        return group.iloc[int(np.argmin(d.sum(axis=1)))]

    lat0 = math.radians(float(np.nanmean(lats)))
    lon0 = math.radians(float(np.nanmean(lons)))
    x = (np.radians(lons) - lon0) * math.cos(lat0)
    y = np.radians(lats) - lat0
    return group.iloc[int(np.argmin((x * x) + (y * y)))]


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
    out = pd.DataFrame(rows)
    # Phenology: default empty columns (filled later by caller with full occ_candidate_input)
    for col in ["observation_months", "flowering_record_count", "flowering_months",
                "recommended_survey_window", "season_confidence"]:
        if col not in out.columns:
            out[col] = "" if col != "flowering_record_count" else 0
    return out


@st.cache_data(show_spinner=False)
def build_occurrence_candidates_cached(
    occ_candidate_input: pd.DataFrame,
    cluster_m: float,
    min_samples: int,
    center_method: str,
    occurrence_weight: float,
    observed_weight: float,
    model_weight: float,
) -> pd.DataFrame:
    if occ_candidate_input.empty:
        return pd.DataFrame()
    work = occ_candidate_input.copy()
    work["cluster_id"] = haversine_dbscan(work, "_latitude", "_longitude", float(cluster_m), int(min_samples))
    candidates = make_candidate_sites(work, center_method, float(occurrence_weight))
    if "_obs_month" in work.columns and not candidates.empty:
        grouped = {int(cid): group for cid, group in work.groupby("cluster_id", sort=False) if int(cid) >= 0}
        for idx, cand_row in candidates.iterrows():
            try:
                cluster_id = int(cand_row.get("cluster_id", -999))
            except Exception:
                continue
            cluster_occ = grouped.get(cluster_id)
            if cluster_occ is None or cluster_occ.empty:
                continue
            summary = candidate_season_summary(cluster_occ)
            for k, v in summary.items():
                candidates.at[idx, k] = v
    candidates = add_priority_rank(candidates, float(observed_weight), float(model_weight))
    return order_sites(candidates, "Nearest-neighbor route")


def available_sort_cols(df: pd.DataFrame, desired: list[str]) -> list[str]:
    return [c for c in desired if c in df.columns]


def add_priority_rank(sites: pd.DataFrame, observed_weight: float = 0.7, model_weight: float = 0.3) -> pd.DataFrame:
    """Compute weighted priority score and rank.

    priority_score = observed_weight * occurrence_support_score
                   + model_weight   * model_support_score
                   + optional small bonuses (recency, photo, base)

    model_support_score is taken from (in priority order):
      1. model_support_score column (if present and non-NaN, and non-zero when sdm_suitability is available)
      2. sdm_suitability column (fallback for rows where model_support_score is NaN or 0 but SDM has run)
      3. ssdm_model_support_score column
      4. 0.0 (when no model data is available)

    SDM/SSDM is optional: when no model data exists, model_support_score=0 and
    priority_score is determined entirely by occurrence support.
    """
    out = sites.copy()
    if out.empty:
        out["priority_rank"] = []
        return out
    observed_w = float(observed_weight)
    model_w = float(model_weight)
    if "occurrence_support_score" in out.columns:
        observed_source = out["occurrence_support_score"]
    elif "priority_score" in out.columns:
        observed_source = out["priority_score"]
    else:
        observed_source = pd.Series(0.0, index=out.index)
    observed = pd.to_numeric(observed_source, errors="coerce").fillna(0.0).clip(0, 1)
    # Build model series with fallback: prefer model_support_score, but if it is 0
    # while sdm_suitability is non-NaN (meaning SDM ran after model_support_score was set),
    # use sdm_suitability instead so re-ranking reflects actual SDM predictions.
    if "model_support_score" in out.columns:
        model = pd.to_numeric(out["model_support_score"], errors="coerce")
    else:
        model = pd.Series(np.nan, index=out.index)
    if "sdm_suitability" in out.columns:
        sdm_suit = pd.to_numeric(out["sdm_suitability"], errors="coerce")
        model = model.where(model.notna() & ~(model.eq(0.0) & sdm_suit.notna()), sdm_suit)
    elif "ssdm_model_support_score" in out.columns:
        ssdm_score = pd.to_numeric(out["ssdm_model_support_score"], errors="coerce")
        model = model.where(model.notna(), ssdm_score)
    model = model.clip(0, 1)
    base_priority = pd.to_numeric(out.get("priority_score", observed), errors="coerce").fillna(observed).clip(0, 1)
    bonus = (base_priority - observed).clip(lower=0, upper=0.20)
    model_filled = model.fillna(0.0)
    out["occurrence_support_score"] = observed.round(3)
    out["model_support_score"] = model_filled.round(3)
    out["observed_weight"] = round(observed_w, 3)
    out["model_weight"] = round(model_w, 3)
    out["priority_score"] = (observed_w * observed + model_w * model_filled + bonus).clip(0, 1).round(3)
    out["score_explanation"] = [
        f"priority = {observed_w:.2f}*observed({obs:.3f}) + {model_w:.2f}*model({mod:.3f}) + bonus({bon:.3f}); SDM/SSDM model support is optional and does not replace observed-data candidates"
        for obs, mod, bon in zip(observed, model_filled, bonus)
    ]
    sort_cols = available_sort_cols(out, ["priority_score", "model_support_score", "occurrence_support_score"])
    if not sort_cols:
        out["priority_rank"] = range(1, len(out) + 1)
        return out
    rank = out.sort_values(sort_cols, ascending=False, na_position="last").reset_index(drop=True)
    rank["priority_rank"] = range(1, len(rank) + 1)
    return out.drop(columns=["priority_rank"], errors="ignore").merge(rank[["site_id", "priority_rank"]], on="site_id", how="left")


# ── ACSP: Adaptive Complementarity-based Survey Prioritization ────────────────
# A candidate-SET selection algorithm. Instead of ranking candidates only by
# their independent priority_score, ACSP greedily builds a survey set whose
# members jointly maximise detection potential, model support, environmental /
# geographic complementarity, exploration value and sampling-gap coverage while
# penalising redundancy and excessive travel. It uses only data already present
# on the candidate dataframe (no new user uploads required) and degrades
# gracefully when optional columns (SDM suitability, species lists, environment
# predictors, region labels) are unavailable.

ACSP_SELECTION_MODES = [
    "Simple top-ranked",
    "Complementarity-based batch selection",
    "Discovery-focused field survey",
    "Learning-focused field survey",
    "Habitat analogue survey",
    "Exploration-focused active survey",
    "Phylogeographic gap-filling",
]

# Per-mode component weights for the marginal-gain function.
# marginal_gain = w_base*base_score + w_coverage*coverage_gain
#               + w_exploration*exploration_gain + w_gap*sampling_gap_gain
#               + w_habitat*habitat_analogue_gain + w_validation*validation_learning_gain
#               + w_access*access_gain
#               - w_redundancy*redundancy_penalty - w_travel*travel_penalty
ACSP_MODE_WEIGHTS: dict[str, dict[str, float]] = {
    "Simple top-ranked": {
        "base": 1.0, "coverage": 0.0, "exploration": 0.0,
        "gap": 0.0, "habitat": 0.0, "validation": 0.0, "access": 0.0,
        "redundancy": 0.0, "travel": 0.0,
    },
    "Complementarity-based batch selection": {
        "base": 1.0, "coverage": 0.8, "exploration": 0.3,
        "gap": 0.4, "habitat": 0.4, "validation": 0.4, "access": 0.2,
        "redundancy": 0.8, "travel": 0.05,
    },
    "Discovery-focused field survey": {
        "base": 0.9, "coverage": 0.35, "exploration": 0.25,
        "gap": 0.25, "habitat": 1.15, "validation": 0.5, "access": 0.25,
        "redundancy": 0.6, "travel": 0.04,
    },
    "Learning-focused field survey": {
        "base": 0.45, "coverage": 0.8, "exploration": 0.65,
        "gap": 1.0, "habitat": 0.45, "validation": 0.6, "access": 0.15,
        "redundancy": 0.7, "travel": 0.07,
    },
    "Habitat analogue survey": {
        "base": 0.6, "coverage": 0.4, "exploration": 0.3,
        "gap": 0.8, "habitat": 1.2, "validation": 0.6, "access": 0.3,
        "redundancy": 0.6, "travel": 0.05,
    },
    "Exploration-focused active survey": {
        "base": 0.6, "coverage": 0.5, "exploration": 1.0,
        "gap": 0.5, "habitat": 0.7, "validation": 0.4, "access": 0.1,
        "redundancy": 0.5, "travel": 0.1,
    },
    "Phylogeographic gap-filling": {
        "base": 0.6, "coverage": 0.6, "exploration": 0.3,
        "gap": 1.0, "habitat": 0.4, "validation": 0.3, "access": 0.1,
        "redundancy": 0.7, "travel": 0.1,
    },
}

# Output columns added by ACSP (in addition to the original candidate columns).
ACSP_GAIN_COLUMNS = [
    "base_score",
    "geographic_complementarity_gain",
    "environmental_complementarity_gain",
    "habitat_analogue_gain",
    "exploration_gain",
    "sampling_gap_gain",
    "validation_learning_gain",
    "access_gain",
    "redundancy_penalty",
    "travel_penalty",
    "marginal_gain_score",
    "selection_step",
    "selection_reason",
    "selection_algorithm",
]


def _acsp_normalize(values: Any) -> np.ndarray:
    """Min-max normalise to 0..1; non-finite entries map to 0; constant arrays map to 0."""
    arr = pd.to_numeric(pd.Series(values), errors="coerce").to_numpy(dtype=float)
    finite = np.isfinite(arr)
    out = np.zeros_like(arr, dtype=float)
    if not finite.any():
        return out
    lo = float(np.min(arr[finite]))
    hi = float(np.max(arr[finite]))
    if hi - lo <= 1e-12:
        return out
    out[finite] = (arr[finite] - lo) / (hi - lo)
    return np.clip(out, 0.0, 1.0)


def _acsp_point_distances_m(lat: float, lon: float, lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
    """Haversine distance (metres) from one point to arrays of points."""
    lat_r = math.radians(float(lat))
    lon_r = math.radians(float(lon))
    lats_r = np.radians(lats)
    lons_r = np.radians(lons)
    dlat = lats_r - lat_r
    dlon = lons_r - lon_r
    a = np.sin(dlat / 2.0) ** 2 + math.cos(lat_r) * np.cos(lats_r) * np.sin(dlon / 2.0) ** 2
    return 2.0 * EARTH_RADIUS_M * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def _acsp_environment_columns(df: pd.DataFrame) -> list[str]:
    """Detect usable numeric environmental / PCA predictor columns on candidates."""
    usable: list[str] = []
    for col in df.columns:
        name = str(col).lower()
        looks_env = (
            name.startswith("pca")
            or name.startswith("pc_")
            or re.match(r"^pc\d+$", name) is not None
            or name.startswith("env_")
            or name.startswith("bio")
            or name in {
                "elevation", "elev", "altitude", "slope", "aspect", "roughness", "tpi", "ndvi",
                "distance_to_road_m", "distance_to_trail_m", "distance_to_coast_m", "distance_to_forest_edge_m",
                "habitat_score", "environmental_similarity", "mahalanobis_environment_distance",
            }
        )
        if not looks_env:
            continue
        series = pd.to_numeric(df[col], errors="coerce")
        if series.notna().sum() >= 2 and float(series.std(skipna=True) or 0.0) > 0.0:
            usable.append(col)
    return usable


def _acsp_region_labels(df: pd.DataFrame) -> Optional[pd.Series]:
    """Return a per-candidate region/island/richness-cluster label Series if any such column exists."""
    for col in ["region", "island", "richness_cluster", "cluster_label", "admin_area",
                "province", "state", "biogeographic_region", "ecoregion"]:
        if col in df.columns and df[col].notna().any():
            return df[col].astype(str)
    return None


def _acsp_species_sets(df: pd.DataFrame) -> Optional[list[set]]:
    """Parse per-candidate species lists (semicolon/comma separated) for coverage gap-filling."""
    if "species_list" not in df.columns:
        return None
    sets: list[set] = []
    any_species = False
    for raw in df["species_list"].astype(str).tolist():
        if raw in ("", "nan", "None"):
            sets.append(set())
            continue
        parts = [p.strip() for chunk in raw.split(";") for p in chunk.split(",")]
        species = {p for p in parts if p and p.lower() not in ("nan", "none")}
        if species:
            any_species = True
        sets.append(species)
    return sets if any_species else None


def acsp_select(
    candidates: pd.DataFrame,
    k: int,
    mode: str = "Complementarity-based batch selection",
    selected_ids: Optional[list] = None,
    *,
    complementarity_scale_m: float = 25_000.0,
    cluster_distance_m: float = 4_000.0,
    redundancy_scale_m: float = 8_000.0,
    travel_scale_m: float = 200_000.0,
    weights: Optional[dict[str, float]] = None,
) -> pd.DataFrame:
    """Greedy Adaptive Complementarity-based Survey Prioritization.

    Builds a survey set of (up to) ``k`` sites. ``selected_ids`` (S0) are treated
    as already chosen and are placed first in the output (preserving the user's
    manual selection order) before greedy complementarity filling continues.

    Returns the selected candidates in selection order, with all ACSP gain
    columns populated. Uses only columns already present on ``candidates``.
    """
    base_cols_present = candidates is not None and not candidates.empty
    if not base_cols_present or int(k) <= 0:
        empty = (candidates.head(0).copy() if candidates is not None else pd.DataFrame())
        for col in ACSP_GAIN_COLUMNS:
            if col not in empty.columns:
                empty[col] = []
        return empty

    df = candidates.reset_index(drop=True).copy()
    n = len(df)
    k = min(int(k), n)
    mode = mode if mode in ACSP_MODE_WEIGHTS else "Complementarity-based batch selection"
    w = dict(ACSP_MODE_WEIGHTS[mode])
    if weights:
        w.update({key: float(val) for key, val in weights.items() if key in w})
    for key in ["base", "coverage", "exploration", "gap", "habitat", "validation", "access", "redundancy", "travel"]:
        w.setdefault(key, 0.0)

    lats = pd.to_numeric(df["latitude"], errors="coerce").to_numpy(dtype=float)
    lons = pd.to_numeric(df["longitude"], errors="coerce").to_numpy(dtype=float)
    base_score = pd.to_numeric(df.get("priority_score", pd.Series(0.0, index=df.index)), errors="coerce").fillna(0.0).clip(0.0, 1.0).to_numpy()

    # ── Static (S-independent) component: exploration gain ───────────────────
    cand_type = df.get("candidate_type", pd.Series("", index=df.index)).astype(str)
    is_explore_type = cand_type.str.contains("exploration", case=False, na=False) | cand_type.str.startswith(("SDM-high", "SSDM-high"))
    expl_parts: list[np.ndarray] = []
    sdm_suit = pd.to_numeric(df.get("sdm_suitability", pd.Series(np.nan, index=df.index)), errors="coerce")
    if sdm_suit.notna().any():
        expl_parts.append(0.5 * _acsp_normalize(sdm_suit))
    dist_known = pd.to_numeric(df.get("distance_to_nearest_known_m", pd.Series(np.nan, index=df.index)), errors="coerce")
    if dist_known.notna().any():
        expl_parts.append(0.3 * _acsp_normalize(dist_known))
    uncertainty = None
    for unc_col in ["model_uncertainty", "model_support_sd", "prediction_sd", "sdm_sd", "ensemble_sd"]:
        if unc_col in df.columns and pd.to_numeric(df[unc_col], errors="coerce").notna().any():
            uncertainty = pd.to_numeric(df[unc_col], errors="coerce")
            break
    if uncertainty is not None:
        expl_parts.append(0.2 * _acsp_normalize(uncertainty))
    exploration_gain = np.sum(expl_parts, axis=0) if expl_parts else np.zeros(n)
    exploration_gain = exploration_gain + 0.2 * is_explore_type.to_numpy(dtype=float)
    exploration_gain = np.clip(exploration_gain, 0.0, 1.0)

    habitat_parts: list[np.ndarray] = []
    for col, weight in [("habitat_score", 0.45), ("environmental_similarity", 0.35), ("analogue_score", 0.25), ("landcover_match_score", 0.15)]:
        if col in df.columns and pd.to_numeric(df[col], errors="coerce").notna().any():
            habitat_parts.append(weight * _acsp_normalize(df[col]))
    if "mahalanobis_environment_distance" in df.columns and pd.to_numeric(df["mahalanobis_environment_distance"], errors="coerce").notna().any():
        habitat_parts.append(0.25 * (1.0 - _acsp_normalize(df["mahalanobis_environment_distance"])))
    habitat_analogue_gain = np.sum(habitat_parts, axis=0) if habitat_parts else np.zeros(n)
    habitat_type = cand_type.str.contains("habitat analogue|under-surveyed analogue|habitat-match|survey-gap", case=False, na=False)
    habitat_analogue_gain = np.clip(habitat_analogue_gain + 0.15 * habitat_type.to_numpy(dtype=float), 0.0, 1.0)

    validation_learning_gain = np.zeros(n)
    if "field_validation_support_score" in df.columns and pd.to_numeric(df["field_validation_support_score"], errors="coerce").notna().any():
        validation_learning_gain = _acsp_normalize(df["field_validation_support_score"])

    access_parts: list[np.ndarray] = []
    if "access_score" in df.columns and pd.to_numeric(df["access_score"], errors="coerce").notna().any():
        access_parts.append(0.6 * _acsp_normalize(df["access_score"]))
    for dist_col, weight in [("distance_to_road_m", 0.25), ("distance_to_trail_m", 0.35)]:
        if dist_col in df.columns and pd.to_numeric(df[dist_col], errors="coerce").notna().any():
            access_parts.append(weight * (1.0 - _acsp_normalize(df[dist_col])))
    access_gain = np.clip(np.sum(access_parts, axis=0), 0.0, 1.0) if access_parts else np.zeros(n)

    # ── Static sampling-gap component: under-sampled (few records) sites ──────
    n_occ = pd.to_numeric(df.get("n_occurrences", pd.Series(0.0, index=df.index)), errors="coerce").fillna(0.0)
    static_gap = 1.0 - _acsp_normalize(np.log1p(n_occ.to_numpy()))
    for gap_col, weight in [("survey_gap_score", 0.5), ("environmental_novelty", 0.25)]:
        if gap_col in df.columns and pd.to_numeric(df[gap_col], errors="coerce").notna().any():
            static_gap = np.clip(0.7 * static_gap + weight * _acsp_normalize(df[gap_col]), 0.0, 1.0)
    contrast_type = cand_type.str.contains("environmental contrast|environmental-test", case=False, na=False)
    static_gap = np.clip(static_gap + 0.15 * contrast_type.to_numpy(dtype=float), 0.0, 1.0)

    if mode == "Discovery-focused field survey":
        contrast_mask = contrast_type.to_numpy(dtype=bool)
        known_anchor_mask = cand_type.str.contains("occurrence-supported", case=False, na=False).to_numpy(dtype=bool)
        habitat_analogue_gain[known_anchor_mask] = np.maximum(habitat_analogue_gain[known_anchor_mask], 0.9)
        exploration_gain[known_anchor_mask] = np.maximum(exploration_gain[known_anchor_mask], 0.15)
        habitat_analogue_gain[contrast_mask] *= 0.2
        static_gap[contrast_mask] *= 0.25
        exploration_gain[contrast_mask] *= 0.35
    elif mode == "Learning-focused field survey":
        contrast_mask = contrast_type.to_numpy(dtype=bool)
        model_only_mask = cand_type.str.contains("exploration|sdm-high|ssdm-high", case=False, na=False).to_numpy(dtype=bool)
        static_gap[contrast_mask] = np.clip(static_gap[contrast_mask] + 0.25, 0.0, 1.0)
        exploration_gain[model_only_mask | contrast_mask] = np.clip(exploration_gain[model_only_mask | contrast_mask] + 0.25, 0.0, 1.0)

    # ── Optional environmental space (standardised) ──────────────────────────
    env_cols = _acsp_environment_columns(df)
    env_matrix = None
    env_scale = 1.0
    if env_cols:
        raw_env = df[env_cols].apply(lambda s: pd.to_numeric(s, errors="coerce"))
        col_means = raw_env.mean(axis=0)
        col_stds = raw_env.std(axis=0).replace(0.0, np.nan)
        env_matrix = ((raw_env - col_means) / col_stds).fillna(0.0).to_numpy(dtype=float)
        env_scale = max(1e-6, math.sqrt(len(env_cols)))

    # ── Dynamic novelty inputs (region / species coverage) ───────────────────
    region_labels = _acsp_region_labels(df)
    species_sets = _acsp_species_sets(df)

    has_env = env_matrix is not None
    forced_positions: list[int] = []
    if selected_ids:
        id_to_pos = {int(sid): pos for pos, sid in enumerate(df["site_id"].astype(int).tolist())}
        seen: set[int] = set()
        for sid in selected_ids:
            try:
                sid_int = int(sid)
            except (TypeError, ValueError):
                continue
            pos = id_to_pos.get(sid_int)
            if pos is not None and pos not in seen:
                forced_positions.append(pos)
                seen.add(pos)

    selected_positions: list[int] = []
    selected_set: set[int] = set()
    selected_regions: set[str] = set()
    selected_species: set = set()
    records: list[dict[str, Any]] = []

    def _component_values(i: int) -> dict[str, float]:
        if selected_positions:
            sel_lat = lats[selected_positions]
            sel_lon = lons[selected_positions]
            dists = _acsp_point_distances_m(lats[i], lons[i], sel_lat, sel_lon)
            d_min = float(np.min(dists)) if dists.size else float("inf")
            geo_gain = 1.0 - math.exp(-d_min / complementarity_scale_m)
            if has_env:
                env_d = np.sqrt(np.sum((env_matrix[selected_positions] - env_matrix[i]) ** 2, axis=1))
                env_min = float(np.min(env_d)) if env_d.size else float("inf")
                env_gain = 1.0 - math.exp(-env_min / env_scale)
            else:
                env_gain = float("nan")
            redundancy = math.exp(-d_min / redundancy_scale_m)
            if d_min < cluster_distance_m:
                redundancy = 1.0
            travel = float(np.clip(d_min / travel_scale_m, 0.0, 1.0))
        else:
            geo_gain = 0.0
            env_gain = 0.0 if has_env else float("nan")
            redundancy = 0.0
            travel = 0.0
        coverage = env_gain if (has_env and np.isfinite(env_gain)) else geo_gain

        novelty_signals: list[float] = []
        if region_labels is not None:
            novelty_signals.append(0.0 if str(region_labels.iloc[i]) in selected_regions else 1.0)
        if species_sets is not None:
            cand_species = species_sets[i]
            if cand_species:
                novelty_signals.append(len(cand_species - selected_species) / len(cand_species))
            else:
                novelty_signals.append(0.0)
        if novelty_signals:
            sampling_gap = 0.4 * float(static_gap[i]) + 0.6 * float(np.mean(novelty_signals))
        else:
            sampling_gap = float(static_gap[i])

        marginal = (
            w["base"] * float(base_score[i])
            + w["coverage"] * float(coverage)
            + w["exploration"] * float(exploration_gain[i])
            + w["gap"] * float(sampling_gap)
            + w["habitat"] * float(habitat_analogue_gain[i])
            + w["validation"] * float(validation_learning_gain[i])
            + w["access"] * float(access_gain[i])
            - w["redundancy"] * float(redundancy)
            - w["travel"] * float(travel)
        )
        return {
            "geo_gain": geo_gain,
            "env_gain": env_gain,
            "coverage": coverage,
            "redundancy": redundancy,
            "travel": travel,
            "sampling_gap": sampling_gap,
            "habitat": float(habitat_analogue_gain[i]),
            "validation": float(validation_learning_gain[i]),
            "access": float(access_gain[i]),
            "marginal": marginal,
        }

    def _selection_reason(step: int, comp: dict[str, float]) -> str:
        contributions = {
            "high priority/base score": w["base"] * float(base_score[i_sel]),
            ("environmental complementarity" if has_env else "geographic complementarity"): w["coverage"] * float(comp["coverage"]),
            "exploration value": w["exploration"] * float(exploration_gain[i_sel]),
            "sampling-gap coverage": w["gap"] * float(comp["sampling_gap"]),
            "local habitat analogue": w["habitat"] * float(comp["habitat"]),
            "field-validation learning": w["validation"] * float(comp["validation"]),
            "access feasibility": w["access"] * float(comp["access"]),
        }
        ranked = sorted(contributions.items(), key=lambda kv: kv[1], reverse=True)
        drivers = [name for name, val in ranked if val > 1e-6][:2]
        if not drivers:
            reason = f"Step {step}: selected by {mode}"
        else:
            reason = f"Step {step}: " + " + ".join(drivers)
        if comp["redundancy"] < 1e-6 and selected_positions:
            reason += "; low redundancy with already-selected sites"
        return reason

    while len(selected_positions) < k:
        remaining = [p for p in range(n) if p not in selected_set]
        if not remaining:
            break
        next_forced = [p for p in forced_positions if p not in selected_set]
        if next_forced:
            i_sel = next_forced[0]
            comp = _component_values(i_sel)
        else:
            best_i = None
            best_comp = None
            best_val = -float("inf")
            for i in remaining:
                comp_i = _component_values(i)
                if comp_i["marginal"] > best_val:
                    best_val = comp_i["marginal"]
                    best_i = i
                    best_comp = comp_i
            i_sel = best_i
            comp = best_comp
        if i_sel is None:
            break

        step = len(selected_positions) + 1
        records.append({
            "_pos": i_sel,
            "selection_step": step,
            "base_score": round(float(base_score[i_sel]), 4),
            "geographic_complementarity_gain": round(float(comp["geo_gain"]), 4),
            "environmental_complementarity_gain": (round(float(comp["env_gain"]), 4) if np.isfinite(comp["env_gain"]) else np.nan),
            "habitat_analogue_gain": round(float(comp["habitat"]), 4),
            "exploration_gain": round(float(exploration_gain[i_sel]), 4),
            "sampling_gap_gain": round(float(comp["sampling_gap"]), 4),
            "validation_learning_gain": round(float(comp["validation"]), 4),
            "access_gain": round(float(comp["access"]), 4),
            "redundancy_penalty": round(float(comp["redundancy"]), 4),
            "travel_penalty": round(float(comp["travel"]), 4),
            "marginal_gain_score": round(float(comp["marginal"]), 4),
            "selection_reason": _selection_reason(step, comp),
            "selection_algorithm": mode,
        })
        selected_positions.append(i_sel)
        selected_set.add(i_sel)
        if region_labels is not None:
            selected_regions.add(str(region_labels.iloc[i_sel]))
        if species_sets is not None:
            selected_species |= species_sets[i_sel]

    if not records:
        empty = df.head(0).copy()
        for col in ACSP_GAIN_COLUMNS:
            if col not in empty.columns:
                empty[col] = []
        return empty

    result_rows = []
    for rec in records:
        pos = rec.pop("_pos")
        row = df.iloc[pos].to_dict()
        if not has_env and "environmental_complementarity_gain" in rec:
            rec.pop("environmental_complementarity_gain")
        row.update(rec)
        result_rows.append(row)
    result = pd.DataFrame(result_rows)
    return result.reset_index(drop=True)


def acsp_merge_columns(selected_df: pd.DataFrame, acsp_result: Optional[pd.DataFrame]) -> pd.DataFrame:
    """Merge ACSP gain columns onto a selected-site dataframe by site_id (no-op if no ACSP result)."""
    if selected_df is None or selected_df.empty or acsp_result is None or acsp_result.empty:
        return selected_df
    merge_cols = [c for c in ACSP_GAIN_COLUMNS if c in acsp_result.columns]
    if not merge_cols:
        return selected_df
    right = acsp_result[["site_id"] + merge_cols].copy()
    right["site_id"] = right["site_id"].astype(int)
    out = selected_df.copy()
    drop_existing = [c for c in merge_cols if c in out.columns]
    if drop_existing:
        out = out.drop(columns=drop_existing)
    out["_merge_site_id"] = out["site_id"].astype(int)
    out = out.merge(right, left_on="_merge_site_id", right_on="site_id", how="left", suffixes=("", "_acsp"))
    out = out.drop(columns=["_merge_site_id"] + [c for c in out.columns if c.endswith("_acsp")], errors="ignore")
    return out


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
    # Vectorised greedy nearest-neighbour ordering. Uses numpy haversine instead of the
    # previous per-row geopy geodesic, which was O(n²) geodesic calls on every rerun.
    work = sites.copy().reset_index(drop=True)
    n = len(work)
    start_idx = int(max(0, min(start_idx, n - 1)))
    lats = pd.to_numeric(work["latitude"], errors="coerce").to_numpy(dtype=float)
    lons = pd.to_numeric(work["longitude"], errors="coerce").to_numpy(dtype=float)
    visited = np.zeros(n, dtype=bool)
    visited[start_idx] = True
    order = [start_idx]
    for _ in range(n - 1):
        cur = order[-1]
        dists = _acsp_point_distances_m(lats[cur], lons[cur], lats, lons)
        dists[visited] = np.inf
        nxt = int(np.argmin(dists))
        order.append(nxt)
        visited[nxt] = True
    return work.iloc[order].reset_index(drop=True)


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
    if var in set(TOPOGRAPHY_VARS):
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


def clean_environment_array(values: Any, nodata: Optional[float] = None) -> np.ndarray:
    arr = np.asarray(values, dtype=float).copy()
    if nodata is not None and np.isfinite(float(nodata)):
        arr[np.isclose(arr, float(nodata), rtol=0.0, atol=0.0)] = np.nan
    arr[~np.isfinite(arr)] = np.nan
    arr[(arr < -ENV_SENTINEL_ABS) | (arr > ENV_SENTINEL_ABS)] = np.nan
    return arr


def extreme_environment_sentinel_present(df: pd.DataFrame, variables: list[str]) -> bool:
    if not variables or df.empty:
        return False
    vals = df[variables].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
    finite = vals[np.isfinite(vals)]
    return bool(finite.size and ((finite < -ENV_SENTINEL_ABS).any() or (finite > ENV_SENTINEL_ABS).any()))


def clean_environment_table(df: pd.DataFrame, variables: list[str], label: str, status=None) -> tuple[pd.DataFrame, int]:
    out = df.copy()
    for var in variables:
        out[var] = clean_environment_array(pd.to_numeric(out[var], errors="coerce").to_numpy(dtype=float))
    if extreme_environment_sentinel_present(out, variables):
        raise RuntimeError(f"{label}: extreme raster NoData/fill values remain after cleaning; VIF was stopped.")
    before = len(out)
    out = out.dropna(subset=variables).reset_index(drop=True)
    dropped = before - len(out)
    if dropped and status is not None:
        status.write(f"{label}: dropped {dropped:,} rows with invalid raster/environment values before VIF/SDM.")
    return out, dropped


def sample_raster_values_fast(points: pd.DataFrame, raster_path: str, lat_col: str, lon_col: str, derived: Optional[str] = None) -> np.ndarray:
    if points.empty:
        return np.array([], dtype=float)
    with rasterio.open(raster_path) as src:
        coords = points[[lon_col, lat_col]].to_numpy(dtype=float)
        rc = np.array([src.index(float(lon), float(lat)) for lon, lat in coords], dtype=int)
        rows, cols = rc[:, 0], rc[:, 1]
        pad = 1 if derived in {"slope", "aspect", "roughness", "tpi"} else 0
        r0 = max(0, int(rows.min()) - pad); r1 = min(src.height - 1, int(rows.max()) + pad)
        c0 = max(0, int(cols.min()) - pad); c1 = min(src.width - 1, int(cols.max()) + pad)
        window = Window(c0, r0, c1 - c0 + 1, r1 - r0 + 1)
        arr = clean_environment_array(src.read(1, window=window, boundless=True, fill_value=np.nan).astype(float), src.nodata)
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
                center = arr[rr, cc] if 0 <= rr < arr.shape[0] and 0 <= cc < arr.shape[1] else np.nan
                if derived == "roughness":
                    values[i] = np.nanmax(sub) - np.nanmin(sub)
                elif derived == "tpi":
                    values[i] = center - np.nanmean(sub) if np.isfinite(center) else np.nan
                elif sub.shape[0] >= 2 and sub.shape[1] >= 2:
                    gy, gx = np.gradient(sub)
                    if not (np.isfinite(gy).any() or np.isfinite(gx).any()):
                        continue
                    if derived == "aspect":
                        if not (np.isfinite(gy).any() and np.isfinite(gx).any()):
                            continue
                        values[i] = (math.degrees(math.atan2(float(np.nanmean(gy)), float(np.nanmean(gx)))) + 360.0) % 360.0
                    else:
                        grad_mag = np.sqrt(gy ** 2 + gx ** 2)
                        if np.isfinite(grad_mag).any():
                            values[i] = np.nanmean(grad_mag)
        return clean_environment_array(values)


def _coords_in_raster_crs(src: rasterio.io.DatasetReader, points: pd.DataFrame, lat_col: str, lon_col: str) -> np.ndarray:
    coords = points[[lon_col, lat_col]].to_numpy(dtype=float)
    if src.crs is not None and str(src.crs).upper() not in {"EPSG:4326", "OGC:CRS84"}:
        xs, ys = rio_transform("EPSG:4326", src.crs, coords[:, 0].tolist(), coords[:, 1].tolist())
        return np.column_stack([xs, ys]).astype(float)
    return coords


def sample_uploaded_raster_values(points: pd.DataFrame, raster_path: str, lat_col: str, lon_col: str, derived: Optional[str] = None) -> np.ndarray:
    """Sample a user raster at WGS84 point coordinates, including DEM-derived local terrain metrics."""
    if not raster_path or points.empty:
        return np.array([], dtype=float)
    with rasterio.open(raster_path) as src:
        coords = _coords_in_raster_crs(src, points, lat_col, lon_col)
        rc = np.array([src.index(float(x), float(y)) for x, y in coords], dtype=int)
        values = np.full(len(points), np.nan, dtype=float)
        pad = 1 if derived in {"slope", "aspect", "roughness", "tpi"} else 0
        for i, (rr, cc) in enumerate(rc):
            if rr < 0 or cc < 0 or rr >= src.height or cc >= src.width:
                continue
            window = Window(max(0, cc - pad), max(0, rr - pad), min(src.width, cc + pad + 1) - max(0, cc - pad), min(src.height, rr + pad + 1) - max(0, rr - pad))
            arr = clean_environment_array(src.read(1, window=window, boundless=True, fill_value=np.nan).astype(float), src.nodata)
            if arr.size == 0 or np.all(np.isnan(arr)):
                continue
            center = arr[min(pad, arr.shape[0] - 1), min(pad, arr.shape[1] - 1)]
            if derived is None:
                values[i] = center
            elif derived == "roughness":
                values[i] = np.nanmax(arr) - np.nanmin(arr)
            elif derived == "tpi":
                values[i] = center - np.nanmean(arr) if np.isfinite(center) else np.nan
            elif arr.shape[0] >= 2 and arr.shape[1] >= 2:
                gy, gx = np.gradient(arr)
                if not (np.isfinite(gy).any() or np.isfinite(gx).any()):
                    continue
                if derived == "aspect":
                    if not (np.isfinite(gy).any() and np.isfinite(gx).any()):
                        continue
                    values[i] = (math.degrees(math.atan2(float(np.nanmean(gy)), float(np.nanmean(gx)))) + 360.0) % 360.0
                else:
                    grad_mag = np.sqrt(gy ** 2 + gx ** 2)
                    if np.isfinite(grad_mag).any():
                        values[i] = np.nanmean(grad_mag)
        return clean_environment_array(values)


def densify_lonlat_coords(coords: list[tuple[float, float]], step_m: float = 75.0) -> list[tuple[float, float]]:
    """Add intermediate lon/lat points along line segments for better nearest-distance proxies."""
    if len(coords) < 2:
        return coords
    out: list[tuple[float, float]] = []
    step = max(10.0, float(step_m))
    for (lon1, lat1), (lon2, lat2) in zip(coords[:-1], coords[1:]):
        if not out:
            out.append((float(lon1), float(lat1)))
        try:
            dist_m = float(geodesic((lat1, lon1), (lat2, lon2)).meters)
        except Exception:
            dist_m = 0.0
        n_steps = int(max(1, math.ceil(dist_m / step)))
        for j in range(1, n_steps + 1):
            frac = j / n_steps
            out.append((float(lon1 + (lon2 - lon1) * frac), float(lat1 + (lat2 - lat1) * frac)))
    return out


def extract_geojson_vertices(path: Optional[str], densify_step_m: float = 75.0) -> np.ndarray:
    if not path:
        return np.empty((0, 2), dtype=float)
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return np.empty((0, 2), dtype=float)
    geoms = []
    if payload.get("type") == "FeatureCollection":
        geoms = [shape(f.get("geometry")) for f in payload.get("features", []) if f.get("geometry")]
    elif payload.get("type") == "Feature":
        geoms = [shape(payload.get("geometry"))]
    else:
        geoms = [shape(payload)]
    coords: list[tuple[float, float]] = []
    for geom in geoms:
        if geom.is_empty:
            continue
        if hasattr(geom, "geoms"):
            parts = geom.geoms
        else:
            parts = [geom]
        for part in parts:
            if hasattr(part, "coords"):
                coords.extend(densify_lonlat_coords([(float(x), float(y)) for x, y in part.coords], densify_step_m))
            elif hasattr(part, "exterior"):
                coords.extend(densify_lonlat_coords([(float(x), float(y)) for x, y in part.exterior.coords], densify_step_m))
    return np.array(coords, dtype=float) if coords else np.empty((0, 2), dtype=float)


def write_vertices_geojson(vertices_lonlat: np.ndarray, path: Path) -> Optional[str]:
    if vertices_lonlat.size == 0:
        return None
    coords = [[float(x), float(y)] for x, y in vertices_lonlat]
    payload = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {}, "geometry": {"type": "LineString", "coordinates": coords}}]}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


@st.cache_data(show_spinner=False)
def app_coastline_geojson_for_bounds(west: float, south: float, east: float, north: float) -> Optional[str]:
    """Create a lightweight coastline-distance proxy from the app's built-in land boundary."""
    try:
        land = load_land_geometry()
        roi = box(float(west), float(south), float(east), float(north)).buffer(0.25)
        boundary = land.intersection(roi).boundary
        coords: list[tuple[float, float]] = []
        parts = boundary.geoms if hasattr(boundary, "geoms") else [boundary]
        for part in parts:
            if hasattr(part, "coords"):
                coords.extend(densify_lonlat_coords([(float(x), float(y)) for x, y in part.coords], 75.0))
        arr = np.array(coords, dtype=float) if coords else np.empty((0, 2), dtype=float)
        digest = hashlib.sha1(f"{west:.4f},{south:.4f},{east:.4f},{north:.4f}".encode()).hexdigest()[:12]
        return write_vertices_geojson(arr, CACHE_DIR / "app_layers" / f"coastline_{digest}.geojson")
    except Exception:
        return None


def _overpass_to_vertices(payload: dict[str, Any]) -> np.ndarray:
    nodes: dict[int, tuple[float, float]] = {}
    coords: list[tuple[float, float]] = []
    for element in payload.get("elements", []):
        if element.get("type") == "node" and "lon" in element and "lat" in element:
            nodes[int(element["id"])] = (float(element["lon"]), float(element["lat"]))
    for element in payload.get("elements", []):
        if element.get("type") == "node" and "lon" in element and "lat" in element:
            coords.append((float(element["lon"]), float(element["lat"])))
        elif "geometry" in element:
            coords.extend(densify_lonlat_coords([(float(p["lon"]), float(p["lat"])) for p in element.get("geometry", []) if "lon" in p and "lat" in p], 75.0))
        elif "nodes" in element:
            coords.extend(densify_lonlat_coords([nodes[nid] for nid in element.get("nodes", []) if nid in nodes], 75.0))
    return np.array(coords, dtype=float) if coords else np.empty((0, 2), dtype=float)


@st.cache_data(show_spinner=False)
def fetch_osm_vertices_geojson(kind: str, west: float, south: float, east: float, north: float) -> Optional[str]:
    """Fetch lightweight app-provided OSM vertices for access/edge distance proxies."""
    bbox = f"{float(south):.6f},{float(west):.6f},{float(north):.6f},{float(east):.6f}"
    if kind == "roads":
        selector = 'way["highway"]["highway"!~"path|footway|cycleway|bridleway|steps|track"]'
    elif kind == "trails":
        selector = 'way["highway"~"path|footway|bridleway|steps|track"]'
    elif kind == "forest_edge":
        selector = 'forest'
    else:
        return None
    if kind in {"roads", "trails"}:
        query = f"[out:json][timeout:25];({selector}({bbox}););out geom;"
    else:
        query = (
            f"[out:json][timeout:25];("
            f"way[\"landuse\"=\"forest\"]({bbox});"
            f"way[\"natural\"=\"wood\"]({bbox});"
            f"relation[\"landuse\"=\"forest\"]({bbox});"
            f"relation[\"natural\"=\"wood\"]({bbox});"
            f");out geom;"
        )
    digest = hashlib.sha1(f"{kind}:{bbox}:{selector}".encode()).hexdigest()[:12]
    out_path = CACHE_DIR / "app_layers" / f"osm_{kind}_{digest}.geojson"
    if out_path.exists() and out_path.stat().st_size > 0:
        return str(out_path)
    try:
        response = requests.post(OVERPASS_URL, data={"data": query}, timeout=45, headers={"User-Agent": GBIF_REQUEST_HEADERS["User-Agent"]})
        response.raise_for_status()
        vertices = _overpass_to_vertices(response.json())
        return write_vertices_geojson(vertices, out_path)
    except Exception:
        return None


def app_provided_habitat_layers(bounds: tuple[float, float, float, float], include_osm: bool) -> dict[str, Optional[str]]:
    west, south, east, north = bounds
    layers: dict[str, Optional[str]] = {
        "dem": None,
        "ndvi": None,
        "landcover": None,
        "roads": None,
        "trails": None,
        "coastline": app_coastline_geojson_for_bounds(west, south, east, north),
        "forest_edge": None,
    }
    if include_osm:
        layers["roads"] = fetch_osm_vertices_geojson("roads", west, south, east, north)
        layers["trails"] = fetch_osm_vertices_geojson("trails", west, south, east, north)
        layers["forest_edge"] = fetch_osm_vertices_geojson("forest_edge", west, south, east, north)
    return layers


def cache_uploaded_habitat_raster(uploaded: Any, layer_name: str) -> Optional[str]:
    """Persist a Streamlit GeoTIFF upload in the app cache for rasterio."""
    if uploaded is None:
        return None
    payload = uploaded.getvalue()
    if not payload:
        return None
    digest = hashlib.sha1(payload).hexdigest()[:16]
    suffix = Path(getattr(uploaded, "name", "layer.tif")).suffix.lower()
    suffix = suffix if suffix in {".tif", ".tiff"} else ".tif"
    path = CACHE_DIR / "uploaded_layers" / f"{layer_name}_{digest}{suffix}"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(payload)
    return str(path)


def raster_pixel_resolution_m(path: Optional[str], reference_latitude: float) -> Optional[float]:
    """Return the coarser raster pixel dimension in metres when CRS units are known."""
    if not path:
        return None
    try:
        with rasterio.open(path) as src:
            x_size = abs(float(src.transform.a))
            y_size = abs(float(src.transform.e))
            if src.crs and src.crs.is_geographic:
                x_m = x_size * 111_320.0 * max(0.2, math.cos(math.radians(float(reference_latitude))))
                y_m = y_size * 111_320.0
                return max(x_m, y_m)
            if src.crs and src.crs.is_projected:
                unit_factor = 1.0
                try:
                    factor = src.crs.linear_units_factor
                    unit_factor = float(factor[1] if isinstance(factor, tuple) else factor)
                except Exception:
                    pass
                return max(x_size, y_size) * unit_factor
    except Exception:
        return None
    return None


def nearest_vector_distance_m(points: pd.DataFrame, vertices_lonlat: np.ndarray, lat_col: str, lon_col: str) -> np.ndarray:
    if points.empty or vertices_lonlat.size == 0:
        return np.full(len(points), np.nan, dtype=float)
    point_latlon = points[[lat_col, lon_col]].to_numpy(dtype=float)
    vertex_latlon = np.column_stack([vertices_lonlat[:, 1], vertices_lonlat[:, 0]])
    tree = BallTree(np.radians(vertex_latlon), metric="haversine")
    dist_rad, _ = tree.query(np.radians(point_latlon), k=1)
    return dist_rad[:, 0] * EARTH_RADIUS_M


def buffered_profile_sample_points(points: pd.DataFrame, radius_m: float, lat_col: str = "latitude", lon_col: str = "longitude") -> pd.DataFrame:
    """Create small local sample points around known occurrences for habitat-profile extraction."""
    base = points.dropna(subset=[lat_col, lon_col]).copy()
    if base.empty:
        return base
    radius = max(0.0, float(radius_m))
    if radius <= 0:
        return base[[lat_col, lon_col]].rename(columns={lat_col: "latitude", lon_col: "longitude"}).reset_index(drop=True)
    rows: list[dict[str, float]] = []
    bearings = [0, 45, 90, 135, 180, 225, 270, 315]
    for _, row in base.iterrows():
        lat = float(row[lat_col]); lon = float(row[lon_col])
        rows.append({"latitude": lat, "longitude": lon})
        for dist in [radius * 0.5, radius]:
            for bearing in bearings:
                dest = geodesic(meters=dist).destination((lat, lon), bearing)
                rows.append({"latitude": float(dest.latitude), "longitude": float(dest.longitude)})
    return pd.DataFrame(rows).drop_duplicates().reset_index(drop=True)


def extract_potential_layer_values(points: pd.DataFrame, layers: dict[str, Optional[str]], lat_col: str = "latitude", lon_col: str = "longitude") -> pd.DataFrame:
    """Extract high-resolution habitat-discovery layer values for candidate or known points."""
    out = points.copy()
    dem_path = layers.get("dem")
    if dem_path:
        out["elevation"] = sample_uploaded_raster_values(out, dem_path, lat_col, lon_col)
        out["slope"] = sample_uploaded_raster_values(out, dem_path, lat_col, lon_col, "slope")
        out["aspect"] = sample_uploaded_raster_values(out, dem_path, lat_col, lon_col, "aspect")
        out["roughness"] = sample_uploaded_raster_values(out, dem_path, lat_col, lon_col, "roughness")
        out["tpi"] = sample_uploaded_raster_values(out, dem_path, lat_col, lon_col, "tpi")
    ndvi_path = layers.get("ndvi")
    if ndvi_path:
        out["ndvi"] = sample_uploaded_raster_values(out, ndvi_path, lat_col, lon_col)
    landcover_path = layers.get("landcover")
    if landcover_path:
        out["landcover"] = sample_uploaded_raster_values(out, landcover_path, lat_col, lon_col)
    for key, col in [
        ("roads", "distance_to_road_m"),
        ("trails", "distance_to_trail_m"),
        ("coastline", "distance_to_coast_m"),
        ("forest_edge", "distance_to_forest_edge_m"),
    ]:
        vertices = extract_geojson_vertices(layers.get(key))
        if vertices.size:
            out[col] = nearest_vector_distance_m(out, vertices, lat_col, lon_col)
    return out


def extract_environment(points: pd.DataFrame, variables: list[str], lat_col: str, lon_col: str, resolution: str, status=None) -> pd.DataFrame:
    out = points.copy()
    for i, var in enumerate(variables, start=1):
        if status is not None:
            status.write(f"Extracting {var} ({resolution}) [{i}/{len(variables)}]...")
        if var in {"slope", "aspect", "tpi"}:
            out[var] = sample_raster_values_fast(out, get_worldclim_raster_path("elevation", resolution), lat_col, lon_col, var)
        elif var == "slope":
            out[var] = sample_raster_values_fast(out, get_worldclim_raster_path("elevation", resolution), lat_col, lon_col, "slope")
        elif var == "roughness":
            out[var] = sample_raster_values_fast(out, get_worldclim_raster_path("elevation", resolution), lat_col, lon_col, "roughness")
        else:
            out[var] = sample_raster_values_fast(out, get_worldclim_raster_path(var, resolution), lat_col, lon_col)
    return out


def compute_vif_table(df: pd.DataFrame, variables: list[str]) -> pd.DataFrame:
    if len(variables) == 0:
        return pd.DataFrame(columns=["variable", "vif", "vif_warning"])
    if extreme_environment_sentinel_present(df, variables):
        raise RuntimeError("Extreme raster NoData/fill values remain in environmental variables; VIF was stopped.")
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


def auto_sdm_partition(n_occ: int, extent_geom) -> tuple[str, str]:
    """Choose the best SDM validation method based on record count and geographic spread.

    Decision rationale
    ------------------
    block      — standard SDM best-practice (Valavi et al. 2019 blockCV). Tests
                 transferability across large spatial gradients. Appropriate for
                 50 – several-thousand records over a broad area. Because the SDM
                 presence cap is 300, block covers nearly all realistic use cases.
    checkerboard — fine-grained checkerboard pattern; better at detecting overfit
                 to local spatial autocorrelation when records are very dense
                 (>= 500). With a 300-point cap this threshold is unreachable in
                 normal use, so checkerboard is available only via manual override.
    random k-fold / holdout — ignore spatial structure; only appropriate when
                 records are few or the geographic extent is small.
    jackknife  — leave-one-out; for tiny datasets (< 15).

    Returns (partition_method, reason_text).
    """
    geo_spread_deg: Optional[float] = None
    if extent_geom is not None and not extent_geom.is_empty:
        minx, miny, maxx, maxy = extent_geom.bounds
        geo_spread_deg = min(maxx - minx, maxy - miny)

    if n_occ < 15:
        return (
            "jackknife",
            f"**Jackknife** (leave-one-out) — {n_occ} records is very few. "
            "Each record is held out once as a test point; the model is retrained n times. "
            "This squeezes the most information out of a tiny dataset.",
        )
    if n_occ < 30 or (geo_spread_deg is not None and geo_spread_deg < 2.0):
        spread_note = f" Geographic spread is also narrow ({geo_spread_deg:.1f}°)." if geo_spread_deg is not None and geo_spread_deg < 2.0 else ""
        return (
            "random holdout",
            f"**Random holdout** (75 % train / 25 % test) — {n_occ} records.{spread_note} "
            "Spatial block partitioning needs enough records on both sides of each block boundary; "
            "with few records or a small extent a random split avoids empty test folds.",
        )
    if n_occ < 50:
        return (
            "random k-fold",
            f"**Random 5-fold cross-validation** — {n_occ} records. "
            "Enough for k-fold but not yet enough to fill all four spatial block quadrants reliably. "
            "Five-fold CV gives a stable AUC estimate without wasting too much training data.",
        )
    # 50 – cap (300): block is the SDM community standard.
    # Checkerboard is only better for very dense datasets (500+), which the 300-point cap prevents.
    return (
        "block",
        f"**Spatial block** cross-validation — {n_occ} records. "
        "The extent is split into four geographic quadrants; each quadrant is held out in turn. "
        "Block CV tests whether the model predicts across space it has never seen — "
        "the standard rigorous approach for SDM (Valavi et al. 2019). "
        "Checkerboard offers finer granularity only at very high record counts (500+); "
        "with the 300-point cap, block is the right choice here.",
    )


def vif_step(df: pd.DataFrame, variables: list[str], threshold: float) -> tuple[list[str], pd.DataFrame]:
    if extreme_environment_sentinel_present(df, variables):
        raise RuntimeError("Extreme raster NoData/fill values remain in environmental variables; VIF was stopped.")
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


def ecological_group(var: str) -> str:
    if var in {"elevation", "slope", "roughness"}:
        return "topography"
    if re.match(r"^bio\d+$", var, re.IGNORECASE):
        n = int(re.sub(r"\D", "", var))
        if n in {1, 5, 6, 7, 8, 9, 10, 11}:
            return "temperature"
        if n in {2, 3, 4}:
            return "temperature seasonality"
        if n in {12, 13, 14, 16, 17, 18, 19}:
            return "precipitation"
        if n == 15:
            return "precipitation seasonality"
        return "climate"
    return "other"


def add_variable_selection_fields(diag: pd.DataFrame, kept: list[str], strategy: str, reason_map: Optional[dict[str, str]] = None, stage_map: Optional[dict[str, str]] = None, fallback_vars: Optional[set[str]] = None, protected_vars: Optional[set[str]] = None) -> pd.DataFrame:
    out = diag.copy() if diag is not None and not diag.empty else pd.DataFrame({"variable": kept})
    reason_map = reason_map or {}
    stage_map = stage_map or {}
    fallback_vars = fallback_vars or set()
    protected_vars = protected_vars or set()
    if "variable" not in out.columns:
        out["variable"] = []
    kept_set = set(kept)
    if "group" not in out.columns:
        out["group"] = out["variable"].map(ecological_group)
    out["variable_selection_strategy"] = strategy
    out["final_status"] = out["variable"].apply(lambda v: "kept" if v in kept_set else "removed")
    out["reason"] = out["variable"].apply(lambda v: reason_map.get(v, "selected" if v in kept_set else "not selected by strategy"))
    out["protected_by_group"] = out["variable"].apply(lambda v: ecological_group(str(v)) if v in protected_vars else "")
    out["fallback_kept"] = out["variable"].apply(lambda v: bool(v in fallback_vars))
    out["vif_stage"] = out["variable"].apply(lambda v: stage_map.get(v, "not_run" if strategy != "VIF stepwise" else "final"))
    return out


def correlation_filter_variables(env_df: pd.DataFrame, variables: list[str], threshold: float, protected_vars: Optional[set[str]] = None) -> tuple[list[str], dict[str, str]]:
    protected_vars = protected_vars or set()
    kept = list(dict.fromkeys(variables))
    reasons = {v: "correlation <= threshold" for v in kept}
    if len(kept) <= 1:
        return kept, reasons
    X = env_df[kept].apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan)
    X_imp = pd.DataFrame(SimpleImputer(strategy="median").fit_transform(X), columns=kept)
    corr = X_imp.corr().abs()
    while len(kept) > 1:
        sub = corr.loc[kept, kept].copy()
        np.fill_diagonal(sub.values, 0.0)
        max_corr = float(sub.max().max())
        if not np.isfinite(max_corr) or max_corr <= float(threshold):
            break
        pair = np.where(sub.to_numpy() == max_corr)
        a = str(sub.index[int(pair[0][0])])
        b = str(sub.columns[int(pair[1][0])])
        if a in protected_vars and b not in protected_vars:
            remove = b
        elif b in protected_vars and a not in protected_vars:
            remove = a
        else:
            mean_corr = sub.mean().sort_values(ascending=False)
            remove = str(mean_corr.index[0])
        kept.remove(remove)
        reasons[remove] = f"removed: correlated with another selected variable above {threshold:.2f}"
    for v in kept:
        reasons[v] = "kept by correlation filter"
    return kept, reasons


def ecological_preset_variables(env_df: pd.DataFrame, variables: list[str], corr_threshold: float = 0.80) -> tuple[list[str], dict[str, str], set[str]]:
    selected = [v for v in ECOLOGICAL_PRESET_VARS if v in variables]
    fallback_vars: set[str] = set()
    if not any(re.match(r"^bio\d+$", v, re.IGNORECASE) for v in selected):
        bio_vars = [v for v in variables if re.match(r"^bio\d+$", v, re.IGNORECASE)]
        if bio_vars:
            X = env_df[bio_vars].apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan)
            X_imp = pd.DataFrame(SimpleImputer(strategy="median").fit_transform(X), columns=bio_vars)
            mean_corr = X_imp.corr().abs().mean()
            best_bio = str(mean_corr.idxmin())
            selected.append(best_bio)
            fallback_vars.add(best_bio)
    selected = list(dict.fromkeys(selected))
    if not selected:
        selected = list(dict.fromkeys(variables[: min(4, len(variables))]))
        fallback_vars.update(selected)
    protected_vars = set(selected)
    kept, reasons = correlation_filter_variables(env_df, selected, corr_threshold, protected_vars)
    for v in selected:
        reasons[v] = "ecological representative preset" if v in kept else reasons.get(v, "removed by preset correlation filter")
    return kept, reasons, fallback_vars


def select_environment_variables(
    env_df: pd.DataFrame,
    variables: list[str],
    strategy: str,
    vif_threshold: float = 10.0,
    corr_threshold: float = 0.80,
    custom_variables: Optional[list[str]] = None,
) -> tuple[list[str], pd.DataFrame]:
    variables = list(dict.fromkeys([v for v in variables if v]))
    if not variables:
        return [], pd.DataFrame()
    diag = ssdm_variable_diagnostics(env_df, variables)
    if strategy == "Advanced custom selection":
        kept = list(dict.fromkeys([v for v in (custom_variables or variables) if v in variables]))
        reasons = {v: "kept by advanced custom selection" for v in kept}
        return kept, add_variable_selection_fields(diag, kept, strategy, reasons)
    if strategy == "Ecological preset / representative climate set":
        kept, reasons, fallback_vars = ecological_preset_variables(env_df, variables, corr_threshold)
        protected_vars = set([v for v in ECOLOGICAL_PRESET_VARS if v in variables])
        return kept, add_variable_selection_fields(diag, kept, strategy, reasons, fallback_vars=fallback_vars, protected_vars=protected_vars)
    if strategy == "Correlation filter":
        protected = set([v for v in ECOLOGICAL_PRESET_VARS if v in variables])
        kept, reasons = correlation_filter_variables(env_df, variables, corr_threshold, protected)
        return kept, add_variable_selection_fields(diag, kept, strategy, reasons, protected_vars=protected)
    if strategy == "VIF stepwise":
        kept, vif_tbl = vif_step(env_df, variables, vif_threshold)
        reasons = {}
        stage = {}
        if not vif_tbl.empty:
            for _, row in vif_tbl.iterrows():
                var = str(row["variable"])
                status_val = str(row.get("status", "kept"))
                reasons[var] = "kept after VIF stepwise" if status_val == "kept" else f"removed by VIF > {vif_threshold:g}"
                stage[var] = status_val
        out = add_variable_selection_fields(diag, kept, strategy, reasons, stage_map=stage)
        if not vif_tbl.empty and "variable" in vif_tbl.columns:
            out = out.drop(columns=[c for c in ["vif", "vif_warning", "status"] if c in out.columns], errors="ignore").merge(vif_tbl, on="variable", how="left")
            out["vif_stage"] = out["variable"].map(stage).fillna(out.get("vif_stage", "final"))
            out["final_status"] = out["variable"].apply(lambda v: "kept" if v in set(kept) else "removed")
        return kept, out
    kept = list(variables)
    reasons = {v: "No VIF/filtering selected; variable retained unless invalid rows were removed by NoData cleaning" for v in kept}
    return kept, add_variable_selection_fields(diag, kept, "No VIF", reasons)


def ssdm_variable_diagnostics(env_df: pd.DataFrame, variables: list[str]) -> pd.DataFrame:
    """Diagnostic table (variable, group, stats, max_abs_corr, VIF) computed before SSDM VIF filtering."""
    if not variables or env_df.empty:
        return pd.DataFrame()
    X = env_df[variables].apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan)
    X_imp = pd.DataFrame(SimpleImputer(strategy="median").fit_transform(X), columns=variables)
    corr_mat = X_imp.corr().abs()
    vif_raw = compute_vif_table(X_imp, variables)
    vif_map = dict(zip(vif_raw["variable"], vif_raw["vif"]))
    rows = []
    for var in variables:
        col = X[var]
        if re.match(r"^bio\d+$", var, re.IGNORECASE):
            group = "climate"
        elif var in {"elevation", "slope", "roughness"}:
            group = "topography"
        else:
            group = "other"
        others = corr_mat[var].drop(var) if var in corr_mat.columns else pd.Series(dtype=float)
        rows.append({
            "variable": var,
            "group": group,
            "min": round(float(col.min()), 4) if col.notna().any() else np.nan,
            "max": round(float(col.max()), 4) if col.notna().any() else np.nan,
            "sd": round(float(col.std()), 4) if col.notna().any() else np.nan,
            "unique_values": int(col.nunique()),
            "missing_fraction": round(float(col.isna().mean()), 4),
            "max_abs_corr": round(float(others.max()), 4) if not others.empty else np.nan,
            "vif": vif_map.get(var, np.nan),
            "status": "to_evaluate",
        })
    return pd.DataFrame(rows)


def run_ssdm_shared_vif(
    env_df: pd.DataFrame,
    variables: list[str],
    vif_threshold: float,
    strategy: str = "No VIF",
    corr_threshold: float = 0.80,
    custom_variables: Optional[list[str]] = None,
) -> tuple[list[str], pd.DataFrame, bool]:
    """Run shared SSDM variable selection once on pooled environmental data."""
    kept, diag = select_environment_variables(env_df, variables, strategy, vif_threshold, corr_threshold, custom_variables)

    bio_orig = [v for v in variables if re.match(r"^bio\d+$", v, re.IGNORECASE)]
    bio_kept = [v for v in kept if re.match(r"^bio\d+$", v, re.IGNORECASE)]
    fallback_used = False

    if bio_orig and not bio_kept:
        X = env_df[bio_orig].apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan)
        X_imp = pd.DataFrame(SimpleImputer(strategy="median").fit_transform(X), columns=bio_orig)
        mean_corr = X_imp.corr().abs().mean()
        best_bio = str(mean_corr.idxmin())
        if best_bio not in kept:
            kept = list(kept) + [best_bio]
        fallback_used = True
        if not diag.empty:
            diag.loc[diag["variable"] == best_bio, "final_status"] = "kept"
            diag.loc[diag["variable"] == best_bio, "reason"] = "fallback-kept: BIO climate protection after shared variable selection"
            diag.loc[diag["variable"] == best_bio, "fallback_kept"] = True
            diag.loc[diag["variable"] == best_bio, "protected_by_group"] = "climate"

    return kept, diag, fallback_used


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


def fit_sdm(train_df: pd.DataFrame, variables: list[str], algorithms: list[str], partition_method: str, k_folds: int, checkerboard_deg: float, holdout_test_size: float = 0.25) -> dict[str, Any]:
    data = train_df.copy()
    X = data[variables].apply(pd.to_numeric, errors="coerce")
    y = data["presence"].astype(int)
    if y.nunique() < 2:
        raise ValueError("Need both presence and background points for SDM.")
    metrics = []; models = {}
    if partition_method == "random holdout":
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=float(holdout_test_size), random_state=42, stratify=y)
        for alg in algorithms:
            model = make_model(alg); model.fit(X_train, y_train)
            auc = float(roc_auc_score(y_test, model.predict_proba(X_test)[:, 1]))
            metrics.append({"algorithm": alg, "partition_method": partition_method, "fold": "diagnostic", "auc": round(auc, 3), "warning": auc_warning(auc, partition_method)})
            model.fit(X, y); models[alg] = model
    elif partition_method == "jackknife":
        # True leave-one-out jackknife over presence rows.
        # For each presence record i, train on all other rows, predict on row i.
        # Background rows are always included in the training set.
        X_all = data[variables].apply(pd.to_numeric, errors="coerce")
        y_all = data["presence"].astype(int)
        pres_idx = list(data.index[y_all == 1])
        n_pres = len(pres_idx)
        for alg in algorithms:
            fold_aucs = []
            for fold_num, test_i in enumerate(pres_idx, start=1):
                train_mask = data.index != test_i
                X_tr = X_all.loc[train_mask]; y_tr = y_all.loc[train_mask]
                if y_tr.nunique() < 2:
                    continue
                model_loo = make_model(alg); model_loo.fit(X_tr, y_tr)
                prob = float(model_loo.predict_proba(X_all.loc[[test_i]])[:, 1][0])
                fold_aucs.append(prob)
                metrics.append({"algorithm": alg, "partition_method": partition_method, "fold": str(fold_num), "auc": round(prob, 3), "warning": ""})
            # For LOO the AUC is computed across all held-out presence predictions vs a random background sample.
            if fold_aucs:
                bg_idx_loo = list(data.index[y_all == 0])
                bg_sample = np.random.default_rng(42).choice(bg_idx_loo, size=min(len(bg_idx_loo), len(pres_idx) * 5), replace=False) if bg_idx_loo else []
                bg_probs = []
                if len(bg_sample):
                    final_model_tmp = make_model(alg); final_model_tmp.fit(X_all, y_all)
                    bg_probs = list(final_model_tmp.predict_proba(X_all.loc[bg_sample])[:, 1])
                all_probs = fold_aucs + bg_probs
                all_labels = [1] * len(fold_aucs) + [0] * len(bg_probs)
                try:
                    mean_auc = float(roc_auc_score(all_labels, all_probs)) if len(set(all_labels)) == 2 else float(np.mean(fold_aucs))
                except Exception:
                    mean_auc = float(np.mean(fold_aucs))
            else:
                mean_auc = np.nan
            metrics.append({"algorithm": alg, "partition_method": partition_method, "fold": "mean", "auc": round(mean_auc, 3) if np.isfinite(mean_auc) else np.nan, "warning": auc_warning(mean_auc, partition_method) if np.isfinite(mean_auc) else "no valid folds"})
            final_model = make_model(alg); final_model.fit(X_all, y_all); models[alg] = final_model
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
                metrics.append({"algorithm": alg, "partition_method": partition_method, "fold": str(int(fold)), "auc": round(auc, 3), "warning": auc_warning(auc, partition_method)})
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
        arr = clean_environment_array(src.read(1, window=window, out_shape=out_shape, resampling=Resampling.bilinear, boundless=True, fill_value=np.nan).astype(float), src.nodata)
    return arr, actual_bounds


def _build_prediction_grid_base(
    occ: pd.DataFrame, variables: list[str], resolution: str,
    area_mode: str, buffer_km: float, rectangle_margin_km: float, max_pixels: int,
    excluded_occ: Optional[pd.DataFrame], exclusion_buffer_km: float,
    status, status_msg: str,
) -> tuple[Any, pd.DataFrame, np.ndarray, np.ndarray, np.ndarray, int, int, tuple[float, float, float, float], int]:
    """Shared raster-grid builder for SDM and SSDM prediction.

    Returns (geom, env_df, valid_mask, lon_grid_flat, lat_grid_flat,
             out_h, out_w, (west2, south2, east2, north2), stride).
    """
    geom = prediction_area_geometry(occ, area_mode, buffer_km, rectangle_margin_km, excluded_occ, exclusion_buffer_km)
    if geom is None or geom.is_empty:
        raise RuntimeError("Prediction area could not be generated.")
    land = load_land_geometry()
    west, south, east, north = geom.bounds
    ref_var = "elevation" if any(v in {"elevation", "slope", "roughness"} for v in variables) else variables[0]
    with rasterio.open(get_worldclim_raster_path(ref_var, resolution)) as src:
        window = from_bounds(west, south, east, north, transform=src.transform).round_offsets().round_lengths()
        raw_h = max(1, int(window.height))
        raw_w = max(1, int(window.width))
    stride = max(1, int(math.ceil(math.sqrt((raw_h * raw_w) / max(1, int(max_pixels))))))
    out_h = max(1, int(math.ceil(raw_h / stride)))
    out_w = max(1, int(math.ceil(raw_w / stride)))
    if status is not None:
        status.write(status_msg.format(out_w=out_w, out_h=out_h, stride=stride))
    arrays: dict[str, np.ndarray] = {}
    actual_bounds = None
    elev_cache = None
    for var in variables:
        if var in {"slope", "roughness"}:
            if elev_cache is None:
                elev_cache, actual_bounds = read_window_array(get_worldclim_raster_path("elevation", resolution), (west, south, east, north), (out_h, out_w))
            gy, gx = np.gradient(elev_cache)
            arrays[var] = clean_environment_array(np.sqrt(gx**2 + gy**2) if var == "slope" else elev_cache - np.nanmean(elev_cache))
        else:
            arrays[var], actual_bounds = read_window_array(get_worldclim_raster_path(var, resolution), (west, south, east, north), (out_h, out_w))
    west2, south2, east2, north2 = actual_bounds
    lon_centers = np.linspace(west2 + (east2 - west2) / (2 * out_w), east2 - (east2 - west2) / (2 * out_w), out_w)
    lat_centers = np.linspace(north2 - (north2 - south2) / (2 * out_h), south2 + (north2 - south2) / (2 * out_h), out_h)
    lon_grid, lat_grid = np.meshgrid(lon_centers, lat_centers)
    env = pd.DataFrame({v: arrays[v].ravel() for v in variables})
    finite = np.isfinite(env.to_numpy()).all(axis=1)
    spatial = np.array([
        geom.covers(Point(float(lo), float(la))) and land.covers(Point(float(lo), float(la)))
        for la, lo in zip(lat_grid.ravel(), lon_grid.ravel())
    ])
    valid = finite & spatial
    return geom, env, valid, lon_grid.ravel(), lat_grid.ravel(), out_h, out_w, (west2, south2, east2, north2), stride


def build_predict_map(occ: pd.DataFrame, variables: list[str], resolution: str, sdm_result: dict[str, Any], area_mode: str, buffer_km: float, rectangle_margin_km: float, max_pixels: int, excluded_occ: Optional[pd.DataFrame] = None, exclusion_buffer_km: float = 0.0, status=None) -> tuple[dict[str, Any], pd.DataFrame]:
    _, X, valid, lon_flat, lat_flat, out_h, out_w, (west2, south2, east2, north2), stride = _build_prediction_grid_base(
        occ, variables, resolution, area_mode, buffer_km, rectangle_margin_km, max_pixels,
        excluded_occ, exclusion_buffer_km, status,
        "Predicting raster map: {out_w:,} × {out_h:,} cells; source stride={stride}",
    )
    if valid.sum() == 0:
        raise RuntimeError("No valid land raster cells were available for prediction.")
    pred_flat = np.full(X.shape[0], np.nan, dtype=float)
    preds = [model.predict_proba(X.loc[valid, variables])[:, 1] for model in sdm_result["models"].values()]
    pred_flat[valid] = np.mean(np.vstack(preds), axis=0)
    pred = pred_flat.reshape(out_h, out_w)
    row_grid, col_grid = np.indices((out_h, out_w))
    overlay = {"image": rgba_from_prediction(pred), "bounds": [[south2, west2], [north2, east2]], "shape": pred.shape, "source_stride": stride, "min": round(float(np.nanmin(pred)), 4), "max": round(float(np.nanmax(pred)), 4), "mean": round(float(np.nanmean(pred)), 4), "method": "Ensemble predict_proba over environmental raster grid"}
    pred_table = pd.DataFrame({"raster_row": row_grid.ravel()[valid].astype(int), "raster_col": col_grid.ravel()[valid].astype(int), "cell_index": np.flatnonzero(valid).astype(int), "x": lon_flat[valid], "y": lat_flat[valid], "longitude": lon_flat[valid], "latitude": lat_flat[valid], "sdm_suitability": pred_flat[valid]})
    return overlay, pred_table


def build_environment_prediction_grid(occ: pd.DataFrame, variables: list[str], resolution: str, area_mode: str, buffer_km: float, rectangle_margin_km: float, max_pixels: int, excluded_occ: Optional[pd.DataFrame] = None, exclusion_buffer_km: float = 0.0, status=None) -> tuple[pd.DataFrame, tuple[int, int], list[list[float]], int]:
    _, env, valid, lon_flat, lat_flat, out_h, out_w, (west2, south2, east2, north2), stride = _build_prediction_grid_base(
        occ, variables, resolution, area_mode, buffer_km, rectangle_margin_km, max_pixels,
        excluded_occ, exclusion_buffer_km, status,
        "Building shared SSDM prediction grid: {out_w:,} × {out_h:,} cells; source stride={stride}",
    )
    if valid.sum() == 0:
        raise RuntimeError("No valid land raster cells were available for SSDM prediction.")
    row_grid, col_grid = np.indices((out_h, out_w))
    grid = pd.DataFrame({"raster_row": row_grid.ravel()[valid].astype(int), "raster_col": col_grid.ravel()[valid].astype(int), "cell_index": np.flatnonzero(valid).astype(int), "longitude": lon_flat[valid], "latitude": lat_flat[valid]})
    for var in variables:
        grid[var] = env.loc[valid, var].to_numpy()
    return grid.reset_index(drop=True), (out_h, out_w), [[south2, west2], [north2, east2]], stride


def ssdm_rgba(values: np.ndarray, max_value: float, alpha: int = 170) -> np.ndarray:
    normalized = np.full(values.shape, np.nan, dtype=float)
    if max_value > 0:
        normalized = values / float(max_value)
    return rgba_from_prediction(np.clip(normalized, 0, 1), alpha=alpha)


def make_ssdm_overlay(grid: pd.DataFrame, value_col: str, shape: tuple[int, int], bounds: list[list[float]]) -> dict[str, Any]:
    arr = np.full(int(shape[0]) * int(shape[1]), np.nan, dtype=float)
    arr[grid["cell_index"].astype(int).to_numpy()] = pd.to_numeric(grid[value_col], errors="coerce").to_numpy(dtype=float)
    arr = arr.reshape(shape)
    max_value = float(np.nanmax(arr)) if np.isfinite(arr).any() else 0.0
    return {
        "image": ssdm_rgba(arr, max_value),
        "bounds": bounds,
        "shape": shape,
        "min": round(float(np.nanmin(arr)), 4) if np.isfinite(arr).any() else np.nan,
        "mean": round(float(np.nanmean(arr)), 4) if np.isfinite(arr).any() else np.nan,
        "max": round(max_value, 4),
    }


@st.cache_data(show_spinner=False)
def make_ssdm_map(grid: pd.DataFrame, hotspots: pd.DataFrame, value_col: str, title: str, shape: tuple[int, int], bounds: list[list[float]], show_coverage_layer: bool = True) -> folium.Map:
    center = (float(grid["latitude"].mean()), float(grid["longitude"].mean())) if not grid.empty else (35.5, 135.5)
    fmap = Map(location=center, zoom_start=7, tiles="OpenStreetMap", control_scale=True)
    overlay = make_ssdm_overlay(grid, value_col, shape, bounds)
    folium.raster_layers.ImageOverlay(image=overlay["image"], bounds=overlay["bounds"], opacity=0.70, name=title, interactive=True).add_to(fmap)
    # Coverage layer: n_species_evaluated as raster overlay (fast — no per-cell Python loop)
    if show_coverage_layer and "n_species_evaluated" in grid.columns and not grid.empty:
        _cov_arr = np.full(int(shape[0]) * int(shape[1]), np.nan, dtype=float)
        _cov_arr[grid["cell_index"].astype(int).to_numpy()] = grid["n_species_evaluated"].to_numpy(dtype=float)
        _cov_arr = _cov_arr.reshape(shape)
        _cov_max = float(np.nanmax(_cov_arr)) if np.isfinite(_cov_arr).any() else 1.0
        _norm = np.where(np.isfinite(_cov_arr) & (_cov_arr > 0), _cov_arr / max(_cov_max, 1.0), np.nan)
        _rgba_cov = np.zeros((shape[0], shape[1], 4), dtype=np.uint8)
        _v = np.isfinite(_norm) & (_norm > 0)
        _rgba_cov[_v, 0] = 60
        _rgba_cov[_v, 1] = 120
        _rgba_cov[_v, 2] = 200
        _rgba_cov[_v, 3] = (180 * _norm[_v]).astype(np.uint8)
        folium.raster_layers.ImageOverlay(
            image=_rgba_cov, bounds=bounds, opacity=1.0,
            name="Species model coverage (n evaluated)", show=False, interactive=False,
        ).add_to(fmap)
    if hotspots is not None and not hotspots.empty:
        fg = FeatureGroup(name="SSDM hotspot candidates", show=True)
        for row in hotspots.itertuples(index=False):
            folium.CircleMarker(
                (row.latitude, row.longitude),
                radius=7,
                color="#d73027",
                fill=True,
                fill_color="#d73027",
                fill_opacity=0.9,
                popup=folium.Popup(f"Hotspot rank {int(row.hotspot_rank)}<br>Continuous richness: {getattr(row, 'ssdm_continuous_richness', '')}<br>Binary richness: {getattr(row, 'ssdm_binary_richness', '')}<br><a href='{getattr(row, 'google_maps_url', '')}' target='_blank'>Open in Google Maps</a>", max_width=360),
                tooltip=f"SSDM hotspot {int(row.hotspot_rank)}",
            ).add_to(fg)
        fg.add_to(fmap)
    _min_v = float(grid[value_col].min()) if not grid.empty and value_col in grid.columns else 0.0
    _max_v = float(grid[value_col].max()) if not grid.empty and value_col in grid.columns else 1.0
    add_ssdm_richness_legend(fmap, value_col, _min_v, _max_v)
    LayerControl(collapsed=True).add_to(fmap)
    try:
        fmap.fit_bounds(bounds, padding=(30, 30))
    except Exception:
        pass
    return fmap


def ssdm_hotspot_candidates(grid: pd.DataFrame, max_candidates: int, min_species_evaluated: int = 2) -> pd.DataFrame:
    if grid.empty:
        return pd.DataFrame()
    filtered = grid.dropna(subset=["ssdm_continuous_richness"])
    # Apply minimum model-coverage filter when n_species_evaluated is available
    if "n_species_evaluated" in filtered.columns and int(min_species_evaluated) > 1:
        coverage_filtered = filtered[filtered["n_species_evaluated"] >= int(min_species_evaluated)]
        if coverage_filtered.empty:
            # Fall back to lower threshold if no cells pass
            coverage_filtered = filtered[filtered["n_species_evaluated"] >= 1]
        filtered = coverage_filtered if not coverage_filtered.empty else filtered
    out = filtered.sort_values(["ssdm_continuous_richness", "ssdm_binary_richness"], ascending=False).head(int(max_candidates)).copy()
    max_richness = float(out["ssdm_continuous_richness"].max()) if not out.empty and float(out["ssdm_continuous_richness"].max()) > 0 else 1.0
    out.insert(0, "hotspot_rank", range(1, len(out) + 1))
    out["site_id"] = out["hotspot_rank"].astype(int)
    out["candidate_type"] = "SSDM-high exploratory richness candidate"
    out["n_occurrences"] = 0
    out["observed_species_richness"] = np.nan
    out["ssdm_predicted_richness"] = pd.to_numeric(out["ssdm_continuous_richness"], errors="coerce").round(4)
    out["occurrence_support_score"] = 0.0
    out["model_support_score"] = (pd.to_numeric(out["ssdm_continuous_richness"], errors="coerce").fillna(0.0) / max_richness).clip(0, 1).round(3)
    out["candidate_method"] = "Stacked SSDM predicted richness"
    out["selection_reason"] = "High predicted stacked richness. Model-only exploratory candidate."
    out["bias_warning"] = "Exploratory SSDM-high candidate. Lower confidence than observed hotspots; field validation is required."
    out["google_maps_url"] = [make_google_maps_point_url(float(r["latitude"]), float(r["longitude"])) for _, r in out.iterrows()]
    return out.reset_index(drop=True)


def add_grid_model_support_to_candidates(candidates: pd.DataFrame, grid: pd.DataFrame, value_col: str = "ssdm_continuous_richness") -> pd.DataFrame:
    if candidates.empty or grid.empty or value_col not in grid.columns:
        return candidates.copy()
    out = candidates.copy()
    max_value = float(pd.to_numeric(grid[value_col], errors="coerce").max())
    if not np.isfinite(max_value) or max_value <= 0:
        max_value = 1.0
    grid_coords = grid[["latitude", "longitude"]].to_numpy(dtype=float)
    grid_values = pd.to_numeric(grid[value_col], errors="coerce").fillna(0.0).to_numpy(dtype=float)
    supports = []
    raw_vals = []
    for _, row in out.iterrows():
        coord = np.array([float(row["latitude"]), float(row["longitude"])], dtype=float)
        idx = int(np.argmin(np.sum((grid_coords - coord) ** 2, axis=1)))
        raw = float(grid_values[idx])
        raw_vals.append(round(raw, 4))
        supports.append(round(max(0.0, min(1.0, raw / max_value)), 3))
    out["ssdm_predicted_richness"] = raw_vals
    out["model_support_score"] = supports
    return out


def fit_stacked_species_sdms(
    occ: pd.DataFrame,
    variables: list[str],
    algorithms: list[str],
    resolution: str,
    area_mode: str,
    buffer_km: float,
    rectangle_margin_km: float,
    max_pixels: int,
    min_records: int,
    max_species: int,
    max_presence_points: int,
    n_background: int,
    binary_threshold: float,
    max_hotspots: int,
    apply_vif: bool,
    vif_threshold: float,
    variable_selection_strategy: str = "No VIF",
    corr_threshold: float = 0.80,
    custom_variables: Optional[list[str]] = None,
    ssdm_partition_override: str = "auto",
    ssdm_partition_method: str = "random holdout",
    ssdm_test_split: float = 0.20,
    ssdm_k_folds: int = 5,
    ssdm_checkerboard_deg: float = 0.05,
    ssdm_holdout_split: float = 0.20,
    per_species_grid_thin_deg: float = 0.0,
    per_species_distance_thin_m: float = 0.0,
    ssdm_extent_mode: str = "species_specific",
    ssdm_min_coverage: int = 2,
    status=None,
    progress=None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, tuple[int, int], list[list[float]], pd.DataFrame]:
    """Fit stacked per-species SDMs on a shared environmental grid.

    VIF is run ONCE on pooled occurrence/background data and the same retained
    variables are used for every species model.  Per-species VIF is intentionally
    avoided to prevent inconsistent variable sets and BIO-variable loss on small
    species samples.

    When ssdm_extent_mode == "species_specific" (default), each species is predicted
    only within its own occurrence-based spatial extent; cells outside are treated as
    NA (unevaluated), not zero absence. Richness is summed only where species-level
    models were evaluated, tracked via n_species_evaluated per cell.

    When ssdm_extent_mode == "shared_genus", all species are predicted across the
    full genus-wide shared grid (legacy exploratory behaviour).

    Returns (summary_df, richness_grid, hotspots, shape, bounds, vif_diag_df).
    """
    work = occ.copy()
    work["_species_clean"] = work["_species"].apply(clean_species_label_for_genus_richness)
    work = work[work["_species_clean"].ne("")]
    counts = work.groupby("_species_clean").size().sort_values(ascending=False)
    eligible = counts[counts >= int(min_records)].head(int(max_species))
    skipped_low = counts[counts < int(min_records)]
    if eligible.empty:
        raise RuntimeError("No species had enough records for SSDM.")

    # Build shared output grid once before the species loop (genus-wide extent).
    shared_grid, shape, bounds, stride = build_environment_prediction_grid(
        work, variables, resolution, area_mode, buffer_km, rectangle_margin_km, max_pixels, status=status
    )
    # NA-aware richness accumulators (per Step 2D specification)
    richness_sum = np.zeros(len(shared_grid), dtype=float)   # continuous richness
    binary_sum = np.zeros(len(shared_grid), dtype=float)     # binary richness
    n_evaluated = np.zeros(len(shared_grid), dtype=int)      # species evaluated per cell

    summary_rows = []
    rng = np.random.default_rng(42)
    background_n = min(int(n_background), len(shared_grid))
    bg_idx = rng.choice(len(shared_grid), size=background_n, replace=False)
    bg_base = shared_grid.iloc[bg_idx][["latitude", "longitude"] + variables].copy()
    bg_base["presence"] = 0
    bg_base["occurrence_row_id"] = np.nan

    # Shared variable selection: run once on pooled presence sample + background.
    vif_diag: pd.DataFrame = pd.DataFrame()
    vif_fallback_used = False
    if variable_selection_strategy != "No VIF" or apply_vif:
        if status is not None:
            status.write(f"Running shared variable selection ({variable_selection_strategy}) on pooled occurrence/background data...")
        all_pres = work[["_latitude", "_longitude"]].rename(columns={"_latitude": "latitude", "_longitude": "longitude"}).copy()
        all_pres["presence"] = 1
        all_pres["occurrence_row_id"] = np.nan
        if len(all_pres) > 1000:
            all_pres = all_pres.sample(1000, random_state=42).reset_index(drop=True)
        all_pres_env = extract_environment(all_pres, variables, "latitude", "longitude", resolution, status=None)
        pooled = pd.concat([all_pres_env, bg_base[[c for c in all_pres_env.columns if c in bg_base.columns]]], ignore_index=True, sort=False)
        pooled, pooled_dropped = clean_environment_table(pooled, variables, "SSDM shared variable-selection environment", status)
        if pooled.empty or pooled["presence"].nunique() < 2:
            raise RuntimeError("SSDM shared variable-selection data had too few valid rows after raster NoData cleaning.")
        strategy_to_run = variable_selection_strategy if variable_selection_strategy != "No VIF" else "VIF stepwise"
        kept_vars, vif_diag, vif_fallback_used = run_ssdm_shared_vif(
            pooled,
            variables,
            float(vif_threshold),
            strategy=strategy_to_run,
            corr_threshold=float(corr_threshold),
            custom_variables=custom_variables,
        )
        if not vif_diag.empty:
            vif_diag["rows_dropped_before_vif"] = int(pooled_dropped)
        removed_vars = [v for v in variables if v not in kept_vars]
    else:
        kept_vars = list(variables)
        removed_vars = []

    if not kept_vars:
        raise RuntimeError("No environmental variables remained after shared VIF filtering.")

    total = len(eligible)
    for i, (species, n_records) in enumerate(eligible.items(), start=1):
        if status is not None:
            status.write(f"Fitting SSDM species {i}/{total}: {species} ({int(n_records):,} records)")
        if progress is not None:
            progress.progress((i - 1) / max(1, total))
        sp_occ = occurrence_sort_for_representative(work[work["_species_clean"].eq(species)])
        sp_occ = exact_coordinate_deduplicate(sp_occ)
        if float(per_species_grid_thin_deg) > 0 and not sp_occ.empty:
            sp_occ = grid_thin(sp_occ, float(per_species_grid_thin_deg))
        if float(per_species_distance_thin_m) > 0 and not sp_occ.empty:
            sp_occ = spatial_thin(sp_occ, float(per_species_distance_thin_m))
        if len(sp_occ) > int(max_presence_points):
            positions = np.linspace(0, len(sp_occ) - 1, int(max_presence_points)).round().astype(int)
            sp_occ = sp_occ.iloc[np.unique(positions)].reset_index(drop=True)
        # Compute species extent once (used for both partition selection and extent masking)
        sp_extent_geom_for_partition = prediction_area_geometry(sp_occ, area_mode, buffer_km, rectangle_margin_km)
        # Determine per-species partition method using auto_sdm_partition with extent_geom
        _effective_override = ssdm_partition_override if ssdm_partition_override != "auto" else (ssdm_partition_method if ssdm_partition_method not in ("Auto recommended", "auto") else "auto")
        if _effective_override == "auto":
            species_partition_method, species_partition_reason = auto_sdm_partition(int(len(sp_occ)), sp_extent_geom_for_partition)
            sp_k = 5; sp_checker = 0.05; sp_holdout = 0.25
        else:
            species_partition_method = _effective_override
            species_partition_reason = f"Forced override: {_effective_override}"
            sp_k = ssdm_k_folds; sp_checker = ssdm_checkerboard_deg; sp_holdout = ssdm_holdout_split
        if len(sp_occ) < int(min_records):
            summary_rows.append({"species": species, "status": "skipped_after_thinning", "n_records": int(n_records), "n_presence_used": int(len(sp_occ)), "n_background": int(background_n), "environment_rows_dropped": np.nan, "mean_auc": np.nan, "algorithms": ", ".join(algorithms), "shared_vif_applied": variable_selection_strategy == "VIF stepwise", "variable_selection_strategy": variable_selection_strategy, "vif_threshold": float(vif_threshold) if variable_selection_strategy == "VIF stepwise" else np.nan, "variables_kept": ", ".join(kept_vars), "variables_removed_by_vif": ", ".join(removed_vars), "variables_removed_by_selection": ", ".join(removed_vars), "partition_method": species_partition_method, "partition_reason": species_partition_reason, "test_split": float(sp_holdout) if species_partition_method == "random holdout" else np.nan, "n_folds": np.nan, "valid_folds": np.nan, "auc_warning": "skipped"})
            continue
        pres = sp_occ[["_row_id", "_latitude", "_longitude"]].rename(columns={"_latitude": "latitude", "_longitude": "longitude", "_row_id": "occurrence_row_id"}).copy()
        pres["presence"] = 1
        pres_env = extract_environment(pres, kept_vars, "latitude", "longitude", resolution, status=None)
        bg_cols = ["latitude", "longitude", "presence", "occurrence_row_id"] + kept_vars
        bg_for_sp = bg_base[["latitude", "longitude", "presence", "occurrence_row_id"] + [v for v in kept_vars if v in bg_base.columns]].copy()
        train = pd.concat([pres_env[[c for c in bg_cols if c in pres_env.columns]], bg_for_sp[[c for c in bg_cols if c in bg_for_sp.columns]]], ignore_index=True, sort=False)
        try:
            if not kept_vars:
                raise RuntimeError("No environmental variables remained after shared VIF filtering.")
            train, species_env_dropped = clean_environment_table(train, kept_vars, f"SSDM {species} environment", status)
            if train.empty or train["presence"].nunique() < 2:
                raise RuntimeError("Too few valid rows after raster NoData cleaning.")
            sdm_result = fit_sdm(
                train, kept_vars, algorithms,
                species_partition_method, int(sp_k), float(sp_checker),
                holdout_test_size=float(sp_holdout),
            )
            # Build species-specific extent mask (or full grid for shared_genus mode)
            if ssdm_extent_mode == "species_specific":
                # Reuse the geometry computed above for partition selection (avoids duplicate call)
                sp_extent_geom = sp_extent_geom_for_partition
                if sp_extent_geom is not None and not sp_extent_geom.is_empty:
                    # Vectorized bounds check: always valid because prediction_area_geometry
                    # with "bounding box" produces a rectangle, and other modes (buffer,
                    # convex hull) are approximated by bounds for O(1) numpy speed (~1000x
                    # faster than Python-level Point.covers loops over 80k+ cells).
                    _minx, _miny, _maxx, _maxy = sp_extent_geom.bounds
                    _lons = shared_grid["longitude"].values
                    _lats = shared_grid["latitude"].values
                    sp_mask = (_lons >= _minx) & (_lons <= _maxx) & (_lats >= _miny) & (_lats <= _maxy)
                else:
                    sp_mask = np.ones(len(shared_grid), dtype=bool)
            else:
                sp_mask = np.ones(len(shared_grid), dtype=bool)
            # Predict only within masked cells; NA outside
            sp_suitability = np.full(len(shared_grid), np.nan, dtype=float)
            if sp_mask.sum() > 0:
                sp_subset = shared_grid.iloc[np.where(sp_mask)[0]].copy()
                sp_pred_df = predict_suitability(sp_subset, sdm_result)
                sp_suitability[sp_mask] = sp_pred_df["sdm_suitability"].to_numpy(dtype=float)
            # NA-aware accumulation: only count cells where species was evaluated
            _valid = ~np.isnan(sp_suitability)
            richness_sum[_valid] += sp_suitability[_valid]
            binary_sum[_valid] += (sp_suitability[_valid] >= float(binary_threshold)).astype(float)
            n_evaluated[_valid] += 1
            metrics_df = sdm_result["metrics"]
            auc_vals = pd.to_numeric(metrics_df.get("auc", pd.Series(dtype=float)), errors="coerce")
            mean_auc_val = float(auc_vals.mean()) if auc_vals.notna().any() else np.nan
            # Compute n_folds and valid_folds from metrics
            fold_rows = metrics_df[metrics_df.get("fold", pd.Series(dtype=object)).apply(lambda x: str(x) not in ("mean", "diagnostic")) if "fold" in metrics_df.columns else pd.Series([False] * len(metrics_df), index=metrics_df.index)]
            n_folds_val = int(len(fold_rows["fold"].unique())) if not fold_rows.empty and "fold" in fold_rows.columns else (1 if species_partition_method == "random holdout" else 0)
            valid_folds_val = int(fold_rows["auc"].notna().sum()) if not fold_rows.empty and "auc" in fold_rows.columns else (1 if (species_partition_method == "random holdout" and np.isfinite(mean_auc_val)) else 0)
            _auc_warn = "AUC not computed" if not np.isfinite(mean_auc_val) else ("low AUC" if mean_auc_val < 0.7 else "")
            summary_rows.append({"species": species, "status": "modeled", "n_records": int(n_records), "n_presence_used": int(len(sp_occ)), "n_background": int(background_n), "environment_rows_dropped": int(species_env_dropped), "mean_auc": round(mean_auc_val, 3) if np.isfinite(mean_auc_val) else np.nan, "algorithms": ", ".join(algorithms), "shared_vif_applied": variable_selection_strategy == "VIF stepwise", "variable_selection_strategy": variable_selection_strategy, "vif_threshold": float(vif_threshold) if variable_selection_strategy == "VIF stepwise" else np.nan, "variables_kept": ", ".join(kept_vars), "variables_removed_by_vif": ", ".join(removed_vars), "variables_removed_by_selection": ", ".join(removed_vars), "partition_method": species_partition_method, "partition_reason": species_partition_reason, "test_split": float(sp_holdout) if species_partition_method == "random holdout" else np.nan, "n_folds": n_folds_val, "valid_folds": valid_folds_val, "auc_warning": _auc_warn})
        except Exception as exc:
            summary_rows.append({"species": species, "status": f"failed: {exc}", "n_records": int(n_records), "n_presence_used": int(len(sp_occ)), "n_background": int(background_n), "environment_rows_dropped": np.nan, "mean_auc": np.nan, "algorithms": ", ".join(algorithms), "shared_vif_applied": variable_selection_strategy == "VIF stepwise", "variable_selection_strategy": variable_selection_strategy, "vif_threshold": float(vif_threshold) if variable_selection_strategy == "VIF stepwise" else np.nan, "variables_kept": "", "variables_removed_by_vif": ", ".join(removed_vars), "variables_removed_by_selection": ", ".join(removed_vars), "partition_method": species_partition_method, "partition_reason": species_partition_reason, "test_split": float(sp_holdout) if species_partition_method == "random holdout" else np.nan, "n_folds": np.nan, "valid_folds": 0, "auc_warning": "AUC not computed"})

    if progress is not None:
        progress.progress(1.0)
    for species, n_records in skipped_low.items():
        _eff_ov2 = ssdm_partition_override if ssdm_partition_override != "auto" else (ssdm_partition_method if ssdm_partition_method not in ("Auto recommended", "auto") else "auto")
        if _eff_ov2 == "auto":
            _skip_method, _skip_reason = auto_sdm_partition(int(n_records), None)
        else:
            _skip_method = _eff_ov2
            _skip_reason = f"Forced override: {_eff_ov2}"
        summary_rows.append({"species": species, "status": "skipped_too_few_records", "n_records": int(n_records), "n_presence_used": 0, "n_background": int(background_n), "environment_rows_dropped": np.nan, "mean_auc": np.nan, "algorithms": "", "shared_vif_applied": variable_selection_strategy == "VIF stepwise", "variable_selection_strategy": variable_selection_strategy, "vif_threshold": float(vif_threshold) if variable_selection_strategy == "VIF stepwise" else np.nan, "variables_kept": "", "variables_removed_by_vif": "", "variables_removed_by_selection": "", "partition_method": _skip_method, "partition_reason": _skip_reason, "test_split": np.nan, "n_folds": np.nan, "valid_folds": 0, "auc_warning": "skipped"})

    out_grid = shared_grid[["raster_row", "raster_col", "cell_index", "latitude", "longitude"]].copy()
    # Cells where no species was evaluated → NaN (not zero — these are unevaluated, not absence)
    out_grid["ssdm_continuous_richness"] = np.where(n_evaluated > 0, np.round(richness_sum, 4), np.nan)
    out_grid["ssdm_binary_richness"] = np.where(n_evaluated > 0, binary_sum.astype(float), np.nan)
    out_grid["n_species_evaluated"] = n_evaluated
    with np.errstate(invalid="ignore"):
        out_grid["mean_suitability"] = np.where(
            n_evaluated > 0,
            np.round(richness_sum / np.maximum(n_evaluated, 1), 4),
            np.nan,
        )
    hotspots = ssdm_hotspot_candidates(out_grid, max_hotspots, min_species_evaluated=int(ssdm_min_coverage))
    return pd.DataFrame(summary_rows), out_grid, hotspots, shape, bounds, vif_diag


def make_sdm_exploration_candidates(pred_table: pd.DataFrame, known_occ: pd.DataFrame, occurrence_candidates: pd.DataFrame, min_suitability: float, quantile_cutoff: float, min_distance_known_m: float, cluster_distance_m: float, max_candidates: int, start_site_id: int) -> pd.DataFrame:
    if pred_table is None or pred_table.empty:
        return pd.DataFrame()
    pred = pred_table.dropna(subset=["sdm_suitability"]).copy()
    cutoff = max(float(min_suitability), float(pred["sdm_suitability"].quantile(float(quantile_cutoff))))
    pred = pred[pred["sdm_suitability"] >= cutoff].copy()
    if pred.empty:
        return pd.DataFrame()
    known = pd.concat([known_occ[["_latitude", "_longitude"]].rename(columns={"_latitude": "latitude", "_longitude": "longitude"}), occurrence_candidates[["latitude", "longitude"]]], ignore_index=True)
    # Vectorised nearest-known-distance via BallTree (haversine). Replaces the previous
    # O(pred × known) geopy nested loop, which recomputed millions of geodesic distances
    # on every Streamlit rerun once SDM was active and made the app crawl.
    known_coords = pd.concat([
        pd.to_numeric(known["latitude"], errors="coerce"),
        pd.to_numeric(known["longitude"], errors="coerce"),
    ], axis=1).dropna().to_numpy(dtype=float)
    pred_coords = pred[["latitude", "longitude"]].to_numpy(dtype=float)
    if known_coords.shape[0] == 0:
        dmin_m = np.full(pred_coords.shape[0], np.inf)
    else:
        tree = BallTree(np.radians(known_coords), metric="haversine")
        dist_rad, _ = tree.query(np.radians(pred_coords), k=1)
        dmin_m = dist_rad[:, 0] * EARTH_RADIUS_M
    pred["distance_to_nearest_known_m"] = np.round(dmin_m).astype(float)
    pred = pred[dmin_m >= float(min_distance_known_m)].copy()
    if pred.empty:
        return pd.DataFrame()
    pred["exploration_cluster"] = haversine_dbscan(pred, "latitude", "longitude", cluster_distance_m, 1)
    rows = []
    for i, (_, group) in enumerate(pred.groupby("exploration_cluster"), start=0):
        best = group.sort_values("sdm_suitability", ascending=False).iloc[0]
        rows.append({"site_id": start_site_id + i, "candidate_type": "SDM-high exploration survey range", "cluster_id": int(best["exploration_cluster"]), "latitude": float(best["latitude"]), "longitude": float(best["longitude"]), "n_occurrences": 0, "occurrence_support_score": 0.0, "priority_score": round(float(best["sdm_suitability"]), 3), "sdm_suitability": round(float(best["sdm_suitability"]), 3), "distance_to_nearest_known_m": float(best["distance_to_nearest_known_m"]), "candidate_method": "Raster predict-map suitability maximum", "selection_reason": "High SDM suitability and away from known records/candidate ranges.", "bias_warning": "Exploratory SDM candidate. Field validation is required."})
    return pd.DataFrame(rows).sort_values("sdm_suitability", ascending=False).head(int(max_candidates)).reset_index(drop=True)


def make_potential_survey_site_candidates(
    occ: pd.DataFrame,
    occurrence_candidates: pd.DataFrame,
    cell_size_m: float,
    max_candidates_per_type: int,
    max_grid_cells: int,
    start_site_id: int,
    prediction_table: Optional[pd.DataFrame] = None,
    env_variables: Optional[list[str]] = None,
    resolution: str = "2.5m",
    highres_layers: Optional[dict[str, Optional[str]]] = None,
    profile_buffer_m: float = 100.0,
) -> pd.DataFrame:
    """Build habitat-first exploratory survey cells from the active survey area.

    This is intentionally not a second SDM. It builds a local habitat analogue
    profile from topographic/environmental variables around known records and
    scores grid cells by environmental similarity. An SDM predict map can be
    supplied only as a broad macro-scale filter.
    """
    if occ is None or occ.empty:
        return pd.DataFrame()
    work = occ.dropna(subset=["_latitude", "_longitude"]).copy()
    if work.empty:
        return pd.DataFrame()
    requested_cell_m = max(50.0, float(cell_size_m))
    highres_layers = highres_layers or {}
    center_latitude = float(work["_latitude"].mean())
    raster_resolutions = [
        raster_pixel_resolution_m(highres_layers.get(name), center_latitude)
        for name in ("dem", "ndvi", "landcover")
        if highres_layers.get(name)
    ]
    raster_resolutions = [value for value in raster_resolutions if value is not None and np.isfinite(value)]
    # Without an uploaded local raster the fallback analogue uses WorldClim
    # 2.5 arc-minutes, so a fine-looking 100 m cell would be false precision.
    if highres_layers.get("dem") and raster_resolutions:
        environmental_resolution_m = max(raster_resolutions)
    else:
        # Topographic predictors still fall back to the 2.5 arc-minute DEM.
        environmental_resolution_m = max([4_500.0, *raster_resolutions])
    coordinate_uncertainty = pd.to_numeric(
        work.get("_coordinate_uncertainty_m", pd.Series(np.nan, index=work.index)), errors="coerce"
    )
    coordinate_q75 = float(coordinate_uncertainty.quantile(0.75)) if coordinate_uncertainty.notna().any() else None
    access_resolution_m = 75.0 if any(highres_layers.get(name) for name in ("roads", "trails")) else None
    resolution_decision = choose_candidate_resolution(
        environmental_resolution_m=environmental_resolution_m,
        access_resolution_m=access_resolution_m,
        coordinate_uncertainty_q75_m=coordinate_q75,
        minimum_practical_search_m=max(100.0, requested_cell_m),
    )
    cell_m = float(resolution_decision.cell_size_m)

    known_coords = work[["_latitude", "_longitude"]].to_numpy(dtype=float)
    if known_coords.shape[0] == 0:
        return pd.DataFrame()
    tree = BallTree(np.radians(known_coords), metric="haversine")
    radius_m = max(cell_m * 1.5, 100.0)

    if prediction_table is not None and not prediction_table.empty and "sdm_suitability" in prediction_table.columns:
        grid = prediction_table.dropna(subset=["latitude", "longitude", "sdm_suitability"]).copy()
        if len(grid) > int(max_grid_cells):
            grid = grid.sort_values("sdm_suitability", ascending=False).head(int(max_grid_cells)).copy()
        grid["sdm_suitability"] = pd.to_numeric(grid["sdm_suitability"], errors="coerce").clip(0, 1)
        grid["macro_filter_basis"] = "SDM predict-map cells used as broad macro-scale filter"
    else:
        center_lat = float(work["_latitude"].mean())
        lat_min, lat_max = float(work["_latitude"].min()), float(work["_latitude"].max())
        lon_min, lon_max = float(work["_longitude"].min()), float(work["_longitude"].max())
        lat_span_m = max(1.0, (lat_max - lat_min) * 111_320.0)
        lon_span_m = max(1.0, (lon_max - lon_min) * 111_320.0 * max(0.2, math.cos(math.radians(center_lat))))
        approx_cells = max(1.0, (lat_span_m / cell_m) * (lon_span_m / cell_m))
        broad_local_search = approx_cells > float(max_grid_cells) * 4.0
        if broad_local_search:
            if occurrence_candidates is not None and not occurrence_candidates.empty:
                center_df = occurrence_candidates[["latitude", "longitude"]].dropna().copy()
            else:
                center_df = work[["_latitude", "_longitude"]].rename(columns={"_latitude": "latitude", "_longitude": "longitude"}).dropna().copy()
            max_centers = max(5, min(80, int(max_grid_cells) // 25))
            center_df = spatially_balanced_cap(center_df.rename(columns={"latitude": "_latitude", "longitude": "_longitude"}), max_centers).rename(columns={"_latitude": "latitude", "_longitude": "longitude"})
            local_radius_m = min(25_000.0, max(3_000.0, requested_cell_m * 8.0))
            rows: list[dict[str, float]] = []
            for _, center in center_df.iterrows():
                c_lat = float(center["latitude"])
                c_lon = float(center["longitude"])
                lat_step = cell_m / 111_320.0
                lon_step = cell_m / max(1.0, 111_320.0 * math.cos(math.radians(c_lat)))
                lat_radius = local_radius_m / 111_320.0
                lon_radius = local_radius_m / max(1.0, 111_320.0 * math.cos(math.radians(c_lat)))
                for lat in np.arange(c_lat - lat_radius, c_lat + lat_radius + lat_step, lat_step):
                    for lon in np.arange(c_lon - lon_radius, c_lon + lon_radius + lon_step, lon_step):
                        if _acsp_point_distances_m(c_lat, c_lon, np.array([lat]), np.array([lon]))[0] <= local_radius_m:
                            rows.append({"latitude": float(lat), "longitude": float(lon)})
            grid = pd.DataFrame(rows)
            if not grid.empty:
                coord_precision = 5 if cell_m < 500 else 4
                grid["_lat_key"] = grid["latitude"].round(coord_precision)
                grid["_lon_key"] = grid["longitude"].round(coord_precision)
                grid = grid.drop_duplicates(["_lat_key", "_lon_key"]).drop(columns=["_lat_key", "_lon_key"])
                if len(grid) > int(max_grid_cells):
                    grid = spatially_balanced_cap(grid.rename(columns={"latitude": "_latitude", "longitude": "_longitude"}), int(max_grid_cells)).rename(columns={"_latitude": "latitude", "_longitude": "longitude"})
            grid["macro_filter_basis"] = f"Local search windows around occurrence-supported candidates ({local_radius_m / 1000.0:.1f} km radius) to keep broad-area searches fine and responsive"
        elif approx_cells > float(max_grid_cells):
            cell_m = cell_m * math.sqrt(approx_cells / max(1.0, float(max_grid_cells)))
            if cell_m <= 250:
                cell_m = math.ceil(cell_m / 25.0) * 25.0
            elif cell_m <= 1000:
                cell_m = math.ceil(cell_m / 50.0) * 50.0
            else:
                cell_m = math.ceil(cell_m / 100.0) * 100.0
        if not broad_local_search:
            lat_step = cell_m / 111_320.0
            lon_step = cell_m / max(1.0, 111_320.0 * math.cos(math.radians(center_lat)))
            lat_pad = max(lat_step, (lat_max - lat_min) * 0.05)
            lon_pad = max(lon_step, (lon_max - lon_min) * 0.05)
            lat_vals = np.arange(lat_min - lat_pad, lat_max + lat_pad + lat_step, lat_step)
            lon_vals = np.arange(lon_min - lon_pad, lon_max + lon_pad + lon_step, lon_step)
            if len(lat_vals) * len(lon_vals) > int(max_grid_cells):
                stride = int(math.ceil(math.sqrt((len(lat_vals) * len(lon_vals)) / max(1, int(max_grid_cells)))))
                lat_vals = lat_vals[::stride]
                lon_vals = lon_vals[::stride]
            grid = pd.DataFrame(
                [{"latitude": float(lat), "longitude": float(lon)} for lat in lat_vals for lon in lon_vals]
            )
    if grid.empty:
        return pd.DataFrame()
    grid = filter_to_land(grid, "latitude", "longitude", radius_m)
    if grid.empty:
        return pd.DataFrame()

    grid_coords = grid[["latitude", "longitude"]].to_numpy(dtype=float)
    dist_rad, _idx = tree.query(np.radians(grid_coords), k=1)
    d_nearest_m = dist_rad[:, 0] * EARTH_RADIUS_M
    density = tree.query_radius(np.radians(grid_coords), r=radius_m / EARTH_RADIUS_M, count_only=True)
    grid["distance_to_nearest_known_m"] = d_nearest_m.astype(float)
    grid["target_record_density"] = np.asarray(density, dtype=float)

    max_dist = max(float(grid["distance_to_nearest_known_m"].quantile(0.95)), 1.0)
    density = pd.to_numeric(grid["target_record_density"], errors="coerce").fillna(0.0)
    max_density = max(float(density.max()), 1.0)
    grid["nearest_known_population_km"] = (grid["distance_to_nearest_known_m"] / 1000.0).round(3)

    has_highres = any(highres_layers.get(k) for k in ["dem", "ndvi", "landcover", "roads", "trails", "coastline", "forest_edge"])
    env_vars = [v for v in (env_variables or POTENTIAL_ANALOGUE_PRESET) if v in SUPPORTED_ENV_VARS]
    try:
            known_points = work.rename(columns={"_latitude": "latitude", "_longitude": "longitude"})
            profile_points = buffered_profile_sample_points(known_points, float(profile_buffer_m), "latitude", "longitude")
            if has_highres:
                occ_env = extract_potential_layer_values(profile_points, highres_layers, "latitude", "longitude")
                grid_env = extract_potential_layer_values(grid, highres_layers, "latitude", "longitude")
                if not highres_layers.get("dem"):
                    occ_topo = extract_environment(profile_points, POTENTIAL_ANALOGUE_PRESET, "latitude", "longitude", resolution)
                    grid_topo = extract_environment(grid, POTENTIAL_ANALOGUE_PRESET, "latitude", "longitude", resolution)
                    for topo_col in POTENTIAL_ANALOGUE_PRESET:
                        occ_env[topo_col] = occ_topo[topo_col].to_numpy()
                        grid_env[topo_col] = grid_topo[topo_col].to_numpy()
                continuous_cols = [
                    "elevation", "slope", "aspect", "roughness", "tpi", "ndvi",
                    "distance_to_road_m", "distance_to_trail_m", "distance_to_coast_m", "distance_to_forest_edge_m",
                ]
                env_vars = [c for c in continuous_cols if c in occ_env.columns and c in grid_env.columns]
            else:
                occ_env = extract_environment(profile_points, env_vars, "latitude", "longitude", resolution)
                grid_env = extract_environment(grid, env_vars, "latitude", "longitude", resolution)
            if not env_vars:
                raise RuntimeError("No usable continuous habitat layers were available.")
            occ_env, _ = clean_environment_table(occ_env, env_vars, "Potential-site known habitat environment")
            grid_env, _ = clean_environment_table(grid_env, env_vars, "Potential-site grid habitat environment")
            mu = occ_env[env_vars].mean()
            sd = occ_env[env_vars].std(ddof=0).replace(0, 1.0).fillna(1.0)
            known_env = ((occ_env[env_vars] - mu) / sd).to_numpy(dtype=float)
            cand_env = ((grid_env[env_vars] - mu) / sd).to_numpy(dtype=float)
            cov = np.cov(known_env, rowvar=False)
            cov = np.atleast_2d(cov) + np.eye(len(env_vars)) * 1e-6
            inv_cov = np.linalg.pinv(cov)
            centered = cand_env - np.nanmean(known_env, axis=0)
            env_dist = np.sqrt(np.einsum("ij,jk,ik->i", centered, inv_cov, centered))
            env_scale = max(float(np.nanpercentile(env_dist, 75)), 1.0)
            scored = grid_env[["latitude", "longitude"]].copy()
            scored["mahalanobis_environment_distance"] = env_dist
            scored["environmental_distance_to_known"] = (env_dist / max(float(np.nanpercentile(env_dist, 95)), 1.0)).clip(0, 1)
            scored["environmental_similarity"] = np.exp(-0.5 * (env_dist / env_scale) ** 2).clip(0, 1)
            scored["analogue_score"] = scored["environmental_similarity"]
            for var in env_vars:
                scored[var] = grid_env[var].to_numpy()
            grid = grid.drop(columns=[c for c in ["environmental_distance_to_known", "analogue_score"] if c in grid.columns])
            grid = grid.merge(scored, on=["latitude", "longitude"], how="inner")
            grid["habitat_score"] = grid["analogue_score"]
            basis_prefix = "High-resolution local habitat analogue" if has_highres else "Built-in elevation-raster local analogue"
            grid["habitat_basis"] = f"{basis_prefix}: {float(profile_buffer_m):.0f} m known-site buffer profile; Mahalanobis distance ({', '.join(env_vars)})"
            missing = []
            for label, key in [("DEM", "dem"), ("NDVI", "ndvi"), ("land cover", "landcover"), ("road distance", "roads"), ("trail distance", "trails"), ("coast distance", "coastline"), ("forest-edge distance", "forest_edge")]:
                if not highres_layers.get(key):
                    missing.append(label)
            grid["missing_layer_note"] = "Missing optional high-resolution layers: " + ", ".join(missing) if missing else "All currently supported high-resolution layer inputs were supplied."
            if "landcover" in occ_env.columns and "landcover" in grid_env.columns:
                known_lc = pd.to_numeric(occ_env["landcover"], errors="coerce").dropna().round().astype(int)
                dominant = set(known_lc.value_counts().head(5).index.tolist())
                grid_lc = pd.to_numeric(grid_env["landcover"], errors="coerce").round()
                grid["landcover"] = grid_lc.to_numpy()
                grid["landcover_match_score"] = grid_lc.astype("Int64").isin(dominant).astype(float).to_numpy()
                grid["habitat_score"] = (0.85 * pd.to_numeric(grid["habitat_score"], errors="coerce").fillna(0.0) + 0.15 * grid["landcover_match_score"]).clip(0, 1)
    except Exception as exc:
        grid["analogue_score"] = np.exp(-grid["distance_to_nearest_known_m"] / max(cell_m * 8.0, 1.0)).clip(0, 1)
        grid["habitat_score"] = grid["analogue_score"]
        grid["environmental_distance_to_known"] = (1.0 - grid["analogue_score"]).clip(0, 1)
        grid["habitat_basis"] = f"Spatial fallback; local topographic analogue scoring failed: {exc}"
        grid["missing_layer_note"] = "Local environmental analogue scoring was unavailable; current score uses distance from known records only."

    if "environmental_distance_to_known" not in grid.columns:
        grid["environmental_distance_to_known"] = (1.0 - pd.to_numeric(grid["analogue_score"], errors="coerce")).clip(0, 1)
    grid["environmental_novelty"] = (grid["distance_to_nearest_known_m"] / max_dist).clip(0, 1)
    grid["survey_effort_proxy"] = (density / max_density).clip(0, 1)
    grid["survey_gap_score"] = (1.0 - grid["survey_effort_proxy"]).clip(0, 1)
    if "slope" in grid.columns or "roughness" in grid.columns:
        rough = pd.to_numeric(grid.get("roughness", pd.Series(0.0, index=grid.index)), errors="coerce").fillna(0.0)
        slope = pd.to_numeric(grid.get("slope", pd.Series(0.0, index=grid.index)), errors="coerce").fillna(0.0)
        terrain = (rough / max(float(rough.quantile(0.95)), 1.0) + slope / max(float(slope.quantile(0.95)), 1.0)) / 2.0
        grid["access_score"] = (1.0 - terrain.clip(0, 1)).round(3)
        grid["access_note"] = "Terrain-access proxy from slope/roughness only; road/trail access still needs Google Maps or field verification."
    else:
        grid["access_score"] = np.nan
        grid["access_note"] = "Road/trail access not evaluated; verify in Google Maps and field conditions."
    grid["all_taxa_record_density"] = np.nan
    grid["search_cell_radius_m"] = round(cell_m / 2.0, 1)
    grid["requested_search_cell_size_m"] = round(requested_cell_m, 1)
    grid["effective_search_cell_size_m"] = round(cell_m, 1)
    grid["resolution_decision_reason"] = resolution_decision.reason
    grid["resolution_data_quality"] = resolution_decision.data_quality
    grid["effective_grid_cells_evaluated"] = int(len(grid))
    if "macro_filter_basis" not in grid.columns:
        grid["macro_filter_basis"] = "Local habitat analogue grid from the active survey-area occurrence set"

    occurrence_points = occurrence_candidates[["latitude", "longitude"]].copy() if occurrence_candidates is not None and not occurrence_candidates.empty else pd.DataFrame(columns=["latitude", "longitude"])
    if not occurrence_points.empty:
        cand_tree = BallTree(np.radians(occurrence_points.to_numpy(dtype=float)), metric="haversine")
        cand_dist_rad, _ = cand_tree.query(np.radians(grid[["latitude", "longitude"]].to_numpy(dtype=float)), k=1)
        grid = grid[cand_dist_rad[:, 0] * EARTH_RADIUS_M >= max(cell_m, 100.0)].copy()
    if grid.empty:
        return pd.DataFrame()

    pools = [
        (
            "Habitat-match",
            grid[(grid["analogue_score"] >= float(grid["analogue_score"].quantile(0.65))) & (grid["distance_to_nearest_known_m"] >= cell_m)].copy(),
            "analogue_score",
            "Known-site local habitat analogue, but outside existing candidate centres.",
        ),
        (
            "Survey-gap",
            grid[(grid["survey_gap_score"] >= float(grid["survey_gap_score"].quantile(0.65))) & (grid["analogue_score"] >= float(grid["analogue_score"].quantile(0.35)))].copy(),
            "survey_gap_score",
            "Known-site analogue with low local target-record density; field validation can test whether this is unsurveyed or unsuitable.",
        ),
        (
            "Environmental-test",
            grid[grid["environmental_novelty"] >= float(grid["environmental_novelty"].quantile(0.75))].copy(),
            "environmental_novelty",
            "Local environmental contrast cell intended to test habitat limits or collect informative absence/edge data.",
        ),
    ]
    out_rows: list[pd.DataFrame] = []
    next_sid = int(start_site_id)
    for candidate_type, pool, score_col, reason in pools:
        if pool.empty:
            continue
        pool = pool.sort_values([score_col, "survey_gap_score", "analogue_score"], ascending=False).head(int(max_candidates_per_type)).copy()
        n = len(pool)
        pool["site_id"] = range(next_sid, next_sid + n)
        next_sid += n
        pool["candidate_type"] = candidate_type
        pool["candidate_method"] = "Habitat-first grid cell"
        pool["n_occurrences"] = 0
        pool["occurrence_support_score"] = pd.to_numeric(pool[score_col], errors="coerce").fillna(0.0).clip(0, 1).round(3)
        habitat_component = pd.to_numeric(pool.get("habitat_score", pool.get("analogue_score", 0.0)), errors="coerce").fillna(0.0).clip(0, 1)
        gap_component = pd.to_numeric(pool.get("survey_gap_score", 0.0), errors="coerce").fillna(0.0).clip(0, 1)
        contrast_component = pd.to_numeric(pool.get("environmental_novelty", 0.0), errors="coerce").fillna(0.0).clip(0, 1)
        access_component = pd.to_numeric(pool.get("access_score", 0.0), errors="coerce").fillna(0.0).clip(0, 1)
        if "sdm_suitability" in pool.columns and pd.to_numeric(pool["sdm_suitability"], errors="coerce").notna().any():
            pool["sdm_suitability"] = pd.to_numeric(pool["sdm_suitability"], errors="coerce").clip(0, 1).round(3)
            pool["model_support_score"] = pool["sdm_suitability"].fillna(0.0)
        else:
            pool["sdm_suitability"] = np.nan
            pool["model_support_score"] = 0.0
        macro_component = pd.to_numeric(pool.get("sdm_suitability", 0.0), errors="coerce").fillna(0.0).clip(0, 1)
        if candidate_type == "Habitat-match":
            pool["priority_score"] = (0.65 * habitat_component + 0.15 * gap_component + 0.10 * access_component + 0.10 * macro_component).clip(0, 1).round(3)
        elif candidate_type == "Survey-gap":
            pool["priority_score"] = (0.45 * habitat_component + 0.35 * gap_component + 0.10 * access_component + 0.10 * macro_component).clip(0, 1).round(3)
        else:
            pool["priority_score"] = (0.40 * contrast_component + 0.25 * habitat_component + 0.20 * gap_component + 0.10 * access_component + 0.05 * macro_component).clip(0, 1).round(3)
        basis = str(pool["habitat_basis"].iloc[0]) if "habitat_basis" in pool.columns and len(pool) else "habitat-first proxy"
        effective_cell = float(pool["effective_search_cell_size_m"].iloc[0]) if "effective_search_cell_size_m" in pool.columns and len(pool) else cell_m
        explained = f"{reason} Effective search cell: {effective_cell:.0f} m. Habitat score basis: {basis}."
        pool["score_explanation"] = explained
        pool["selection_reason"] = explained
        pool["why_selected"] = explained
        pool["bias_warning"] = "Potential survey cell, not a confirmed occurrence. Requires field validation."
        out_rows.append(pool)
    if not out_rows:
        return pd.DataFrame()
    out = pd.concat(out_rows, ignore_index=True, sort=False)
    return out.reset_index(drop=True)


def recommended_potential_survey_settings(occ: pd.DataFrame) -> dict[str, int]:
    """Choose simple, fast defaults for local habitat-analogue discovery."""
    if occ is None or occ.empty:
        return {"cell_m": 250, "max_cells": 1500, "per_type": 10}
    lat_span = float(pd.to_numeric(occ["_latitude"], errors="coerce").max() - pd.to_numeric(occ["_latitude"], errors="coerce").min())
    lon_span = float(pd.to_numeric(occ["_longitude"], errors="coerce").max() - pd.to_numeric(occ["_longitude"], errors="coerce").min())
    center_lat = float(pd.to_numeric(occ["_latitude"], errors="coerce").mean())
    lat_span_km = max(0.0, lat_span * 111.32)
    lon_span_km = max(0.0, lon_span * 111.32 * max(0.2, math.cos(math.radians(center_lat))))
    max_span_km = max(lat_span_km, lon_span_km)
    if max_span_km <= 20:
        return {"cell_m": 100, "max_cells": 2500, "per_type": 12}
    if max_span_km <= 80:
        return {"cell_m": 250, "max_cells": 2000, "per_type": 10}
    if max_span_km <= 250:
        return {"cell_m": 500, "max_cells": 1800, "per_type": 10}
    return {"cell_m": 1000, "max_cells": 1500, "per_type": 8}


def apply_field_validation_learning(candidates: pd.DataFrame, validation: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    """Lightweight feedback learning from field-validation results.

    The model is intentionally simple and optional: it learns from previously
    validated candidate rows and predicts a field-validation support score for
    current candidates using already exported habitat/model/access columns.
    """
    if candidates is None or candidates.empty or validation is None or validation.empty:
        return candidates, "No validation data supplied."
    if "site_id" not in candidates.columns or "site_id" not in validation.columns:
        return candidates, "Validation learning needs a site_id column matching exported candidates."
    target_cols = [
        "result",
        "target_species_found", "target_taxa_found", "presence", "present",
        "found", "detected", "newly_confirmed_population",
    ]
    target_col = next((c for c in target_cols if c in validation.columns), None)
    if target_col is None:
        return candidates, "Validation CSV needs a presence/result column such as target_species_found, found, or detected."
    labels = parse_field_results(validation, target_col)
    train = candidates.merge(labels[["site_id", "_field_success"]], on="site_id", how="inner")
    if len(train) < 6 or train["_field_success"].nunique() < 2:
        return candidates, "Validation learning needs at least 6 matched candidate rows with both success and non-success outcomes."
    feature_cols = [
        "occurrence_support_score", "model_support_score", "sdm_suitability",
        "habitat_score", "environmental_similarity", "mahalanobis_environment_distance",
        "survey_gap_score", "access_score", "nearest_known_population_km",
        "elevation", "slope", "aspect", "roughness", "tpi", "ndvi",
        "distance_to_road_m", "distance_to_trail_m", "distance_to_coast_m", "distance_to_forest_edge_m",
    ]
    feature_cols = [c for c in feature_cols if c in candidates.columns and pd.to_numeric(candidates[c], errors="coerce").notna().any()]
    if not feature_cols:
        return candidates, "No numeric candidate features were available for validation learning."
    X_train = train[feature_cols].apply(pd.to_numeric, errors="coerce")
    X_all = candidates[feature_cols].apply(pd.to_numeric, errors="coerce")
    y = train["_field_success"].astype(int)
    model = Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("scaler", StandardScaler()),
        ("clf", LogisticRegression(max_iter=1000, class_weight="balanced")),
    ])
    try:
        model.fit(X_train, y)
        out = candidates.copy()
        out["field_validation_support_score"] = model.predict_proba(X_all)[:, 1].round(3)
        current_model = pd.to_numeric(out.get("model_support_score", pd.Series(0.0, index=out.index)), errors="coerce").fillna(0.0)
        out["model_support_score"] = np.maximum(current_model, out["field_validation_support_score"])
        note = f"Field-validation learning applied from {len(train):,} matched rows using {len(feature_cols):,} candidate features."
        out["validation_learning_note"] = note
        if "score_explanation" in out.columns:
            out["score_explanation"] = out["score_explanation"].fillna("").astype(str) + " Field-validation support was added from previous survey outcomes."
        return out, note
    except Exception as exc:
        return candidates, f"Validation learning failed: {exc}"


def popup_html_site(row: pd.Series) -> str:
    survey_window = row.get('recommended_survey_window', '')
    fl_count = row.get('flowering_record_count', 0)
    season_conf = row.get('season_confidence', '')
    phenology_line = ""
    if survey_window and str(survey_window) not in ("", "nan", "unknown"):
        phenology_line = f"Recommended visit: {survey_window} (confidence: {season_conf}, flowering evidence: {fl_count})<br>"
    return f"""
    <b>Survey range {int(row.get('site_id', 0))}</b><br>
    Type: {row.get('candidate_type', '')}<br>
    Priority rank: {row.get('priority_rank', '')}<br>
    Priority score: {row.get('priority_score', '')}<br>
    Occurrence support: {row.get('occurrence_support_score', '')}<br>
    Occurrence records: {int(row.get('n_occurrences', 0))}<br>
    Habitat analogue score: {row.get('analogue_score', '')}<br>
    Survey gap score: {row.get('survey_gap_score', '')}<br>
    Nearest known population: {row.get('nearest_known_population_km', '')} km<br>
    SDM suitability: {row.get('sdm_suitability', '')}<br>
    SSDM predicted richness: {row.get('ssdm_predicted_richness', '')}<br>
    Species richness: {row.get('observed_species_richness', row.get('species_richness', ''))}<br>
    Latitude: {float(row['latitude']):.6f}<br>
    Longitude: {float(row['longitude']):.6f}<br>
    Note: {row.get('bias_warning', '')}<br>
    {phenology_line}<a href='{make_google_maps_point_url(float(row['latitude']), float(row['longitude']))}' target='_blank'>Open in Google Maps</a>
    {image_html(row.get('representative_media_url', ''))}
    """


def _priority_marker_style(row: Any) -> tuple[int, str]:
    """Return (radius, color) for a candidate site marker based on priority_rank and candidate_type."""
    ctype = str(row.get("candidate_type", ""))
    ctype_lower = ctype.lower()
    if ctype_lower.startswith("sdm-high") or ctype_lower.startswith("sdm_high") or ctype_lower.startswith("ssdm-high"):
        return 9, "#9467bd"
    if ctype in {"Habitat-match", "Survey-gap", "Environmental-test", "Habitat analogue", "Under-surveyed analogue", "Environmental contrast"}:
        return 9, {
            "Habitat-match": "#17becf",
            "Survey-gap": "#bcbd22",
            "Environmental-test": "#8c564b",
            "Habitat analogue": "#17becf",
            "Under-surveyed analogue": "#bcbd22",
            "Environmental contrast": "#8c564b",
        }.get(ctype, "#17becf")
    rank = int(row.get("priority_rank", 99)) if str(row.get("priority_rank", "")).strip() not in ("", "nan") else 99
    if rank <= 3:
        return 14, "#d62728"
    elif rank <= 10:
        return 11, "#ff7f0e"
    elif rank <= 20:
        return 9, "#2ca02c"
    else:
        return 7, "#7f7f7f"


def make_selected_site_overlay(sites: pd.DataFrame, selected_ids: Optional[tuple], name: str = "selected survey sites") -> Optional[FeatureGroup]:
    if sites is None or sites.empty or not selected_ids:
        return None
    selected_set = set(int(s) for s in selected_ids)
    selected = sites[sites["site_id"].astype(int).isin(selected_set)].copy()
    if selected.empty:
        return None
    fg = FeatureGroup(name=name, show=True)
    for _, row in selected.iterrows():
        sid = int(row["site_id"])
        marker_radius, _color = _priority_marker_style(row)
        folium.CircleMarker(
            (float(row["latitude"]), float(row["longitude"])),
            radius=marker_radius + 5,
            color="#00cc44",
            fill=False,
            weight=3,
            tooltip=f"SELECTED | site {sid}",
        ).add_to(fg)
    return fg


def st_folium_with_overlay(fmap: folium.Map, selected_overlay: Optional[FeatureGroup] = None, **kwargs):
    if selected_overlay is None:
        return st_folium(fmap, **kwargs)
    try:
        return st_folium(fmap, feature_group_to_add=selected_overlay, **kwargs)
    except TypeError as exc:
        if "feature_group_to_add" not in str(exc):
            raise
        return st_folium(fmap, **kwargs)


@st.cache_data(show_spinner=False)
def build_map(occ: pd.DataFrame, sites: pd.DataFrame, overlay: Optional[dict[str, Any]], route_plan: Optional[pd.DataFrame], occurrence_buffer_m: float, survey_range_m: float, layers: dict[str, bool], show_images: bool = True, selected_ids: Optional[tuple] = None, add_draw: bool = False) -> folium.Map:
    center = (float(occ["_latitude"].mean()), float(occ["_longitude"].mean())) if not occ.empty else (35.5, 135.5)
    fmap = Map(location=center, zoom_start=8, tiles="OpenStreetMap", control_scale=True)
    if layers.get("predict") and overlay is not None:
        folium.raster_layers.ImageOverlay(image=overlay["image"], bounds=overlay["bounds"], opacity=0.68, name="SDM predict map", interactive=True).add_to(fmap)
        add_sdm_predict_legend(fmap)
    if layers.get("occ"):
        fg = FeatureGroup(name="occurrences after exclusion", show=True)
        mc = MarkerCluster()
        for _, row in occ.iterrows():
            media_html = image_html(row.get("_media_url", "")) if show_images else ""
            html = f"Occurrence<br>{row['_latitude']:.6f}, {row['_longitude']:.6f}<br>{row.get('_species','')}<br>GBIF {row.get('_gbif_id','')}<br>{media_html}"
            folium.CircleMarker((row["_latitude"], row["_longitude"]), radius=4, color="#1f77b4", fill=True, popup=folium.Popup(html, max_width=330)).add_to(mc)
        mc.add_to(fg); fg.add_to(fmap)
    selected_set = set(int(s) for s in (selected_ids or []))
    if layers.get("candidate_circles") and sites is not None and not sites.empty:
        fg = FeatureGroup(name="candidate circles", show=True)
        for _, row in sites.iterrows():
            ctype = str(row.get("candidate_type", ""))
            marker_radius, color = _priority_marker_style(row)
            rank = row.get("priority_rank", "")
            rank_label = f"Rank {rank} | " if str(rank).strip() not in ("", "nan") else ""
            is_sdm_high = ctype.lower().startswith("sdm-high") or ctype.lower().startswith("sdm_high")
            weight = 2
            dash = "10 5" if is_sdm_high else None
            tooltip_text = f"{rank_label}{ctype} | site {int(row['site_id'])}"
            popup_html = popup_html_site(row)
            loc = (row["latitude"], row["longitude"])
            # Survey range circle
            folium.Circle(loc, radius=survey_range_m, color=color, fill=True, fill_opacity=0.12, weight=weight, popup=folium.Popup(popup_html, max_width=460)).add_to(fg)
            # Priority marker dot
            kwargs: dict[str, Any] = dict(radius=marker_radius, color=color, fill=True, fill_color=color, fill_opacity=0.85, weight=2 if not is_sdm_high else 2, tooltip=tooltip_text, popup=folium.Popup(popup_html, max_width=460))
            if dash:
                kwargs["dash_array"] = dash
            folium.CircleMarker(loc, **kwargs).add_to(fg)
            # Selected-site outer ring
            sid = int(row["site_id"])
            if sid in selected_set:
                folium.CircleMarker(loc, radius=marker_radius + 5, color="#00cc44", fill=False, weight=3, tooltip=f"SELECTED | site {sid}").add_to(fg)
        fg.add_to(fmap)
    if add_draw:
        Draw(export=False, draw_options={"rectangle": True, "polyline": False, "circle": False, "marker": False, "circlemarker": False, "polygon": False}, edit_options={"edit": False, "remove": True}).add_to(fmap)
    LayerControl(collapsed=True).add_to(fmap)
    try:
        lat_values = []
        lon_values = []
        if occ is not None and not occ.empty:
            lat_values.extend(pd.to_numeric(occ["_latitude"], errors="coerce").dropna().tolist())
            lon_values.extend(pd.to_numeric(occ["_longitude"], errors="coerce").dropna().tolist())
        if sites is not None and not sites.empty:
            lat_values.extend(pd.to_numeric(sites["latitude"], errors="coerce").dropna().tolist())
            lon_values.extend(pd.to_numeric(sites["longitude"], errors="coerce").dropna().tolist())
        if lat_values and lon_values:
            fmap.fit_bounds([[min(lat_values), min(lon_values)], [max(lat_values), max(lon_values)]], padding=(30, 30))
    except Exception:
        pass
    return fmap


def load_input_controls(default_fetch_cap: int = FAST_SPECIES_GBIF_FETCH_CAP) -> None:
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
                st.session_state.target_rect_features = []
                st.session_state.target_last_draw_sig = ""
                st.session_state.target_map_reset_token = st.session_state.get("target_map_reset_token", 0) + 1
                st.session_state.sl_last_draw_sig = ""
                st.session_state.sl_reset_token = st.session_state.get("sl_reset_token", 0) + 1
                st.session_state.potential_survey_candidates = None
                reset_model_outputs()
        return
    name = st.sidebar.text_input("Taxon scientific name", value="", placeholder="e.g. Campanula punctata", key="gbif_taxon_scientific_name_input")
    country_options = ["", "JP", "US", "GB", "CN", "KR", "TW", "DE", "FR", "IT", "ES", "AU", "NZ", "CA", "BR", "IN", "ID", "TH", "VN"]
    selected_country = st.sidebar.selectbox("Country code filter (optional)", country_options, index=1, key="gbif_country_code_filter_select", help="Leave blank for worldwide. Two-letter ISO country code.")
    country = selected_country
    use_year = st.sidebar.checkbox("Filter by year", value=False)
    year_from = year_to = None
    if use_year:
        c1, c2 = st.sidebar.columns(2)
        year_from = int(c1.number_input("From", 1600, 2100, 2000))
        year_to = int(c2.number_input("To", 1600, 2100, 2026))
    total_count: Optional[int] = None
    if name.strip():
        try:
            payload, total_count, _params = gbif_species_count_cached(name.strip(), country.strip().upper(), year_from, year_to)
            st.sidebar.info(
                f"GBIF total coordinate records: {total_count:,}. "
                f"The app will fetch up to {int(default_fetch_cap):,} representative records by default."
            )
            st.sidebar.caption(f"Matched taxon: {payload.get('scientificName', name)} / usageKey={payload.get('usageKey')}")
        except Exception as exc:
            st.sidebar.warning(f"GBIF count check failed: {exc}")
    max_records = st.sidebar.number_input(
        "Maximum GBIF records to fetch",
        100,
        200_000,
        int(default_fetch_cap),
        100 if int(default_fetch_cap) <= 3000 else 1000,
        help="The app first checks the GBIF total, then fetches only this survey-planning cap. If total records exceed the cap, pages are sampled from evenly spaced offsets across the full GBIF result range.",
    )
    st.sidebar.caption(
        "Representative fetch: when GBIF total exceeds the cap, records are retrieved from evenly spaced offsets, then deduplicated and spatially capped for survey planning."
    )
    if st.sidebar.button("Fetch occurrences from GBIF", type="primary"):
        if not name.strip():
            st.warning("Scientific name is empty.")
            return
        try:
            with st.spinner("Fetching representative GBIF occurrence subset, 300 records per request..."):
                msg, df = fetch_gbif_occurrences_cached(name.strip(), int(max_records), country.strip().upper(), year_from, year_to)
        except Exception as exc:
            st.error(f"GBIF occurrence download failed after retries: {exc}")
            st.info("Try again in a minute, reduce the maximum record cap, or clear country/year filters. GBIF sometimes resets long paginated requests from Streamlit Cloud.")
            return
        st.session_state.raw_df = df
        st.session_state.source_key = f"gbif::{name}::{country}::{max_records}::{year_from}::{year_to}"
        st.session_state.source_message = msg
        st.session_state.excluded_row_ids = set()
        st.session_state.restore_excluded_row_ids = []
        st.session_state.target_rect_features = []
        st.session_state.target_last_draw_sig = ""
        st.session_state.target_map_reset_token = st.session_state.get("target_map_reset_token", 0) + 1
        st.session_state.sl_last_draw_sig = ""
        st.session_state.sl_reset_token = st.session_state.get("sl_reset_token", 0) + 1
        st.session_state.potential_survey_candidates = None
        reset_model_outputs()


def genus_diversity_panel() -> None:
    st.subheader("1 - Get genus occurrence data")
    st.caption(
        "Genus mode mirrors species mode: load records, choose an observed-data survey area, "
        "generate observed richness hotspot candidates, optionally run SSDM, then use model support for re-ranking or exploration."
    )
    st.sidebar.header("Genus data source")
    genus_fetch_cap = FAST_GENUS_GBIF_FETCH_CAP
    genus_fetch_max_cap = 50_000
    genus_map_records = FAST_MAP_RECORDS
    genus_candidate_records = FAST_CANDIDATE_RECORDS
    genus_ssdm_records = FAST_SSDM_RECORDS_PER_SPECIES
    genus_name = st.sidebar.text_input("Genus name", value="", placeholder="e.g. Cirsium", key="genus_name_input_no_autofill")
    country_options = ["", "JP", "US", "GB", "CN", "KR", "TW", "DE", "FR", "IT", "ES", "AU", "NZ", "CA", "BR", "IN", "ID", "TH", "VN"]
    selected_country = st.sidebar.selectbox("Country code filter (optional)", country_options, index=1, key="genus_country_code_filter", help="Leave blank for worldwide. Two-letter ISO country code.")
    country = selected_country
    use_year = st.sidebar.checkbox("Filter by year", value=False, key="genus_use_year_filter")
    year_from = year_to = None
    if use_year:
        c1, c2 = st.sidebar.columns(2)
        year_from = int(c1.number_input("From", 1600, 2100, 2000, key="genus_year_from"))
        year_to = int(c2.number_input("To", 1600, 2100, 2026, key="genus_year_to"))
    if genus_name.strip():
        try:
            payload, total_count, _params, usage_key = gbif_genus_count_cached(genus_name.strip(), country.strip().upper(), year_from, year_to)
            st.sidebar.info(
                f"GBIF total coordinate records: {total_count:,}. "
                f"The app will fetch up to {int(genus_fetch_cap):,} survey-planning records by default."
            )
            st.sidebar.caption(f"Matched genus: {payload.get('scientificName') or payload.get('canonicalName') or genus_name} / taxonKey={usage_key}")
        except Exception as exc:
            st.sidebar.warning(f"GBIF genus count check failed: {exc}")
    max_records = st.sidebar.number_input(
        "Maximum GBIF records to fetch",
        300,
        int(genus_fetch_max_cap),
        int(genus_fetch_cap),
        300 if int(genus_fetch_cap) <= 3000 else 1000,
        key="genus_max_records_low_offset_unlocked_v4",
        help="Default is lightweight for survey planning, but larger caps such as 10,000 are allowed. GBIF pages are fetched sequentially from low offsets to avoid Streamlit Cloud stalls.",
    )
    st.sidebar.caption("Fetch uses low GBIF offsets to avoid stalls; downstream deduplication and spatial thinning create the working survey subset.")
    if st.sidebar.button("Clear genus data", key="clear_genus_data_button"):
        clear_genus_data()
    if st.sidebar.button("Fetch genus occurrences from GBIF", type="primary", key="fetch_genus_occurrences_button"):
        if not genus_name.strip():
            st.warning("Genus name is empty.")
        else:
            try:
                msg, df, partial_warning = fetch_gbif_genus_occurrences_with_progress(
                    genus_name.strip(),
                    int(max_records),
                    country.strip().upper(),
                    year_from,
                    year_to,
                )
            except Exception as exc:
                st.error(f"GBIF genus download failed after retries: {exc}")
                st.info("Try again in a minute, reduce the maximum record cap, or clear country/year filters. GBIF sometimes resets long paginated requests from Streamlit Cloud.")
            else:
                st.session_state.genus_raw_df = df
                st.session_state.genus_source_key = f"genus::{genus_name}::{country}::{max_records}::{year_from}::{year_to}"
                st.session_state.genus_source_message = msg
                st.session_state.genus_target_rect_features = []
                st.session_state.genus_target_last_draw_sig = ""
                st.session_state.genus_target_map_reset_token = st.session_state.get("genus_target_map_reset_token", 0) + 1
                st.session_state.genus_selected_site_ids = []
                st.session_state.genus_last_click_signature = ""
                st.session_state.genus_last_draw_sig = ""
                st.session_state.genus_selection_map_reset_token = st.session_state.get("genus_selection_map_reset_token", 0) + 1
                st.session_state.genus_ssdm_grid = None
                st.session_state.genus_ssdm_hotspots = None
                st.session_state.genus_ssdm_shape = None
                st.session_state.genus_ssdm_bounds = None
                if partial_warning:
                    st.warning(partial_warning)
                    st.info("Continuing with the successfully fetched partial genus subset.")

    if st.session_state.genus_raw_df is None:
        st.info(st.session_state.genus_source_message)
        return
    st.success(st.session_state.genus_source_message)
    if st.session_state.genus_raw_df.empty:
        st.warning("GBIF returned 0 coordinate records for this genus and filter. Try clearing the country/year filter or increasing the record cap.")
        return
    try:
        detected = detect_occurrence_columns(st.session_state.genus_raw_df)
        occ = clean_occurrences(st.session_state.genus_raw_df, detected)
    except Exception as exc:
        st.error(str(exc))
        return
    if occ.empty:
        st.error("No valid genus coordinate records found.")
        return
    occ_cleaned = enrich_occurrences_with_phenology(occ.copy())

    st.sidebar.divider()
    st.sidebar.subheader("Richness grid")
    grid_deg = st.sidebar.number_input("Grid cell size (degrees)", min_value=0.01, max_value=5.0, value=0.25, step=0.05, format="%.2f", key="genus_grid_deg")
    min_records_cell = st.sidebar.number_input("Minimum records per species per cell", min_value=1, max_value=100, value=1, step=1, key="genus_min_records_cell")
    min_records_for_sdm = st.sidebar.number_input(
        "Minimum records for SSDM eligibility",
        min_value=1, max_value=500, value=10, step=1,
        key="genus_min_records_for_sdm",
        help="Species with fewer records than this value will be flagged as too sparse for SSDM modeling. They can still appear in the occurrence-based richness map, but they will be skipped in SSDM.",
    )
    richness_metric = st.sidebar.selectbox("Hotspot ranking metric", ["Species richness", "Species with minimum records", "Record count"], index=0, key="genus_richness_metric")
    max_hotspots = st.sidebar.number_input("Max hotspot candidates", min_value=1, max_value=200, value=20, step=1, key="genus_max_hotspots")
    # Candidate scoring: fixed scientific defaults
    genus_observed_weight: float = 0.7
    genus_model_weight: float = 0.3
    with st.sidebar.expander("Advanced working subset caps", expanded=False):
        genus_map_records = st.number_input("Genus map display records", 100, 50_000, genus_map_records, 100, key="genus_map_records")
        genus_candidate_records = st.number_input("Genus richness candidate records", 50, 50_000, genus_candidate_records, 50, key="genus_candidate_records")
        genus_ssdm_records = st.number_input("SSDM presence records per species", 3, 5_000, genus_ssdm_records, 25, key="genus_ssdm_records")

    st.subheader("🗺️ Known distribution")
    genus_known_richness_grid = occurrence_richness_grid(occ_cleaned, float(grid_deg), int(min_records_cell))
    st.caption(
        f"{len(occ_cleaned):,} fetched records. "
        "Observed species richness grid is overlaid from all cleaned genus records. "
        "Draw a rectangle to define your fieldwork area."
    )
    if genus_known_richness_grid.empty:
        st.info("Observed species richness grid is not available yet because species names could not be grouped into richness cells.")
    genus_target_display = limit_occurrence_display(occ_cleaned, set(), int(genus_map_records))
    occ, genus_target_counts = target_occurrence_set_panel(
        occ_cleaned,
        genus_target_display,
        raw_record_count=len(occ_cleaned),
        key_prefix="genus_target",
        label="Survey area",
        show_map=True,
        model_label="SSDM",
        allow_advanced_modes=False,
        richness_grid=genus_known_richness_grid,
        richness_metric=richness_metric,
    )
    if occ.empty:
        st.error("The active genus target occurrence set is empty. Change the rectangle target option or clear the target rectangle.")
        return

    # ── Best time to visit (shown right after distribution map) ──────────────
    if "_obs_month" in occ_cleaned.columns:
        _gc_ph_dated = occ_cleaned.dropna(subset=["_obs_month"])
        if not _gc_ph_dated.empty:
            st.subheader("📅 Best time to visit")
            _gc_ph_fl = _gc_ph_dated[_gc_ph_dated["_phenology_state"] == "flowering"] if "_phenology_state" in _gc_ph_dated.columns else pd.DataFrame()
            _gc_ph_all_m = sorted(_gc_ph_dated["_obs_month"].dropna().astype(int).unique().tolist())
            _gc_ph_fl_m = sorted(_gc_ph_fl["_obs_month"].dropna().astype(int).unique().tolist()) if not _gc_ph_fl.empty else []
            _gc_all_counts_d = _gc_ph_dated["_obs_month"].value_counts().to_dict()
            if _gc_ph_fl_m:
                _gc_fl_counts_d = _gc_ph_fl["_obs_month"].value_counts().to_dict()
                _gc_ph_window = _months_to_window_str(_gc_ph_fl_m, counts=_gc_fl_counts_d)
            else:
                _gc_ph_window = _months_to_window_str(_gc_ph_all_m, counts=_gc_all_counts_d)
            _gc_pc1, _gc_pc2 = st.columns([3, 1])
            with _gc_pc1:
                _gc_month_counts = _gc_ph_dated["_obs_month"].value_counts().sort_index()
                if not _gc_ph_fl.empty:
                    _gc_chart = pd.DataFrame({
                        "All records": _gc_month_counts,
                        "Flowering": _gc_ph_fl["_obs_month"].value_counts().sort_index(),
                    }).fillna(0).astype(int)
                else:
                    _gc_chart = _gc_month_counts.rename("All records").to_frame()
                st.bar_chart(_gc_chart, height=160)
            with _gc_pc2:
                st.metric("Recommended window", _gc_ph_window)
                if _gc_ph_fl.empty:
                    st.caption(f"Based on {len(_gc_ph_dated):,} dated records (date-inferred, no flowering evidence).")
                else:
                    _gc_conf = "high" if len(_gc_ph_fl) >= 5 else "medium" if len(_gc_ph_fl) >= 2 else "low"
                    st.caption(f"Flowering evidence: {len(_gc_ph_fl):,} records (confidence: {_gc_conf}).")
            st.caption("⚠️ Observation dates reflect when specimens were collected, not guaranteed flowering dates.")

    genus_candidate_input, summary, grid, hotspots = build_genus_observed_outputs_cached(
        occ,
        int(genus_candidate_records),
        int(min_records_for_sdm),
        float(grid_deg),
        int(min_records_cell),
        richness_metric,
        int(max_hotspots),
    )
    genus_ssdm_grid = st.session_state.get("genus_ssdm_grid")
    genus_ssdm_hotspots = st.session_state.get("genus_ssdm_hotspots")
    if genus_ssdm_grid is not None and isinstance(genus_ssdm_grid, pd.DataFrame) and not genus_ssdm_grid.empty and not hotspots.empty:
        hotspots = add_grid_model_support_to_candidates(hotspots, genus_ssdm_grid)
    hotspots = add_priority_rank(hotspots, float(genus_observed_weight), float(genus_model_weight)) if not hotspots.empty else hotspots
    exploratory_hotspots = pd.DataFrame()
    if genus_ssdm_hotspots is not None and isinstance(genus_ssdm_hotspots, pd.DataFrame) and not genus_ssdm_hotspots.empty:
        exploratory_hotspots = genus_ssdm_hotspots.copy()
        start_sid = int(hotspots["site_id"].max()) + 1 if not hotspots.empty else 1
        exploratory_hotspots["site_id"] = range(start_sid, start_sid + len(exploratory_hotspots))
        exploratory_hotspots = add_priority_rank(exploratory_hotspots, float(genus_observed_weight), float(genus_model_weight))
    genus_all_candidates = pd.concat([hotspots, exploratory_hotspots], ignore_index=True, sort=False) if not exploratory_hotspots.empty else hotspots.copy()
    genus_sort_cols = available_sort_cols(genus_all_candidates, ["priority_score", "model_support_score", "occurrence_support_score"])
    genus_all_candidates = genus_all_candidates.sort_values(genus_sort_cols, ascending=False, na_position="last").reset_index(drop=True) if genus_sort_cols else genus_all_candidates.reset_index(drop=True)

    # Species summary metrics (below the survey area panel).
    species_level_record_count = int(occ["_species"].apply(clean_species_label_for_genus_richness).astype(str).ne("").sum())
    excluded_non_species_count = max(0, int(len(occ)) - species_level_record_count)
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Valid target records", f"{len(occ):,}")
    c2.metric("Species-level records", f"{species_level_record_count:,}", help="Records with a binomial species name used for observed richness and SSDM.")
    c3.metric("Species", f"{summary['species'].nunique():,}" if not summary.empty else "0")
    c4.metric("Grid cells", f"{len(grid):,}")
    c5.metric("Hotspots", f"{len(hotspots):,}", help=f"Excluded genus-only / cf. / sp. labels from richness: {excluded_non_species_count:,}")
    st.dataframe(summary, width="stretch", hide_index=True)
    genus_ssdm_slot = st.container()

    # Richness hotspot suggestions and selection.
    st.subheader("🌿 Richness hotspots")
    st.caption(
        "Observed richness hotspot candidates — no SSDM required. "
        "Optional SSDM below can re-rank candidates and add exploratory model-only hotspots."
    )
    has_ssdm_support = (
        "model_support_score" in hotspots.columns
        and pd.to_numeric(hotspots["model_support_score"], errors="coerce").gt(0).any()
    )
    if not has_ssdm_support:
        st.info(
            f"**Model support score: not available yet.** Hotspots are ranked by observed richness only "
            f"(observed weight = {genus_observed_weight:.2f}). Run optional SSDM above to add predicted richness support."
        )
    else:
        st.success(
            f"**Model support score: SSDM predicted richness active.** Observed hotspots are re-ranked with "
            f"observed weight = {genus_observed_weight:.2f} and SSDM model weight = {genus_model_weight:.2f}."
        )

    if grid.empty:
        st.warning("No richness grid could be built. Check whether GBIF records have species names.")
    elif genus_all_candidates.empty:
        st.warning("No richness hotspot candidates found. Try increasing Max hotspot candidates or adjusting the grid settings.")
    else:
        valid_genus_site_ids = set(genus_all_candidates["site_id"].astype(int).tolist())
        st.session_state.genus_selected_site_ids = [s for s in st.session_state.get("genus_selected_site_ids", []) if s in valid_genus_site_ids]

        st.markdown("#### Select hotspot candidates on the map")
        st.caption(
            "Top-ranked hotspots are shown automatically. Click individual hotspot markers to add/remove them, "
            "or draw a rectangle to add nearby hotspot groups together."
        )
        has_exploratory = "candidate_type" in genus_all_candidates.columns and genus_all_candidates["candidate_type"].astype(str).str.startswith("SSDM-high").any()
        gc1, gc2, gc3 = st.columns(3)
        genus_top_sites_shown = gc1.number_input("Top-ranked hotspots shown", min_value=1, value=20, step=1, key="genus_top_hotspots_shown")
        genus_min_priority = gc2.number_input("Minimum priority score", 0.0, 1.0, 0.0, 0.05, format="%.2f", key="genus_min_priority")
        genus_min_model = gc3.number_input("Minimum SSDM model support", 0.0, 1.0, 0.0, 0.05, format="%.2f", key="genus_min_model_support", disabled=not has_ssdm_support, help="Available after SSDM is built.")
        gi1, gi2, gi3, gi4 = st.columns(4)
        include_observed_hotspots = gi1.checkbox("Include observed richness hotspots", value=True, key="genus_include_observed_hotspots")
        include_ssdm_exploration = gi2.checkbox("Include SSDM-high exploratory hotspots", value=True, key="genus_include_ssdm_exploration", disabled=not has_exploratory)
        genus_travelmode = gi3.selectbox("Google Maps travel mode", ["driving", "walking", "bicycling", "transit"], index=0, key="genus_travelmode")
        if gi4.button("Clear selected hotspots", key="genus_clear_selected_hotspots", disabled=not st.session_state.genus_selected_site_ids):
            st.session_state.genus_selected_site_ids = []
            st.session_state.acsp_result_genus = None
            st.session_state.genus_last_click_signature = ""
            st.session_state.genus_last_draw_sig = ""
            st.session_state.genus_selection_map_reset_token = st.session_state.get("genus_selection_map_reset_token", 0) + 1
            st.rerun()
        genus_show_grid_on_selection_map = st.checkbox(
            "Show richness grid on selection map (slower)",
            value=True,
            key="genus_show_grid_on_selection_map",
            help="Off keeps hotspot selection responsive. Turn on when you want to inspect observed richness cells behind the candidates.",
        )
        if st.button("Clear selection rectangles", key="genus_clear_selection_rectangles", use_container_width=True):
            st.session_state.genus_last_draw_sig = ""
            st.session_state.genus_selection_map_reset_token = st.session_state.get("genus_selection_map_reset_token", 0) + 1
            st.rerun()

        map_hotspots = genus_all_candidates.copy()
        type_mask = pd.Series(False, index=map_hotspots.index)
        if include_observed_hotspots:
            type_mask |= map_hotspots.get("candidate_type", pd.Series("", index=map_hotspots.index)).astype(str).str.startswith("Occurrence")
        if include_ssdm_exploration and has_exploratory:
            type_mask |= map_hotspots.get("candidate_type", pd.Series("", index=map_hotspots.index)).astype(str).str.startswith("SSDM-high")
        if include_observed_hotspots or (include_ssdm_exploration and has_exploratory):
            map_hotspots = map_hotspots[type_mask]
        if "priority_score" in map_hotspots.columns:
            map_hotspots = map_hotspots[pd.to_numeric(map_hotspots["priority_score"], errors="coerce").fillna(0.0) >= float(genus_min_priority)]
        if has_ssdm_support and "model_support_score" in map_hotspots.columns:
            map_hotspots = map_hotspots[pd.to_numeric(map_hotspots["model_support_score"], errors="coerce").fillna(0.0) >= float(genus_min_model)]
        map_sort_cols = available_sort_cols(map_hotspots, ["priority_score", "model_support_score", "occurrence_support_score"])
        map_hotspots = map_hotspots.sort_values(map_sort_cols, ascending=False, na_position="last") if map_sort_cols else map_hotspots
        genus_acsp_pool = map_hotspots.copy()
        map_hotspots = map_hotspots.head(int(genus_top_sites_shown)).copy()
        st.markdown(f"**Top-ranked hotspot output ({len(map_hotspots)})**")
        if map_hotspots.empty:
            st.info("No hotspots match the current display filters.")
        else:
            rank_cols = [c for c in ["site_id", "priority_rank", "priority_score", "candidate_type", "occurrence_support_score", "model_support_score", "observed_species_richness", "ssdm_predicted_richness", "latitude", "longitude", "score_explanation"] if c in map_hotspots.columns]
            st.dataframe(map_hotspots[rank_cols], width="stretch", hide_index=True)
            gh1, gh2, gh3 = st.columns(3)
            gh1.download_button("Top-ranked hotspots CSV", make_export_csv(map_hotspots), "genus_top_ranked_hotspots.csv", "text/csv", use_container_width=True, key="genus_top_ranked_hotspots_csv_download")
            gh2.download_button("Top-ranked hotspots KML", make_export_kml(map_hotspots).encode("utf-8"), "genus_top_ranked_hotspots.kml", "application/vnd.google-earth.kml+xml", use_container_width=True, key="genus_top_ranked_hotspots_kml_download")
            gh3.download_button("Field validation CSV", make_validation_template(map_hotspots).to_csv(index=False).encode("utf-8"), "genus_top_ranked_validation_template.csv", "text/csv", use_container_width=True, key="genus_top_ranked_validation_csv_download")
        if not map_hotspots.empty:
            add_ids = set(map_hotspots["site_id"].astype(int).tolist())
            if st.button(
                f"Add top-ranked shown hotspots ({len(add_ids)})",
                key="genus_add_top_ranked_shown_hotspots",
                use_container_width=True,
            ):
                existing = set(map(int, st.session_state.get("genus_selected_site_ids", [])))
                st.session_state.genus_selected_site_ids = sorted(existing | add_ids)

        # ── ACSP: candidate-SET selection for genus hotspots ─────────────────
        st.markdown("#### Auto-select a survey set (ACSP)")
        st.caption(
            "Adaptive Complementarity-based Survey Prioritization picks a *set* of hotspots that jointly "
            "maximises detection potential, model support, geographic/environmental complementarity, "
            "exploration value and species/sampling-gap coverage while reducing redundancy. "
            "Discovery-focused selection prioritizes likely richness hotspots; Learning-focused selection prioritizes "
            "under-sampled or contrasting areas for field validation."
        )
        gac1, gac2, gac3 = st.columns([2, 1, 1])
        genus_default_mode = "Discovery-focused field survey"
        genus_acsp_mode = gac1.selectbox("Selection algorithm", ACSP_SELECTION_MODES, index=ACSP_SELECTION_MODES.index(genus_default_mode), key="acsp_mode_genus")
        genus_acsp_k = gac2.number_input("Sites to select (K)", 1, max(1, len(genus_acsp_pool)), min(10, max(1, len(genus_acsp_pool))), 1, key="acsp_k_genus")
        genus_acsp_seed = gac3.checkbox("Seed with current selection", value=False, key="acsp_seed_genus", help="Keep already-selected hotspots as the starting set (S0) and fill the rest by complementarity.")
        if st.button("Auto-select by selected algorithm", key="acsp_run_genus", use_container_width=True, disabled=genus_acsp_pool.empty):
            genus_seed_ids = list(st.session_state.get("genus_selected_site_ids", [])) if genus_acsp_seed else None
            genus_acsp_res = acsp_select(genus_acsp_pool, int(genus_acsp_k), genus_acsp_mode, selected_ids=genus_seed_ids)
            if genus_acsp_res.empty:
                st.warning("ACSP could not select any hotspots from the current candidate pool.")
            else:
                st.session_state.acsp_result_genus = genus_acsp_res
                st.session_state.genus_selected_site_ids = [int(s) for s in genus_acsp_res["site_id"].tolist()]
                st.session_state.genus_selection_map_reset_token = st.session_state.get("genus_selection_map_reset_token", 0) + 1
                st.rerun()

        _genus_sel_ids_for_map = tuple(sorted(st.session_state.genus_selected_site_ids))
        genus_map = make_genus_candidate_selection_map(
            grid,
            map_hotspots,
            richness_metric,
            selected_ids=(),
            add_draw=True,
            show_grid=bool(genus_show_grid_on_selection_map),
        )
        genus_selected_overlay = make_selected_site_overlay(genus_all_candidates, _genus_sel_ids_for_map, name="selected hotspot sites")
        genus_map_data = st_folium_with_overlay(
            genus_map,
            genus_selected_overlay,
            width=None,
            height=720,
            returned_objects=["last_object_clicked", "last_object_clicked_tooltip", "all_drawings", "last_active_drawing"],
            key=f"genus_hotspot_selection_map_{st.session_state.get('genus_selection_map_reset_token', 0)}",
        )
        clicked = (genus_map_data or {}).get("last_object_clicked")
        clicked_tooltip = (genus_map_data or {}).get("last_object_clicked_tooltip") or ""
        if clicked:
            sig = f"{clicked.get('lat'):.6f},{clicked.get('lng'):.6f},{clicked_tooltip}"
            if sig != st.session_state.get("genus_last_click_signature", ""):
                st.session_state.genus_last_click_signature = sig
                sid = None
                match = re.search(r"site\s+(\d+)", str(clicked_tooltip), flags=re.IGNORECASE)
                if match:
                    sid = int(match.group(1))
                else:
                    sid = nearest_site_id_from_click(map_hotspots, clicked)
                if sid is not None and sid in valid_genus_site_ids:
                    selected = list(st.session_state.genus_selected_site_ids)
                    if sid in selected:
                        selected.remove(sid)
                    else:
                        selected.append(sid)
                    st.session_state.genus_selected_site_ids = selected
        raw_drawings = (genus_map_data or {}).get("all_drawings") or (genus_map_data or {}).get("last_active_drawing")
        features = extract_drawn_features(raw_drawings)
        if features:
            draw_sig = str(features)[:800]
            if draw_sig != st.session_state.get("genus_last_draw_sig", ""):
                st.session_state.genus_last_draw_sig = draw_sig
                rect_ids = ids_inside_drawn_rectangles(genus_all_candidates, "site_id", "latitude", "longitude", features)
                if rect_ids:
                    existing = set(st.session_state.genus_selected_site_ids)
                    st.session_state.genus_selected_site_ids = sorted(existing | set(map(int, rect_ids)))

        html_bytes = genus_map.get_root().render().encode("utf-8")
        selected_ids_now = list(st.session_state.get("genus_selected_site_ids", []))
        selected_hotspots = genus_all_candidates[genus_all_candidates["site_id"].astype(int).isin(selected_ids_now)].copy()
        if not selected_hotspots.empty:
            selected_hotspots = acsp_merge_columns(selected_hotspots, st.session_state.get("acsp_result_genus"))
        if not selected_hotspots.empty and selected_ids_now:
            order_map = {sid: i for i, sid in enumerate(selected_ids_now)}
            selected_hotspots = selected_hotspots.assign(_ord=selected_hotspots["site_id"].astype(int).map(order_map)).sort_values("_ord").drop(columns=["_ord"])
        st.markdown(f"**Selected hotspot sites ({len(selected_hotspots)})**")
        if selected_hotspots.empty:
            st.info("No hotspots selected yet. Click candidate markers, draw a rectangle, or use ACSP auto-select above.")
        else:
            selected_hotspots["google_maps_point_url"] = selected_hotspots.apply(lambda r: make_google_maps_point_url(float(r["latitude"]), float(r["longitude"])), axis=1)
            sum_cols = [c for c in ["site_id", "selection_step", "priority_rank", "priority_score", "candidate_type", "observed_species_richness", "ssdm_predicted_richness", "marginal_gain_score", "selection_reason", "google_maps_point_url"] if c in selected_hotspots.columns]
            cfg: dict[str, Any] = {}
            if "google_maps_point_url" in sum_cols:
                cfg["google_maps_point_url"] = st.column_config.LinkColumn("Google Maps", display_text="Open")
            st.dataframe(selected_hotspots[sum_cols], column_config=cfg, width="stretch", hide_index=True)
            gs1, gs2, gs3, gs4, gs5, gs6 = st.columns(6)
            gs1.link_button("Open all in Google Maps", make_google_maps_route_url(selected_hotspots, travelmode=genus_travelmode, max_waypoints=8), use_container_width=True)
            gs2.download_button("CSV", make_export_csv(selected_hotspots), "genus_selected_hotspot_sites.csv", "text/csv", use_container_width=True, key="genus_selected_hotspots_csv_download")
            gs3.download_button("HTML", make_shareable_html(selected_hotspots), "genus_selected_hotspot_sites.html", "text/html", use_container_width=True, key="genus_selected_hotspots_html_download")
            gs4.download_button("KML", make_export_kml(selected_hotspots).encode("utf-8"), "genus_selected_hotspot_sites.kml", "application/vnd.google-earth.kml+xml", use_container_width=True, key="genus_selected_hotspots_kml_download")
            gs5.download_button("Validation CSV", make_validation_template(selected_hotspots).to_csv(index=False).encode("utf-8"), "genus_field_validation_template.csv", "text/csv", use_container_width=True, key="genus_selected_hotspots_validation_csv_download")
            if gs6.button("Clear selected", key="genus_clear_selected_hotspots_summary"):
                st.session_state.genus_selected_site_ids = []
                st.session_state.acsp_result_genus = None
                st.session_state.genus_last_click_signature = ""
                st.session_state.genus_last_draw_sig = ""
                st.rerun()

        with st.expander("Optional: full genus hotspot tables and downloads", expanded=False):
            hotspot_cols = ["site_id", "hotspot_rank", "priority_rank", "priority_score", "occurrence_support_score", "model_support_score", "observed_weight", "model_weight", "candidate_type", "latitude", "longitude", "observed_species_richness", "ssdm_predicted_richness", "species_richness", "record_count", "species_with_min_records", "species_list", "score_explanation", "google_maps_url"]
            st.write("All genus hotspot candidates")
            st.dataframe(genus_all_candidates[[c for c in hotspot_cols if c in genus_all_candidates.columns]], width="stretch", hide_index=True)
            d1, d2, d3, d4, d5 = st.columns(5)
            d1.download_button("Species summary CSV", summary.to_csv(index=False).encode("utf-8"), "genus_species_summary.csv", "text/csv", width="stretch", key="genus_species_summary_csv_download")
            d2.download_button("Richness grid CSV", grid.to_csv(index=False).encode("utf-8"), "genus_richness_grid.csv", "text/csv", width="stretch", key="genus_richness_grid_csv_download")
            d3.download_button("All hotspots CSV", genus_all_candidates.to_csv(index=False).encode("utf-8"), "genus_all_hotspot_candidates.csv", "text/csv", width="stretch", key="genus_all_hotspots_csv_download")
            d4.download_button("Richness HTML map", html_bytes, "genus_hotspot_selection_map.html", "text/html", width="stretch", key="genus_richness_html_map_download")
            d5.download_button("All hotspots KML", make_export_kml(genus_all_candidates).encode("utf-8"), "genus_all_hotspot_candidates.kml", "application/vnd.google-earth.kml+xml", width="stretch", key="genus_all_hotspots_kml_download")

    # ── Best time to visit (genus survey area) ────────────────────────────────
    if not genus_all_candidates.empty and "_obs_month" in occ_cleaned.columns:
        _gc2_ph_dated = occ_cleaned.dropna(subset=["_obs_month"])
        if not _gc2_ph_dated.empty:
            st.subheader("📅 Best time to visit (survey area)")
            _gc2_ph_fl = _gc2_ph_dated[_gc2_ph_dated["_phenology_state"] == "flowering"] if "_phenology_state" in _gc2_ph_dated.columns else pd.DataFrame()
            _gc2_all_months = sorted(_gc2_ph_dated["_obs_month"].dropna().astype(int).unique().tolist())
            _gc2_fl_months = sorted(_gc2_ph_fl["_obs_month"].dropna().astype(int).unique().tolist()) if not _gc2_ph_fl.empty else []
            _gc2_all_counts_d = _gc2_ph_dated["_obs_month"].value_counts().to_dict()
            if _gc2_fl_months:
                _gc2_fl_counts_d = _gc2_ph_fl["_obs_month"].value_counts().to_dict()
                _gc2_ph_window = _months_to_window_str(_gc2_fl_months, counts=_gc2_fl_counts_d)
            else:
                _gc2_ph_window = _months_to_window_str(_gc2_all_months, counts=_gc2_all_counts_d)
            _gc2_pc1, _gc2_pc2 = st.columns([3, 1])
            with _gc2_pc1:
                _gc2_month_counts = _gc2_ph_dated["_obs_month"].value_counts().sort_index()
                if not _gc2_ph_fl.empty:
                    _gc2_chart = pd.DataFrame({
                        "All records": _gc2_month_counts,
                        "Flowering": _gc2_ph_fl["_obs_month"].value_counts().sort_index(),
                    }).fillna(0).astype(int)
                else:
                    _gc2_chart = _gc2_month_counts.rename("All records").to_frame()
                st.bar_chart(_gc2_chart, height=160)
            with _gc2_pc2:
                st.metric("Recommended window", _gc2_ph_window)
                if _gc2_ph_fl.empty:
                    st.caption(f"Based on {len(_gc2_ph_dated):,} dated records (no flowering evidence).")
                else:
                    _gc2_conf = "high" if len(_gc2_ph_fl) >= 5 else "medium" if len(_gc2_ph_fl) >= 2 else "low"
                    st.caption(f"Flowering evidence: {len(_gc2_ph_fl):,} records (confidence: {_gc2_conf}).")
            st.caption("⚠️ Based on genus occurrence records used to generate hotspot candidates.")

    # ── Auto-generated Methods text (genus) ───────────────────────────────────
    st.subheader("Methods (auto-generated)")
    st.caption("Copy this text for the Methods section of your report or paper.")
    _genus_ssdm_summary = st.session_state.get("genus_ssdm_model_summary")
    _genus_ssdm_methods = ""
    if _genus_ssdm_summary is not None and not _genus_ssdm_summary.empty:
        _modeled_sp = _genus_ssdm_summary[_genus_ssdm_summary["status"] == "modeled"]
        _n_modeled = len(_modeled_sp)
        _n_eligible = len(_genus_ssdm_summary[_genus_ssdm_summary["status"].isin(["modeled", "skipped_after_thinning"])])
        _mean_aucs = pd.to_numeric(_modeled_sp["mean_auc"], errors="coerce").dropna()
        _mean_auc_str = f"{_mean_aucs.mean():.3f}" if not _mean_aucs.empty else "N/A"
        _kept_vars_str = _modeled_sp["variables_kept"].iloc[0] if not _modeled_sp.empty and "variables_kept" in _modeled_sp.columns else ", ".join(BALANCED_ECOLOGY_PRESET)
        _algs_str = _modeled_sp["algorithms"].iloc[0] if not _modeled_sp.empty and "algorithms" in _modeled_sp.columns else "Random Forest and ExtraTrees"
        _extent_mode = st.session_state.get("ssdm_extent_mode", "species_specific")
        _extent_note = (
            "Species-specific prediction extents were used; cells outside each species' occurrence-based bounding box were treated as unevaluated (NA), not as absence."
            if _extent_mode == "species_specific"
            else "A shared genus-wide prediction extent was used for all species."
        )
        _genus_ssdm_methods = (
            f" An ensemble SSDM was fitted for {_n_modeled} of {_n_eligible} eligible species "
            f"using {_algs_str} with environmental predictors ({_kept_vars_str[:80]}{'...' if len(_kept_vars_str) > 80 else ''}; "
            f"WorldClim 2.1, 2.5 arc-minutes). "
            f"Predictor collinearity was reduced by shared VIF stepwise filtering (threshold = 10) "
            f"applied once on pooled occurrence and background data. "
            f"{_extent_note} "
            f"SSDM predicted richness was summed from per-species suitability values (mean cross-validation AUC = {_mean_auc_str}). "
            f"Hotspot candidates were re-ranked by a weighted composite score "
            f"(observed richness support w = {genus_observed_weight:.1f}; SSDM richness support w = {genus_model_weight:.1f})."
        )
    _genus_source = st.session_state.get("genus_source_key", "[genus]")
    _genus_methods_text = (
        f"Genus {_genus_source} occurrence records were retrieved from the Global Biodiversity Information Facility "
        f"(GBIF; gbif.org) on {__import__('datetime').date.today().isoformat()} "
        f"({len(occ_cleaned):,} records fetched). "
        f"Records were aggregated to a {float(grid_deg):.2f}° grid; observed species richness was computed per cell. "
        f"Survey hotspot candidates (top {len(hotspots):,}) were identified from peak-richness grid cells "
        f"and ranked by {richness_metric.lower()}.{_genus_ssdm_methods}"
    )
    st.code(_genus_methods_text, language=None)

    with genus_ssdm_slot:
        st.subheader("Optional: Run SSDM")
        st.caption("Predicted stacked richness: fit one SDM per eligible species, predict on a shared environmental grid, then sum suitability values across species. This does not run automatically.")
        # Record-count guidance (mirrors species SDM guidance)
        _pre_ssdm_n = min(len(occ_cleaned), int(genus_ssdm_records))
        if _pre_ssdm_n < 20:
            st.info(f"⚠️ Source records are sparse ({_pre_ssdm_n} per-species cap). SSDM predictions will be highly uncertain — use for exploration only, with field validation required.")
        elif _pre_ssdm_n < 50:
            st.info(f"SSDM can help identify exploratory potential sites beyond known hotspots ({_pre_ssdm_n} per-species cap).")
        else:
            st.info(f"SSDM will use a spatially representative subset of up to {_pre_ssdm_n} records per species rather than all fetched records.")
        sm1, sm2, sm3 = st.columns(3)
        sm1.metric("SSDM source records", f"{len(occ_cleaned):,}", help="Independent from the Step 2 observed-richness survey-area rectangle.")
        sm2.metric("Observed hotspot records", f"{len(genus_candidate_input):,}", help="Records used for observed richness hotspot generation after Step 2 and thinning.")
        sm3.metric("Per-species SSDM cap", f"{int(genus_ssdm_records):,}", help="Maximum presence records used per species before fitting SSDM.")
        ssdm_expander = st.expander("Run stacked species distribution models", expanded=False)
    with ssdm_expander:
        # ── SSDM prediction extent (user decision — mirrors SDM) ──────────────
        st.markdown("**SSDM prediction extent**")
        st.caption(
            "The extent defines where stacked suitability is predicted. "
            "It is independent from the Step 2 survey area. "
            "A broader extent generally improves individual species SDMs."
        )
        ssdm_area_mode = st.selectbox("SSDM prediction area", AREA_MODES, index=2, key="ssdm_area_mode")
        _sb1, _sb2 = st.columns(2)
        ssdm_buffer_km = _sb1.number_input("Buffer radius / hull buffer (km)", min_value=0.1, max_value=500.0, value=10.0, step=1.0, key="ssdm_buffer_km")
        ssdm_margin_km = _sb2.number_input("Bounding-box margin (km)", min_value=0.0, max_value=500.0, value=20.0, step=5.0, key="ssdm_margin_km")

        st.divider()
        # ── Environmental variables (fixed default + Advanced, mirrors SDM) ───
        _SSDM_DEFAULT_ALGORITHMS = ["Random forest", "ExtraTrees"]
        ssdm_resolution = "2.5m"           # fixed, same as species SDM
        ssdm_variables = list(BALANCED_ECOLOGY_PRESET)
        ssdm_algorithms = list(_SSDM_DEFAULT_ALGORITHMS)
        ssdm_variable_strategy = "VIF stepwise"
        ssdm_vif_threshold = 10.0
        ssdm_corr_threshold = 0.80
        ssdm_custom_variables = ssdm_variables
        st.markdown("**Environmental variables**")
        st.caption(
            f"Default: balanced ecology preset — {', '.join(BALANCED_ECOLOGY_PRESET)}. "
            "Override in Advanced below. Shared VIF stepwise (threshold 10) applied once on pooled data."
        )

        with st.expander("Advanced: variables & algorithms", expanded=False):
            st.caption(
                "Override scientific defaults. Variable selection is run once on a pooled sample of all genus "
                "occurrences and background points, then the retained variable set is used for every per-species model."
            )
            ssdm_variables = st.multiselect(
                "SSDM environmental variables",
                TOPOGRAPHY_VARS + CLIMATE_VARS,
                default=list(BALANCED_ECOLOGY_PRESET),
                key="ssdm_environment_variables",
                help="Balanced ecology variables are selected by default.",
            )
            ssdm_algorithms = st.multiselect(
                "SSDM algorithms",
                ALGORITHMS,
                default=list(_SSDM_DEFAULT_ALGORITHMS),
                key="ssdm_algorithms",
                help="Random Forest + ExtraTrees is the scientific default.",
            )
            ssdm_variable_strategy = st.selectbox(
                "Advanced SSDM variable-selection strategy",
                ["VIF stepwise", "Correlation filter", "Advanced custom selection"],
                index=0,
                key="ssdm_variable_strategy",
            )
            vc1, vc2 = st.columns(2)
            ssdm_corr_threshold = vc1.number_input("SSDM correlation threshold", min_value=0.50, max_value=0.99, value=0.80, step=0.05, format="%.2f", key="ssdm_corr_threshold")
            ssdm_vif_threshold = vc2.number_input("SSDM VIF threshold", min_value=1.0, max_value=100.0, value=10.0, step=1.0, key="ssdm_vif_threshold")
            ssdm_custom_variables = ssdm_variables
            if ssdm_variable_strategy == "Advanced custom selection":
                ssdm_custom_variables = st.multiselect("SSDM custom final variables", ssdm_variables, default=ssdm_variables, key="ssdm_custom_final_variables")

        # ── Per-species bias reduction (Auto default) ─────────────────────────
        ssdm_per_species_grid_deg = 0.05   # Auto default
        ssdm_per_species_distance_m = 0
        with st.expander("Advanced: per-species bias reduction", expanded=False):
            ssdm_bias_mode = st.radio(
                "Per-species bias reduction",
                ["Auto (Recommended)", "Advanced / Custom", "Off"],
                index=0, horizontal=True, key="ssdm_bias_reduction_mode",
            )
            if ssdm_bias_mode.startswith("Auto"):
                ssdm_per_species_grid_deg = 0.05
                ssdm_per_species_distance_m = 0
                st.caption("Auto: exact coordinate deduplication + one record per 0.05° grid cell per species.")
            elif ssdm_bias_mode.startswith("Off"):
                ssdm_per_species_grid_deg = 0.0
                ssdm_per_species_distance_m = 0
                st.caption("Off: exact coordinate deduplication only.")
            else:
                ps1, ps2 = st.columns(2)
                ssdm_per_species_grid_deg = ps1.number_input("Per-species grid thinning (degrees, 0 = off)", min_value=0.0, max_value=5.0, value=0.05, step=0.01, format="%.2f", key="ssdm_per_species_grid_deg")
                ssdm_per_species_distance_m = ps2.number_input("Per-species distance thinning (m, 0 = off)", min_value=0, max_value=100_000, value=0, step=500, key="ssdm_per_species_distance_m")

        # ── Advanced model settings (mirrors SDM Advanced model settings) ─────
        ssdm_min_records = max(10, int(min_records_for_sdm))
        ssdm_max_species = 20
        ssdm_max_presence = int(genus_ssdm_records)
        ssdm_background = 500
        ssdm_max_pixels = 30_000
        ssdm_hotspot_n = 20
        ssdm_binary_threshold = 0.50
        with st.expander("Advanced model settings", expanded=False):
            _am1, _am2 = st.columns(2)
            ssdm_min_records = _am1.number_input("Minimum records per species", min_value=3, max_value=500, value=ssdm_min_records, step=1, key="ssdm_min_records")
            ssdm_max_species = _am2.number_input("Max species to model", min_value=1, max_value=200, value=ssdm_max_species, step=1, key="ssdm_max_species")
            _am3, _am4 = st.columns(2)
            ssdm_max_presence = _am3.number_input("Max presence points per species", min_value=3, max_value=5_000, value=ssdm_max_presence, step=25, key="ssdm_max_presence")
            ssdm_background = _am4.number_input("Shared background cells", min_value=50, max_value=20_000, value=ssdm_background, step=50, key="ssdm_background")
            _am5, _am6, _am7 = st.columns(3)
            ssdm_max_pixels = _am5.number_input("Max prediction cells", min_value=1_000, max_value=200_000, value=ssdm_max_pixels, step=5_000, key="ssdm_max_pixels")
            ssdm_hotspot_n = _am6.number_input("SSDM hotspot candidates", min_value=1, max_value=200, value=ssdm_hotspot_n, step=1, key="ssdm_hotspot_n")
            ssdm_binary_threshold = _am7.number_input("Binary suitability threshold", min_value=0.0, max_value=1.0, value=ssdm_binary_threshold, step=0.05, key="ssdm_binary_threshold")

        st.markdown("**SSDM validation / partition**")
        st.caption("Validation: automatically selected per species using the same rules as species SDM (auto_sdm_partition).")
        ssdm_partition_override = "auto"  # default
        ssdm_k_folds = 5
        ssdm_checkerboard_deg = 0.05
        ssdm_holdout_split = 0.20
        with st.expander("Advanced: force validation method across all species", expanded=False):
            st.caption("block/checkerboard needs enough records per species; jackknife for very small samples.")
            ssdm_partition_override = st.selectbox(
                "Force validation method (or keep Auto)",
                ["auto"] + PARTITION_METHODS,
                index=0,
                key="ssdm_partition_override",
            )
            if ssdm_partition_override == "random k-fold":
                ssdm_k_folds = st.number_input("k", 2, 20, 5, 1, key="ssdm_k_folds")
            if ssdm_partition_override in ("checkerboard1", "checkerboard2"):
                ssdm_checkerboard_deg = st.number_input("Checkerboard cell size (degrees)", 0.001, 5.0, 0.05, 0.01, format="%.3f", key="ssdm_checker_deg")
            if ssdm_partition_override == "random holdout":
                ssdm_holdout_split = st.number_input("Test split proportion", 0.10, 0.50, 0.20, 0.05, key="ssdm_holdout_split")
        # Legacy variables kept for backward compatibility in call site
        ssdm_partition_method = ssdm_partition_override
        ssdm_test_split = ssdm_holdout_split

        st.markdown("**SSDM prediction extent strategy**")
        st.caption(
            "Species-specific extents (default): each species is predicted only within its own "
            "occurrence-based spatial extent. Cells outside are NA (unevaluated), not absence. "
            "Richness is summed only where each species-level model was evaluated."
        )
        ssdm_extent_mode = "species_specific"
        ssdm_min_coverage = 2
        with st.expander("Advanced: prediction extent strategy", expanded=False):
            ssdm_extent_mode = st.radio(
                "SSDM prediction extent",
                ["species_specific", "shared_genus"],
                index=0,
                format_func=lambda x: {
                    "species_specific": "Species-specific extents (recommended) — NA outside each species' range",
                    "shared_genus": "Shared genus-wide extent (exploratory) — may overpredict narrow-range species",
                }[x],
                key="ssdm_extent_mode",
            )
            ssdm_min_coverage = st.number_input(
                "Minimum species evaluated per candidate cell",
                min_value=1, max_value=20, value=2, step=1,
                key="ssdm_min_coverage",
                help="SSDM-high exploration candidates require this many species to have been modeled in the cell.",
            )

        run_ssdm = st.button("Run SSDM", type="primary", key="run_ssdm_button")

    if run_ssdm:
        if not ssdm_variables:
            st.warning("Select at least one environmental variable for SSDM.")
        elif not ssdm_algorithms:
            st.warning("Select at least one algorithm for SSDM.")
        else:
            status = st.empty()
            progress = st.progress(0.0)
            try:
                model_summary, ssdm_grid, ssdm_hotspots, ssdm_shape, ssdm_bounds, ssdm_vif_diag = fit_stacked_species_sdms(
                    occ=occ_cleaned,
                    variables=ssdm_variables,
                    algorithms=ssdm_algorithms,
                    resolution=ssdm_resolution,
                    area_mode=ssdm_area_mode,
                    buffer_km=float(ssdm_buffer_km),
                    rectangle_margin_km=float(ssdm_margin_km),
                    max_pixels=int(ssdm_max_pixels),
                    min_records=int(ssdm_min_records),
                    max_species=int(ssdm_max_species),
                    max_presence_points=int(ssdm_max_presence),
                    n_background=int(ssdm_background),
                    binary_threshold=float(ssdm_binary_threshold),
                    max_hotspots=int(ssdm_hotspot_n),
                    apply_vif=False,
                    vif_threshold=float(ssdm_vif_threshold),
                    variable_selection_strategy=ssdm_variable_strategy,
                    corr_threshold=float(ssdm_corr_threshold),
                    custom_variables=ssdm_custom_variables,
                    ssdm_partition_override=ssdm_partition_override,
                    ssdm_partition_method=ssdm_partition_method,
                    ssdm_test_split=float(ssdm_test_split),
                    ssdm_k_folds=int(ssdm_k_folds),
                    ssdm_checkerboard_deg=float(ssdm_checkerboard_deg),
                    ssdm_holdout_split=float(ssdm_holdout_split),
                    per_species_grid_thin_deg=float(ssdm_per_species_grid_deg),
                    per_species_distance_thin_m=float(ssdm_per_species_distance_m),
                    ssdm_extent_mode=ssdm_extent_mode,
                    ssdm_min_coverage=int(ssdm_min_coverage),
                    status=status,
                    progress=progress,
                )
                ssdm_hotspots = add_priority_rank(ssdm_hotspots, float(genus_observed_weight), float(genus_model_weight))
                ranked_observed_hotspots = add_grid_model_support_to_candidates(hotspots, ssdm_grid)
                ranked_observed_hotspots = add_priority_rank(ranked_observed_hotspots, float(genus_observed_weight), float(genus_model_weight))
                st.session_state.genus_ssdm_grid = ssdm_grid
                st.session_state.genus_ssdm_hotspots = ssdm_hotspots
                st.session_state.genus_ssdm_shape = ssdm_shape
                st.session_state.genus_ssdm_bounds = ssdm_bounds
                st.session_state.genus_ssdm_model_summary = model_summary
                st.success("SSDM complete.")

                # Shared variable-selection diagnostics.
                if ssdm_vif_diag is not None and not ssdm_vif_diag.empty:
                    fallback_rows = ssdm_vif_diag[ssdm_vif_diag.get("fallback_kept", pd.Series(dtype=bool)).astype(bool)]
                    if not fallback_rows.empty:
                        st.warning(
                            "Shared variable selection kept a fallback/protected climate variable despite high collinearity. "
                            f"Fallback: {', '.join(fallback_rows['variable'].tolist())} was restored. "
                            "Check final_status, reason, protected_by_group, fallback_kept, and vif_stage in the diagnostics."
                        )
                    st.write("Shared variable-selection diagnostics (run once for all species)")
                    st.caption(
                        "This table shows variable statistics, max pairwise correlation, and VIF computed on a pooled sample "
                        "of all genus occurrences and background points before variable selection. "
                        "All species models use the same 'kept' variable set."
                    )
                    st.dataframe(ssdm_vif_diag, width="stretch", hide_index=True)

                st.write("SSDM species model summary")
                st.dataframe(model_summary, width="stretch", hide_index=True)
                st.write("Continuous SSDM richness map")
                continuous_map = make_ssdm_map(ssdm_grid, ssdm_hotspots, "ssdm_continuous_richness", "continuous SSDM richness", ssdm_shape, ssdm_bounds)
                st_folium(continuous_map, width=None, height=620, returned_objects=[], key="ssdm_continuous_map")
                st.write("Binary SSDM richness map")
                binary_map = make_ssdm_map(ssdm_grid, ssdm_hotspots, "ssdm_binary_richness", "binary SSDM richness", ssdm_shape, ssdm_bounds)
                st_folium(binary_map, width=None, height=620, returned_objects=[], key="ssdm_binary_map")
                st.write("SSDM hotspot candidates")
                st.dataframe(ssdm_hotspots, width="stretch", hide_index=True)
                st.write("Observed richness hotspots re-ranked with optional SSDM support")
                st.caption("These remain observed-data hotspot candidates; SSDM predicted richness only contributes model_support_score for prioritization.")
                st.dataframe(ranked_observed_hotspots, width="stretch", hide_index=True)
                st.info("SSDM results were saved for the main richness hotspot map. The next app rerun will add SSDM support in the Step 4 candidate selection workflow.")
                d1, d2, d3, d4, d5 = st.columns(5)
                d1.download_button("ssdm_species_model_summary.csv", model_summary.to_csv(index=False).encode("utf-8"), "ssdm_species_model_summary.csv", "text/csv", width="stretch", key="ssdm_species_model_summary_csv_download")
                d2.download_button("ssdm_richness_grid.csv", ssdm_grid.to_csv(index=False).encode("utf-8"), "ssdm_richness_grid.csv", "text/csv", width="stretch", key="ssdm_richness_grid_csv_download")
                d3.download_button("ssdm_hotspot_candidates.csv", ssdm_hotspots.to_csv(index=False).encode("utf-8"), "ssdm_hotspot_candidates.csv", "text/csv", width="stretch", key="ssdm_hotspot_candidates_csv_download")
                d4.download_button("continuous SSDM HTML", continuous_map.get_root().render().encode("utf-8"), "ssdm_continuous_richness_map.html", "text/html", width="stretch", key="ssdm_continuous_html_download")
                d5.download_button("binary SSDM HTML", binary_map.get_root().render().encode("utf-8"), "ssdm_binary_richness_map.html", "text/html", width="stretch", key="ssdm_binary_html_download")
                if ssdm_vif_diag is not None and not ssdm_vif_diag.empty:
                    d_vif_col = st.columns(1)[0]
                    d_vif_col.download_button("ssdm_variable_selection_diagnostics.csv", ssdm_vif_diag.to_csv(index=False).encode("utf-8"), "ssdm_variable_selection_diagnostics.csv", "text/csv", use_container_width=True, key="ssdm_variable_selection_diagnostics_csv_download")
            except Exception as exc:
                st.error(f"SSDM failed: {exc}")


def nearest_site_id_from_click(sites: pd.DataFrame, click: dict[str, Any]) -> Optional[int]:
    if not click or "lat" not in click or "lng" not in click or sites.empty:
        return None
    coord = (float(click["lat"]), float(click["lng"]))
    dists = sites.apply(lambda r: geodesic(coord, (float(r["latitude"]), float(r["longitude"]))).km, axis=1)
    return int(sites.loc[int(dists.idxmin()), "site_id"])


SURVEY_DAY_CSV_COLS = ["survey_day", "order_within_day", "site_id", "candidate_type", "priority_rank", "priority_score", "occurrence_support_score", "model_support_score", "observed_weight", "model_weight", "score_explanation", "sdm_suitability", "n_occurrences", "latitude", "longitude", "google_maps_url", "access_note"]


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
            rows.append({"survey_day": day_num, "order_within_day": order, "site_id": int(r.get("site_id", sid)), "candidate_type": r.get("candidate_type", ""), "priority_rank": r.get("priority_rank", ""), "priority_score": r.get("priority_score", ""), "sdm_suitability": r.get("sdm_suitability", ""), "occurrence_support_score": r.get("occurrence_support_score", ""), "model_support_score": r.get("model_support_score", ""), "observed_weight": r.get("observed_weight", ""), "model_weight": r.get("model_weight", ""), "score_explanation": r.get("score_explanation", ""), "n_occurrences": r.get("n_occurrences", ""), "latitude": float(r["latitude"]), "longitude": float(r["longitude"]), "google_maps_url": make_google_maps_point_url(float(r["latitude"]), float(r["longitude"])), "access_note": r.get("access_note", "")})
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


EXPORT_CSV_COLS = ["site_id", "name", "latitude", "longitude", "plan_name", "plan_rank", "discover_utility", "discovery_value", "learning_value", "accessibility_score", "representation_value", "discovery_label", "learning_label", "access_label", "data_quality", "constraint_status", "priority_rank", "priority_score", "occurrence_support_score", "model_support_score", "field_validation_support_score", "observed_weight", "model_weight", "score_explanation", "sdm_suitability", "ssdm_predicted_richness", "observed_species_richness", "species_richness", "record_count", "species_list", "n_occurrences", "candidate_type", "candidate_method", "habitat_basis", "macro_filter_basis", "habitat_score", "environmental_similarity", "mahalanobis_environment_distance", "analogue_score", "environmental_distance_to_known", "environmental_novelty", "survey_effort_proxy", "survey_gap_score", "access_score", "target_record_density", "all_taxa_record_density", "nearest_known_population_km", "requested_search_cell_size_m", "effective_search_cell_size_m", "resolution_decision_reason", "resolution_data_quality", "effective_grid_cells_evaluated", "search_cell_radius_m", "elevation", "slope", "aspect", "roughness", "tpi", "ndvi", "landcover", "landcover_match_score", "distance_to_road_m", "distance_to_trail_m", "distance_to_coast_m", "distance_to_forest_edge_m", "missing_layer_note", "validation_learning_note", "why_selected", "selection_reason", "selection_algorithm", "selection_step", "base_score", "geographic_complementarity_gain", "environmental_complementarity_gain", "habitat_analogue_gain", "exploration_gain", "sampling_gap_gain", "validation_learning_gain", "access_gain", "redundancy_penalty", "travel_penalty", "marginal_gain_score", "access_note", "recommended_survey_window", "season_confidence", "flowering_record_count", "google_maps_url"]


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
        '  <name>ACSP — Adaptive Complementarity-based Survey Prioritization survey sites</name>',
    ]
    for _, r in sites.iterrows():
        name = f"Site {int(r['site_id'])}"
        desc_parts = [f"{col}: {r[col]}" for col in ["candidate_type", "priority_rank", "priority_score", "sdm_suitability", "ssdm_predicted_richness", "observed_species_richness", "species_list", "occurrence_support_score", "n_occurrences", "selection_reason", "access_note"] if col in r and str(r[col]) not in ("", "nan")]
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


def make_validation_template(sites: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "site_id", "candidate_type", "selection_algorithm", "selection_reason", "selection_step", "marginal_gain_score",
        "priority_rank", "priority_score",
        "occurrence_support_score", "model_support_score", "sdm_suitability", "ssdm_predicted_richness",
        "observed_species_richness", "species_richness", "species_list",
        "recommended_survey_window", "season_confidence", "flowering_record_count",
        "latitude", "longitude", "google_maps_url",
        "google_maps_checked", "accessible", "access_mode", "access_note",
        "visited", "survey_date", "result", "survey_minutes", "observer", "survey_effort_minutes", "search_area_m2",
        "access_success", "target_species_found", "target_taxa_found", "abundance_count", "abundance_class",
        "flowering_state", "flowering_status", "estimated_abundance", "access_failure_reason",
        "number_of_species_detected", "newly_confirmed_population",
        "photographs_taken", "photo_file", "specimen_collected", "specimens_collected", "specimen_id",
        "dna_sample_collected", "dna_samples_collected", "dna_sample_id", "habitat_note", "notes", "comments",
        "visit_date", "flowering_observed", "fruiting_observed", "vegetative_only", "phenology_notes",
    ]
    base = sites.copy()
    if not base.empty and {"latitude", "longitude"}.issubset(base.columns):
        base["google_maps_url"] = base.apply(lambda r: make_google_maps_point_url(float(r["latitude"]), float(r["longitude"])), axis=1)
    for col in cols:
        if col not in base.columns:
            base[col] = ""
    return base[cols]


def automatic_candidate_scale_m(occ: pd.DataFrame) -> int:
    """Choose a local occurrence grouping scale without asking the user."""
    if occ is None or len(occ) < 2:
        return 2_000
    coords = occ[["_latitude", "_longitude"]].dropna().to_numpy(dtype=float)
    if len(coords) < 2:
        return 2_000
    tree = BallTree(np.radians(coords), metric="haversine")
    distances, _ = tree.query(np.radians(coords), k=2)
    nearest_m = distances[:, 1] * EARTH_RADIUS_M
    finite = nearest_m[np.isfinite(nearest_m) & (nearest_m > 0)]
    typical = float(np.quantile(finite, 0.60)) if finite.size else 1_000.0
    raw = float(np.clip(typical * 2.5, 500.0, 10_000.0))
    return int(max(500, round(raw / 500.0) * 500))


def automatic_region_label(scope: pd.DataFrame) -> str:
    if scope is None or scope.empty:
        return "Unknown"
    center_lat = float(scope["_latitude"].mean())
    center_lon = float(scope["_longitude"].mean())
    locality = scope.get("_locality", pd.Series("", index=scope.index)).astype(str).str.strip()
    valid_locality = ~locality.str.lower().isin({"", "nan", "none"})
    if valid_locality.any():
        local_rows = scope.loc[valid_locality].copy()
        local_rows["_center_distance"] = (
            (pd.to_numeric(local_rows["_latitude"], errors="coerce") - center_lat) ** 2
            + ((pd.to_numeric(local_rows["_longitude"], errors="coerce") - center_lon) * math.cos(math.radians(center_lat))) ** 2
        )
        nearest_idx = local_rows["_center_distance"].idxmin()
        nearest_name = str(locality.loc[nearest_idx])
        return f"Main range near {nearest_name} ({center_lat:.3f}, {center_lon:.3f})"
    return f"Main recorded range around {center_lat:.3f}, {center_lon:.3f}"


def estimate_default_short_trip(
    plan: pd.DataFrame,
    hub_latitude: float,
    hub_longitude: float,
    survey_protocol: Optional[dict[str, Any]] = None,
    target_days: int = 2,
) -> dict[str, Any]:
    """Schedule hub-to-hub field days with taxon-aware search effort.

    This remains a route proxy, but unlike the former total-hours calculation,
    every field day starts and ends at the hub and must fit its own time budget.
    """
    protocol = survey_protocol or infer_survey_protocol().as_dict()
    assumptions = {
        "daily_field_hours": float(protocol["daily_field_hours"]),
        "operational_reserve_fraction": 0.15,
        "usable_daily_hours": round(float(protocol["daily_field_hours"]) * 0.85, 3),
        "average_road_speed_kmh": 35.0,
        "road_distance_factor": 1.35,
        "search_minutes_per_cell": int(protocol["search_minutes_per_cell"]),
        "access_buffer_minutes_per_cell": int(protocol["access_buffer_minutes_per_cell"]),
        "start_end": "recommended region hub",
        "target_days": int(target_days),
        "protocol_id": str(protocol["protocol_id"]),
        "taxon_group": str(protocol["taxon_group"]),
    }
    if plan is None or plan.empty:
        return {
            **assumptions, "route_order_site_ids": [], "day_schedules": [],
            "estimated_road_km": 0.0, "total_hours": 0.0, "estimated_days": 0,
            "fits_target_days": True, "overtime_days": 0,
        }
    remaining = set(range(len(plan)))
    route_positions: list[int] = []
    day_schedules: list[dict[str, Any]] = []
    total_straight_km = 0.0
    service_hours = (
        assumptions["search_minutes_per_cell"] + assumptions["access_buffer_minutes_per_cell"]
    ) / 60.0
    while remaining:
        current_lat, current_lon = float(hub_latitude), float(hub_longitude)
        day_positions: list[int] = []
        day_straight_km = 0.0
        day_elapsed_hours = 0.0
        overtime = False
        while remaining:
            positions = np.array(sorted(remaining), dtype=int)
            distances_km = _acsp_point_distances_m(
                current_lat, current_lon,
                pd.to_numeric(plan.iloc[positions]["latitude"], errors="coerce").to_numpy(dtype=float),
                pd.to_numeric(plan.iloc[positions]["longitude"], errors="coerce").to_numpy(dtype=float),
            ) / 1000.0
            order = np.argsort(distances_km)
            chosen: Optional[tuple[int, float, float]] = None
            for candidate_index in order:
                position = int(positions[int(candidate_index)])
                leg_km = float(distances_km[int(candidate_index)])
                candidate_lat = float(plan.iloc[position]["latitude"])
                candidate_lon = float(plan.iloc[position]["longitude"])
                return_km = float(_acsp_point_distances_m(
                    candidate_lat, candidate_lon, np.array([hub_latitude]), np.array([hub_longitude])
                )[0]) / 1000.0
                projected_hours = day_elapsed_hours + (
                    (leg_km + return_km) * assumptions["road_distance_factor"]
                    / assumptions["average_road_speed_kmh"]
                ) + service_hours
                if projected_hours <= assumptions["usable_daily_hours"]:
                    chosen = position, leg_km, return_km
                    break
            if chosen is None:
                if day_positions:
                    break
                position = int(positions[int(order[0])])
                leg_km = float(distances_km[int(order[0])])
                candidate_lat = float(plan.iloc[position]["latitude"])
                candidate_lon = float(plan.iloc[position]["longitude"])
                return_km = float(_acsp_point_distances_m(
                    candidate_lat, candidate_lon, np.array([hub_latitude]), np.array([hub_longitude])
                )[0]) / 1000.0
                chosen = position, leg_km, return_km
                overtime = True
            next_pos, leg_km, _return_km = chosen
            day_straight_km += leg_km
            day_elapsed_hours += (
                leg_km * assumptions["road_distance_factor"] / assumptions["average_road_speed_kmh"]
            ) + service_hours
            day_positions.append(next_pos)
            route_positions.append(next_pos)
            remaining.remove(next_pos)
            current_lat = float(plan.iloc[next_pos]["latitude"])
            current_lon = float(plan.iloc[next_pos]["longitude"])
        return_km = float(_acsp_point_distances_m(
            current_lat, current_lon, np.array([hub_latitude]), np.array([hub_longitude])
        )[0]) / 1000.0
        day_straight_km += return_km
        day_elapsed_hours += (
            return_km * assumptions["road_distance_factor"] / assumptions["average_road_speed_kmh"]
        )
        overtime = overtime or day_elapsed_hours > assumptions["usable_daily_hours"]
        total_straight_km += day_straight_km
        day_schedules.append({
            "day": len(day_schedules) + 1,
            "site_ids": [int(plan.iloc[pos]["site_id"]) for pos in day_positions],
            "straight_line_km": round(day_straight_km, 1),
            "estimated_road_km": round(day_straight_km * assumptions["road_distance_factor"], 1),
            "estimated_hours": round(day_elapsed_hours, 1),
            "overtime": bool(overtime),
        })
    road_km = total_straight_km * assumptions["road_distance_factor"]
    travel_hours = road_km / assumptions["average_road_speed_kmh"]
    site_hours = len(plan) * service_hours
    total_hours = travel_hours + site_hours
    repeat_visits = int(protocol.get("minimum_repeat_visits", 1))
    return {
        **assumptions,
        "route_order_site_ids": [int(plan.iloc[pos]["site_id"]) for pos in route_positions],
        "day_schedules": day_schedules,
        "straight_line_route_km": round(total_straight_km, 1),
        "estimated_road_km": round(road_km, 1),
        "travel_hours": round(travel_hours, 1),
        "site_hours": round(site_hours, 1),
        "total_hours": round(total_hours, 1),
        "estimated_days": len(day_schedules),
        "fits_target_days": len(day_schedules) <= int(target_days) and not any(day["overtime"] for day in day_schedules),
        "overtime_days": sum(bool(day["overtime"]) for day in day_schedules),
        "minimum_repeat_visits": repeat_visits,
        "inference_ready_minimum_field_days": len(day_schedules) * repeat_visits,
        "routing_confidence": "low; straight-line legs use a road-distance factor and do not model ferries, road topology, traffic, or trail time",
    }


def build_default_short_trip_plans(
    eligible_candidates: pd.DataFrame,
    hub_latitude: float,
    hub_longitude: float,
    target_days: int = 2,
    max_cells: int = 8,
    survey_protocol: Optional[dict[str, Any]] = None,
) -> tuple[dict[str, pd.DataFrame], dict[str, Any], int]:
    """Reduce plan size until the transparent default logistics fit the target days."""
    requested_k = min(int(max_cells), len(eligible_candidates))
    protocol = survey_protocol or infer_survey_protocol().as_dict()
    pool = eligible_candidates.copy().reset_index(drop=True)
    hub_distances_m = _acsp_point_distances_m(
        float(hub_latitude), float(hub_longitude),
        pd.to_numeric(pool["latitude"], errors="coerce").to_numpy(dtype=float),
        pd.to_numeric(pool["longitude"], errors="coerce").to_numpy(dtype=float),
    ) if not pool.empty else np.array([], dtype=float)
    pool["distance_to_hub_m"] = hub_distances_m
    service_hours = (
        int(protocol["search_minutes_per_cell"]) + int(protocol["access_buffer_minutes_per_cell"])
    ) / 60.0
    usable_daily_hours = float(protocol["daily_field_hours"]) * 0.85
    individual_hours = (
        2.0 * hub_distances_m / 1000.0 * 1.35 / 35.0 + service_hours
    )
    feasible_mask = individual_hours <= usable_daily_hours
    individually_infeasible = int((~feasible_mask).sum())
    feasible_pool = pool.loc[feasible_mask].copy().reset_index(drop=True)
    if not feasible_pool.empty:
        pool = feasible_pool
    pool_start_k = min(requested_k, len(pool))
    minimum_k = min(1, pool_start_k)
    plans: dict[str, pd.DataFrame] = {}
    trip_estimate: dict[str, Any] = {}
    for plan_k in range(pool_start_k, minimum_k - 1, -1):
        plans = build_acsp_discover_plans(pool, plan_k)
        trip_estimate = estimate_default_short_trip(
            plans.get("Balanced", pd.DataFrame()), float(hub_latitude), float(hub_longitude),
            survey_protocol=survey_protocol, target_days=target_days,
        )
        if bool(trip_estimate.get("fits_target_days")) or plan_k == minimum_k:
            break
    trip_estimate["individually_infeasible_candidates_excluded"] = individually_infeasible if not feasible_pool.empty else 0
    trip_estimate["candidate_pool_had_no_individually_feasible_site"] = bool(pool_start_k and feasible_pool.empty)
    return plans, trip_estimate, requested_k


def make_region_overview_map(
    occurrences: pd.DataFrame,
    region_cards: list[dict[str, Any]],
    selected_region_id: Optional[int],
) -> folium.Map:
    center = [float(occurrences["_latitude"].mean()), float(occurrences["_longitude"].mean())]
    fmap = Map(location=center, zoom_start=6, tiles="OpenStreetMap", control_scale=True)
    display = spatially_balanced_cap(occurrences, min(500, len(occurrences)))
    records_group = FeatureGroup(name="Known distribution", show=True)
    for _, row in display.iterrows():
        scope_class = str(row.get("_scope_class", ""))
        color = "#d62728" if scope_class == "possible_remote_noise" else "#4c78a8"
        folium.CircleMarker(
            (float(row["_latitude"]), float(row["_longitude"])), radius=3,
            color=color, fill=True, fill_opacity=0.55, weight=1,
        ).add_to(records_group)
    records_group.add_to(fmap)
    colors = ["#2ca02c", "#ff7f0e", "#9467bd"]
    for index, region in enumerate(region_cards):
        region_id = int(region["region_id"])
        selected = selected_region_id is not None and region_id == int(selected_region_id)
        color = colors[min(index, len(colors) - 1)]
        radius_m = max(5_000.0, float(region.get("diameter_km", 0.0)) * 500.0)
        folium.Circle(
            (float(region["center_latitude"]), float(region["center_longitude"])),
            radius=radius_m,
            color=color,
            fill=True,
            fill_opacity=0.18 if selected else 0.08,
            weight=5 if selected else 2,
            tooltip=f"{region['card_role']} region {region_id}: {region['record_count']} records",
        ).add_to(fmap)
    Draw(
        export=False,
        draw_options={"rectangle": True, "polygon": True, "polyline": False, "circle": False, "marker": False, "circlemarker": False},
        edit_options={"edit": False, "remove": True},
    ).add_to(fmap)
    LayerControl(collapsed=True).add_to(fmap)
    try:
        fmap.fit_bounds([
            [float(occurrences["_latitude"].min()), float(occurrences["_longitude"].min())],
            [float(occurrences["_latitude"].max()), float(occurrences["_longitude"].max())],
        ], padding=(30, 30))
    except Exception:
        pass
    return fmap


def build_automatic_discover_bundle(
    scientific_name: str,
    occ_raw: pd.DataFrame,
    source_message: str,
    country_scope: str,
    selected_region_id: Optional[int] = None,
    override_row_ids: Optional[list[int]] = None,
    taxon_metadata: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Run the no-parameter ACSP-Discover path after occurrence retrieval."""
    if occ_raw is None or occ_raw.empty:
        raise ValueError("No valid coordinate records were available for automatic planning.")
    warnings: list[str] = []
    survey_protocol = infer_survey_protocol(taxon_metadata).as_dict()
    enriched = enrich_occurrences_with_phenology(occ_raw)
    _default_scope, scope_audit, scope_summary = infer_default_survey_scope(enriched)
    region_cards, region_audit, distribution_summary = recommend_survey_regions(enriched, scope_audit)
    selected_region: Optional[dict[str, Any]] = None
    if override_row_ids:
        override_set = set(map(int, override_row_ids))
        scope = enriched[enriched["_row_id"].astype(int).isin(override_set)].copy().reset_index(drop=True)
        selected_region_label = "Custom map area"
    else:
        if not region_cards:
            scope = _default_scope.copy().reset_index(drop=True)
            selected_region_label = automatic_region_label(scope)
        else:
            selected_region = next(
                (region for region in region_cards if int(region["region_id"]) == int(selected_region_id)),
                region_cards[0],
            ) if selected_region_id is not None else region_cards[0]
            member_ids = set(map(int, selected_region["member_row_ids"]))
            scope = enriched[enriched["_row_id"].astype(int).isin(member_ids)].copy().reset_index(drop=True)
            selected_region_label = automatic_region_label(scope)
    if scope.empty:
        raise ValueError("The selected survey region did not retain usable occurrence records.")

    cluster_m = automatic_candidate_scale_m(scope)
    candidate_input, _sdm_unused, pipeline_summary = prepare_large_dataset_inputs(
        scope,
        True,
        0.05,
        max(0.0, cluster_m * 0.5),
        len(scope) > 1_000,
        candidate_target=FAST_CANDIDATE_RECORDS,
        sdm_target=FAST_SDM_RECORDS,
    )
    known_candidates = build_occurrence_candidates_cached(
        candidate_input,
        float(cluster_m),
        1,
        "Medoid",
        0.35,
        0.7,
        0.3,
    )
    if known_candidates.empty:
        raise ValueError("Occurrence records could not be converted into survey candidates.")

    potential_candidates = pd.DataFrame()
    try:
        bounds = (
            float(scope["_longitude"].min()), float(scope["_latitude"].min()),
            float(scope["_longitude"].max()), float(scope["_latitude"].max()),
        )
        habitat_layers = app_provided_habitat_layers(bounds, include_osm=False)
        settings = recommended_potential_survey_settings(scope)
        potential_candidates = make_potential_survey_site_candidates(
            scope,
            known_candidates,
            float(settings["cell_m"]),
            min(10, int(settings["per_type"])),
            min(800, int(settings["max_cells"])),
            int(known_candidates["site_id"].max()) + 1,
            env_variables=POTENTIAL_ANALOGUE_PRESET,
            resolution="2.5m",
            highres_layers=habitat_layers,
            profile_buffer_m=100.0,
        )
        if potential_candidates.empty:
            warnings.append("No habitat-first cells survived the automatic local search; plans use known anchors only.")
    except Exception as exc:
        warnings.append(f"Automatic habitat-first generation was unavailable: {exc}")

    all_candidates = pd.concat([known_candidates, potential_candidates], ignore_index=True, sort=False)
    try:
        all_candidates = filter_to_land(all_candidates, "latitude", "longitude", 500.0)
    except Exception as exc:
        warnings.append(f"Land-mask verification was unavailable: {exc}")
    all_candidates = add_priority_rank(all_candidates, 0.7, 0.3)
    eligible, constraint_audit = apply_discover_hard_constraints(all_candidates)
    hub_lat = float(selected_region["center_latitude"]) if selected_region else float(scope["_latitude"].mean())
    hub_lon = float(selected_region["center_longitude"]) if selected_region else float(scope["_longitude"].mean())
    plans, trip_estimate, requested_k = build_default_short_trip_plans(
        eligible, hub_lat, hub_lon, target_days=2, max_cells=8, survey_protocol=survey_protocol
    )
    balanced = plans.get("Balanced", pd.DataFrame())
    if balanced.empty:
        raise ValueError("No candidate survived automatic hard-constraint screening.")
    if len(balanced) < requested_k:
        warnings.append(
            f"The default two-day feasibility assumption reduced the plan from {requested_k} to {len(balanced)} cells."
        )
    if not bool(trip_estimate.get("fits_target_days")):
        warnings.append(
            "Even the smallest candidate plan exceeds the proxy day budget; choose a closer hub or verify actual routing before fieldwork."
        )
    if int(survey_protocol.get("minimum_repeat_visits", 1)) > 1:
        warnings.append(
            f"The {survey_protocol['taxon_group']} protocol recommends at least "
            f"{survey_protocol['minimum_repeat_visits']} visits before treating non-detection as evidence of absence."
        )
    if str(survey_protocol.get("confidence")) == "low":
        warnings.append(
            "The automatic taxon protocol is only a coarse reconnaissance profile; verify a focal-species method before inference-ready sampling."
        )

    recommended_window = preferred_survey_window(
        balanced.get("recommended_survey_window", pd.Series(dtype=object))
    )
    proposal = summarize_discover_plan(balanced)
    balanced_ids = set(balanced["site_id"].astype(int))
    balanced_audit = constraint_audit[constraint_audit["site_id"].astype(int).isin(balanced_ids)]
    if proposal.get("data_quality") == "high" and balanced_audit["unknown_constraints"].astype(str).ne("").any():
        proposal["data_quality"] = "medium"
    proposal.update({
        "region": selected_region_label,
        "estimated_days": int(trip_estimate["estimated_days"]),
        "recommended_window": recommended_window,
    })
    return {
        "scientific_name": scientific_name,
        "country_scope": country_scope,
        "taxon_metadata": dict(taxon_metadata or {}),
        "survey_protocol": survey_protocol,
        "source_message": source_message,
        "occurrences": enriched,
        "scope": scope,
        "scope_audit": scope_audit,
        "scope_summary": scope_summary,
        "region_cards": region_cards,
        "region_audit": region_audit,
        "distribution_summary": distribution_summary,
        "selected_region": selected_region,
        "selected_region_id": (int(selected_region["region_id"]) if selected_region else None),
        "custom_override": bool(override_row_ids),
        "pipeline_summary": pipeline_summary,
        "cluster_m": cluster_m,
        "known_candidates": known_candidates,
        "potential_candidates": potential_candidates,
        "all_candidates": all_candidates,
        "constraint_audit": constraint_audit,
        "plans": plans,
        "proposal": proposal,
        "trip_estimate": trip_estimate,
        "warnings": warnings,
    }


def render_automatic_discover() -> None:
    """Normal species-name-only product surface."""
    st.title("🌿 ACSP-Discover")
    st.caption("Enter one scientific name. ACSP automatically retrieves records, infers a practical survey region, builds candidate cells, and returns three field plans.")
    query = st.text_input(
        "Species scientific name",
        value=st.session_state.get("automatic_discover_query") or "",
        placeholder="e.g. Campanula microdonta",
        key="automatic_species_name_input",
    )
    if st.button("Create survey proposal", type="primary", use_container_width=True):
        if not query.strip():
            st.error("Enter a scientific name.")
        else:
            try:
                with st.spinner("Retrieving records and building ACSP-Discover plans..."):
                    payload, jp_count, _ = gbif_species_count_cached(query.strip(), "JP", None, None)
                    country_scope = "Japan"
                    country_code = "JP"
                    if int(jp_count) == 0:
                        payload, world_count, _ = gbif_species_count_cached(query.strip(), "", None, None)
                        if int(world_count) == 0:
                            raise ValueError("GBIF returned no coordinate records for this taxon.")
                        country_scope = "Worldwide fallback"
                        country_code = ""
                    matched_rank = str(payload.get("rank") or "").upper()
                    if matched_rank and matched_rank not in {"SPECIES", "SUBSPECIES", "VARIETY", "FORM"}:
                        raise ValueError(f"GBIF matched rank {matched_rank}, not a species-level taxon. Enter a more specific name.")
                    message, raw = fetch_gbif_occurrences_cached(query.strip(), 1_000, country_code, None, None)
                    detected = detect_occurrence_columns(raw)
                    cleaned = clean_occurrences(raw, detected)
                    bundle = build_automatic_discover_bundle(
                        str(payload.get("scientificName") or query.strip()), cleaned, message, country_scope,
                        taxon_metadata=payload,
                    )
                st.session_state.automatic_discover_query = query.strip()
                st.session_state.automatic_discover_bundle = bundle
                st.session_state.automatic_region_draw_features = []
                st.session_state.automatic_region_map_reset_token = st.session_state.get("automatic_region_map_reset_token", 0) + 1
            except Exception as exc:
                st.session_state.automatic_discover_bundle = None
                st.error(f"Could not create the automatic survey proposal: {exc}")

    bundle = st.session_state.get("automatic_discover_bundle")
    if not isinstance(bundle, dict):
        st.info("The ordinary workflow needs no SDM, VIF, grid, clustering, or weight choices. Those remain available in Advanced workflow.")
        return

    distribution = bundle.get("distribution_summary", {})
    st.subheader("Known distribution and suggested survey regions")
    d1, d2, d3 = st.columns(3)
    d1.metric("Distribution regime", str(distribution.get("distribution_regime", "unknown")).title())
    d2.metric("Eligible range span", f"{float(distribution.get('total_span_km', 0.0)):.0f} km")
    d3.metric("Compact trip regions", int(distribution.get("stable_regions", 0)))
    st.caption(str(distribution.get("distribution_regime_reason", "")))

    region_cards = bundle.get("region_cards", [])
    if region_cards:
        card_columns = st.columns(len(region_cards))
        for column, region in zip(card_columns, region_cards):
            with column:
                selected = bundle.get("selected_region_id") == int(region["region_id"]) and not bundle.get("custom_override")
                st.markdown(f"**{region['card_role']} region**{' ✅' if selected else ''}")
                st.metric("Known records", int(region["record_count"]))
                st.caption(
                    f"Diameter ≈ {float(region['diameter_km']):.0f} km · "
                    f"center {float(region['center_latitude']):.3f}, {float(region['center_longitude']):.3f}"
                )
                st.caption(str(region["card_reason"]))
                if st.button(
                    "Use this region" if not selected else "Using this region",
                    key=f"automatic_use_region_{int(region['region_id'])}",
                    disabled=selected,
                    use_container_width=True,
                ):
                    with st.spinner("Rebuilding the proposal inside the selected region..."):
                        st.session_state.automatic_discover_bundle = build_automatic_discover_bundle(
                            bundle["scientific_name"], bundle["occurrences"], bundle["source_message"],
                            bundle["country_scope"], selected_region_id=int(region["region_id"]),
                            taxon_metadata=bundle.get("taxon_metadata"),
                        )
                    st.session_state.automatic_region_draw_features = []
                    st.session_state.automatic_region_map_reset_token = st.session_state.get("automatic_region_map_reset_token", 0) + 1
                    st.rerun()

    region_map_data = st_folium(
        make_region_overview_map(bundle["occurrences"], region_cards, bundle.get("selected_region_id")),
        width=None,
        height=560,
        returned_objects=["all_drawings", "last_active_drawing"],
        key=(
            f"automatic_region_map_{bundle.get('selected_region_id')}_{int(bundle.get('custom_override', False))}_"
            f"{st.session_state.get('automatic_region_map_reset_token', 0)}"
        ),
    )
    drawn_raw = (region_map_data or {}).get("all_drawings") or (region_map_data or {}).get("last_active_drawing")
    drawn_features = extract_drawn_features(drawn_raw)
    if drawn_features:
        st.session_state.automatic_region_draw_features = drawn_features
    active_drawings = st.session_state.get("automatic_region_draw_features", [])
    map_action1, map_action2 = st.columns(2)
    if map_action1.button(
        "Rebuild within drawn area",
        key="automatic_rebuild_drawn_area",
        disabled=not bool(active_drawings),
        use_container_width=True,
    ):
        override_ids = ids_inside_drawn_rectangles(
            bundle["occurrences"], "_row_id", "_latitude", "_longitude", active_drawings
        )
        if len(override_ids) < 3:
            st.error("The drawn area contains fewer than three usable records. Draw a broader area.")
        else:
            with st.spinner("Rebuilding the proposal inside the drawn area..."):
                st.session_state.automatic_discover_bundle = build_automatic_discover_bundle(
                    bundle["scientific_name"], bundle["occurrences"], bundle["source_message"],
                    bundle["country_scope"], override_row_ids=override_ids,
                    taxon_metadata=bundle.get("taxon_metadata"),
                )
            st.session_state.automatic_region_map_reset_token = st.session_state.get("automatic_region_map_reset_token", 0) + 1
            st.rerun()
    if map_action2.button(
        "Clear drawn area",
        key="automatic_clear_drawn_area",
        disabled=not bool(active_drawings),
        use_container_width=True,
    ):
        st.session_state.automatic_region_draw_features = []
        st.session_state.automatic_region_map_reset_token = st.session_state.get("automatic_region_map_reset_token", 0) + 1
        st.rerun()

    proposal = bundle["proposal"]
    st.subheader(f"Survey proposal — {bundle['scientific_name']}")
    st.caption(f"Record scope: {bundle['country_scope']}. {bundle['source_message']}")
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Recommended region", proposal["region"])
    c2.metric("Estimated days", proposal["estimated_days"])
    c3.metric("Priority cells", proposal["priority_cells"])
    c4.metric("Known revisits", proposal["known_anchors"])
    c5.metric("Discovery cells", proposal["discovery_cells"])
    c6.metric("Data quality", str(proposal["data_quality"]).title())
    trip_estimate = bundle.get("trip_estimate", {})
    survey_protocol = bundle.get("survey_protocol", {})
    st.caption(
        f"Suggested season: {proposal['recommended_window']}. Default logistics estimate: "
        f"{float(trip_estimate.get('estimated_road_km', 0.0)):.0f} road-km proxy, "
        f"{float(trip_estimate.get('total_hours', 0.0)):.1f} total hours. "
        f"Each day starts/ends at the region hub; assumes 35 km/h, "
        f"{int(trip_estimate.get('search_minutes_per_cell', 0))} survey minutes plus "
        f"{int(trip_estimate.get('access_buffer_minutes_per_cell', 0))} access minutes per station, and "
        f"{float(trip_estimate.get('daily_field_hours', 0.0)):.1f} field hours/day with a "
        f"{float(trip_estimate.get('operational_reserve_fraction', 0.0)):.0%} operational reserve."
    )
    st.caption("Presence, flowering, access permission, actual roads/ferries, weather, and safety require current field verification.")
    with st.expander("Taxon-aware survey protocol and daily schedule", expanded=False):
        st.write({
            "taxon_group": survey_protocol.get("taxon_group"),
            "protocol": survey_protocol.get("protocol_id"),
            "method": survey_protocol.get("method"),
            "observation_unit": survey_protocol.get("observation_unit"),
            "daily_window": survey_protocol.get("daily_window"),
            "minimum_repeat_visits": survey_protocol.get("minimum_repeat_visits"),
            "protocol_confidence": survey_protocol.get("confidence"),
            "movement_caution": survey_protocol.get("movement_caution"),
            "weather_caution": survey_protocol.get("weather_caution"),
            "routing_confidence": trip_estimate.get("routing_confidence"),
            "inference_ready_minimum_field_days": trip_estimate.get("inference_ready_minimum_field_days"),
        })
        st.dataframe(pd.DataFrame(trip_estimate.get("day_schedules", [])), width="stretch", hide_index=True)
    for warning in bundle.get("warnings", []):
        st.warning(warning)

    scope_summary = bundle["scope_summary"]
    with st.expander("Automatic scope and QC evidence", expanded=False):
        st.write({
            "distribution_regime": distribution.get("distribution_regime"),
            "eligible_range_span_km": distribution.get("total_span_km"),
            "compact_trip_regions": distribution.get("stable_regions"),
            "main_range_records": scope_summary.get("main_records", 0),
            "disjunct_range_records": scope_summary.get("disjunct_records", 0),
            "possible_remote_noise_records": scope_summary.get("possible_noise_records", 0),
            "scope_cluster_distance_m": scope_summary.get("cluster_eps_m"),
            "candidate_grouping_scale_m": bundle["cluster_m"],
        })
        st.dataframe(bundle["scope_audit"], width="stretch", hide_index=True)
        st.download_button(
            "Download scope audit CSV", bundle["scope_audit"].to_csv(index=False).encode("utf-8"),
            "acsp_discover_scope_audit.csv", "text/csv", key="automatic_scope_audit_download",
        )
        st.download_button(
            "Download region assignment CSV", bundle["region_audit"].to_csv(index=False).encode("utf-8"),
            "acsp_discover_region_audit.csv", "text/csv", key="automatic_region_audit_download",
        )

    tabs = st.tabs(list(ACSP_DISCOVER_PLAN_ORDER))
    for tab, plan_name in zip(tabs, ACSP_DISCOVER_PLAN_ORDER):
        with tab:
            plan = bundle["plans"].get(plan_name, pd.DataFrame())
            if plan.empty:
                st.info("No eligible cells in this plan.")
                continue
            show_cols = [c for c in [
                "plan_rank", "site_id", "candidate_type", "discovery_label", "learning_label", "access_label",
                "effective_search_cell_size_m", "search_cell_radius_m", "recommended_survey_window",
                "data_quality", "why_selected", "latitude", "longitude",
            ] if c in plan.columns]
            st.dataframe(plan[show_cols], width="stretch", hide_index=True)
            d1, d2, d3 = st.columns(3)
            d1.download_button(
                "Plan CSV", make_export_csv(plan).encode("utf-8"), f"acsp_discover_{plan_name.lower()}.csv",
                "text/csv", use_container_width=True, key=f"automatic_{plan_name.lower()}_csv",
            )
            d2.download_button(
                "Field validation CSV", make_validation_template(plan).to_csv(index=False).encode("utf-8"),
                f"acsp_discover_{plan_name.lower()}_validation.csv", "text/csv", use_container_width=True,
                key=f"automatic_{plan_name.lower()}_validation",
            )
            route_url = make_google_maps_route_url(plan, "driving")
            d3.link_button("Open in Google Maps", route_url, use_container_width=True)

    st.subheader("Balanced plan map")
    balanced = bundle["plans"]["Balanced"]
    auto_layers = {"predict": False, "occ": True, "candidate_circles": True}
    auto_map = build_map(bundle["scope"], balanced, None, None, 0.0, 500.0, auto_layers, False)
    st_folium(auto_map, width=None, height=650, returned_objects=[], key="automatic_balanced_map")

    with st.expander("Constraint audit", expanded=False):
        st.dataframe(bundle["constraint_audit"], width="stretch", hide_index=True)
        st.download_button(
            "Download constraint audit CSV", bundle["constraint_audit"].to_csv(index=False).encode("utf-8"),
            "acsp_discover_constraint_audit.csv", "text/csv", key="automatic_constraint_audit_download",
        )


def main() -> None:
    st.set_page_config(page_title=APP_TITLE, page_icon="🗺️", layout="wide")
    init_session_state()
    st.sidebar.caption(f"Build: {APP_BUILD_ID}")
    workflow = st.sidebar.radio(
        "Workflow",
        ["Species name only", "Advanced / manual"],
        index=0,
        key="product_workflow",
    )
    if workflow == "Species name only":
        render_automatic_discover()
        return

    st.title("🗺️ ACSP — Adaptive Complementarity-based Survey Prioritization")
    st.caption("Adaptive Complementarity-based Survey Prioritization: occurrence-based survey ranges, rectangle coordinate QC, raster-style SDM predict maps, VIF diagnostics, spatial partition diagnostics, complementarity-based set selection, and route planning.")

    analysis_mode = st.sidebar.radio("Analysis mode", ["Single species survey planning", "Genus diversity / SSDM"], index=0, key="analysis_mode")

    # Reset widget-collision-prone state when switching between modes to avoid
    # Streamlit session-state inconsistencies and stale map-click signatures.
    last_mode = st.session_state.get("_last_analysis_mode")
    if last_mode is not None and last_mode != analysis_mode:
        st.session_state.sl_selected_site_ids = []
        st.session_state.sl_last_draw_sig = ""
        st.session_state.sl_reset_token = st.session_state.get("sl_reset_token", 0) + 1
        st.session_state.last_route_click_signature = ""
        st.session_state.last_exclude_click_signature = ""
        st.session_state.excluded_row_ids = set()
        st.session_state.qc_last_draw_sig = ""
        st.session_state.qc_rect_selected_ids = []
        st.session_state.qc_rect_features = []
        st.session_state.target_rect_features = []
        st.session_state.target_last_draw_sig = ""
        st.session_state.target_map_reset_token = st.session_state.get("target_map_reset_token", 0) + 1
        st.session_state.genus_target_rect_features = []
        st.session_state.genus_target_last_draw_sig = ""
        st.session_state.genus_target_map_reset_token = st.session_state.get("genus_target_map_reset_token", 0) + 1
        st.session_state.genus_selected_site_ids = []
        st.session_state.genus_last_click_signature = ""
        st.session_state.genus_last_draw_sig = ""
        st.session_state.genus_selection_map_reset_token = st.session_state.get("genus_selection_map_reset_token", 0) + 1
    st.session_state["_last_analysis_mode"] = analysis_mode

    if analysis_mode == "Genus diversity / SSDM":
        genus_diversity_panel()
        return

    default_fetch_cap = FAST_SPECIES_GBIF_FETCH_CAP
    default_map_records = FAST_MAP_RECORDS
    default_candidate_records = FAST_CANDIDATE_RECORDS
    default_sdm_records = FAST_SDM_RECORDS
    st.sidebar.header("Data source")
    load_input_controls(int(default_fetch_cap))
    st.sidebar.divider()
    st.sidebar.subheader("Sampling design")
    survey_range_m = st.sidebar.number_input("Survey range radius (m)", 50, 50_000, 500, 50, help="Radius around each candidate center shown as a survey range circle on the map.")
    with st.sidebar.expander("Advanced sampling settings", expanded=False):
        cluster_m = st.number_input("Candidate grouping scale (m)", 1, 500_000, 2000, 500, help="Occurrences within this distance are grouped into a single survey candidate (DBSCAN clustering distance).")
        thinning_m = st.number_input("Spatial thinning before clustering (m)", 0, 50_000, 1000, 500, help="Minimum distance between retained records used for candidate clustering.")
        large_dataset_mode = st.checkbox("Large dataset mode", value=False, help="Also enabled automatically when valid records exceed 1,000.")
        max_map_points = st.number_input("Max occurrence points shown on map", 100, 50_000, default_map_records, 100, help="Only this many occurrence points are drawn on Folium maps. Raw records are kept.")
        candidate_working_records = st.number_input("Candidate input working records", 50, 50_000, default_candidate_records, 50, help="Spatially representative occurrence records used for observed-data candidate generation.")
        sdm_working_records = st.number_input("SDM presence working records", 20, 50_000, default_sdm_records, 25, help="Bias-reduced presence records used for optional SDM.")
        exact_dedup = st.checkbox("Exact coordinate deduplication", value=True, help="Keep one representative record per unique lat/lon coordinate before clustering.")
        grid_thinning_deg = st.number_input("Grid thinning for analysis (degrees)", min_value=0.0, max_value=5.0, value=0.05, step=0.01, format="%.2f", help="One record per grid cell before clustering.")
        center_method = st.selectbox("Candidate center method", ["Medoid", "Centroid"], index=0, help="How to pick the representative point for each occurrence cluster.")
        min_samples = st.number_input("Minimum records per cluster", 1, 50, 1, 1, help="Clusters with fewer records are discarded.")
        occurrence_weight = st.slider("Record-density bonus", 0.0, 0.60, 0.35, 0.05, help="How much the number of records in a cluster boosts candidate priority.")
        show_occurrence_images = st.checkbox("Occurrence image popups", value=False, help="Show GBIF occurrence photos in map popups. Off by default to keep maps fast.")
    # Candidate scoring: fixed scientific defaults — no user decision needed
    observed_weight: float = 0.7
    model_weight: float = 0.3
    st.sidebar.divider()
    st.sidebar.subheader("Layers")
    layers = {"predict": st.sidebar.checkbox("SDM predict map", True), "occ": st.sidebar.checkbox("Occurrences", True), "candidate_circles": st.sidebar.checkbox("Candidate circles", True)}

    if st.session_state.raw_df is None:
        st.info(st.session_state.source_message)
        return
    st.success(st.session_state.source_message)
    st.caption(
        "📊 The GBIF total, requested cap, and actual fetched count are shown in the green banner above. "
        "Fetched count < cap means GBIF has fewer matching records than your cap, "
        "or deduplication during fetch reduced the count."
    )
    try:
        detected = detect_occurrence_columns(st.session_state.raw_df)
        occ_raw = clean_occurrences(st.session_state.raw_df, detected)
    except Exception as exc:
        st.error(str(exc))
        return
    if occ_raw.empty:
        st.error("No valid coordinate records found.")
        return
    # Enrich with phenology (adds _obs_month, _obs_doy, _phenology_state)
    occ_raw = enrich_occurrences_with_phenology(occ_raw)

    auto_large_dataset_mode = len(occ_raw) > 1000
    effective_large_dataset_mode = bool(large_dataset_mode or auto_large_dataset_mode)
    effective_max_map_points = min(int(max_map_points), 1000) if effective_large_dataset_mode else int(max_map_points)

    # ── Known distribution map ────────────────────────────────────────────────
    st.subheader("🗺️ Known distribution")
    st.caption(
        f"{len(occ_raw):,} fetched records shown as clusters. "
        "Draw a rectangle to define your fieldwork area."
    )
    col_p1_map, col_p1_clear = st.columns([4, 1])
    with col_p1_clear:
        if st.button("Clear rectangle", key="target_clear_target_rect"):
            st.session_state["target_rect_features"] = []
            st.session_state["target_last_draw_sig"] = ""
            st.session_state["target_map_reset_token"] = st.session_state.get("target_map_reset_token", 0) + 1
            reset_model_outputs()
            st.rerun()
    with col_p1_map:
        p1_draw_data = st_folium(
            make_macro_cluster_map(occ_raw),
            width=None, height=600,
            returned_objects=["all_drawings", "last_active_drawing"],
            key=f"macro_cluster_map_{st.session_state.get('target_map_reset_token', 0)}",
        )
    _p1_raw = (p1_draw_data or {}).get("all_drawings") or (p1_draw_data or {}).get("last_active_drawing")
    _p1_features = extract_drawn_features(_p1_raw)
    if _p1_features:
        _p1_sig = str(_p1_features)[:800]
        if _p1_sig != st.session_state.get("target_last_draw_sig", ""):
            st.session_state["target_last_draw_sig"] = _p1_sig
            st.session_state["target_rect_features"] = _p1_features
            reset_model_outputs()

    # ── Best time to visit (shown right after fetch) ──────────────────────────
    if "_obs_month" in occ_raw.columns:
        _ph_dated = occ_raw.dropna(subset=["_obs_month"])
        if not _ph_dated.empty:
            st.subheader("📅 Best time to visit")
            _ph_fl = _ph_dated[_ph_dated["_phenology_state"] == "flowering"] if "_phenology_state" in _ph_dated.columns else pd.DataFrame()
            _ph_all_months = sorted(_ph_dated["_obs_month"].dropna().astype(int).unique().tolist())
            _ph_fl_months = sorted(_ph_fl["_obs_month"].dropna().astype(int).unique().tolist()) if not _ph_fl.empty else []
            _ph_month_counts_d = _ph_dated["_obs_month"].value_counts().to_dict()
            if _ph_fl_months:
                _ph_fl_counts_d = _ph_fl["_obs_month"].value_counts().to_dict()
                _ph_window = _months_to_window_str(_ph_fl_months, counts=_ph_fl_counts_d)
            else:
                _ph_window = _months_to_window_str(_ph_all_months, counts=_ph_month_counts_d)
            _ph_col1, _ph_col2 = st.columns([3, 1])
            with _ph_col1:
                _ph_month_counts = _ph_dated["_obs_month"].value_counts().sort_index()
                if not _ph_fl.empty:
                    _ph_chart = pd.DataFrame({
                        "All records": _ph_month_counts,
                        "Flowering": _ph_fl["_obs_month"].value_counts().sort_index(),
                    }).fillna(0).astype(int)
                else:
                    _ph_chart = _ph_month_counts.rename("All records").to_frame()
                st.bar_chart(_ph_chart, height=160)
            with _ph_col2:
                st.metric("Recommended window", _ph_window)
                if _ph_fl.empty:
                    st.caption(f"Based on {len(_ph_dated):,} dated records (no flowering evidence — date-inferred).")
                else:
                    _ph_conf = "high" if len(_ph_fl) >= 5 else "medium" if len(_ph_fl) >= 2 else "low"
                    st.caption(f"Flowering evidence: {len(_ph_fl):,} records (confidence: {_ph_conf}). Based on {len(_ph_dated):,} dated records.")
            st.caption("⚠️ Observation dates reflect when specimens were collected, not guaranteed flowering dates.")

    # ── Survey area ───────────────────────────────────────────────────────────
    st.subheader("📍 Survey area")
    st.caption("Draw a rectangle on the map above to set your fieldwork area. Candidates are generated from records inside.")
    target_map_display = limit_occurrence_display(occ_raw, set(), int(effective_max_map_points))
    occ_extent_selected, target_counts = target_occurrence_set_panel(
        occ_raw,
        target_map_display,
        raw_record_count=len(occ_raw),
        key_prefix="target",
        show_map=False,
        model_label="SDM",
        allow_advanced_modes=False,
    )
    if occ_extent_selected.empty:
        st.error("No records in the selected area. Draw a larger rectangle or clear the rectangle to use all records.")
        return

    occ_before_dedup_n = len(occ_extent_selected)
    occ_candidate_input, _unused_sdm_train, large_summary = prepare_large_dataset_inputs(
        occ_extent_selected,
        bool(exact_dedup),
        float(grid_thinning_deg),
        float(thinning_m),
        effective_large_dataset_mode,
        candidate_target=int(candidate_working_records),
        sdm_target=int(sdm_working_records),
    )
    exact_dedup_removed = occ_before_dedup_n - large_summary["after_exact_dedup"]
    grid_thinning_removed = large_summary["after_exact_dedup"] - large_summary["candidate_input"]
    if occ_candidate_input.empty:
        st.error("All included occurrence records were removed from candidate input. Reduce thinning settings.")
        return

    # ── Record pipeline: transparent stage-by-stage counts ───────────────────
    _n_fetched = len(occ_raw)
    _n_survey = len(occ_extent_selected)
    _n_after_dedup = large_summary["after_exact_dedup"]
    _n_after_grid = large_summary.get("after_grid_thin", _n_after_dedup)
    _n_candidates = len(occ_candidate_input)

    st.caption("**Record pipeline** — why counts change at each stage:")
    if float(large_summary.get("candidate_grid_deg", float(grid_thinning_deg))) != float(grid_thinning_deg):
        st.caption(
            f"Adaptive local thinning: requested grid thinning {float(grid_thinning_deg):.3f} degrees, "
            f"effective candidate grid {float(large_summary.get('candidate_grid_deg', 0.0)):.3f} degrees "
            "because this is a small/local occurrence set."
        )
    rp1, rp2, rp3, rp4, rp5 = st.columns(5)
    rp1.metric(
        "GBIF fetched records",
        f"{_n_fetched:,}",
        help=(
            "Actual records fetched from GBIF after representative retrieval and coordinate cleaning. "
            "This may be less than your requested cap if GBIF has fewer matching records, "
            "or if deduplication during fetch reduced the count."
        ),
    )
    rp2.metric(
        "Active survey-area records",
        f"{_n_survey:,}",
        delta=f"{_n_survey - _n_fetched:,}" if _n_survey != _n_fetched else None,
        help="Records within the Step 2 survey area (after rectangle filter, if any). Used only for observed-data candidate generation.",
    )
    rp3.metric(
        "After exact deduplication",
        f"{_n_after_dedup:,}",
        delta=f"{_n_after_dedup - _n_survey:,}" if _n_after_dedup < _n_survey else None,
        help="Duplicate lat/lon coordinates removed — keeps one representative record per unique location.",
    )
    rp4.metric(
        "After grid/spatial thinning",
        f"{_n_after_grid:,}" if _n_after_grid != _n_after_dedup else f"{_n_after_dedup:,}",
        delta=f"{_n_after_grid - _n_after_dedup:,}" if _n_after_grid < _n_after_dedup else None,
        help="Grid thinning (one record per grid cell) and/or distance thinning reduce spatial clustering bias.",
    )
    rp5.metric(
        "Records used for candidates",
        f"{_n_candidates:,}",
        delta=f"{_n_candidates - _n_after_grid:,}" if _n_candidates < _n_after_grid else None,
        help=(
            f"Spatially balanced representative subset used for survey candidate generation (target ≈ {large_summary['candidate_target']:,}). "
            "Fewer records reduce computation; candidates still cover the full geographic range."
        ),
    )
    st.caption(
        f"Fetched records ({_n_fetched:,}) are independent from the candidate pipeline and are used as the starting point for optional SDM. "
        "See 'Optional: Build SDM' for the SDM-specific record pipeline."
    )

    occ_map_display = limit_occurrence_display(occ_extent_selected, set(), int(effective_max_map_points))
    occurrence_candidates = build_occurrence_candidates_cached(
        occ_candidate_input,
        float(cluster_m),
        int(min_samples),
        center_method,
        float(occurrence_weight),
        float(observed_weight),
        float(model_weight),
    )

    # ── SDM record-count guidance (before SDM expander) ──────────────────────
    _pre_sdm_n = min(len(occ_raw), int(sdm_working_records))
    _raw_n = len(occ_raw)
    if _pre_sdm_n < 20:
        st.info(
            f"⚠️ Known occurrence records are sparse ({_pre_sdm_n}). Optional SDM may help identify potential "
            "unsampled survey areas, but predictions will be uncertain and require field validation. "
            "Jackknife validation is recommended."
        )
    elif _pre_sdm_n < 50:
        st.info(
            f"Optional SDM can add model support to observed-data candidates and help identify exploratory "
            f"potential sites ({_pre_sdm_n} presence points)."
        )
    elif _pre_sdm_n < 300:
        st.info(
            f"Optional SDM can add model support to observed-data candidates and identify exploratory "
            f"potential sites ({_pre_sdm_n} presence points)."
        )
    else:
        st.info(
            f"ℹ️ Observed-data candidates may already be sufficient for survey planning. Optional SDM will use "
            f"{_pre_sdm_n} spatially representative presence points (cap applied) rather than all {_raw_n:,} fetched records."
        )

    st.subheader("Optional: Build SDM")
    with st.expander("Build SDM and predict map", expanded=False):
        # ── SDM presence point cap (single control) ───────────────────────────
        sdm_ind_max_presence = st.number_input(
            "Max SDM presence points",
            min_value=10, max_value=50_000, value=int(sdm_working_records), step=25,
            key="sdm_ind_prep_max_presence",
            help=(
                "When fetched records exceed this number, spatially balanced grid subsampling "
                "is applied: the extent is divided into a √N × √N grid and the highest-quality "
                "record per cell is kept. This handles both performance and spatial bias in one step. "
                "When records are fewer than this cap, all records are used and a clustering check is run."
            ),
        )
        st.caption(
            f"SDM uses a spatially representative subset of up to {int(sdm_working_records):,} presence points "
            "regardless of how many records are fetched. This keeps SDM fast and reduces sampling bias — "
            "the cap is most relevant for abundant-record species."
        )

        # ── Bias reduction: spatially balanced cap only ────────────────────────
        with st.expander("Advanced: SDM QC settings", expanded=False):
            auto_sdm_outlier_qc = st.checkbox(
                "Automatically ignore remote spatial outliers for SDM",
                value=True,
                key="sdm_auto_remote_outlier_qc",
                help=(
                    "Recommended. Conservatively removes small, far-away occurrence clusters from SDM training "
                    "and SDM extent generation while preserving fetched records for transparency."
                ),
            )

        _sdm_br_n0 = len(occ_raw)
        if _sdm_br_n0 > int(sdm_ind_max_presence):
            occ_sdm_bias_reduced = spatially_balanced_cap(occ_raw, int(sdm_ind_max_presence))
        else:
            occ_sdm_bias_reduced = occ_raw.copy()
        _sdm_br_n4 = len(occ_sdm_bias_reduced)
        # Keep intermediate aliases for metrics (dedup/thinning no longer separate steps)
        _sdm_br_n1 = _sdm_br_n0
        _sdm_br_n3 = _sdm_br_n0

        # ── Step 2: QC exclusion on the bias-reduced set (map only shows ~N pts) ─
        if auto_sdm_outlier_qc:
            _, _sdm_auto_excl_raw, _sdm_auto_qc_report = auto_remote_spatial_outlier_qc(occ_sdm_bias_reduced)
        else:
            _sdm_auto_excl_raw = occ_sdm_bias_reduced.iloc[0:0].copy()
            _sdm_auto_qc_report = {
                "enabled": False,
                "input_records": int(len(occ_sdm_bias_reduced)),
                "excluded_records": 0,
                "reason": "automatic remote-outlier screening disabled",
            }
        _auto_excl_ids = set(_sdm_auto_excl_raw["_row_id"].astype(int)) if not _sdm_auto_excl_raw.empty else set()
        _sdm_manual_excl_ids = set(map(int, st.session_state.sdm_excluded_row_ids))
        _valid_manual_excl_ids = _sdm_manual_excl_ids & set(occ_sdm_bias_reduced["_row_id"].astype(int))
        _combined_excl_ids = _auto_excl_ids | _valid_manual_excl_ids
        occ_sdm_train = occ_sdm_bias_reduced[~occ_sdm_bias_reduced["_row_id"].astype(int).isin(_combined_excl_ids)].copy().reset_index(drop=True)
        _sdm_excl_raw = occ_sdm_bias_reduced[occ_sdm_bias_reduced["_row_id"].astype(int).isin(_combined_excl_ids)].copy()
        if not _sdm_excl_raw.empty:
            _sdm_excl_raw["sdm_qc_reason"] = np.where(
                _sdm_excl_raw["_row_id"].astype(int).isin(_auto_excl_ids),
                "Auto remote spatial outlier",
                "Manual SDM QC rectangle",
            )
        # Keep only valid manual IDs in session state (stale IDs from previous bias settings are dropped)
        if _valid_manual_excl_ids != _sdm_manual_excl_ids:
            st.session_state.sdm_excluded_row_ids = _valid_manual_excl_ids
        occ_sdm_qc_included = occ_sdm_train  # alias for metrics compatibility
        if _sdm_auto_qc_report.get("excluded_records", 0):
            st.info(
                "Automatic SDM QC excluded "
                f"{int(_sdm_auto_qc_report['excluded_records']):,} remote occurrence record(s) from SDM training and extent generation. "
                "They remain preserved in the fetched data, but are not used for the model."
            )
        elif auto_sdm_outlier_qc:
            st.caption("Automatic SDM QC: no remote minor occurrence cluster detected.")

        st.divider()
        # ── SDM prediction extent controls ────────────────────────────────────
        st.markdown("**SDM prediction extent — macro scale**")
        st.caption(
            "The extent defines where SDM suitability is predicted. "
            "It is independent from your Step 2 survey area and can be set wider to capture more environmental variation. "
            "A broader extent generally improves SDM accuracy — increase the buffer radius or use 'bounding box'."
        )
        area_mode = st.selectbox("Area to predict", AREA_MODES, index=2, help="buffer = expand around each point; convex hull = polygon around all records; bounding box = rectangular area. All land-only.", key="sdm_area_mode")
        _ec1, _ec2 = st.columns(2)
        buffer_km = _ec1.number_input("Buffer radius / hull buffer (km)", min_value=0.1, max_value=500.0, value=10.0, step=1.0, key="sdm_buffer_km")
        rectangle_margin_km = _ec2.number_input("Bounding-box margin (km)", min_value=0.0, max_value=500.0, value=20.0, step=5.0, key="sdm_rectangle_margin_km")
        exclusion_buffer_km = 0.0

        extent_geom = prediction_area_geometry(occ_sdm_train, area_mode, float(buffer_km), float(rectangle_margin_km), None, 0.0)

        st.divider()
        # ── Consolidated SDM setup map (bias-reduced points only — fast) ──────
        st.markdown("**SDM setup map**")
        st.caption(
            f"Blue points = {len(occ_sdm_train):,} final SDM analysis points after bias reduction (all shown). "
            "Red points = records excluded by automatic SDM QC or SDM QC rectangles. "
            "Orange outline = SDM prediction extent. "
            "Draw a rectangle only if you need to manually exclude additional suspicious SDM records."
        )
        if occ_sdm_train.empty and _sdm_excl_raw.empty:
            st.warning("Bias reduction removed all records. Reduce grid/distance thinning or increase the max presence cap.")
        else:
            if extent_geom is not None and not extent_geom.is_empty:
                minx, miny, maxx, maxy = extent_geom.bounds
                st.caption(f"Final SDM presence points: {len(occ_sdm_train):,}. Prediction extent: lon {minx:.4f}–{maxx:.4f}, lat {miny:.4f}–{maxy:.4f}.")
            _sdm_map_data = st_folium(
                make_sdm_setup_map(occ_sdm_train, _sdm_excl_raw, extent_geom, area_mode),
                width=None, height=500,
                returned_objects=["all_drawings", "last_active_drawing"],
                key="sdm_setup_map",
            )
            # Rectangle draw matches against bias-reduced set (not occ_raw)
            _raw_drawings = (_sdm_map_data or {}).get("all_drawings") or (_sdm_map_data or {}).get("last_active_drawing")
            _qc_features = extract_drawn_features(_raw_drawings)
            if _qc_features:
                _draw_sig = str(_qc_features)[:800]
                if _draw_sig != st.session_state.get("sdm_qc_click_sig", ""):
                    _new_excl = set(ids_inside_drawn_rectangles(occ_sdm_bias_reduced, "_row_id", "_latitude", "_longitude", _qc_features))
                    st.session_state.sdm_qc_click_sig = _draw_sig
                    st.session_state.sdm_excluded_row_ids = _new_excl
                    reset_model_outputs()
                    st.rerun()
            if _valid_manual_excl_ids and st.button("Clear manual SDM QC rectangles", key="sdm_qc_clear"):
                st.session_state.sdm_excluded_row_ids = set()
                st.session_state.sdm_qc_click_sig = ""
                reset_model_outputs()
                st.rerun()
        st.divider()
        # ── Environmental variables ───────────────────────────────────────────
        # WorldClim 2.1 at 2.5 arc-minutes (~4.5 km) — standard resolution for
        # national-scale SDM; coarser than 1km but avoids over-precision at
        # occurrence-record density.
        resolution = "2.5m"
        st.markdown("**Environmental variables**")
        st.caption(
            f"Default: balanced ecology preset — {', '.join(BALANCED_ECOLOGY_PRESET)}. "
            "Covers temperature level, seasonality, precipitation amount/seasonality, "
            "dryness, and elevation. Override in Advanced below."
        )
        # Default algorithms: Random Forest + ExtraTrees — well-calibrated for SDM,
        # complementary bias-variance trade-off, no hyperparameter tuning required.
        _DEFAULT_ALGORITHMS = ["Random forest", "ExtraTrees"]
        # Fixed defaults — no user decision required
        variables = list(BALANCED_ECOLOGY_PRESET)
        variable_strategy = "VIF stepwise"
        vif_threshold = 10.0
        corr_threshold = 0.80
        custom_variables = variables
        algorithms = list(_DEFAULT_ALGORITHMS)

        with st.expander("Advanced: variables & algorithms", expanded=False):
            st.caption("Override scientific defaults. Changes here are reflected in the auto-generated Methods text.")
            variables = st.multiselect(
                "Environmental variables",
                TOPOGRAPHY_VARS + CLIMATE_VARS,
                default=list(BALANCED_ECOLOGY_PRESET),
                key="sdm_environment_variables",
                help="Balanced ecology preset is the default. Add or remove variables.",
            )
            algorithms = st.multiselect(
                "Ensemble algorithms",
                ALGORITHMS,
                default=list(_DEFAULT_ALGORITHMS),
                key="sdm_algorithms_override",
                help="Random Forest + ExtraTrees is the scientific default. Both are robust without hyperparameter tuning.",
            )
            variable_strategy = st.selectbox(
                "Variable-selection strategy",
                ["VIF stepwise", "Correlation filter", "Advanced custom selection"],
                index=0,
                key="sdm_variable_strategy",
            )
            vc1, vc2 = st.columns(2)
            corr_threshold = vc1.number_input("Correlation threshold", min_value=0.50, max_value=0.99, value=0.80, step=0.05, format="%.2f", key="sdm_corr_threshold")
            vif_threshold = vc2.number_input("VIF threshold", min_value=1.0, max_value=100.0, value=10.0, step=1.0, key="sdm_vif_threshold")
            custom_variables = variables
            if variable_strategy == "Advanced custom selection":
                custom_variables = st.multiselect("Custom final variables", variables, default=variables, key="sdm_custom_final_variables")
        st.caption("VIF stepwise filtering (threshold 10) applied automatically. WorldClim 2.1, 2.5 arc-min.")

        # Auto-select validation method based on record count + geographic extent
        _auto_partition, _auto_reason = auto_sdm_partition(len(occ_sdm_train), extent_geom)
        st.markdown("**Validation method** — auto-selected")
        st.info(_auto_reason)
        k_folds = 5
        checkerboard_deg = 0.05
        partition_method = _auto_partition
        with st.expander("Override validation method (advanced)", expanded=False):
            st.caption(
                "block: spatially separated folds — best general-purpose SDM validation. "
                "checkerboard: fine-grained spatial folds for dense datasets. "
                "random holdout/k-fold: ignores spatial structure — use only when records are few or extent is small. "
                "jackknife: leave-one-out — for very small datasets (< 15 records)."
            )
            partition_method = st.selectbox(
                "Validation method",
                PARTITION_METHODS,
                index=PARTITION_METHODS.index(_auto_partition),
                key="sdm_partition_method",
            )
            if partition_method == "random k-fold":
                k_folds = st.number_input("k for random k-fold", min_value=2, max_value=20, value=5, step=1)
            if partition_method in ["checkerboard1", "checkerboard2"]:
                checkerboard_deg = st.number_input("Checkerboard cell size (degrees)", min_value=0.001, max_value=5.0, value=0.05, step=0.01, format="%.3f")
        default_background = 500
        default_max_pixels = 40_000
        with st.expander("Advanced model settings", expanded=False):
            n_background = st.number_input("Number of land-only background points", 100, 20_000, default_background, 100)
            max_pixels = st.number_input("Maximum predict-map pixels", 2_000, 500_000, default_max_pixels, 10_000)
        st.caption("buffer = around each occurrence point; convex hull = polygon around records; bounding box = latitude/longitude rectangle around records. All are clipped to land.")
        run_sdm = st.button("Build SDM and predict map", type="primary")

    # ── SDM preprocessing pipeline result ─────────────────────────────────────
    occ_for_sdm = occ_sdm_train.copy().reset_index(drop=True)
    sdm_excluded_ids = set(_combined_excl_ids)
    sdm_n_final = len(occ_for_sdm)

    # Preprocessing metrics display
    st.caption("**SDM training point summary:**")
    pm1, pm2, pm3 = st.columns(3)
    pm1.metric("Fetched records (SDM source)", f"{_sdm_br_n0:,}", help="All GBIF records — independent from Step 2 survey area.")
    _cap_help = (
        f"Spatially balanced grid subsampling to {int(sdm_ind_max_presence):,} points: "
        f"extent divided into ≈{int(math.sqrt(int(sdm_ind_max_presence))):d}×{int(math.sqrt(int(sdm_ind_max_presence))):d} grid cells; "
        "highest-quality record per cell kept (photo → recent year). "
        "Handles performance and spatial bias in one step."
    ) if _sdm_br_n4 < _sdm_br_n0 else "Records are fewer than the cap — all used without subsampling."
    pm2.metric(
        "After spatial balancing", f"{_sdm_br_n4:,}",
        delta=f"{_sdm_br_n4 - _sdm_br_n0:,}" if _sdm_br_n4 < _sdm_br_n0 else None,
        help=_cap_help,
    )
    pm3.metric(
        "Final SDM presence points", f"{sdm_n_final:,}",
        delta=f"{sdm_n_final - _sdm_br_n4:,}" if sdm_n_final < _sdm_br_n4 else None,
        help="After automatic remote-outlier screening and any manual SDM QC rectangles on the setup map.",
    )
    if sdm_n_final == 0 and not occ_raw.empty:
        st.warning("All records removed by cap or SDM QC. Increase the cap, disable automatic SDM outlier screening, or clear manual SDM QC rectangles.")
    # Spatial clustering check for small datasets (all records used, no subsampling)
    if 0 < sdm_n_final <= _sdm_br_n0 and _sdm_br_n4 == _sdm_br_n0 and not occ_for_sdm.empty:
        _coords = occ_for_sdm[["_latitude", "_longitude"]].values
        _centroid = _coords.mean(axis=0)
        _dists_deg = np.sqrt(((_coords - _centroid) ** 2).sum(axis=1))
        _median_dist = float(np.median(_dists_deg))
        if _median_dist < 1.5:
            st.info(
                f"Local-range SDM note: {sdm_n_final} records have median spread {_median_dist:.2f} degrees from centroid. "
                "This can be normal for island or range-restricted taxa. Automatic SDM QC checks for remote minor outliers; "
                "use SDM as broad model support and rely on Potential Survey Sites / ACSP for fine-scale field destinations."
            )

    current_sdm_occurrence_row_ids = tuple(sorted(occ_for_sdm["_row_id"].astype(int).tolist())) if not occ_for_sdm.empty else ()
    if st.session_state.sdm_occurrence_row_ids is not None and st.session_state.sdm_occurrence_row_ids != current_sdm_occurrence_row_ids:
        reset_model_outputs()
        st.info("SDM preprocessing settings or QC exclusions changed. Previous SDM was cleared; rebuild SDM to use the current preprocessed occurrence set.")

    status = st.empty()
    if run_sdm:
        if not variables:
            st.warning("Select at least one environmental variable.")
        elif not algorithms:
            st.warning("Select at least one algorithm.")
        elif occ_for_sdm.empty:
            st.error("SDM preprocessing removed all records. Reduce thinning settings.")
        elif extent_geom is None or extent_geom.is_empty:
            st.error("The SDM prediction extent is empty. SDM was stopped.")
        else:
            try:
                progress = st.progress(0.0)
                status.write("Generating presence/background data...")
                pb = build_presence_background(occ_for_sdm, int(n_background), area_mode, float(buffer_km), float(rectangle_margin_km), None, 0.0, status)
                progress.progress(0.15)
                status.write("Extracting environmental variables for training data...")
                train = extract_environment(pb, variables, "latitude", "longitude", resolution, status)
                train, env_dropped = clean_environment_table(train, variables, "SDM training environment", status)
                if train.empty or train["presence"].nunique() < 2:
                    raise RuntimeError("SDM training data had too few valid rows after raster NoData cleaning.")
                if "occurrence_row_id" in train.columns:
                    train_presence_ids = set(pd.to_numeric(train.loc[train["presence"].eq(1), "occurrence_row_id"], errors="coerce").dropna().astype(int))
                    leaked_train_ids = sorted(train_presence_ids.intersection(sdm_excluded_ids))
                    if leaked_train_ids:
                        raise RuntimeError(f"Excluded rows reached the SDM training table: {leaked_train_ids[:20]}")
                progress.progress(0.35)
                status.write(f"Running variable selection: {variable_strategy}...")
                kept_vars, vif_tbl = select_environment_variables(
                    train,
                    variables,
                    variable_strategy,
                    vif_threshold=float(vif_threshold),
                    corr_threshold=float(corr_threshold),
                    custom_variables=custom_variables,
                )
                if not vif_tbl.empty:
                    vif_tbl["rows_dropped_before_vif"] = int(env_dropped)
                if not kept_vars:
                    raise RuntimeError("No environmental variables remained after variable selection.")
                progress.progress(0.50)
                status.write(f"Fitting ensemble SDM with {partition_method} partition...")
                sdm_result = fit_sdm(train, kept_vars, algorithms, partition_method, int(k_folds), float(checkerboard_deg))
                progress.progress(0.70)
                status.write("Predicting raster-style suitability map...")
                overlay, pred_table = build_predict_map(occ_for_sdm, kept_vars, resolution, sdm_result, area_mode, float(buffer_km), float(rectangle_margin_km), int(max_pixels), None, 0.0, status)
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
        st.write("Variable-selection diagnostics")
        st.caption("Variables can be kept despite high VIF when protected by an ecological group or restored as fallback_kept; inspect final_status, reason, protected_by_group, fallback_kept, and vif_stage.")
        st.dataframe(vif_table, width="stretch", hide_index=True)

    if sdm_result is not None:
        st.success("SDM predict map is available.")
        st.caption(f"SDM training presence rows: {len(current_sdm_occurrence_row_ids)} included occurrence records; excluded row IDs are not used.")
        if overlay is not None:
            st.caption(f"Predict map: R/terra-style raster grid prediction using {overlay.get('method', 'ensemble raster prediction')}; array={overlay.get('shape')} cells; stride={overlay.get('source_stride')}; suitability min/mean/max={overlay.get('min')}/{overlay.get('mean')}/{overlay.get('max')}")
        st.write("SDM metrics")
        _metrics_display = sdm_result["metrics"].copy()
        if "fold" in _metrics_display.columns:
            _metrics_display["fold"] = _metrics_display["fold"].astype(str)
        st.dataframe(_metrics_display, width="stretch", hide_index=True)
        try:
            tmp = all_candidates.rename(columns={"latitude": "lat_tmp", "longitude": "lon_tmp"})
            tmp = extract_environment(tmp, sdm_result["variables"], "lat_tmp", "lon_tmp", resolution, status)
            all_candidates = tmp.rename(columns={"lat_tmp": "latitude", "lon_tmp": "longitude"})
            all_candidates = predict_suitability(all_candidates, sdm_result)
            # Explicitly refresh model_support_score from sdm_suitability so the weighted
            # re-ranking in add_priority_rank (called below) uses the actual SDM predictions.
            if "sdm_suitability" in all_candidates.columns:
                all_candidates["model_support_score"] = (
                    pd.to_numeric(all_candidates["sdm_suitability"], errors="coerce")
                    .clip(0, 1).round(3)
                )
        except Exception as exc:
            st.warning(f"Could not predict suitability for occurrence-supported ranges: {exc}")
        st.caption(
            "📍 Occurrence-supported candidates — based on known occurrence records, optionally re-ranked by SDM suitability."
        )
        with st.expander("Create SDM-high exploration ranges", expanded=True):
            st.caption(
                "🔭 SDM-high exploration candidates — model-only potential survey areas away from known records. "
                "These are exploratory and lower confidence; field validation is essential."
            )
            c1, c2, c3, c4 = st.columns(4)
            min_suit = c1.number_input("Minimum suitability", 0.0, 1.0, 0.60, 0.05)
            q = c2.number_input("Predict-map quantile", 0.0, 0.99, 0.90, 0.01)
            min_dist = c3.number_input("Min distance from known records/ranges (m)", 0, 200_000, 3000, 500)
            max_new = c4.number_input("Max new ranges", 1, 200, 20, 1)
            explore_cluster_m = st.number_input("Exploration clustering distance (m)", 100, 200_000, 3000, 500)
            exploration = make_sdm_exploration_candidates(pred_table, occ_for_sdm, all_candidates, float(min_suit), float(q), float(min_dist), float(explore_cluster_m), int(max_new), int(all_candidates["site_id"].max()) + 1 if not all_candidates.empty else 1)
        if not exploration.empty:
            all_candidates = pd.concat([all_candidates, exploration], ignore_index=True, sort=False)

    with st.expander("Optional: Potential Survey Sites (Habitat-first Discovery)", expanded=False):
        st.caption(
            "Generate exploratory grid-cell candidates that are not limited to known occurrence clusters. "
            "This is a local habitat-analogue search: known-site terrain profiles are compared with grid cells using "
            "Mahalanobis environmental distance. SDM remains a separate broad climate-niche tool."
        )
        _layer_bounds = (
            float(occ_extent_selected["_longitude"].min()),
            float(occ_extent_selected["_latitude"].min()),
            float(occ_extent_selected["_longitude"].max()),
            float(occ_extent_selected["_latitude"].max()),
        )
        include_osm_layers = st.checkbox(
            "Include app-provided access / edge layers",
            value=False,
            key="potential_fetch_osm_layers",
            help="Adds OpenStreetMap road, trail, and forest-edge distance proxies for the current survey area. Keep off if Overpass is slow.",
        )
        highres_layers = app_provided_habitat_layers(_layer_bounds, bool(include_osm_layers))
        st.markdown("**Optional local GeoTIFF evidence**")
        st.caption(
            "Upload rasters covering the active survey area. The coarsest supplied raster and the 75th percentile "
            "of coordinate uncertainty set the minimum honest search-cell width. Without a local raster, the built-in "
            "~4.5 km elevation fallback prevents false 100 m precision."
        )
        ul1, ul2, ul3 = st.columns(3)
        dem_upload = ul1.file_uploader("DEM GeoTIFF", type=["tif", "tiff"], key="potential_dem_geotiff")
        ndvi_upload = ul2.file_uploader("NDVI GeoTIFF", type=["tif", "tiff"], key="potential_ndvi_geotiff")
        landcover_upload = ul3.file_uploader("Land-cover GeoTIFF", type=["tif", "tiff"], key="potential_landcover_geotiff")
        uploaded_layer_paths = {
            "dem": cache_uploaded_habitat_raster(dem_upload, "dem"),
            "ndvi": cache_uploaded_habitat_raster(ndvi_upload, "ndvi"),
            "landcover": cache_uploaded_habitat_raster(landcover_upload, "landcover"),
        }
        highres_layers.update({name: path for name, path in uploaded_layer_paths.items() if path})
        base_supplied = [name for name, path in highres_layers.items() if path]
        st.caption(
            "App-provided layers: elevation/topography and coastline proxy"
            + (f"; optional active layers: {', '.join(base_supplied)}" if base_supplied else "")
        )
        recommended_potential = recommended_potential_survey_settings(occ_extent_selected)
        use_recommended_potential = st.checkbox(
            "Use recommended fast local settings",
            value=True,
            key="potential_use_recommended_settings",
            help="Recommended keeps the local habitat search responsive while using the finest practical cell size for the selected survey area.",
        )
        if use_recommended_potential:
            potential_cell_m = int(recommended_potential["cell_m"])
            potential_per_type = int(recommended_potential["per_type"])
            potential_max_cells = int(recommended_potential["max_cells"])
            profile_buffer_m = 100
            st.caption(
                f"Recommended settings: requested cell {potential_cell_m:,} m; "
                f"evaluate up to {potential_max_cells:,} grid cells; {potential_per_type} candidates per type. "
                "The app may automatically coarsen the effective cell size for broad survey areas to avoid lag."
            )
        else:
            pc1, pc2, pc3, pc4 = st.columns(4)
            potential_cell_m = pc1.selectbox("Search cell size", [100, 250, 500, 1000], index=0, format_func=lambda v: f"{v} m", key="potential_cell_size_m")
            profile_buffer_m = pc2.number_input("Known-site profile buffer (m)", min_value=10, max_value=1000, value=100, step=10, key="potential_profile_buffer_m")
            potential_per_type = pc3.number_input("Candidates per type", min_value=1, max_value=100, value=10, step=1, key="potential_candidates_per_type")
            potential_max_cells = pc4.number_input("Max grid cells to evaluate", min_value=100, max_value=20_000, value=2_000, step=100, key="potential_max_grid_cells")
        mc1, _mc2 = st.columns(2)
        use_sdm_macro_filter = mc1.checkbox(
            "Use SDM as broad filter",
            value=False,
            disabled=pred_table is None or pred_table.empty,
            key="potential_use_sdm_macro_filter",
            help="Optional. Uses SDM predict-map cells as the macro-scale search frame, but local topographic analogue score remains the main habitat score.",
        )
        st.caption("Candidate types: Habitat-match, Survey-gap, and Environmental-test. Local variables come from uploaded high-resolution layers when supplied.")
        if st.button("Build potential survey-site candidates", key="build_potential_survey_sites", use_container_width=True):
            start_sid = int(all_candidates["site_id"].max()) + 1 if not all_candidates.empty and "site_id" in all_candidates.columns else 1
            potential_candidates = make_potential_survey_site_candidates(
                occ_extent_selected,
                all_candidates,
                float(potential_cell_m),
                int(potential_per_type),
                int(potential_max_cells),
                start_sid,
                prediction_table=pred_table if use_sdm_macro_filter and pred_table is not None and not pred_table.empty else None,
                env_variables=POTENTIAL_ANALOGUE_PRESET,
                resolution=resolution,
                highres_layers=highres_layers,
                profile_buffer_m=float(profile_buffer_m),
            )
            st.session_state["potential_survey_candidates"] = potential_candidates
            st.session_state.acsp_discover_plans = None
            st.session_state.acsp_discover_constraint_audit = None
            st.session_state.acsp_discover_pool_signature = None
            if potential_candidates.empty:
                st.warning("No potential survey-site candidates were generated. Try a coarser cell size or a broader survey area.")
            else:
                st.success(f"Generated {len(potential_candidates):,} potential survey-site candidates.")
        potential_candidates = st.session_state.get("potential_survey_candidates")
        if isinstance(potential_candidates, pd.DataFrame) and not potential_candidates.empty:
            show_cols = [c for c in ["site_id", "candidate_type", "habitat_basis", "habitat_score", "environmental_similarity", "mahalanobis_environment_distance", "sdm_suitability", "survey_gap_score", "access_score", "distance_to_road_m", "distance_to_trail_m", "distance_to_coast_m", "distance_to_forest_edge_m", "environmental_novelty", "nearest_known_population_km", "requested_search_cell_size_m", "effective_search_cell_size_m", "effective_grid_cells_evaluated", "search_cell_radius_m", "latitude", "longitude", "why_selected"] if c in potential_candidates.columns]
            st.dataframe(potential_candidates[show_cols], width="stretch", hide_index=True)
            pdl1, pdl2 = st.columns(2)
            pdl1.download_button("Potential candidates CSV", potential_candidates.to_csv(index=False).encode("utf-8"), "potential_survey_site_candidates.csv", "text/csv", use_container_width=True, key="potential_candidates_csv_download")
            pdl2.download_button("Potential candidates KML", make_export_kml(potential_candidates).encode("utf-8"), "potential_survey_site_candidates.kml", "application/vnd.google-earth.kml+xml", use_container_width=True, key="potential_candidates_kml_download")
            all_candidates = pd.concat([all_candidates, potential_candidates], ignore_index=True, sort=False)

    with st.expander("Optional: learn from field-validation results", expanded=False):
        st.caption(
            "Upload a previous validation CSV exported from this app. "
            "If it contains matching site_id values and a result column such as target_species_found, found, or detected, "
            "the app learns a lightweight field-validation support score and can use it for re-ranking."
        )
        validation_upload = st.file_uploader("Field-validation CSV", type=["csv"], key="field_validation_learning_upload")
        if validation_upload is not None:
            try:
                validation_df = read_uploaded_csv(validation_upload)
                all_candidates, learning_msg = apply_field_validation_learning(all_candidates, validation_df)
                if "applied" in learning_msg:
                    st.success(learning_msg)
                else:
                    st.info(learning_msg)
            except Exception as exc:
                st.warning(f"Could not apply field-validation learning: {exc}")

    all_candidates = filter_to_land(all_candidates, "latitude", "longitude", float(survey_range_m)) if not all_candidates.empty else all_candidates
    all_candidates = add_priority_rank(all_candidates, float(observed_weight), float(model_weight))
    all_candidates = order_sites(all_candidates, "Nearest-neighbor route")

    # ── Survey candidates ─────────────────────────────────────────────────────
    st.subheader("🎯 Survey candidates")
    st.caption(
        "Candidate sites generated from occurrence clusters in your survey area. "
        "Optional SDM below can re-rank or add exploratory sites. "
        "⚠️ Google Maps verification required — road/access not guaranteed."
    )
    if st.session_state.sdm_result is None:
        st.info(
            f"ℹ️ **Model support score: not available yet.** "
            f"Candidates are ranked by observed occurrence support only "
            f"(observed weight = {observed_weight:.2f}). "
            "Run optional SDM above to add SDM suitability-based model support and re-rank candidates."
        )
    else:
        st.success(
            f"✅ **Model support score: SDM suitability active.** "
            f"Candidates are re-ranked with observed weight = {observed_weight:.2f} and "
            f"model weight = {model_weight:.2f}. "
            "Rebuild SDM if settings changed."
        )

    if all_candidates.empty:
        st.warning("No occurrence clusters found. Try reducing the cluster distance or minimum-samples setting in the sidebar.")
        route_plan = pd.DataFrame()
    else:
        valid_site_ids = set(all_candidates["site_id"].astype(int).tolist())
        st.session_state.sl_selected_site_ids = [s for s in st.session_state.get("sl_selected_site_ids", []) if s in valid_site_ids]

        st.markdown("#### Select candidate sites on the map")
        st.caption(
            "Top-ranked sites are shown on the map for inspection. "
            "Click individual candidate markers to add/remove them, or draw a rectangle to add nearby candidate groups together."
        )
        has_suit = "sdm_suitability" in all_candidates.columns and all_candidates["sdm_suitability"].notna().any()
        has_sdm_high = "candidate_type" in all_candidates.columns and all_candidates["candidate_type"].astype(str).str.startswith("SDM-high").any()
        potential_types = ["Habitat-match", "Survey-gap", "Environmental-test", "Habitat analogue", "Under-surveyed analogue", "Environmental contrast"]
        has_potential = "candidate_type" in all_candidates.columns and all_candidates["candidate_type"].astype(str).isin(potential_types).any()
        sc1, sc2, sc3 = st.columns(3)
        top_sites_shown = sc1.number_input("Top-ranked sites shown", min_value=1, value=20, step=1, key="sl_top_sites_shown")
        min_priority = sc2.number_input("Minimum priority score", 0.0, 1.0, 0.0, 0.05, format="%.2f", key="sl_min_priority")
        min_suit = sc3.number_input(
            "Minimum SDM suitability",
            0.0,
            1.0,
            0.0,
            0.05,
            format="%.2f",
            key="sl_min_suit",
            disabled=not has_suit,
            help="Available after SDM is built." if not has_suit else "Filter displayed candidates by SDM suitability.",
        )
        ic1, ic2, ic3, ic4, ic5 = st.columns(5)
        include_occurrence_candidates = ic1.checkbox("Include occurrence-supported candidates", value=True, key="sl_incl_occ")
        include_sdm_candidates = ic2.checkbox("Include SDM-high exploration candidates", value=True, key="sl_incl_sdm", disabled=not has_sdm_high)
        include_potential_candidates = ic3.checkbox("Include potential survey cells", value=True, key="sl_incl_potential", disabled=not has_potential)
        travelmode = ic4.selectbox("Google Maps travel mode", ["driving", "walking", "bicycling", "transit"], index=0, key="sl_travelmode")
        if ic5.button("Clear selected sites", key="sl_clear_map_controls", disabled=not st.session_state.sl_selected_site_ids):
            st.session_state.sl_selected_site_ids = []
            st.session_state.acsp_result_species = None
            st.session_state.last_route_click_signature = ""
            st.session_state.sl_last_draw_sig = ""
            st.session_state.sl_reset_token = st.session_state.get("sl_reset_token", 0) + 1
            st.rerun()
        show_occurrences_on_selection_map = st.checkbox(
            "Show candidate-input occurrence points on selection map (slower)",
            value=False,
            key="sl_show_occurrences_on_selection_map",
            help="Off keeps map selection responsive. Turn on to verify all occurrence points used for candidate generation on this same map.",
        )
        if st.button("Clear selection rectangles", key="sl_clear_selection_rectangles", use_container_width=True):
            st.session_state.sl_last_draw_sig = ""
            st.session_state.sl_reset_token = st.session_state.get("sl_reset_token", 0) + 1
            st.rerun()

        map_candidates = all_candidates.copy()
        type_mask = pd.Series(False, index=map_candidates.index)
        if include_occurrence_candidates:
            type_mask |= map_candidates.get("candidate_type", pd.Series("", index=map_candidates.index)).astype(str).str.startswith("Occurrence")
        if include_sdm_candidates and has_sdm_high:
            type_mask |= map_candidates.get("candidate_type", pd.Series("", index=map_candidates.index)).astype(str).str.startswith("SDM-high")
        if include_potential_candidates and has_potential:
            type_mask |= map_candidates.get("candidate_type", pd.Series("", index=map_candidates.index)).astype(str).isin(potential_types)
        if include_occurrence_candidates or (include_sdm_candidates and has_sdm_high) or (include_potential_candidates and has_potential):
            map_candidates = map_candidates[type_mask]
        if "priority_score" in map_candidates.columns:
            map_candidates = map_candidates[pd.to_numeric(map_candidates["priority_score"], errors="coerce").fillna(0.0) >= float(min_priority)]
        if has_suit:
            map_candidates = map_candidates[pd.to_numeric(map_candidates["sdm_suitability"], errors="coerce").fillna(0.0) >= float(min_suit)]

        sort_cols = available_sort_cols(map_candidates, ["priority_score", "sdm_suitability", "occurrence_support_score"])
        map_candidates = map_candidates.sort_values(sort_cols, ascending=False, na_position="last") if sort_cols else map_candidates
        acsp_pool = map_candidates.copy()
        map_candidates = map_candidates.head(int(top_sites_shown)).copy()
        st.markdown(f"**Top-ranked candidate output ({len(map_candidates)})**")
        if map_candidates.empty:
            st.info("No candidates match the current display filters.")
        else:
            rank_cols = [c for c in ["site_id", "priority_rank", "priority_score", "candidate_type", "occurrence_support_score", "model_support_score", "sdm_suitability", "latitude", "longitude", "score_explanation"] if c in map_candidates.columns]
            st.dataframe(map_candidates[rank_cols], width="stretch", hide_index=True)
            tr1, tr2, tr3 = st.columns(3)
            tr1.download_button("Top-ranked candidates CSV", make_export_csv(map_candidates), "top_ranked_survey_candidates.csv", "text/csv", use_container_width=True, key="top_ranked_candidates_csv_download")
            tr2.download_button("Top-ranked candidates KML", make_export_kml(map_candidates).encode("utf-8"), "top_ranked_survey_candidates.kml", "application/vnd.google-earth.kml+xml", use_container_width=True, key="top_ranked_candidates_kml_download")
            tr3.download_button("Field validation CSV", make_validation_template(map_candidates).to_csv(index=False).encode("utf-8"), "top_ranked_field_validation_template.csv", "text/csv", use_container_width=True, key="top_ranked_validation_csv_download")
        if not map_candidates.empty:
            add_ids = set(map_candidates["site_id"].astype(int).tolist())
            if st.button(
                f"Add top-ranked shown sites ({len(add_ids)})",
                key="sl_add_top_ranked_shown_sites",
                use_container_width=True,
            ):
                existing = set(map(int, st.session_state.get("sl_selected_site_ids", [])))
                st.session_state.sl_selected_site_ids = sorted(existing | add_ids)

        # ── ACSP: candidate-SET selection algorithm ──────────────────────────
        st.markdown("#### ACSP-Discover v1 — three ready-to-compare plans")
        st.caption(
            "The same eligible candidate pool produces Balanced, Discovery, and Learning plans. "
            "Known water, dangerous slopes, restricted access, and cells beyond the 500 m road/trail limit "
            "are excluded before scoring; unknown constraints remain visible as unknown, not assumed safe."
        )
        discover_k = st.number_input(
            "Priority cells per ACSP-Discover plan",
            1,
            max(1, len(acsp_pool)),
            min(8, max(1, len(acsp_pool))),
            1,
            key="acsp_discover_k_species",
        )
        signature_cols = [c for c in [
            "site_id", "candidate_type", "latitude", "longitude", "analogue_score", "habitat_score",
            "sdm_suitability", "survey_gap_score", "environmental_novelty", "access_score",
            "distance_to_road_m", "distance_to_trail_m", "slope",
        ] if c in acsp_pool.columns]
        pool_signature = hashlib.sha1(
            pd.util.hash_pandas_object(acsp_pool[signature_cols], index=False).values.tobytes()
            if signature_cols else b"empty"
        ).hexdigest()
        if st.session_state.get("acsp_discover_pool_signature") not in (None, pool_signature):
            st.session_state.acsp_discover_plans = None
            st.session_state.acsp_discover_constraint_audit = None
        if st.button(
            "Build Balanced / Discovery / Learning plans",
            key="acsp_discover_run_species",
            type="primary",
            use_container_width=True,
            disabled=acsp_pool.empty,
        ):
            eligible_pool, constraint_audit = apply_discover_hard_constraints(acsp_pool)
            st.session_state.acsp_discover_constraint_audit = constraint_audit
            st.session_state.acsp_discover_plans = build_acsp_discover_plans(eligible_pool, int(discover_k))
            st.session_state.acsp_discover_pool_signature = pool_signature

        discover_plans = st.session_state.get("acsp_discover_plans")
        if isinstance(discover_plans, dict) and discover_plans:
            audit = st.session_state.get("acsp_discover_constraint_audit")
            if isinstance(audit, pd.DataFrame) and not audit.empty:
                excluded_n = int((~audit["eligible"]).sum())
                unknown_n = int(audit["unknown_constraints"].astype(str).ne("").sum())
                st.caption(
                    f"Hard-constraint audit: {int(audit['eligible'].sum())} eligible, "
                    f"{excluded_n} excluded, {unknown_n} retained with one or more unknown constraints."
                )
                with st.expander("Constraint audit", expanded=False):
                    st.dataframe(audit, width="stretch", hide_index=True)
                    st.download_button(
                        "Download constraint audit CSV",
                        audit.to_csv(index=False).encode("utf-8"),
                        "acsp_discover_constraint_audit.csv",
                        "text/csv",
                        key="acsp_discover_constraint_audit_download",
                    )
            plan_tabs = st.tabs(list(ACSP_DISCOVER_PLAN_ORDER))
            for tab, plan_name in zip(plan_tabs, ACSP_DISCOVER_PLAN_ORDER):
                with tab:
                    plan = discover_plans.get(plan_name, pd.DataFrame())
                    summary = summarize_discover_plan(plan)
                    m1, m2, m3, m4, m5 = st.columns(5)
                    m1.metric("Priority cells", summary["priority_cells"])
                    m2.metric("Known anchors", summary["known_anchors"])
                    m3.metric("Discovery cells", summary["discovery_cells"])
                    m4.metric("Learning cells", summary["learning_cells"])
                    m5.metric("Data quality", str(summary["data_quality"]).title())
                    if plan.empty:
                        st.info("No eligible cells were available for this plan.")
                        continue
                    plan_cols = [c for c in [
                        "plan_rank", "site_id", "candidate_type", "discovery_label", "learning_label",
                        "access_label", "effective_search_cell_size_m", "search_cell_radius_m",
                        "data_quality", "why_selected", "latitude", "longitude",
                    ] if c in plan.columns]
                    st.dataframe(plan[plan_cols], width="stretch", hide_index=True)
                    p1, p2 = st.columns(2)
                    p1.download_button(
                        f"Download {plan_name} plan CSV",
                        make_export_csv(plan).encode("utf-8"),
                        f"acsp_discover_{plan_name.lower()}_plan.csv",
                        "text/csv",
                        use_container_width=True,
                        key=f"acsp_discover_{plan_name.lower()}_download",
                    )
                    if p2.button(
                        f"Use {plan_name} plan on map",
                        key=f"acsp_discover_{plan_name.lower()}_use",
                        use_container_width=True,
                    ):
                        st.session_state.acsp_result_species = plan
                        st.session_state.sl_selected_site_ids = [int(s) for s in plan["site_id"].tolist()]
                        st.session_state.sl_reset_token = st.session_state.get("sl_reset_token", 0) + 1
                        st.rerun()

        with st.expander("Advanced: legacy single-algorithm ACSP selection", expanded=False):
            st.markdown("#### Auto-select a survey set (ACSP)")
            st.caption(
                "Legacy and specialist selection modes remain available for backward compatibility and research comparisons."
            )
            ac1, ac2, ac3 = st.columns([2, 1, 1])
            acsp_default_index = ACSP_SELECTION_MODES.index("Discovery-focused field survey") if has_potential else ACSP_SELECTION_MODES.index("Complementarity-based batch selection")
            acsp_mode = ac1.selectbox("Selection algorithm", ACSP_SELECTION_MODES, index=acsp_default_index, key="acsp_mode_species")
            acsp_k = ac2.number_input("Sites to select (K)", 1, max(1, len(acsp_pool)), min(10, max(1, len(acsp_pool))), 1, key="acsp_k_species")
            acsp_seed = ac3.checkbox("Seed with current selection", value=False, key="acsp_seed_species", help="Keep already-selected sites as the starting set (S0) and fill the rest by complementarity.")
            if st.button("Auto-select by selected algorithm", key="acsp_run_species", use_container_width=True, disabled=acsp_pool.empty):
                seed_ids = list(st.session_state.get("sl_selected_site_ids", [])) if acsp_seed else None
                acsp_res = acsp_select(acsp_pool, int(acsp_k), acsp_mode, selected_ids=seed_ids, cluster_distance_m=float(cluster_m))
                if acsp_res.empty:
                    st.warning("ACSP could not select any sites from the current candidate pool.")
                else:
                    st.session_state.acsp_result_species = acsp_res
                    st.session_state.sl_selected_site_ids = [int(s) for s in acsp_res["site_id"].tolist()]
                    st.session_state.sl_reset_token = st.session_state.get("sl_reset_token", 0) + 1
                    st.rerun()

        route_plan = pd.DataFrame()

    # ── Priority-aware candidate map ─────────────────────────────────────────
    # Marker legend: red (rank 1-3) | orange (rank 4-10) | green (rank 11-20) | grey (rank >20) | purple dashed (SDM-high)
    # Selected sites show a green outer ring.
    _sel_ids_for_map = tuple(sorted(st.session_state.get("sl_selected_site_ids", [])))
    _sites_for_map = map_candidates if not all_candidates.empty else all_candidates
    selection_layers = dict(layers)
    selection_layers["occ"] = bool(st.session_state.get("sl_show_occurrences_on_selection_map", False))
    fmap = build_map(occ_candidate_input, _sites_for_map, overlay, None, 0.0, float(survey_range_m), selection_layers, bool(show_occurrence_images), selected_ids=(), add_draw=not all_candidates.empty)
    selected_overlay = make_selected_site_overlay(all_candidates, _sel_ids_for_map)
    main_map_data = st_folium_with_overlay(
        fmap,
        selected_overlay,
        width=None,
        height=720,
        returned_objects=["last_object_clicked", "last_object_clicked_tooltip", "all_drawings", "last_active_drawing"],
        key=f"main_map_{st.session_state.get('sl_reset_token', 0)}",
    )

    if not all_candidates.empty:
        clicked = (main_map_data or {}).get("last_object_clicked")
        clicked_tooltip = (main_map_data or {}).get("last_object_clicked_tooltip") or ""
        if clicked:
            sig = f"{clicked.get('lat'):.6f},{clicked.get('lng'):.6f},{clicked_tooltip}"
            if sig != st.session_state.last_route_click_signature:
                st.session_state.last_route_click_signature = sig
                sid = None
                match = re.search(r"site\s+(\d+)", str(clicked_tooltip), flags=re.IGNORECASE)
                if match:
                    sid = int(match.group(1))
                elif _sites_for_map is not None and not _sites_for_map.empty:
                    sid = nearest_site_id_from_click(_sites_for_map, clicked)
                if sid is not None and sid in valid_site_ids:
                    selected = list(st.session_state.sl_selected_site_ids)
                    if sid in selected:
                        selected.remove(sid)
                    else:
                        selected.append(sid)
                    st.session_state.sl_selected_site_ids = selected
        raw_drawings = (main_map_data or {}).get("all_drawings") or (main_map_data or {}).get("last_active_drawing")
        features = extract_drawn_features(raw_drawings)
        if features:
            draw_sig = str(features)[:800]
            if draw_sig != st.session_state.get("sl_last_draw_sig", ""):
                st.session_state.sl_last_draw_sig = draw_sig
                rect_ids = ids_inside_drawn_rectangles(all_candidates, "site_id", "latitude", "longitude", features)
                if rect_ids:
                    existing = set(st.session_state.sl_selected_site_ids)
                    st.session_state.sl_selected_site_ids = sorted(existing | set(map(int, rect_ids)))

    html_bytes = fmap.get_root().render().encode("utf-8")

    # ── Selected-sites compact summary (replaces Step 4) ─────────────────────
    _sel_ids_now = list(st.session_state.get("sl_selected_site_ids", []))
    _sel_df_summary = all_candidates[all_candidates["site_id"].astype(int).isin(_sel_ids_now)].copy() if not all_candidates.empty else pd.DataFrame()
    _acsp_res_species = st.session_state.get("acsp_result_species")
    if not _sel_df_summary.empty:
        _sel_df_summary = acsp_merge_columns(_sel_df_summary, _acsp_res_species)
    if not _sel_df_summary.empty and _sel_ids_now:
        _ord_map = {sid: i for i, sid in enumerate(_sel_ids_now)}
        _sel_df_summary = _sel_df_summary.assign(_ord=_sel_df_summary["site_id"].astype(int).map(_ord_map)).sort_values("_ord").drop(columns=["_ord"])
    st.markdown(f"**Selected survey sites ({len(_sel_df_summary)})**")
    if _sel_df_summary.empty:
        st.info("No sites selected yet. Click candidate markers, draw a rectangle, or use ACSP auto-select above.")
    else:
        _sel_df_summary["google_maps_point_url"] = _sel_df_summary.apply(
            lambda r: make_google_maps_point_url(float(r["latitude"]), float(r["longitude"])), axis=1
        )
        _sum_cols = [c for c in ["site_id", "selection_step", "priority_rank", "priority_score", "candidate_type", "marginal_gain_score", "habitat_analogue_gain", "sampling_gap_gain", "validation_learning_gain", "access_gain", "selection_reason", "google_maps_point_url"] if c in _sel_df_summary.columns]
        _sum_cfg: dict[str, Any] = {}
        if "google_maps_point_url" in _sum_cols:
            _sum_cfg["google_maps_point_url"] = st.column_config.LinkColumn("Google Maps", display_text="📍")
        st.dataframe(_sel_df_summary[_sum_cols], column_config=_sum_cfg, width="stretch", hide_index=True)
        _travelmode_sum = st.session_state.get("sl_travelmode", "driving")
        _gmaps_all_url_sum = make_google_maps_route_url(_sel_df_summary, travelmode=_travelmode_sum, max_waypoints=8)
        _sb1, _sb2, _sb3, _sb4, _sb5, _sb6 = st.columns(6)
        _sb1.link_button("🗺️ Open all in Google Maps", _gmaps_all_url_sum, use_container_width=True)
        _sb2.download_button("⬇ CSV", make_export_csv(_sel_df_summary), "survey_site_list.csv", "text/csv", use_container_width=True, key="selected_summary_csv_download")
        _sb3.download_button("⬇ HTML", make_shareable_html(_sel_df_summary), "survey_site_list.html", "text/html", use_container_width=True, key="selected_summary_html_download")
        _sb4.download_button("⬇ KML", make_export_kml(_sel_df_summary).encode("utf-8"), "survey_site_list.kml", "application/vnd.google-earth.kml+xml", use_container_width=True, key="selected_summary_kml_download")
        _sb5.download_button(
            "Validation CSV",
            make_validation_template(_sel_df_summary).to_csv(index=False).encode("utf-8"),
            "field_validation_template.csv",
            "text/csv",
            use_container_width=True,
            key="selected_summary_validation_csv_download",
        )
        if _sb6.button("Clear selected sites", key="sl_clear_summary"):
            st.session_state.sl_selected_site_ids = []
            st.session_state.acsp_result_species = None
            st.session_state.sl_reset_token = st.session_state.get("sl_reset_token", 0) + 1
            st.session_state.last_route_click_signature = ""
            st.session_state.sl_last_draw_sig = ""
            st.rerun()
        route_plan = _sel_df_summary.copy()

    # ── Optional: full candidate details table ────────────────────────────────
    with st.expander("Optional: candidate details table", expanded=False):
        if all_candidates.empty:
            st.info("No candidates generated yet.")
        else:
            all_cand_show_cols = [c for c in ["site_id", "priority_rank", "priority_score", "occurrence_support_score", "model_support_score", "field_validation_support_score", "observed_weight", "model_weight", "candidate_type", "n_occurrences", "habitat_score", "environmental_similarity", "mahalanobis_environment_distance", "analogue_score", "survey_gap_score", "access_score", "habitat_analogue_gain", "sampling_gap_gain", "validation_learning_gain", "access_gain", "distance_to_road_m", "distance_to_trail_m", "distance_to_coast_m", "distance_to_forest_edge_m", "environmental_novelty", "nearest_known_population_km", "search_cell_radius_m", "latitude", "longitude", "score_explanation", "recommended_survey_window", "season_confidence", "flowering_record_count"] if c in all_candidates.columns]
            st.dataframe(all_candidates[all_cand_show_cols], width="stretch", hide_index=True)
            oc1, oc2 = st.columns(2)
            oc1.download_button(
                "Candidates CSV",
                all_candidates.to_csv(index=False).encode("utf-8"),
                "survey_candidates.csv",
                "text/csv",
                use_container_width=True,
                key="candidate_details_csv_download",
            )
            oc2.download_button(
                "Candidates KML",
                make_export_kml(all_candidates).encode("utf-8"),
                "survey_candidates.kml",
                "application/vnd.google-earth.kml+xml",
                use_container_width=True,
                key="candidate_details_kml_download",
            )

    st.subheader("Performance summary")
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("GBIF fetched records", f"{len(occ_raw):,}")
    c2.metric("Active survey-area records", f"{len(occ_extent_selected):,}")
    c3.metric("Inside rectangle", f"{target_counts['records_inside_rectangle']:,}")
    c4.metric("Active target set", f"{target_counts['active_target_records']:,}")
    c5.metric("Survey ranges", f"{len(all_candidates):,}")
    c6.metric("Selected sites", f"{len(route_plan):,}" if route_plan is not None else "0")
    p1, p2, p3, p4, p5, p6 = st.columns(6)
    p1.metric("Excluded by rectangle", f"{target_counts['records_excluded_by_rectangle']:,}")
    p2.metric("Candidate input", f"{len(occ_candidate_input):,}")
    p3.metric("SDM train records", f"{len(occ_sdm_train):,}")
    p4.metric("Map occurrence points", f"{len(occ_map_display):,}")
    p5.metric("Exact dedupe removed", f"{exact_dedup_removed:,}")
    p6.metric("Grid thinning removed", f"{grid_thinning_removed:,}")

    # ── Auto-generated Methods text ───────────────────────────────────────────
    st.subheader("Methods (auto-generated)")
    st.caption("Copy this text for the Methods section of your report or paper.")
    _sdm_result_now = st.session_state.get("sdm_result")
    _sdm_methods = ""
    if _sdm_result_now is not None:
        _auc_val = _sdm_result_now.get("mean_auc", float("nan"))
        _kept = _sdm_result_now.get("kept_variables", variables)
        _algs_used = _sdm_result_now.get("algorithms", algorithms)
        _part_used = _sdm_result_now.get("partition_method", partition_method)
        _auc_str = f"{_auc_val:.3f}" if isinstance(_auc_val, float) and not math.isnan(_auc_val) else "N/A"
        _sdm_methods = (
            f" An ensemble SDM was fitted using {' and '.join(_algs_used)} "
            f"with {len(_kept)} environmental predictors "
            f"({', '.join(_kept[:4])}{'...' if len(_kept) > 4 else ''}; "
            f"WorldClim 2.1, 2.5 arc-minutes). "
            f"Predictor collinearity was reduced by VIF stepwise filtering (threshold = {int(vif_threshold)}). "
            f"Model performance was evaluated by {_part_used} spatial cross-validation "
            f"(mean AUC = {_auc_str}, n = {len(occ_for_sdm):,} presence points). "
            f"SDM prediction extent: {area_mode} ({buffer_km:.0f} km buffer). "
            f"Survey candidates were re-ranked by a weighted composite score "
            f"(observed occurrence support w = {observed_weight:.1f}; SDM suitability w = {model_weight:.1f})."
        )
    _methods_text = (
        f"Species occurrence records for {st.session_state.get('source_key', '[species]')} "
        f"were retrieved from the Global Biodiversity Information Facility (GBIF; gbif.org) "
        f"on {__import__('datetime').date.today().isoformat()} "
        f"({len(occ_raw):,} records fetched). "
        f"Records were spatially balanced to {len(occ_sdm_train) if occ_sdm_train is not None else len(occ_raw):,} "
        f"representative presence points using a "
        f"≈{int(math.sqrt(int(sdm_ind_max_presence)))}×{int(math.sqrt(int(sdm_ind_max_presence)))} "
        f"geographic grid (highest-quality record per cell retained, prioritising photo-verified "
        f"and recent observations; spatially_balanced_cap). "
        f"Survey candidates were generated by DBSCAN spatial clustering "
        f"(ε = {cluster_m:,} m) of {len(occ_candidate_input):,} spatially thinned occurrence records "
        f"within the study area, and ranked by occurrence density.{_sdm_methods}"
    )
    st.code(_methods_text, language=None)

    st.subheader("Downloads")
    st.download_button("Download sampling HTML map", html_bytes, "fieldmap.html", "text/html", width="stretch", key="sampling_html_map_download")


if __name__ == "__main__":
    main()
