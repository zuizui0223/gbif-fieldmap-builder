import unittest
from unittest.mock import patch, sentinel

import numpy as np
import pandas as pd
from rasterio.errors import RasterioIOError
from acsp import aggregate_candidates_to_zones
from acsp_discover import build_acsp_discover_plans, infer_survey_protocol

from gbif_fieldmap_builder_app import (
    add_priority_rank,
    add_sdm_grid_support_to_candidates,
    build_automatic_discover_bundle,
    build_automatic_genus_bundle,
    build_default_short_trip_plans,
    build_map,
    candidate_points_in_zones,
    correlation_filter_variables,
    decode_gsi_dem_rgb,
    estimate_default_short_trip,
    get_worldclim_raster_path,
    ids_inside_drawn_rectangles,
    _power_query_bounds,
    attach_power_bioclim,
    make_sdm_exploration_candidates,
    make_ssdm_exploration_candidates,
    model_connected_recommendations,
    open_raster_with_retry,
    simple_recommended_candidates,
    select_automatic_trip_scale,
)


class AutomaticHierarchyTests(unittest.TestCase):
    def test_polygon_selection_does_not_use_only_its_bounding_box(self):
        records = pd.DataFrame({
            "_row_id": [1, 2], "_latitude": [0.25, 0.75], "_longitude": [0.25, 0.75],
        })
        triangle = [{
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [0, 1], [0, 0]]]},
            "properties": {},
        }]
        self.assertEqual(ids_inside_drawn_rectangles(records, "_row_id", "_latitude", "_longitude", triangle), [1])

    def test_zone_member_points_remain_available_for_mapping(self):
        zones = pd.DataFrame({
            "zone_id": ["1-Z001"], "recommended_zone_rank": [1],
            "representative_site_id": [2], "zone_member_site_ids": ["1;2"],
        })
        candidates = pd.DataFrame({
            "site_id": [1, 2, 3], "latitude": [35.0, 35.01, 36.0], "longitude": [139.0, 139.01, 140.0],
        })
        points = candidate_points_in_zones(zones, candidates)
        self.assertEqual(points["site_id"].tolist(), [1, 2])
        self.assertEqual(points.loc[points["is_zone_representative"], "site_id"].tolist(), [2])

    def test_multi_island_days_never_mix_survey_areas(self):
        plan = pd.DataFrame({
            "site_id": [1, 2, 3, 4],
            "survey_area_id": [1, 2, 3, 4],
            "latitude": [34.72, 34.52, 34.38, 34.21],
            "longitude": [139.40, 139.28, 139.26, 139.14],
        })
        estimate = estimate_default_short_trip(
            plan, 34.72, 139.40,
            infer_survey_protocol({"kingdom": "Plantae"}).as_dict(), target_days=4,
        )
        self.assertEqual(estimate["estimated_days"], 4)
        self.assertTrue(estimate["fits_target_days"])
        self.assertEqual(estimate["inter_area_transfers"], 3)
        self.assertTrue(all(len(day["site_ids"]) == 1 for day in estimate["day_schedules"]))
        self.assertEqual(len({day["survey_area_id"] for day in estimate["day_schedules"]}), 4)

    def test_marine_trip_uses_water_transport_caution_not_road_claim(self):
        plan = pd.DataFrame({
            "site_id": [1], "survey_area_id": [1],
            "latitude": [34.5], "longitude": [139.5],
        })
        protocol = infer_survey_protocol({"kingdom": "Animalia", "class": "Reptilia"}).as_dict()
        protocol["surface_domain"] = "marine"
        estimate = estimate_default_short_trip(plan, 34.4, 139.4, protocol, target_days=1)
        self.assertEqual(estimate["transport_mode"], "small-vessel proxy")
        self.assertIn("launch site", estimate["routing_confidence"])
        self.assertIn("estimated_transit_km", estimate["day_schedules"][0])

    def test_plan_covers_each_survey_area_before_adding_duplicates(self):
        candidates = pd.DataFrame({
            "site_id": [1, 2, 3, 4, 5],
            "survey_area_id": [1, 2, 3, 4, 1],
            "candidate_type": ["Habitat-match"] * 5,
            "priority_score": [1.0, 0.8, 0.7, 0.6, 0.99],
            "analogue_score": [0.8] * 5, "access_score": [0.8] * 5,
            "latitude": [34.72, 34.52, 34.38, 34.21, 34.721],
            "longitude": [139.40, 139.28, 139.26, 139.14, 139.401],
        })
        plan = build_acsp_discover_plans(candidates, 4)["Balanced"]
        self.assertEqual(set(plan["survey_area_id"].astype(int)), {1, 2, 3, 4})

    def test_route_insertion_cost_is_recorded_between_candidates(self):
        candidates = pd.DataFrame({
            "site_id": [1, 2, 3],
            "candidate_type": ["Habitat-match"] * 3,
            "priority_score": [0.9, 0.8, 0.7],
            "analogue_score": [0.9, 0.8, 0.7], "access_score": [0.8] * 3,
            "latitude": [35.01, 35.02, 35.30], "longitude": [139.0] * 3,
        })
        plan = build_acsp_discover_plans(candidates, 3, 35.0, 139.0)["Balanced"]
        self.assertIn("marginal_route_km", plan.columns)
        self.assertGreater(plan.loc[plan["site_id"].eq(1), "marginal_route_km"].iloc[0], 0)
        self.assertTrue((plan["marginal_route_km"] >= 0).all())

    def test_feasibility_curve_selects_trip_scale_automatically(self):
        candidates = pd.DataFrame({
            "site_id": range(1, 9),
            "candidate_type": ["Occurrence-supported survey range", "Habitat-match"] * 4,
            "priority_score": [0.95 - i * 0.05 for i in range(8)],
            "analogue_score": [0.8] * 8, "access_score": [0.8] * 8,
            "latitude": [35.0 + i * 0.035 for i in range(8)],
            "longitude": [139.0 + (i % 2) * 0.02 for i in range(8)],
        })
        zones = aggregate_candidates_to_zones(candidates, merge_distance_m=1000)
        decision = select_automatic_trip_scale(
            candidates, zones, 35.0, 139.0,
            infer_survey_protocol({"kingdom": "Plantae"}).as_dict(),
        )
        self.assertIn(decision["selected_days"], range(1, 6))
        self.assertEqual(len(decision["curve"]), 5)
        self.assertTrue(decision["trip_estimate"]["fits_target_days"])
        self.assertIn("feasibility-curve knee", decision["reason"])
        self.assertIn("five-day evidence value", decision["reason"])

    def test_power_query_expands_small_survey_extent(self):
        west, south, east, north = _power_query_bounds((139.1, 34.1, 139.3, 34.3))
        self.assertGreaterEqual(east - west, 2.0)
        self.assertGreaterEqual(north - south, 2.0)

    def test_power_climate_is_interpolated_to_requested_points(self):
        climate = pd.DataFrame({
            "latitude": [34.0, 34.0, 35.0, 35.0],
            "longitude": [139.0, 140.0, 139.0, 140.0],
            "bio1": [10.0, 12.0, 14.0, 16.0],
            "bio4": [100.0, 120.0, 140.0, 160.0],
            "bio12": [1000.0, 1200.0, 1400.0, 1600.0],
            "bio14": [10.0, 12.0, 14.0, 16.0],
            "bio15": [20.0, 22.0, 24.0, 26.0],
        })
        points = pd.DataFrame({"latitude": [34.0, 34.5], "longitude": [139.0, 139.5]})
        with patch("gbif_fieldmap_builder_app.load_power_bioclim_grid", return_value=climate):
            result = attach_power_bioclim(points, ["bio1", "bio12"], "latitude", "longitude")
        self.assertAlmostEqual(result.loc[0, "bio1"], 10.0, places=5)
        self.assertAlmostEqual(result.loc[1, "bio1"], 13.0, places=1)
        self.assertTrue(np.isfinite(result[["bio1", "bio12"]].to_numpy()).all())

    def test_completed_sdm_grid_supplies_candidates_without_raster_reopen(self):
        candidates = pd.DataFrame({
            "site_id": [1, 2], "latitude": [35.001, 35.099], "longitude": [139.001, 139.099],
        })
        prediction = pd.DataFrame({
            "latitude": [35.0, 35.1], "longitude": [139.0, 139.1], "sdm_suitability": [0.2, 0.9],
        })
        supported = add_sdm_grid_support_to_candidates(candidates, prediction)
        self.assertEqual(supported["sdm_suitability"].tolist(), [0.2, 0.9])
        self.assertEqual(supported["model_support_score"].tolist(), [0.2, 0.9])

    def test_joint_observed_and_model_support_receives_agreement_bonus(self):
        candidates = pd.DataFrame({
            "site_id": [1, 2],
            "candidate_type": ["Occurrence-supported survey range"] * 2,
            "occurrence_support_score": [0.80, 0.80],
            "sdm_suitability": [0.90, 0.20],
        })
        ranked = add_priority_rank(candidates)
        high = ranked.set_index("site_id").loc[1]
        low = ranked.set_index("site_id").loc[2]
        self.assertGreater(high["priority_score"], low["priority_score"])
        self.assertGreater(high["observed_model_agreement_score"], low["observed_model_agreement_score"])
        self.assertEqual(high["candidate_evidence"], "Cross-scale consensus")
        reranked = add_priority_rank(ranked)
        self.assertEqual(ranked.sort_values("site_id")["priority_score"].tolist(), reranked.sort_values("site_id")["priority_score"].tolist())

    def test_model_connected_recommendations_reserve_exploration_slot(self):
        candidates = pd.DataFrame({
            "site_id": [1, 2, 3, 4],
            "candidate_type": ["Occurrence-supported survey range"] * 3 + ["SDM-high model-only exploratory site"],
            "priority_score": [0.90, 0.80, 0.70, 0.40],
            "observed_model_agreement_score": [0.9, 0.8, 0.7, 0.0],
            "model_support_score": [0.9, 0.8, 0.7, 0.99],
            "occurrence_support_score": [0.9, 0.8, 0.7, 0.0],
        })
        selected = model_connected_recommendations(candidates, default_total=3)
        self.assertEqual(len(selected), 3)
        self.assertIn(4, selected["site_id"].tolist())
        self.assertIn("Model-only high prediction", selected.loc[selected["site_id"].eq(4), "recommendation_basis"].iloc[0])

    def test_sdm_exploration_cells_are_spatially_separated(self):
        prediction = pd.DataFrame({
            "latitude": [35.00, 35.01, 35.04, 35.08],
            "longitude": [139.00, 139.01, 139.04, 139.08],
            "sdm_suitability": [0.99, 0.98, 0.97, 0.96],
        })
        known = pd.DataFrame({"_latitude": [34.8], "_longitude": [138.8]})
        observed = pd.DataFrame({"latitude": [34.81], "longitude": [138.81]})
        exploratory = make_sdm_exploration_candidates(
            prediction, known, observed, 0.5, 0.0, 1000.0, 3000.0, 10, 100,
        )
        self.assertGreaterEqual(len(exploratory), 3)
        self.assertTrue(exploratory["candidate_type"].str.contains("model-only").all())

    def test_ssdm_exploration_uses_full_grid_and_avoids_observed_hotspot(self):
        grid = pd.DataFrame({
            "latitude": [35.00, 35.01, 35.05, 35.10, 35.15] * 2,
            "longitude": [139.00, 139.01, 139.05, 139.10, 139.15] * 2,
            "ssdm_continuous_richness": np.linspace(2.0, 4.0, 10),
            "n_species_evaluated": [3] * 10,
        })
        observed = pd.DataFrame({"latitude": [34.8], "longitude": [138.8]})
        exploratory = make_ssdm_exploration_candidates(grid, observed, max_candidates=4)
        self.assertFalse(exploratory.empty)
        self.assertTrue(exploratory["candidate_type"].str.contains("model-only").all())

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
            "candidate_type": ["Occurrence-supported survey range", "SDM-high model-only exploratory site", "Habitat-match"],
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
        self.assertIn("Observed / local candidate points", html)
        self.assertIn("Model-only exploratory points", html)
        self.assertIn("Recommended 500 m survey ranges", html)

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
            patch("gbif_fieldmap_builder_app.land_fraction", return_value=1.0),
            patch("gbif_fieldmap_builder_app.filter_to_surface_domain", side_effect=lambda frame, *args, **kwargs: frame) as surface_filter,
        ):
            bundle = build_automatic_discover_bundle(
                "Example species", occurrences, "synthetic records", "Test"
            )
        self.assertEqual(bundle["distribution_summary"]["distribution_regime"], "narrow/local")
        self.assertEqual(len(bundle["region_cards"]), 1)
        self.assertLessEqual(bundle["trip_estimate"]["estimated_days"], 5)
        self.assertEqual(bundle["target_days"], bundle["trip_estimate"]["estimated_days"])
        self.assertEqual(len(bundle["reachability_curve"]), 5)
        self.assertIn("candidate_pool", bundle)
        self.assertIn("zones", bundle)
        self.assertNotIn("candidate_pool_without_sdm", bundle)
        self.assertNotIn("zones_without_sdm", bundle)
        self.assertIn("integrated_support_score", bundle["candidate_pool"].columns)
        self.assertTrue(bundle["warnings"])
        self.assertEqual(surface_filter.call_args.args[1], "terrestrial")

        with (
            patch("gbif_fieldmap_builder_app.app_provided_habitat_layers", return_value={}),
            patch("gbif_fieldmap_builder_app.make_potential_survey_site_candidates", return_value=pd.DataFrame()),
            patch("gbif_fieldmap_builder_app.land_fraction", return_value=1.0),
            patch("gbif_fieldmap_builder_app.filter_to_surface_domain", side_effect=lambda frame, *args, **kwargs: frame),
        ):
            custom = build_automatic_discover_bundle(
                "Example species", occurrences, "synthetic records", "Test",
                override_row_ids=occurrences["_row_id"].tolist(),
                survey_bounds=(138.9, 34.9, 139.5, 35.1),
            )
        self.assertIn(custom["target_days"], range(1, 6))
        self.assertEqual(custom["target_days"], custom["trip_estimate"]["estimated_days"])
        self.assertEqual(custom["trip_estimate"]["target_days"], custom["target_days"])

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
