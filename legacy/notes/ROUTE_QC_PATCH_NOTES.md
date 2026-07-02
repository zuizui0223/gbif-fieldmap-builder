# Route/QC patch notes

These notes summarize the remaining fixes requested after Issue #1 was partially implemented.

## Current observations from `gbif_fieldmap_builder_app.py`

- `coordinate_exclusion_panel()` still shows the caption: `Blue = included, red = excluded...`. The user wants this explanation removed.
- The existing point-click exclusion / restore behavior should not be changed right now.
- Candidate-site rectangle selection is present in `route_planner_panel()` through `folium.plugins.Draw`, but it likely does not work reliably because `streamlit-folium` may return `all_drawings` as a list, while the current code only extracts features when `all_drawings` is a dict with a `features` key.
- Survey days UI is visible, but Day 1 / Day 2 stay at `0 site(s)` because staging is not being populated from rectangle selection.
- Occurrence QC rectangle/batch selection is listed in CHANGELOG, but current `coordinate_exclusion_panel()` still appears to use only point-click selection and does not yet expose rectangle selection actions.

## Requested behavior

### 1. Remove only the explanatory caption

Remove this caption from `coordinate_exclusion_panel()`:

```python
st.caption("Blue = included, red = excluded. Click an occurrence point to toggle it. Use the row-ID box below only to recover excluded records.")
```

Do not change the existing click-based point exclusion behavior.

### 2. Add rectangle/batch selection without changing existing click behavior

Add rectangle selection as an additional method only.

#### For candidate survey sites

In manual survey-site selection:

- Keep current click-to-toggle behavior.
- Add rectangle selection so that all candidate survey sites inside the drawn rectangle are added to staging.
- Then the existing buttons `Add to Day 1`, `Add to Day 2`, etc. should move staged sites into day lists.

Implementation detail:

`streamlit-folium` may return drawn shapes in different formats. Handle both:

```python
drawings = (click_data or {}).get("all_drawings") or []
if isinstance(drawings, dict):
    features = drawings.get("features", [])
elif isinstance(drawings, list):
    features = drawings
else:
    features = []
```

Also consider adding `last_active_drawing` to returned objects:

```python
returned_objects=["last_object_clicked", "all_drawings", "last_active_drawing"]
```

and include it if `all_drawings` is empty.

#### For raw occurrence QC points

- Keep current point-click exclusion / restore behavior.
- Add a rectangle selection map action.
- Drawing a rectangle should select all raw occurrence points inside the rectangle.
- Provide buttons:
  - `Exclude rectangle-selected occurrence points`
  - `Restore rectangle-selected occurrence points`
  - `Clear rectangle selection`
- Excluded points remain red QC-only points and must not be used for SDM, prediction extent, candidate sites, or route planning.

## Minimal helper suggested

```python
def extract_drawn_features(draw_data: Any) -> list[dict[str, Any]]:
    if not draw_data:
        return []
    if isinstance(draw_data, dict):
        if draw_data.get("type") == "Feature":
            return [draw_data]
        return draw_data.get("features", []) or []
    if isinstance(draw_data, list):
        return [x for x in draw_data if isinstance(x, dict)]
    return []


def ids_inside_drawn_rectangles(df: pd.DataFrame, id_col: str, lat_col: str, lon_col: str, features: list[dict[str, Any]]) -> list[int]:
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
```

Use this helper for both candidate survey sites and raw occurrence QC points.

## Required after editing

- Update `CHANGELOG_AI.md`.
- Run:

```bash
python -m py_compile gbif_fieldmap_builder_app.py
```

- Preserve all existing features listed in `AGENTS.md`.
