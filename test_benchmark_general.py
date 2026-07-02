import unittest

import pandas as pd

from acsp import clustered_recovery_inference

from benchmark_general_random_taxa_regions import REGION_CELLS, rectangle_feature, rectangle_wkt, summarize_recovery


class GeneralBenchmarkTests(unittest.TestCase):
    def test_region_frame_spans_four_geographic_strata(self):
        self.assertEqual({row[0] for row in REGION_CELLS}, {"north", "east", "west", "south"})
        self.assertGreaterEqual(len(REGION_CELLS), 12)

    def test_rectangle_serializations_use_same_bounds(self):
        bounds = (138.5, 35.0, 140.5, 36.5)
        self.assertTrue(rectangle_wkt(bounds).startswith("POLYGON((138.5 35.0"))
        coordinates = rectangle_feature(bounds, "Kanto")["geometry"]["coordinates"][0]
        self.assertEqual(coordinates[0], [138.5, 35.0])
        self.assertEqual(coordinates[-1], coordinates[0])

    def test_recovery_marks_pool_larger_than_top_k_as_rankable(self):
        candidates = pd.DataFrame({
            "benchmark_taxon": ["A"] * 6, "benchmark_region": ["R"] * 6,
            "taxon_group": ["plant"] * 6, "geographic_stratum": ["east"] * 6,
            "repeat": [1] * 6, "all_heldout_ids": ["0;1"] * 6,
            "heldout_distances_km": ["1;20"] * 6, "covered_heldout_ids": [""] * 6,
            "integrated_support_score": [0.9, 0.8, 0.7, 0.6, 0.5, 0.4],
        })
        row = summarize_recovery(candidates, 5.0, top_k=5, seed=1)[0]
        self.assertTrue(row["rankable_fold"])
        self.assertEqual(row["candidate_pool"], 6)

    def test_clustered_inference_penalizes_failed_declared_pair(self):
        recovery = pd.DataFrame({
            "benchmark_taxon": ["A", "A"], "taxon_group": ["plant", "plant"],
            "radius_km": [5.0, 5.0], "default_recall": [1.0, 1.0],
            "random_recall": [0.0, 0.0], "greedy_oracle_recall": [1.0, 1.0],
            "rankable_fold": [True, True],
        })
        declared = pd.DataFrame({
            "benchmark_taxon": ["A", "B"], "taxon_group": ["plant", "plant"],
        })
        first = clustered_recovery_inference(
            recovery, declared, repeats=2, bootstrap_draws=50, permutation_draws=50, random_state=7
        )
        second = clustered_recovery_inference(
            recovery, declared, repeats=2, bootstrap_draws=50, permutation_draws=50, random_state=7
        )
        self.assertAlmostEqual(first.loc[0, "ite_default_recall"], 0.5)
        self.assertAlmostEqual(first.loc[0, "fold_completion_rate"], 0.5)
        pd.testing.assert_frame_equal(first, second)


if __name__ == "__main__":
    unittest.main()
