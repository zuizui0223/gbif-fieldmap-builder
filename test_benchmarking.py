import unittest
from unittest.mock import Mock, patch

import pandas as pd
import requests

from acsp.benchmarking import coverage_at_radius, fold_completion, get_json


class BenchmarkingHelperTests(unittest.TestCase):
    def test_coverage_at_radius_is_recomputed(self):
        candidates = pd.DataFrame({
            "all_heldout_ids": ["a;b;c"],
            "heldout_distances_km": ["1;4;8"],
        })
        self.assertEqual(coverage_at_radius(candidates, 5)["covered_heldout_ids"].iloc[0], "a;b")

    def test_fold_completion_keeps_failures_in_audit(self):
        self.assertEqual(fold_completion(pd.DataFrame({"status": ["ok", "failed"]}), 2)["status"], "partial")
        self.assertEqual(fold_completion(pd.DataFrame({"status": ["failed"]}), 2)["failed_repeats"], 2)

    @patch("acsp.benchmarking.time.sleep")
    @patch("acsp.benchmarking.requests.get")
    def test_get_json_retries_transient_failure(self, get, _sleep):
        success = Mock()
        success.raise_for_status.return_value = None
        success.json.return_value = {"ok": True}
        get.side_effect = [requests.exceptions.SSLError("temporary"), success]
        self.assertEqual(get_json("https://example.test", attempts=2), {"ok": True})


if __name__ == "__main__":
    unittest.main()
