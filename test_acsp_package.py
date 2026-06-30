import unittest

import pandas as pd
import numpy as np

from acsp import (
    DEFAULT_ENSEMBLE_ALGORITHMS,
    choose_spatial_partition,
    filter_candidates_to_extent,
    model_performance_table,
    make_classifier,
    predict_equal_weight_ensemble,
    recommend_candidates,
    sdm_method_record,
)


class AcspPackageTests(unittest.TestCase):
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
