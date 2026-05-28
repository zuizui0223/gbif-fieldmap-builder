"""
GBIF FieldMap Builder

Streamlit app for building interactive field-survey planning maps from
GBIF occurrence CSV files or directly from a scientific name via the GBIF API.
"""

from __future__ import annotations

import math
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

LAT_CANDIDATES = [
    "decimallatitude",
    "decimal_latitude",
    "decimal latitude",
    "latitude",
    "lat",
    "y",
    "緯度",
]
LON_CANDIDATES = [
    "decimallongitude",
    "decimal_longitude",
    "decimal longitude",
    "longitude",
    "lon",
    "lng",
    "long",
    "x",
    "経度",
]
DATE_CANDIDATES = [
    "eventdate",
    "event_date",
    "event date",
    "date",
    "observedon",
    "observed_on",
    "observationdate",
    "観察日",
    "日付",
]
YEAR_CANDIDATES = ["year", "eventyear", "event_year", "observationyear", "年"]
SPECIES_CANDIDATES = [
    "species",
    "scientificname",
    "scientific_name",
    "scientific name",
    "taxonname",
    "acceptedscientificname",
    "verbatimscientificname",
    "種名",
]


@dataclass(frozen=True)
class ColumnDetection:
    latitude: str
    longitude: str
    event_date: Optional[str] = None
    year: Optional[str] = None
    species: Optional[str] = None


@dataclass(frozen=True)
class GBIFTaxonMatch:
    input_name: str
    usage_key: Optional[int]
    matched_name: str = ""
    rank: str = ""
    status: str = ""
    confidence: Optional[int] = None


def normalize_name(name: str) -> str:
    return "".join(ch for ch in str(name).lower() if ch.isalnum() or "\u3040" <= ch <= "\u9fff")


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
            "Latitude/longitude columns could not be detected. Use columns such as "
            "decimalLatitude and decimalLongitude, or latitude and longitude."
        )
    return ColumnDetection(
        latitude=lat,
        longitude=lon,
        event_date=detect_column(cols, DATE_CANDIDATES),
        year=detect_column(cols, YEAR_CANDIDATES),
        species=detect_column(cols, SPECIES_CANDIDATES),
    )


def clean_occurrences(df: pd.DataFrame, cols: ColumnDetection) -> pd.DataFrame:
    out = df.copy()
    out[cols.latitude] = pd.to_numeric(out[cols.latitude], errors="coerce")
    out[cols.longitude] = pd.to_numeric(out[cols.longitude], errors="coerce")
    out = out.dropna(subset=[cols.latitude, cols.longitude]).copy()
    out = out[
        out[cols.latitude].between(-90, 90) & out[cols.longitude].between(-180, 180)
    ].copy()

    out = out.rename(columns={cols.latitude: "_latitude", cols.longitude: "_longitude"})

    if cols.event_date and cols.event_date in out.columns:
        out["_event_date"] = out[cols.event_date].astype(str).replace({"nan": ""})
    else:
        out["_event_date"] = ""

    if cols.species and cols.species in out.columns:
        out["_species"] = out[cols.species].astype(str).replace({"nan": ""})
    else:
        out["_species"] = ""

    if cols.year and cols.year in out.columns:
        out["_year"] = pd.to_numeric(out[cols.year], errors="coerce")
    else:
        out["_year"] = pd.to_datetime(out["_event_date"], errors="coerce").dt.year

    return out.reset_index(drop=True)


def match_gbif_taxon(scientific_name: str, timeout_s: int = 30) -> GBIFTaxonMatch:
    if not scientific_name.strip():
        raise ValueError("Scientific name is empty.")
    response = requests.get(
        GBIF_SPECIES_MATCH_URL,
        params={"name": scientific_name.strip()},
        timeout=timeout_s,
    )
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
        rows.append(
            {
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
            }
        )
    return pd.DataFrame(rows)


def fetch_gbif_occurrences(
    scientific_name: str,
    max_records: int = 5000,
    country_code: str = "",
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
) -> tuple[GBIFTaxonMatch, pd.DataFrame]:
    match = match_gbif_taxon(scientific_name)
    if match.usage_key is None:
        raise ValueError(f"GBIF could not match this scientific name: {scientific_name}")

    limit_per_request = 300
    offset = 0
    records: list[dict[str, Any]] = []
    params_base: dict[str, Any] = {
        "taxonKey": match.usage_key,
        "hasCoordinate": "true",
        "hasGeospatialIssue": "false",
        "limit": limit_per_request,
    }
    if country_code.strip():
        params_base["country"] = country_code.strip().upper()
    if year_from is not None and year_to is not None:
        params_base["year"] = f"{int(year_from)},{int(year_to)}"
    elif year_from is not None:
        params_base["year"] = f"{int(year_from)},"
    elif year_to is not None:
        params_base["year"] = f",{int(year_to)}"

    while len(records) < max_records:
        params = dict(params_base)
        params["offset"] = offset
        params["limit"] = min(limit_per_request, max_records - len(records))
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


