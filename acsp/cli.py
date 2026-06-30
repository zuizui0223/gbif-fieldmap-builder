"""Command-line interface for reproducible ACSP candidate selection."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

import pandas as pd

from .planning import recommend_candidates


def _positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Expected an integer, got {value!r}.") from exc
    if number < 1:
        raise argparse.ArgumentTypeError("Value must be at least 1.")
    return number


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="acsp-recommend",
        description="Select transparent, ranked ACSP field-survey candidates from a CSV file.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    recommend = subparsers.add_parser(
        "recommend",
        help="Rank candidate rows and apply an equal per-area quota when multiple survey areas exist.",
    )
    recommend.add_argument("--input", required=True, help="Input candidate CSV path.")
    recommend.add_argument("--output", required=True, help="Output CSV path for selected candidates.")
    recommend.add_argument(
        "--summary-json",
        default="acsp-summary.json",
        help="Output JSON path for run metadata and selected-row counts (default: acsp-summary.json).",
    )
    recommend.add_argument("--per-area", type=_positive_int, default=3, help="Top rows retained per survey area (default: 3).")
    recommend.add_argument(
        "--default-total",
        type=_positive_int,
        default=8,
        help="Top rows retained when one or no survey area is supplied (default: 8).",
    )
    recommend.add_argument("--area-column", default="survey_area_id", help="Survey-area column name (default: survey_area_id).")
    recommend.add_argument("--score-column", default="priority_score", help="Priority-score column name (default: priority_score).")
    recommend.add_argument("--site-column", default="site_id", help="Stable candidate-ID column name (default: site_id).")
    recommend.add_argument("--extent", nargs=4, type=float, metavar=("WEST", "SOUTH", "EAST", "NORTH"), help="Optional rectangular candidate extent.")
    recommend.add_argument("--latitude-column", default="latitude", help="Latitude column used with --extent.")
    recommend.add_argument("--longitude-column", default="longitude", help="Longitude column used with --extent.")
    return parser


def run_recommendation(args: argparse.Namespace) -> dict[str, object]:
    input_path = Path(args.input)
    output_path = Path(args.output)
    summary_path = Path(args.summary_json)

    if not input_path.is_file():
        raise FileNotFoundError(f"Candidate CSV was not found: {input_path}")

    candidates = pd.read_csv(input_path)
    selected = recommend_candidates(
        candidates,
        per_area=args.per_area,
        default_total=args.default_total,
        area_col=args.area_column,
        score_col=args.score_column,
        id_col=args.site_column,
        extent=args.extent,
        latitude_col=args.latitude_column,
        longitude_col=args.longitude_column,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    selected.to_csv(output_path, index=False)

    area_counts: dict[str, int] = {}
    if args.area_column in selected.columns:
        area_counts = {
            str(area): int(count)
            for area, count in selected.groupby(args.area_column, dropna=False).size().items()
        }

    summary: dict[str, object] = {
        "input_csv": str(input_path),
        "output_csv": str(output_path),
        "input_candidate_count": int(len(candidates)),
        "selected_count": int(len(selected)),
        "per_area": int(args.per_area),
        "default_total": int(args.default_total),
        "area_column": args.area_column,
        "area_column_present": bool(args.area_column in candidates.columns),
        "score_column": args.score_column,
        "site_column": args.site_column,
        "extent": list(args.extent) if args.extent is not None else None,
        "selected_count_by_area": area_counts,
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "recommend":
        summary = run_recommendation(args)
        print(json.dumps(summary, ensure_ascii=False))
        return 0
    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
