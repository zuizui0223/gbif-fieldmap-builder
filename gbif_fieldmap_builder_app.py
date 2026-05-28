"""
GBIF FieldMap Builder

Bias-aware Streamlit app for field-survey planning from either:
1) any coordinate CSV with latitude/longitude columns, or
2) direct scientific-name searches via the GBIF API.

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
import pandas as pd
import requests
import streamlit as st
from folium import FeatureGroup, LayerControl, Map
from folium.plugins import MarkerCluster
from geopy.distance import geodesic
from shapely.geometry import MultiPoint, Point
from sklearn.cluster import DBSCAN
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
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def clear_loaded_data() -> None:
    st.session_state.raw_df = None
    st.session_state.source_message = "No occurrence data loaded yet."
    st.session_state.source_kind = None
    st.session_state.source_key = None


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
def fetch_gbif_occurrences_cached(
    scientific_name: str,
    max_records: int,
    country_code: str,
    year_from: Optional[int],
    year_to: Optional[int],
) -> tuple[GBIFTaxonMatch, pd.DataFrame]:
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


def make_google_maps_transit_url(origin: tuple[float, float], destination: tuple[float, float]) -> str:
    params = {
        "api": "1",
        "origin": f"{origin[0]:.6f},{origin[1]:.6f}",
        "destination": f"{destination[0]:.6f},{destination[1]:.6f}",
        "travelmode": "transit",
    }
    return "https://www.google.com/maps/dir/?" + urllib.parse.urlencode(params, safe=",")


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


def build_public_transit_legs(sites: pd.DataFrame) -> pd.DataFrame:
    if sites.empty or len(sites) < 2:
        return pd.DataFrame(columns=["leg", "from_site", "to_site", "google_maps_transit_url", "fare_yen", "notes"])
    ordered = sites.sort_values("route_order").reset_index(drop=True)
    rows = []
    for i in range(len(ordered) - 1):
        a = ordered.loc[i]
        b = ordered.loc[i + 1]
        origin = (float(a["latitude"]), float(a["longitude"]))
        dest = (float(b["latitude"]), float(b["longitude"]))
        rows.append({
            "leg": i + 1,
            "from_site": int(a["site_id"]),
            "to_site": int(b["site_id"]),
            "google_maps_transit_url": make_google_maps_transit_url(origin, dest),
            "fare_yen": 0,
            "notes": "Enter actual train/bus/ferry fare checked manually.",
        })
    return pd.DataFrame(rows)


def transit_cost_summary(
    legs: pd.DataFrame,
    origin_roundtrip_yen: float,
    lodging_per_night: float,
    nights: int,
    per_diem: float,
    days: int,
    misc: float,
) -> dict[str, float]:
    fares = pd.to_numeric(legs.get("fare_yen", pd.Series(dtype=float)), errors="coerce").fillna(0).sum() if legs is not None and not legs.empty else 0
    lodging = lodging_per_night * nights
    daily = per_diem * days
    total = fares + origin_roundtrip_yen + lodging + daily + misc
    return {
        "inter_site_public_transport_yen": round(float(fares)),
        "origin_roundtrip_yen": round(float(origin_roundtrip_yen)),
        "lodging_yen": round(float(lodging)),
        "per_diem_yen": round(float(daily)),
        "misc_yen": round(float(misc)),
        "estimated_total_yen": round(float(total)),
    }


def fit_bounds_or_default(df: pd.DataFrame) -> tuple[list[list[float]], tuple[float, float], int]:
    if df.empty:
        return [[35.0, 135.0], [36.0, 136.0]], (35.5, 135.5), 6
    min_lat, max_lat = df["_latitude"].min(), df["_latitude"].max()
    min_lon, max_lon = df["_longitude"].min(), df["_longitude"].max()
    return [[min_lat, min_lon], [max_lat, max_lon]], ((min_lat + max_lat) / 2, (min_lon + max_lon) / 2), 8


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
    return f"""
    <b>Candidate site {int(row['site_id'])}</b><br>
    Priority rank: {row.get('priority_rank', '')}<br>
    Route order: {int(row.get('route_order', row['site_id']))}<br>
    Cluster: {int(row['cluster_id'])}<br>
    Method: {row.get('candidate_method', '')}<br>
    Priority score: {row.get('priority_score', '')}<br>
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


