import unittest
from unittest.mock import patch, sentinel

import numpy as np
import pandas as pd
from rasterio.errors import RasterioIOError

from gbif_fieldmap_builder_app import (
    build_automatic_discover_bundle,
    build_automatic_genus_bundle,
    build_default_short_trip_plans,
    build_map,
    correlation_filter_variables,
    decode_gsi_dem_rgb,
    estimate_default_short_trip,
    get_worldclim_raster_path,
    open_raster_with_retry,
    simple_recommended_candidates,
)


class AutomaticHierarchyTests(unittest.TestCase):
    def test_correlation_filter_works_with_read_only_pandas_arrays(self):
        environment = pd.DataFrame({
            "bio1": [1.0, 2.0, 3.0, 4.0],
            "bio12": [1.0, 2.1, 2.9, 4.2],
            "bio15": [4.0, 1.0, 3.0, 2.0],
        })
        with pd.option_context("mode.copy_on_write", True):
            kept, _ = correlation_filter_variables(environment, list(environment.columns), 0.8)
        self.assertGreaterEqual(len(kept), 1)

    def test_automatic_result_map_buffers_only_recommended_sites(self):
        occurrences = pd.DataFrame({"_latitude": [35.0], "_longitude": [139.0]})
        sites = pd.DataFrame({
            "site_id": [1, 2, 3],
            "latitude": [35.0, 35.01, 35.02],
            "longitude": [139.0, 139.01, 139.02],
            "candidate_type": ["Habitat-match"] * 3,
            "priority_score": [0.9, 0.8, 0.7],
        })
        fmap = build_map(
            occurrences, sites, None, None, 0.0, 500.0,
            {"predict": False, "occ": False, "candidate_circles": True},
            False, selected_ids=(2,), range_ids=(2,),
        )
        html = fmap.get_root().render()
        self.assertEqual(html.count("L.circle("), 1)
        self.assertGreaterEqual(html.count("L.circleMarker("), 4)

    def test_remote_raster_open_retries_transient_failures(self):
        with (
            patch(
                "gbif_fieldmap_builder_app.rasterio.open",
                side_effect=[RasterioIOError("first"), RasterioIOError("second"), sentinel.dataset],
            ) as mocked,
            patch("gbif_fieldmap_builder_app.time.sleep"),
        ):
            opened = open_raster_with_retry("https://example.test/a.tif")
        self.assertIs(opened, sentinel.dataset)
        self.assertEqual(mocked.call_count, 3)

    def test_automatic_climate_uses_remote_30_second_cog(self):
        path = get_worldclim_raster_path("bio12", "30s-cog")
        self.assertIn("CHELSA_bio12_1981-2010_V.2.1.tif", path)
        self.assertTrue(path.startswith("https://"))

    def test_simple_recommendations_keep_three_per_drawn_area(self):
        candidates = pd.DataFrame({
            "site_id": range(1, 17),
            "survey_area_id": np.repeat([1, 2, 3, 4], 4),
            "priority_score": np.tile([0.9, 0.8, 0.7, 0.6], 4),
        })
        selected = simple_recommended_candidates(candidates)
        self.assertEqual(len(selected), 12)
        self.assertEqual(selected.groupby("survey_area_id").size().to_dict(), {1: 3, 2: 3, 3: 3, 4: 3})

    def test_gsi_rgb_elevation_decode(self):
        rgb = np.array([[[0, 128, 255]], [[0, 0, 255]], [[100, 0, 156]]], dtype=np.uint8)
        decoded = decode_gsi_dem_rgb(rgb)
        self.assertAlmostEqual(float(decoded[0, 0]), 1.0)
        self.assertTrue(np.isnan(decoded[0, 1]))
        self.assertAlmostEqual(float(decoded[0, 2]), -1.0)

    def test_each_survey_day_returns_to_hub(self):
        plan = pd.DataFrame({
            "site_id": [1, 2],
            "latitude": [35.0, 35.0],
            "longitude": [139.35, 138.65],
        })
        protocol = {
            "protocol_id": "test", "taxon_group": "test", "daily_field_hours": 4.0,
            "search_minutes_per_cell": 30, "access_buffer_minutes_per_cell": 0,
            "minimum_repeat_visits": 1,
        }
        estimate = estimate_default_short_trip(plan, 35.0, 139.0, protocol, target_days=2)
        self.assertEqual(len(estimate["day_schedules"]), 2)
        self.assertEqual([len(day["site_ids"]) for day in estimate["day_schedules"]], [1, 1])
        self.assertTrue(estimate["fits_target_days"])
        self.assertGreater(estimate["straight_line_route_km"], 120.0)

    def test_short_trip_builder_reduces_unrealistic_eight_cell_plan(self):
        candidate_types = (
            ["Occurrence-supported survey range"] * 3
            + ["Habitat-match"] * 3
            + ["Environmental-test"] * 2
        )
        candidates = pd.DataFrame({
            "site_id": range(1, 9),
            "candidate_type": candidate_types,
            "latitude": [35.00, 35.25, 35.50, 35.05, 35.30, 35.55, 35.15, 35.45],
            "longitude": [139.00, 139.35, 139.00, 139.40, 139.05, 139.40, 139.20, 139.20],
            "analogue_score": [0.7] * 8,
            "access_score": [0.8] * 8,
            "environmental_novelty": [0.2] * 6 + [0.9] * 2,
            "survey_gap_score": [0.2] * 3 + [0.8] * 3 + [0.4] * 2,
        })
        plans, estimate, requested = build_default_short_trip_plans(
            candidates, 35.275, 139.20, target_days=2, max_cells=8
        )
        self.assertEqual(requested, 8)
        self.assertLess(len(plans["Balanced"]), requested)
        self.assertLessEqual(estimate["estimated_days"], 2)
        self.assertGreater(estimate["estimated_road_km"], 0)

    def test_automatic_bundle_uses_region_hierarchy_without_network(self):
        points = []
        for cluster in range(8):
            base_lon = 139.0 + cluster * 0.045
            points.extend([(35.0, base_lon), (35.0005, base_lon + 0.0005)])
        occurrences = pd.DataFrame({
            "_row_id": range(len(points)),
            "_latitude": [point[0] for point in points],
            "_longitude": [point[1] for point in points],
            "_event_date": ["2024-05-01"] * len(points),
            "_year": [2024] * len(points),
            "_species": ["Example species"] * len(points),
            "_media_url": [""] * len(points),
            "_gbif_id": [str(i) for i in range(len(points))],
            "_locality": ["Example area"] * len(points),
            "_coordinate_uncertainty_m": [30.0] * len(points),
        })
        with (
            patch("gbif_fieldmap_builder_app.app_provided_habitat_layers", return_value={}),
            patch("gbif_fieldmap_builder_app.make_potential_survey_site_candidates", return_value=pd.DataFrame()),
            patch("gbif_fieldmap_builder_app.filter_to_land", side_effect=lambda frame, *args, **kwargs: frame) as land_filter,
        ):
            bundle = build_automatic_discover_bundle(
                "Example species", occurrences, "synthetic records", "Test"
            )
        self.assertEqual(bundle["distribution_summary"]["distribution_regime"], "narrow/local")
        self.assertEqual(len(bundle["region_cards"]), 1)
        self.assertLessEqual(bundle["trip_estimate"]["estimated_days"], 2)
        self.assertTrue(bundle["warnings"])
        self.assertEqual(float(land_filter.call_args.args[3]), 0.0)

        with (
            patch("gbif_fieldmap_builder_app.app_provided_habitat_layers", return_value={}),
            patch("gbif_fieldmap_builder_app.make_potential_survey_site_candidates", return_value=pd.DataFrame()),
            patch("gbif_fieldmap_builder_app.filter_to_land", side_effect=lambda frame, *args, **kwargs: frame),
        ):
            custom = build_automatic_discover_bundle(
                "Example species", occurrences, "synthetic records", "Test",
                override_row_ids=occurrences["_row_id"].tolist(),
                survey_bounds=(138.9, 34.9, 139.5, 35.1),
            )
        self.assertEqual(custom["target_days"], 1)
        self.assertEqual(custom["trip_estimate"]["target_days"], 1)

    def test_automatic_genus_bundle_builds_observed_richness_plans(self):
        rows = []
        for species_index, species in enumerate(["Example alpha", "Example beta", "Example gamma"]):
            for point_index in range(12):
                rows.append({
                    "_row_id": len(rows),
                    "_latitude": 35.0 + (point_index % 4) * 0.025,
                    "_longitude": 139.0 + (point_index // 4) * 0.04 + species_index * 0.002,
                    "_event_date": "2024-05-01",
                    "_year": 2024,
                    "_species": species,
                    "_media_url": "",
                    "_gbif_id": str(len(rows)),
                    "_locality": "Example area",
                    "_coordinate_uncertainty_m": 30.0,
                })
        bundle = build_automatic_genus_bundle(
            "Example", pd.DataFrame(rows), "synthetic genus records", "Test",
            override_row_ids=list(range(len(rows))),
            taxon_metadata={"rank": "GENUS"}, survey_bounds=(138.9, 34.9, 139.3, 35.2),
        )
        self.assertEqual(bundle["taxon_mode"], "genus")
        self.assertEqual(len(bundle["species_summary"]), 3)
        self.assertFalse(bundle["richness_grid"].empty)
        self.assertFalse(bundle["all_candidates"].empty)
        self.assertFalse(bundle["plans"]["Balanced"].empty)
        self.assertEqual(bundle["target_days"], 1)


if __name__ == "__main__":
    unittest.main()