def haversine_dbscan(df: pd.DataFrame, threshold_m: float, min_samples: int) -> pd.Series:
    if df.empty:
        return pd.Series(dtype=int, name="cluster_id")
    if threshold_m <= 0:
        raise ValueError("DBSCAN threshold must be greater than 0 m.")
    if min_samples < 1:
        raise ValueError("Minimum occurrences per cluster must be at least 1.")

    coords_rad = [
        [math.radians(lat), math.radians(lon)]
        for lat, lon in df[["_latitude", "_longitude"]].to_numpy(dtype=float)
    ]
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


def make_candidate_sites(df: pd.DataFrame) -> pd.DataFrame:
    output_columns = [
        "site_id",
        "cluster_id",
        "latitude",
        "longitude",
        "n_occurrences",
        "species_summary",
        "year_min",
        "year_max",
    ]
    clustered = df[df["cluster_id"] >= 0].copy()
    if clustered.empty:
        return pd.DataFrame(columns=output_columns)

    sites = []
    for site_id, (cluster_id, group) in enumerate(clustered.groupby("cluster_id", sort=True), start=1):
        points = [
            Point(float(row["_longitude"]), float(row["_latitude"]))
            for _, row in group.iterrows()
        ]
        centroid = MultiPoint(points).centroid
        years = pd.to_numeric(group.get("_year"), errors="coerce").dropna()
        sites.append(
            {
                "site_id": site_id,
                "cluster_id": int(cluster_id),
                "latitude": float(centroid.y),
                "longitude": float(centroid.x),
                "n_occurrences": int(len(group)),
                "species_summary": summarize_species(group.get("_species", pd.Series(dtype=str))),
                "year_min": int(years.min()) if not years.empty else None,
                "year_max": int(years.max()) if not years.empty else None,
            }
        )
    return pd.DataFrame(sites, columns=output_columns)


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
        distances = remaining.apply(
            lambda row: geodesic(current_xy, (float(row["latitude"]), float(row["longitude"]))).km,
            axis=1,
        )
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
        raise ValueError(f"Unknown route order mode: {mode}")
    ordered = ordered.reset_index(drop=True)
    ordered["route_order"] = range(1, len(ordered) + 1)
    return ordered


def make_google_maps_point_url(latitude: float, longitude: float) -> str:
    return f"https://www.google.com/maps/search/?api=1&query={latitude:.6f}%2C{longitude:.6f}"


def make_google_maps_route_url(sites: pd.DataFrame, max_waypoints: int = 8) -> str:
    if sites.empty:
        return ""
    ordered = sites.sort_values("route_order") if "route_order" in sites.columns else sites.copy()
    coords = [(float(row["latitude"]), float(row["longitude"])) for _, row in ordered.iterrows()]
    if len(coords) == 1:
        return make_google_maps_point_url(coords[0][0], coords[0][1])
    origin = f"{coords[0][0]:.6f},{coords[0][1]:.6f}"
    destination = f"{coords[-1][0]:.6f},{coords[-1][1]:.6f}"
    waypoint_coords = coords[1:-1][:max_waypoints]
    params = {
        "api": "1",
        "origin": origin,
        "destination": destination,
        "travelmode": "driving",
    }
    if waypoint_coords:
        params["waypoints"] = "|".join(f"{lat:.6f},{lon:.6f}" for lat, lon in waypoint_coords)
    return "https://www.google.com/maps/dir/?" + urllib.parse.urlencode(params, safe=",|")


def add_navigation_columns(sites: pd.DataFrame) -> pd.DataFrame:
    out = sites.copy()
    if out.empty:
        out["google_maps_point_url"] = []
        out["next_site_straight_km"] = []
        return out
    out = out.sort_values("route_order").reset_index(drop=True) if "route_order" in out.columns else out
    out["google_maps_point_url"] = out.apply(
        lambda row: make_google_maps_point_url(float(row["latitude"]), float(row["longitude"])),
        axis=1,
    )
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


def fit_bounds_or_default(df: pd.DataFrame) -> tuple[list[list[float]], tuple[float, float], int]:
    if df.empty:
        return [[35.0, 135.0], [36.0, 136.0]], (35.5, 135.5), 6
    min_lat, max_lat = df["_latitude"].min(), df["_latitude"].max()
    min_lon, max_lon = df["_longitude"].min(), df["_longitude"].max()
    return [[min_lat, min_lon], [max_lat, max_lon]], ((min_lat + max_lat) / 2, (min_lon + max_lon) / 2), 8