def build_map(
    occurrences: pd.DataFrame,
    sites: pd.DataFrame,
    buffer_radius_m: float,
    show_occurrences: bool,
    show_buffers: bool,
    show_clusters: bool,
    show_candidate_sites: bool,
    show_routes: bool,
    show_distance_labels: bool,
) -> folium.Map:
    bounds, center, zoom = fit_bounds_or_default(occurrences)
    fmap = Map(location=center, zoom_start=zoom, tiles="OpenStreetMap", control_scale=True)
    cluster_colors = ["red", "orange", "green", "purple", "cadetblue", "darkred", "darkgreen", "darkblue", "pink", "gray"]

    if show_buffers:
        group = FeatureGroup(name="Buffers", show=True)
        for _, row in occurrences.iterrows():
            folium.Circle(
                location=(row["_latitude"], row["_longitude"]),
                radius=float(buffer_radius_m),
                color="#7aa6ff",
                weight=1,
                fill=True,
                fill_opacity=0.08,
                opacity=0.35,
            ).add_to(group)
        group.add_to(fmap)

    if show_occurrences:
        group = FeatureGroup(name="Occurrences", show=True)
        marker_cluster = MarkerCluster(name="Occurrence marker cluster")
        for _, row in occurrences.iterrows():
            folium.CircleMarker(
                location=(row["_latitude"], row["_longitude"]),
                radius=4,
                color="#1f77b4",
                fill=True,
                fill_color="#1f77b4",
                fill_opacity=0.75,
                weight=1,
                popup=folium.Popup(popup_html_occurrence(row), max_width=330),
            ).add_to(marker_cluster)
        marker_cluster.add_to(group)
        group.add_to(fmap)

    if show_clusters:
        group = FeatureGroup(name="Clusters", show=True)
        for _, row in occurrences.iterrows():
            label = int(row["cluster_id"])
            color = "black" if label < 0 else cluster_colors[label % len(cluster_colors)]
            folium.CircleMarker(
                location=(row["_latitude"], row["_longitude"]),
                radius=6,
                color=color,
                fill=True,
                fill_color=color,
                fill_opacity=0.45,
                weight=2,
                popup=f"Cluster: {label}",
            ).add_to(group)
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
            folium.Marker(
                location=mid,
                icon=folium.DivIcon(
                    html=(
                        "<div style='font-size:12px;font-weight:700;background:white;"
                        "border:1px solid #999;border-radius:4px;padding:2px 5px;white-space:nowrap;'>"
                        f"{dist_km:.1f} km</div>"
                    )
                ),
            ).add_to(group)
        group.add_to(fmap)

    if show_candidate_sites:
        group = FeatureGroup(name="Candidate survey sites", show=True)
        for _, row in sites.iterrows():
            order = int(row.get("route_order", row["site_id"]))
            folium.Marker(
                location=(row["latitude"], row["longitude"]),
                popup=folium.Popup(popup_html_site(row), max_width=380),
                tooltip=f"Site {int(row['site_id'])} / Priority {row.get('priority_rank', '')}",
                icon=folium.DivIcon(
                    html="<div style='font-size:22px;line-height:22px;color:red;text-shadow:0 0 2px white,0 0 4px white;'>★</div>"
                ),
            ).add_to(group)
            folium.Marker(
                location=(row["latitude"], row["longitude"]),
                icon=folium.DivIcon(
                    html=(
                        "<div style='font-size:11px;font-weight:700;background:white;"
                        "border:1px solid #c00;border-radius:10px;padding:1px 5px;margin-left:14px;'>"
                        f"{order}</div>"
                    )
                ),
            ).add_to(group)
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
        uploaded = st.sidebar.file_uploader(
            "Upload CSV with latitude/longitude columns",
            type=["csv"],
            key="csv_upload",
            help="GBIF format is not required. Any CSV is OK if it has coordinate columns such as latitude/longitude, lat/lon, lat/lng, decimalLatitude/decimalLongitude, or 緯度/経度. Species/date/photo columns are optional.",
        )
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

    request_key = f"gbif::{scientific_name.strip()}::{country_code.strip().upper()}::{int(max_records)}::{year_from}::{year_to}"
    if st.sidebar.button("Fetch occurrences from GBIF", type="primary"):
        if not scientific_name.strip():
            st.warning("Scientific name is empty.")
            return
        with st.spinner("Fetching GBIF occurrences..."):
            match, df = fetch_gbif_occurrences_cached(scientific_name.strip(), int(max_records), country_code.strip().upper(), year_from, year_to)
        st.session_state.raw_df = df.copy()
        st.session_state.source_message = (
            f"GBIF match: {match.matched_name or match.input_name} / usageKey={match.usage_key} "
            f"/ confidence={match.confidence}. Fetched {len(df):,} raw occurrence records."
        )
        st.session_state.source_kind = "gbif"
        st.session_state.source_key = request_key


