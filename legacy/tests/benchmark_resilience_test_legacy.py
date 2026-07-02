import unittest
from unittest.mock import Mock, patch

import requests

from legacy.benchmarks import benchmark_random_species_models as model_benchmark


class BenchmarkResilienceTests(unittest.TestCase):
    @patch("legacy.benchmarks.benchmark_random_species_models.time.sleep")
    @patch("legacy.benchmarks.benchmark_random_species_models.requests.get")
    def test_get_json_retries_transient_ssl_failure(self, get, _sleep):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"ok": True}
        get.side_effect = [requests.exceptions.SSLError("temporary"), response]

        self.assertEqual(model_benchmark._get_json("https://example.test"), {"ok": True})
        self.assertEqual(get.call_count, 2)

    @patch("legacy.benchmarks.benchmark_random_species_models._get_json")
    def test_sampling_frame_skips_one_failed_species_resolution(self, get_json):
        get_json.side_effect = [
            {"facets": [{"counts": [{"name": "1", "count": 50}, {"name": "2", "count": 40}]}]},
            requests.exceptions.SSLError("temporary"),
            {"rank": "SPECIES", "scientificName": "Plantus secundus"},
        ]

        frame = model_benchmark.japan_plant_sampling_frame(10, 10)

        self.assertEqual(frame["speciesKey"].tolist(), [2])
        self.assertEqual(frame["scientific_name"].tolist(), ["Plantus secundus"])


if __name__ == "__main__":
    unittest.main()
