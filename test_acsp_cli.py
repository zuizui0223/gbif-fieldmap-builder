import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from acsp.cli import main


class AcspCliTests(unittest.TestCase):
    def test_recommend_command_writes_ranked_csv_and_summary(self):
        candidates = pd.DataFrame(
            {
                "site_id": ["n1", "n2", "n3", "n4", "s1", "s2", "s3", "s4"],
                "survey_area_id": ["north"] * 4 + ["south"] * 4,
                "priority_score": [0.90, 0.80, 0.70, 0.60, 0.95, 0.85, 0.75, 0.65],
            }
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            workdir = Path(temporary_directory)
            input_csv = workdir / "candidates.csv"
            output_csv = workdir / "recommended.csv"
            summary_json = workdir / "summary.json"
            candidates.to_csv(input_csv, index=False)

            exit_code = main(
                [
                    "recommend",
                    "--input",
                    str(input_csv),
                    "--output",
                    str(output_csv),
                    "--summary-json",
                    str(summary_json),
                    "--per-area",
                    "3",
                ]
            )

            selected = pd.read_csv(output_csv)
            summary = json.loads(summary_json.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(selected.groupby("survey_area_id").size().to_dict(), {"north": 3, "south": 3})
        self.assertEqual(selected["recommendation_rank"].tolist(), [1, 2, 3, 4, 5, 6])
        self.assertEqual(summary["selected_count"], 6)
        self.assertEqual(summary["selected_count_by_area"], {"north": 3, "south": 3})


if __name__ == "__main__":
    unittest.main()
