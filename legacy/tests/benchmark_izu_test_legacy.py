from pathlib import Path
import tempfile
import unittest

import pandas as pd

from legacy.benchmarks.benchmark_izu_random_taxa import (
    ISLAND_BOUNDS,
    _coverage_at_radius,
    _fold_completion,
    _read_candidate_files,
    island_features,
    island_wkt,
)


class IzuBenchmarkTests(unittest.TestCase):
    def test_sampling_frame_contains_four_independent_islands(self):
        self.assertEqual(len(ISLAND_BOUNDS), 4)
        self.assertEqual(len(island_features()), 4)
        self.assertTrue(island_wkt().startswith("MULTIPOLYGON("))

    def test_radius_sensitivity_reuses_stored_distances(self):
        candidates = pd.DataFrame({
            "all_heldout_ids": ["0;1;2"],
            "heldout_distances_km": ["1.0;4.0;8.0"],
            "covered_heldout_ids": [""],
        })
        self.assertEqual(_coverage_at_radius(candidates, 2)["covered_heldout_ids"].iloc[0], "0")
        self.assertEqual(_coverage_at_radius(candidates, 5)["covered_heldout_ids"].iloc[0], "0;1")
        self.assertEqual(_coverage_at_radius(candidates, 10)["covered_heldout_ids"].iloc[0], "0;1;2")

    def test_zero_valid_repeats_are_not_reported_as_success(self):
        failed = pd.DataFrame({"status": ["no_distance_free_candidates"] * 5})
        partial = pd.DataFrame({"status": ["ok", "no_candidates"]})
        self.assertEqual(_fold_completion(failed, 5)["status"], "failed")
        self.assertEqual(_fold_completion(partial, 2)["status"], "partial")

    def test_empty_candidate_checkpoint_is_ignored_safely(self):
        with tempfile.TemporaryDirectory() as directory:
            empty = Path(directory) / "empty.csv"
            valid = Path(directory) / "valid.csv"
            empty.write_text("", encoding="utf-8")
            pd.DataFrame({"benchmark_taxon": ["Plantus test"], "latitude": [34.5]}).to_csv(valid, index=False)
            combined = _read_candidate_files([empty, valid])
        self.assertEqual(combined["benchmark_taxon"].tolist(), ["Plantus test"])


if __name__ == "__main__":
    unittest.main()