def popup_html_occurrence(row: pd.Series) -> str:
    return f"""
    <b>Occurrence</b><br>
    Latitude: {row['_latitude']:.6f}<br>
    Longitude: {row['_longitude']:.6f}<br>
    Cluster: {row.get('cluster_id', '')}<br>
    Species: {row.get('_species', '')}<br>
    Event date: {row.get('_event_date', '')}
    """


def popup_html_site(row: pd.Series) -> str:
    point_url = row.get("google_maps_point_url", "")
    nav = f"<br><a href='{point_url}' target='_blank'>Open this site in Google Maps</a>" if point_url else ""
    years = ""
    if pd.notna(row.get("year_min")) and pd.notna(row.get("year_max")):
        years = f"<br>Years: {int(row['year_min'])}–{int(row['year_max'])}"
    return f"""
    <b>Candidate site {int(row['site_id'])}</b><br>
    Route order: {int(row.get('route_order', row['site_id']))}<br>
    Cluster: {int(row['cluster_id'])}<br>
    Occurrences: {int(row['n_occurrences'])}<br>
    Latitude: {row['latitude']:.6f}<br>
    Longitude: {row['longitude']:.6f}<br>
    Species: {row.get('species_summary', '') or 'Not detected'}
    {years}
    {nav}
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
                popup=folium.Popup(popup_html_occurrence(row), max_width=300),
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
        group = FeatureGroup(name="Distance labels", show=True)
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
                        "<div style='font-size: 12px; font-weight: 700; background: white; "
                        "border: 1px solid #999; border-radius: 4px; padding: 2px 5px; white-space: nowrap;'>"
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
                popup=folium.Popup(popup_html_site(row), max_width=360),
                tooltip=f"Site {int(row['site_id'])} / Order {order}",
                icon=folium.DivIcon(
                    html="<div style='font-size: 22px; line-height: 22px; color: red; text-shadow: 0 0 2px white, 0 0 4px white;'>★</div>"
                ),
            ).add_to(group)
            folium.Marker(
                location=(row["latitude"], row["longitude"]),
                icon=folium.DivIcon(
                    html=(
                        "<div style='font-size: 11px; font-weight: 700; background: white; "
                        "border: 1px solid #c00; border-radius: 10px; padding: 1px 5px; margin-left: 14px;'>"
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


def load_input_dataframe_from_ui() -> tuple[Optional[pd.DataFrame], str]:
    mode = st.sidebar.radio("Input source", ["Upload CSV", "Search GBIF by scientific name"], index=0)
    if mode == "Upload CSV":
        uploaded = st.sidebar.file_uploader("Upload GBIF occurrence CSV", type=["csv"])
        if uploaded is None:
            return None, "Upload a GBIF occurrence CSV to start."
        return read_uploaded_csv(uploaded), "Loaded from uploaded CSV."

    scientific_name = st.sidebar.text_input("Scientific name", value="", placeholder="e.g. Campanula punctata")
    country_code = st.sidebar.text_input("Country code filter optional", value="JP", max_chars=2)
    max_records = st.sidebar.number_input("Maximum GBIF records", min_value=100, max_value=100_000, value=5000, step=500)
    use_year_filter = st.sidebar.checkbox("Filter by year", value=False)
    year_from: Optional[int] = None
    year_to: Optional[int] = None
    if use_year_filter:
        c1, c2 = st.sidebar.columns(2)
        with c1:
            year_from = int(st.number_input("From", min_value=1600, max_value=2100, value=2000, step=1))
        with c2:
            year_to = int(st.number_input("To", min_value=1600, max_value=2100, value=2026, step=1))

    if not st.sidebar.button("Fetch occurrences from GBIF", type="primary"):
        return None, "Enter a scientific name and click Fetch occurrences from GBIF."
    if not scientific_name.strip():
        return None, "Scientific name is empty."

    with st.spinner("Fetching GBIF occurrences..."):
        match, df = fetch_gbif_occurrences(
            scientific_name=scientific_name,
            max_records=int(max_records),
            country_code=country_code,
            year_from=year_from,
            year_to=year_to,
        )
    message = (
        f"GBIF match: {match.matched_name or match.input_name} / usageKey={match.usage_key} "
        f"/ confidence={match.confidence}. Fetched {len(df):,} raw occurrence records."
    )
    return df, message


def main() -> None:
    st.set_page_config(page_title=APP_TITLE, page_icon="🗺️", layout="wide")
    st.title("🗺️ GBIF FieldMap Builder")
    st.caption("Build field survey candidate sites from uploaded CSV files or scientific-name GBIF searches.")

    st.sidebar.header("Data source")
    try:
        raw_df, source_message = load_input_dataframe_from_ui()
    except Exception as exc:
        st.error(f"Could not load occurrence data: {exc}")
        return

    st.sidebar.divider()
    st.sidebar.subheader("Survey settings")
    buffer_radius_m = st.sidebar.number_input("Buffer radius around occurrences (m)", 0, 100_000, 500, 100)
    dbscan_threshold_m = st.sidebar.number_input("DBSCAN cluster distance threshold (m)", 1, 500_000, 2000, 500)
    min_samples = st.sidebar.number_input("Minimum occurrences per cluster", 1, 50, 1, 1)
    route_order_mode = st.sidebar.selectbox(
        "Candidate site order",
        ["Cluster ID", "Nearest-neighbor route", "North → South", "South → North", "West → East", "East → West"],
        index=1,
    )

    st.sidebar.divider()
    st.sidebar.subheader("Layers")
    show_occurrences = st.sidebar.checkbox("Occurrences", value=True)
    show_buffers = st.sidebar.checkbox("Buffers", value=True)
    show_clusters = st.sidebar.checkbox("Clusters", value=False)
    show_candidate_sites = st.sidebar.checkbox("Candidate survey sites", value=True)
    show_routes = st.sidebar.checkbox("Routes", value=True)
    show_distance_labels = st.sidebar.checkbox("Distance labels", value=True)

    if raw_df is None:
        st.info(source_message)
        st.markdown(
            """
            **Two ways to start:**
            1. Upload a GBIF occurrence CSV.
            2. Enter a scientific name and fetch occurrences directly from GBIF.
            """
        )
        return

    st.success(source_message)

    try:
        detected = detect_columns(raw_df)
        occ = clean_occurrences(raw_df, detected)
    except Exception as exc:
        st.error(str(exc))
        return

    if occ.empty:
        st.error("No valid coordinate records were found after cleaning.")
        return
    if len(occ) > 20_000:
        st.warning("This dataset has more than 20,000 valid occurrences. The map may become slow.")

    try:
        occ["cluster_id"] = haversine_dbscan(occ, float(dbscan_threshold_m), int(min_samples))
    except Exception as exc:
        st.error(f"Clustering failed: {exc}")
        return

    candidate_sites = make_candidate_sites(occ)
    ordered_sites = add_navigation_columns(order_sites(candidate_sites, route_order_mode))
    route_url = make_google_maps_route_url(ordered_sites)

    clustered_mask = occ["cluster_id"] >= 0
    total_clusters = int(occ.loc[clustered_mask, "cluster_id"].nunique()) if clustered_mask.any() else 0
    noise_points = int((occ["cluster_id"] < 0).sum())

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Valid occurrences", f"{len(occ):,}")
    col2.metric("Clusters", f"{total_clusters:,}")
    col3.metric("Candidate sites", f"{len(ordered_sites):,}")
    col4.metric("Noise points", f"{noise_points:,}")

    if route_url:
        st.link_button("Open candidate route in Google Maps", route_url, width="content")
        st.caption("Distance labels are straight-line distances. Google Maps handles real-world route planning.")

    with st.expander("Detected columns", expanded=False):
        st.write(
            {
                "latitude": detected.latitude,
                "longitude": detected.longitude,
                "event_date": detected.event_date,
                "year": detected.year,
                "species": detected.species,
            }
        )

    fmap = build_map(
        occ,
        ordered_sites,
        float(buffer_radius_m),
        show_occurrences,
        show_buffers,
        show_clusters,
        show_candidate_sites,
        show_routes,
        show_distance_labels,
    )
    st_folium(fmap, width=None, height=720, returned_objects=[])

    st.subheader("Candidate survey sites")
    if ordered_sites.empty:
        st.warning("No candidate sites were generated. Try changing DBSCAN settings.")
    else:
        display_cols = [
            "route_order",
            "site_id",
            "cluster_id",
            "latitude",
            "longitude",
            "n_occurrences",
            "next_site_straight_km",
            "species_summary",
            "year_min",
            "year_max",
            "google_maps_point_url",
        ]
        st.dataframe(ordered_sites[display_cols], width="stretch", hide_index=True)

    html_bytes = fmap.get_root().render().encode("utf-8")
    csv_bytes = ordered_sites.to_csv(index=False).encode("utf-8-sig")
    dl1, dl2 = st.columns(2)
    with dl1:
        st.download_button("Download standalone HTML map", html_bytes, "gbif_fieldmap.html", "text/html", width="stretch")
    with dl2:
        st.download_button("Download candidate sites CSV", csv_bytes, "candidate_survey_sites.csv", "text/csv", width="stretch")


if __name__ == "__main__":
    main()
