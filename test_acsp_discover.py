import unittest

import pandas as pd

from acsp_discover import (
    PLAN_ORDER,
    apply_hard_constraints,
    build_acsp_discover_plans,
    choose_candidate_resolution,
    infer_default_survey_scope,
    infer_surface_domain,
    infer_survey_protocol,
    parse_field_results,
    primary_recovery_radius_km,
    preferred_survey_window,
    recommend_survey_regions,
    score_discovery_learning,
)


class DiscoverV1Tests(unittest.TestCase):
    def test_surface_domain_combines_taxonomy_with_record_land_fraction(self):
        self.assertEqual(infer_surface_domain({"kingdom": "Plantae"}, occurrence_land_fraction=0.0), "terrestrial")
        self.assertEqual(infer_surface_domain({"kingdom": "Animalia", "class": "Aves"}, occurrence_land_fraction=0.1), "marine")
        self.assertEqual(infer_surface_domain({"kingdom": "Animalia", "class": "Reptilia"}, occurrence_land_fraction=0.5), "coastal")
        self.assertEqual(infer_surface_domain({"kingdom": "Animalia", "class": "Actinopterygii"}, occurrence_land_fraction=0.9), "inland_aquatic")
        self.assertEqual(infer_surface_domain({"kingdom": "Animalia", "class": "Mammalia"}, occurrence_land_fraction=0.9), "terrestrial")
        self.assertEqual(primary_recovery_radius_km({"kingdom": "Plantae"}), 5.0)
        self.assertEqual(primary_recovery_radius_km({"class": "Aves"}), 10.0)
        self.assertEqual(primary_recovery_radius_km({"class": "Insecta"}), 5.0)
        self.assertEqual(primary_recovery_radius_km({"class": "Reptilia"}, surface_domain="marine"), 10.0)

    def test_taxonomy_changes_protocol_without_user_parameters(self):
        plant = infer_survey_protocol({"kingdom": "Plantae", "class": "Magnoliopsida"})
        bird = infer_survey_protocol({"kingdom": "Animalia", "class": "Aves"})
        fish = infer_survey_protocol({"kingdom": "Animalia", "class": "Actinopterygii"})
        self.assertEqual(plant.taxon_group, "plant")
        self.assertEqual(bird.taxon_group, "bird")
        self.assertEqual(bird.minimum_repeat_visits, 2)
        self.assertLess(bird.daily_field_hours, plant.daily_field_hours)
        self.assertIn("aquatic distance", fish.movement_caution)

    def test_resolution_never_overstates_inputs(self):
        decision = choose_candidate_resolution(10, 25, 310, 100)
        self.assertEqual(decision.cell_size_m, 500)
        self.assertGreaterEqual(decision.cell_size_m, decision.required_resolution_m)
        self.assertIn("coordinate uncertainty", decision.reason)

    def test_hard_constraints_return_audit_and_keep_unknowns(self):
        candidates = pd.DataFrame({
            "site_id": [1, 2, 3], "latitude": [35.0, 35.1, 35.2], "longitude": [139.0, 139.1, 139.2],
            "is_land": [True, False, True], "slope": [10, 5, 55], "distance_to_road_m": [100, 100, None],
        })
        eligible, audit = apply_hard_constraints(candidates)
        self.assertEqual(eligible["site_id"].tolist(), [1])
        self.assertEqual(audit.loc[audit.site_id.eq(2), "exclusion_reason"].item(), "water")
        self.assertIn("dangerous_slope", audit.loc[audit.site_id.eq(3), "exclusion_reason"].item())

    def test_discovery_is_multiplicative_and_sdm_optional(self):
        candidates = pd.DataFrame({
            "site_id": [1, 2], "latitude": [35.0, 35.1], "longitude": [139.0, 139.1],
            "analogue_score": [0.9, 0.2], "access_score": [0.8, 0.8], "detectability": [0.5, 0.5],
            "environmental_novelty": [0.1, 0.9],
        })
        scored = score_discovery_learning(candidates)
        self.assertAlmostEqual(scored.loc[0, "discovery_value"], 0.28, places=3)
        self.assertGreater(scored.loc[0, "integrated_support_score"], scored.loc[1, "integrated_support_score"])
        self.assertGreater(scored.loc[1, "learning_value"], scored.loc[0, "learning_value"])

    def test_three_plans_share_pool_but_prioritize_differently(self):
        candidates = pd.DataFrame({
            "site_id": [1, 2, 3, 4],
            "latitude": [35.0, 35.01, 35.3, 35.6], "longitude": [139.0, 139.01, 139.3, 139.6],
            "analogue_score": [0.95, 0.85, 0.25, 0.45], "access_score": [1.0, 0.9, 0.8, 0.7],
            "detectability": [1.0, 1.0, 0.7, 0.8], "environmental_novelty": [0.05, 0.1, 1.0, 0.8],
            "survey_gap_score": [0.2, 0.3, 1.0, 0.8], "model_uncertainty": [0.0, 0.1, 1.0, 0.8],
            "candidate_type": ["Habitat-match", "Habitat-match", "Environmental-test", "Survey-gap"],
        })
        plans = build_acsp_discover_plans(candidates, k=2)
        self.assertEqual(tuple(plans), PLAN_ORDER)
        self.assertEqual(plans["Discovery"].iloc[0].site_id, 1)
        self.assertEqual(plans["Learning"].iloc[0].site_id, 3)
        self.assertTrue(all(len(plan) == 2 for plan in plans.values()))

    def test_plans_never_count_one_coordinate_as_multiple_sites(self):
        candidates = pd.DataFrame({
            "site_id": [1, 2, 3],
            "candidate_type": ["Habitat-match", "Environmental-test", "Occurrence-supported survey range"],
            "latitude": [34.33, 34.33, 34.38],
            "longitude": [139.21, 139.21, 139.26],
            "analogue_score": [0.8, 0.8, 0.5],
            "environmental_novelty": [0.9, 0.9, 0.1],
            "access_score": [0.5, 0.5, 0.5],
        })
        for plan in build_acsp_discover_plans(candidates, k=3).values():
            self.assertFalse(plan.duplicated(["latitude", "longitude"]).any())

    def test_indeterminate_field_results_are_not_false_absences(self):
        validation = pd.DataFrame({
            "site_id": range(1, 6),
            "result": ["found", "not_found", "flowering_absent", "inaccessible", "uncertain_id"],
        })
        labels = parse_field_results(validation, "result")
        self.assertEqual(labels["site_id"].tolist(), [1, 2])
        self.assertEqual(labels["_field_success"].tolist(), [True, False])

    def test_scope_keeps_main_range_and_audits_disjunct_and_noise(self):
        main = [(35.0 + i * 0.005, 139.0 + i * 0.005) for i in range(10)]
        disjunct = [(34.0 + i * 0.005, 135.0 + i * 0.005) for i in range(3)]
        noise = [(43.0, 141.0)]
        points = main + disjunct + noise
        occurrences = pd.DataFrame({
            "_row_id": range(len(points)),
            "_latitude": [point[0] for point in points],
            "_longitude": [point[1] for point in points],
        })
        selected, audit, summary = infer_default_survey_scope(occurrences)
        self.assertEqual(len(selected), 10)
        self.assertEqual(summary["disjunct_records"], 3)
        self.assertEqual(summary["possible_noise_records"], 1)
        self.assertEqual(set(audit["scope_class"]), {"main_range", "disjunct_range", "possible_remote_noise"})

    def test_unknown_phenology_windows_have_safe_fallback(self):
        self.assertEqual(
            preferred_survey_window([None, float("nan"), "<NA>", "unknown"]),
            "Unknown; verify phenology locally",
        )
        self.assertEqual(preferred_survey_window(["May", "Jun", "May"]), "May")

    def test_balanced_plan_enforces_available_type_minimums(self):
        rows = []
        types = (["Occurrence-supported survey range"] * 3
                 + ["Habitat-match"] * 4
                 + ["Environmental-test"] * 3)
        for i, candidate_type in enumerate(types, start=1):
            rows.append({
                "site_id": i, "candidate_type": candidate_type,
                "latitude": 35.0 + i * 0.01, "longitude": 139.0 + i * 0.01,
                "analogue_score": 0.7, "access_score": 0.8,
                "environmental_novelty": 0.7 if "Environmental" in candidate_type else 0.2,
                "survey_gap_score": 0.7 if "Habitat" in candidate_type else 0.2,
            })
        balanced = build_acsp_discover_plans(pd.DataFrame(rows), k=8)["Balanced"]
        counts = balanced["quota_category"].value_counts().to_dict()
        self.assertGreaterEqual(counts.get("known", 0), 2)
        self.assertGreaterEqual(counts.get("discovery", 0), 3)
        self.assertGreaterEqual(counts.get("learning", 0), 1)

    def test_narrow_species_returns_one_compact_region(self):
        occurrences = pd.DataFrame({
            "_row_id": range(12),
            "_latitude": [34.70 + i * 0.002 for i in range(12)],
            "_longitude": [139.40 + i * 0.002 for i in range(12)],
        })
        _, scope_audit, _ = infer_default_survey_scope(occurrences)
        regions, audit, summary = recommend_survey_regions(occurrences, scope_audit)
        self.assertEqual(summary["distribution_regime"], "narrow/local")
        self.assertEqual(len(regions), 1)
        self.assertEqual(regions[0]["record_count"], 12)
        self.assertTrue(audit["region_id"].notna().all())

    def test_widespread_species_returns_distinct_short_trip_regions(self):
        groups = [
            [(35.0 + i * 0.01, 139.0 + i * 0.005) for i in range(10)],
            [(38.0 + i * 0.01, 140.0 + i * 0.005) for i in range(8)],
            [(43.0 + i * 0.01, 141.0 + i * 0.005) for i in range(6)],
            [(31.5 + i * 0.01, 130.5 + i * 0.005) for i in range(5)],
        ]
        points = [point for group in groups for point in group]
        occurrences = pd.DataFrame({
            "_row_id": range(len(points)),
            "_latitude": [point[0] for point in points],
            "_longitude": [point[1] for point in points],
        })
        scope_audit = occurrences[["_row_id", "_latitude", "_longitude"]].copy()
        scope_audit["scope_class"] = "disjunct_range"
        regions, _, summary = recommend_survey_regions(occurrences, scope_audit)
        self.assertEqual(summary["distribution_regime"], "widespread")
        self.assertEqual(len(regions), 3)
        self.assertEqual([region["card_role"] for region in regions], ["Recommended", "Discovery", "Range contrast"])
        self.assertTrue(all(float(region["diameter_km"]) <= 80.0 for region in regions))

    def test_region_center_radius_covers_members_from_medoid(self):
        occurrences = pd.DataFrame({
            "_row_id": [1, 2, 3],
            "_latitude": [35.00, 35.09, 35.35],
            "_longitude": [139.0, 139.0, 139.0],
        })
        audit = occurrences.copy()
        audit["scope_class"] = "main_range"
        regions, _, _ = recommend_survey_regions(occurrences, audit)
        region = regions[0]
        self.assertGreater(region["center_radius_km"], region["diameter_km"] / 2.0)
        self.assertLessEqual(region["center_radius_km"], region["diameter_km"])


if __name__ == "__main__":
    unittest.main()
