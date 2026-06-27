import unittest
from unittest.mock import patch

from gbif_fieldmap_builder_app import fetch_gbif_records_representative


class GbifFetchResilienceTests(unittest.TestCase):
    def test_keeps_completed_pages_when_one_page_fails(self):
        successful_page = {"results": [{"key": i} for i in range(300)], "endOfRecords": False}
        with patch("gbif_fieldmap_builder_app.gbif_get_json", side_effect=[successful_page, RuntimeError("temporary")]):
            records, retrieval = fetch_gbif_records_representative(
                {"taxonKey": 1}, max_records=600, total_count=1000, timeout=1
            )
        self.assertEqual(len(records), 300)
        self.assertIn("1 pages completed, 1 failed", retrieval)


if __name__ == "__main__":
    unittest.main()