def main() -> None:
    st.set_page_config(page_title=APP_TITLE, page_icon="🗺️", layout="wide")
    init_session_state()

    st.title("🗺️ GBIF FieldMap Builder")
    st.caption("Bias-aware field survey planning from any coordinate CSV or direct GBIF scientific-name search.")

    st.sidebar.header("Data source")
    load_input_controls()

    st.sidebar.divider()
    st.sidebar.subheader("Sampling design")
    thinning_m = st.sidebar.number_input("Spatial thinning distance before clustering (m)", min_value=0, max_value=50_000, value=1000, step=500)
    candidate_method = st.sidebar.selectbox("Candidate site method", ["Medoid", "Centroid"], index=0, help="Medoid is recommended: it selects an actual occurrence point.")
    buffer_radius_m = st.sidebar.number_input("Buffer radius around occurrences (m)", 0, 100_000, 500, 100)
    dbscan_threshold_m = st.sidebar.number_input("DBSCAN cluster distance threshold (m)", 1, 500_000, 2000, 500)
    min_samples = st.sidebar.number_input("Minimum occurrences per cluster", 1, 50, 1, 1)
    route_order_mode = st.sidebar.selectbox(
        "Candidate site order",
        ["Cluster ID", "Priority score", "Nearest-neighbor route", "North → South", "South → North", "West → East", "East → West"],
        index=2,
    )
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
        st.markdown(
            """
            **Two ways to start:**
            1. Upload any CSV with latitude/longitude columns. GBIF format is not required.
            2. Enter a scientific name and fetch occurrences directly from GBIF.

            Optional columns such as species/scientificName, eventDate/year, locality, gbifID, and image/media URL will be detected automatically when present.

            Once loaded, the data stay in the app session. Changing layers or sampling settings will not force another upload or GBIF search.
            """
        )
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
    ordered_sites = add_navigation_columns(order_sites(candidate_sites, route_order_mode))
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
        st.caption("Transit fares are not automatically estimated. Use the public-transit links to check actual train/bus/ferry fares and enter them below.")

    with st.expander("Detected columns", expanded=False):
        st.write(detected.__dict__)

    fmap = build_map(occ, ordered_sites, float(buffer_radius_m), show_occurrences, show_buffers, show_clusters, show_candidate_sites, show_routes, show_distance_labels)
    st_folium(fmap, width=None, height=720, returned_objects=[])

    st.subheader("Priority candidate sites")
    priority_cols = [
        "priority_rank", "site_id", "route_order", "priority_score", "n_occurrences",
        "latitude", "longitude", "year_min", "year_max",
        "bias_warning", "selection_reason", "representative_media_url",
    ]
    priority_sites = ordered_sites.sort_values(["priority_rank"]).head(int(priority_top_n)) if not ordered_sites.empty else ordered_sites
    if priority_sites.empty:
        st.warning("No priority candidates were generated. Try changing DBSCAN settings.")
    else:
        st.dataframe(priority_sites[priority_cols], width="stretch", hide_index=True)

    st.subheader("All candidate survey sites")
    if ordered_sites.empty:
        st.warning("No candidate sites were generated. Try changing DBSCAN settings.")
    else:
        display_cols = [
            "route_order", "priority_rank", "site_id", "cluster_id", "latitude", "longitude",
            "n_occurrences", "priority_score", "next_site_straight_km", "species_summary",
            "year_min", "year_max", "candidate_method", "bias_warning", "selection_reason",
            "representative_gbif_id", "representative_media_url", "google_maps_point_url",
        ]
        st.dataframe(ordered_sites[display_cols], width="stretch", hide_index=True)

    st.subheader("Public transit fare calculator")
    transit_legs = build_public_transit_legs(ordered_sites)
    if transit_legs.empty:
        st.info("At least two candidate sites are needed for public-transit leg calculation.")
        edited_legs = transit_legs
    else:
        st.caption("Open each Google Maps transit URL, check the actual train/bus/ferry fare, and enter it in `fare_yen`. This avoids unreliable rough fare estimation.")
        edited_legs = st.data_editor(transit_legs, width="stretch", hide_index=True, num_rows="fixed")

    with st.expander("Additional trip costs", expanded=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            origin_roundtrip_yen = st.number_input("Origin → survey area round trip fare (yen)", min_value=0, value=0, step=1000)
            lodging_per_night = st.number_input("Lodging per night (yen)", min_value=0, value=8000, step=1000)
        with c2:
            nights = st.number_input("Nights", min_value=0, value=0, step=1)
            per_diem = st.number_input("Per diem / food per day (yen)", min_value=0, value=2000, step=500)
        with c3:
            days = st.number_input("Days", min_value=0, value=1, step=1)
            misc = st.number_input("Miscellaneous / local taxi / supplies (yen)", min_value=0, value=0, step=1000)

    cost = transit_cost_summary(edited_legs, origin_roundtrip_yen, lodging_per_night, int(nights), per_diem, int(days), misc)
    st.metric("Estimated public-transport-based total", f"¥{cost['estimated_total_yen']:,}")
    st.json(cost)

    html_bytes = fmap.get_root().render().encode("utf-8")
    candidates_csv = ordered_sites.to_csv(index=False).encode("utf-8-sig")
    transit_csv = edited_legs.to_csv(index=False).encode("utf-8-sig") if edited_legs is not None else b""
    cost_csv = pd.DataFrame([cost]).to_csv(index=False).encode("utf-8-sig")

    dl1, dl2, dl3, dl4 = st.columns(4)
    with dl1:
        st.download_button("Download HTML map", html_bytes, "fieldmap.html", "text/html", width="stretch")
    with dl2:
        st.download_button("Download candidate CSV", candidates_csv, "candidate_survey_sites.csv", "text/csv", width="stretch")
    with dl3:
        st.download_button("Download transit legs CSV", transit_csv, "public_transit_legs.csv", "text/csv", width="stretch")
    with dl4:
        st.download_button("Download cost summary CSV", cost_csv, "travel_cost_summary.csv", "text/csv", width="stretch")


if __name__ == "__main__":
    main()
