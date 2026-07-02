import unittest

import pandas as pd
import numpy as np

from acsp import (
    DEFAULT_ENSEMBLE_ALGORITHMS,
    choose_spatial_partition,
    calibrate_candidate_weights,
    calibrate_model_ensemble_weights,
    multi_taxon_weight_benchmark,
    filter_candidates_to_extent,
    integrated_candidate_scores,
    model_performance_table,
    make_classifier,
    predict_equal_weight_ensemble,
    recommend_candidates,
    select_complementary_candidates,
    sdm_method_record,
    spatial_block_recovery_validation,
    spatial_block_candidate_benchmark,
    spatial_model_accuracy_benchmark,
    stratified_random_taxa,
)


class AcspPackageTests(unittest.TestCase):
    def test_complementary_selection_retains_evidence_anchor_and_spatial_alternative(self):
        candidates = pd.DataFrame({
            "site_id": [1, 2, 3], "integrated_support_score": [1.0, 0.9, 0.8],
            "latitude": [35.0, 35.001, 36.0], "longitude": [139.0, 139.001, 140.0],
        })
        selected = select_complementary_candidates(candidates, 2, evidence_weight=0.25)
        self.assertEqual(selected["site_id"].tolist(), [1, 3])
        self.assertIn("alternatives", selected["complementary_selection_policy"].iloc[0])

    def test_integrated_score_renormalizes_when_model_is_unavailable(self):
        candidate = pd.DataFrame({
            "site_id": [1], "occurrence_support_score": [0.8],
            "analogue_score": [0.7], "access_score": [0.6],
        })
        without_model = integrated_candidate_scores(candidate)
        with_empty_model = integrated_candidate_scores(candidate.assign(sdm_suitability=np.nan))
        self.assertAlmostEqual(
            without_model.loc[0, "integrated_support_score"],
            with_empty_model.loc[0, "integrated_support_score"],
        )
        self.assertFalse(with_empty_model.loc[0, "component_macro_model_available"])

    def test_distance_excluded_score_ignores_occurrence_and_gap_evidence(self):
        candidates = pd.DataFrame({
            "site_id": [1, 2], "occurrence_support_score": [1.0, 0.0],
            "survey_gap_score": [0.0, 1.0], "environmental_novelty": [0.0, 1.0],
            "analogue_score": [0.8, 0.8], "sdm_suitability": [0.7, 0.7], "access_score": [0.6, 0.6],
        })
        scored = integrated_candidate_scores(candidates, exclude_occurrence_derived=True)
        self.assertEqual(scored["integrated_support_score"].nunique(), 1)
        self.assertTrue(scored["distance_excluded_validation_score"].all())

    def test_distance_excluded_score_rejects_spatial_habitat_fallback(self):
        candidates = pd.DataFrame({
            "latitude": [35.0, 35.1], "longitude": [139.0, 139.1],
            "analogue_score": [0.9, 0.2],
            "occurrence_derived_habitat_score": [True, False],
        })
        scored = integrated_candidate_scores(candidates, exclude_occurrence_derived=True)
        self.assertFalse(bool(scored.loc[0, "component_local_habitat_available"]))
        self.assertTrue(bool(scored.loc[1, "component_local_habitat_available"]))

    def test_spatial_block_recovery_is_reproducible_and_uses_training_only(self):
        occurrences = pd.DataFrame({
            "record_id": range(8),
            "latitude": [35.0, 35.02, 35.5, 35.52, 36.0, 36.02, 36.5, 36.52],
            "longitude": [139.0, 139.02, 139.5, 139.52, 140.0, 140.02, 140.5, 140.52],
        })
        training_sizes = []

        def builder(training):
            training_sizes.append(len(training))
            return pd.DataFrame({
                "site_id": range(1, 9),
                "latitude": occurrences["latitude"], "longitude": occurrences["longitude"],
                "candidate_type": ["Habitat-match"] * 8,
                "analogue_score": np.linspace(1.0, 0.3, 8),
                "sdm_suitability": np.linspace(0.9, 0.2, 8),
                "access_score": [0.8] * 8,
            })

        folds, summary = spatial_block_recovery_validation(
            occurrences, builder, block_degrees=0.25, repeats=3, top_k=3,
            hit_radius_km=10.0, random_draws=10, random_state=7,
        )
        self.assertEqual(summary["valid_repeats"], 3)
        self.assertTrue(all(size < len(occurrences) for size in training_sizes))
        self.assertTrue(folds["distance_excluded_recall"].between(0, 1).all())

    def test_candidate_benchmark_and_taxon_heldout_calibration(self):
        occurrences = pd.DataFrame({
            "latitude": [35.0, 35.02, 35.5, 35.52, 36.0, 36.02, 36.5, 36.52],
            "longitude": [139.0, 139.02, 139.5, 139.52, 140.0, 140.02, 140.5, 140.52],
        })

        def builder(_training):
            return pd.DataFrame({
                "site_id": range(8), "latitude": occurrences["latitude"],
                "longitude": occurrences["longitude"], "candidate_type": ["Habitat-match"] * 8,
                "analogue_score": np.linspace(1, 0.2, 8), "sdm_suitability": np.linspace(0.2, 1, 8),
                "access_score": [0.5] * 8, "field_validation_support_score": [0.5] * 8,
            })

        candidates, folds, summary = spatial_block_candidate_benchmark(
            occurrences, builder, repeats=2, top_k=2, hit_radius_km=10, random_draws=5,
            random_state=9, selection_evidence_weight=1.0,
        )
        self.assertEqual(summary["valid_repeats"], 2)
        self.assertIn("covered_heldout_ids", candidates)
        self.assertTrue(folds["selection_evidence_weight"].eq(1.0).all())
        combined = pd.concat([candidates.assign(benchmark_taxon=name) for name in ["a", "b", "c", "d"]])
        search, calibration = calibrate_candidate_weights(combined, search_draws=10, top_k=2, random_state=3)
        self.assertEqual(len(calibration["heldout_evaluation_taxa"]), 2)
        self.assertAlmostEqual(sum(calibration["selected_weights"].values()), 1.0, places=5)
        self.assertFalse(calibration["recommend_production_change"])
        self.assertIn("calibration_informative", calibration)
        self.assertEqual(calibration["field_only_components"], ["access", "field_validation"])
        self.assertNotIn("access", calibration["selected_weights"])
        self.assertGreaterEqual(
            calibration["greedy_same_pool_oracle_recall"], calibration["selected_heldout_recall"]
        )
        self.assertFalse(search.empty)

    def test_stratified_random_taxa_is_seeded_and_spans_count_strata(self):
        taxa = pd.DataFrame({
            "scientific_name": [f"Species {index}" for index in range(12)],
            "coordinate_records": np.geomspace(5, 5000, 12).astype(int),
        })
        first = stratified_random_taxa(taxa, 6, random_state=17)
        second = stratified_random_taxa(taxa, 6, random_state=17)
        self.assertEqual(first["scientific_name"].tolist(), second["scientific_name"].tolist())
        self.assertEqual(first["benchmark_count_stratum"].nunique(), 3)

    def test_multi_taxon_benchmark_keeps_failed_taxa_visible(self):
        occurrences = pd.DataFrame({
            "latitude": [35.0, 35.02, 35.5, 35.52, 36.0, 36.02, 36.5, 36.52],
            "longitude": [139.0, 139.02, 139.5, 139.52, 140.0, 140.02, 140.5, 140.52],
        })

        def builder(taxon, _training):
            if taxon == "failed taxon":
                raise RuntimeError("declared failure")
            return pd.DataFrame({
                "site_id": range(8), "latitude": occurrences["latitude"],
                "longitude": occurrences["longitude"], "candidate_type": ["Habitat-match"] * 8,
                "analogue_score": np.linspace(1, 0.2, 8), "sdm_suitability": np.linspace(0.2, 1, 8),
                "access_score": [0.5] * 8, "field_validation_support_score": [0.5] * 8,
            })

        taxa = {name: occurrences for name in ["a", "b", "c", "d", "failed taxon"]}
        result = multi_taxon_weight_benchmark(
            taxa, builder,
            benchmark_kwargs={"repeats": 1, "top_k": 2, "hit_radius_km": 10, "random_draws": 3},
            calibration_kwargs={"search_draws": 5, "top_k": 2},
        )
        self.assertEqual(result["calibration_summary"]["successful_taxa"], 4)
        self.assertEqual(result["calibration_summary"]["failed_taxa"], 1)
        self.assertIn("failed", result["taxon_status"]["status"].tolist())

    def test_spatial_benchmark_accepts_app_internal_coordinate_columns(self):
        occurrences = pd.DataFrame({
            "_latitude": [35.0, 35.02, 35.5, 35.52],
            "_longitude": [139.0, 139.02, 139.5, 139.52],
        })

        def builder(_training):
            return pd.DataFrame({
                "site_id": [1, 2], "latitude": [35.0, 35.5], "longitude": [139.0, 139.5],
                "candidate_type": ["Habitat-match", "Habitat-match"], "analogue_score": [0.8, 0.7],
            })

        candidates, folds, _ = spatial_block_candidate_benchmark(
            occurrences, builder, repeats=1, top_k=1, random_draws=2, hit_radius_km=5,
        )
        self.assertFalse(candidates.empty)
        self.assertEqual(folds.loc[0, "status"], "ok")

    def test_spatial_model_accuracy_returns_ensemble_and_auditable_predictions(self):
        rng = np.random.default_rng(21)
        rows = []
        for block in range(8):
            for label in [0, 1]:
                for _ in range(5):
                    rows.append({
                        "latitude": 34.0 + block * 0.3 + rng.normal(0, 0.01),
                        "longitude": 139.0 + block * 0.3 + rng.normal(0, 0.01),
                        "presence": label, "bio1": label + rng.normal(0, 0.2),
                        "bio12": label * 0.7 + rng.normal(0, 0.2),
                    })
        metrics, predictions = spatial_model_accuracy_benchmark(
            pd.DataFrame(rows), ["bio1", "bio12"], repeats=3,
            block_degrees=0.2, holdout_fraction=0.25, random_state=8,
        )
        self.assertEqual(metrics["repeat"].nunique(), 3)
        self.assertIn("Equal-weight ensemble", metrics["algorithm"].tolist())
        self.assertTrue(metrics["roc_auc"].between(0, 1).all())
        self.assertTrue(metrics["brier"].between(0, 1).all())
        self.assertEqual(set(predictions["label"].unique()), {0, 1})

        multi_predictions = pd.concat([
            predictions.assign(benchmark_taxon=f"taxon {index}") for index in range(10)
        ], ignore_index=True)
        multi_metrics = pd.concat([
            metrics.assign(benchmark_taxon=f"taxon {index}") for index in range(10)
        ], ignore_index=True)
        search, calibration = calibrate_model_ensemble_weights(
            multi_predictions, multi_metrics, search_draws=3, random_state=5,
        )
        self.assertFalse(search.empty)
        self.assertEqual(len(calibration["heldout_evaluation_taxa"]), 3)
        self.assertIn("equal_weight_heldout_log_loss", calibration)

    def test_all_default_classifiers_produce_an_ensemble_probability(self):
        X = pd.DataFrame({"bio1": np.linspace(0, 1, 24), "bio12": np.tile([0.1, 0.9], 12)})
        y = np.array([0] * 12 + [1] * 12)
        models = {}
        for name in DEFAULT_ENSEMBLE_ALGORITHMS:
            model = make_classifier(name)
            model.fit(X, y)
            models[name] = model
        prediction = predict_equal_weight_ensemble(models, X)
        self.assertEqual(set(models), set(DEFAULT_ENSEMBLE_ALGORITHMS))
        self.assertEqual(len(prediction), len(X))
        self.assertTrue(np.all((prediction >= 0) & (prediction <= 1)))

    def test_area_quota(self):
        candidates = pd.DataFrame({
            "site_id": range(1, 9),
            "survey_area_id": [1, 1, 1, 1, 2, 2, 2, 2],
            "priority_score": [0.9, 0.8, 0.7, 0.6] * 2,
        })
        selected = recommend_candidates(candidates, per_area=3)
        self.assertEqual(selected.groupby("survey_area_id").size().to_dict(), {1: 3, 2: 3})

    def test_extent_filters_candidates_before_ranking(self):
        candidates = pd.DataFrame({
            "site_id": [1, 2, 3],
            "priority_score": [0.7, 0.9, 1.0],
            "latitude": [35.0, 35.2, 36.0],
            "longitude": [139.0, 139.2, 140.0],
        })
        extent = (138.9, 34.9, 139.3, 35.3)
        filtered = filter_candidates_to_extent(candidates, extent)
        selected = recommend_candidates(candidates, extent=extent)
        self.assertEqual(filtered["site_id"].tolist(), [1, 2])
        self.assertEqual(selected["site_id"].tolist(), [2, 1])

    def test_partition_and_method_reporting(self):
        method, reason = choose_spatial_partition(86, 1.8)
        self.assertEqual(method, "random holdout")
        metrics = pd.DataFrame({
            "algorithm": ["Random forest", "ExtraTrees"],
            "fold": ["diagnostic", "diagnostic"],
            "auc": [0.81, 0.87],
            "warning": ["random split may be optimistic", "random split may be optimistic"],
        })
        performance = model_performance_table(metrics)
        best = performance.loc[performance["model_role"].str.startswith("best"), "algorithm"].iloc[0]
        self.assertEqual(best, "ExtraTrees")
        record = sdm_method_record(
            n_source_records=87,
            n_qc_excluded=1,
            n_presence_used=86,
            n_background=500,
            partition_method=method,
            partition_reason=reason,
            variables=["bio1", "bio12"],
            performance=performance,
            environment_source="CHELSA 30-second COG",
            prediction_extent="QC-derived bounding box",
        )
        self.assertEqual(record["best_individual_model"], "ExtraTrees")
        self.assertIn("equal-weight mean", record["ensemble_method"])
        self.assertIn("optimistic", record["validation_caution"])


if __name__ == "__main__":
    unittest.main()
