"""Rebuild the database from the CSV dataset.

    python -m swishos.build --data ../data --db swishos.db

Deliberately a batch command rather than something the API triggers: the whole
pipeline is deterministic and re-runnable, so the recovery procedure for any
corruption downstream is to delete the database and run this again.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import gates
from .db import apply_schema, connect
from .ingest import IngestError, ingest_dataset
from .quality import GateSummary, apply_quality_gate


def build(data_dir: Path, database_path: Path) -> GateSummary:
    """Load the CSVs and materialise quality verdicts. Safe to re-run."""
    connection = connect(database_path)
    try:
        apply_schema(connection)
        summary = ingest_dataset(connection, data_dir)
        print(
            f"ingested {summary.plants} plants, {summary.crews} crews, "
            f"{summary.daily_readings:,} daily readings, {summary.events:,} events"
        )
        return apply_quality_gate(connection)
    finally:
        connection.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data", type=Path, default=Path("../data"), help="directory of source CSVs"
    )
    parser.add_argument(
        "--db", type=Path, default=Path("swishos.db"), help="SQLite file to write"
    )
    args = parser.parse_args(argv)

    try:
        summary = build(args.data, args.db)
    except IngestError as error:
        print(f"ingest failed: {error}", file=sys.stderr)
        return 1

    _report(summary)
    return 0


def _report(summary: GateSummary) -> None:
    print(
        f"\nquality gate: {summary.usable:,} usable, "
        f"{summary.withheld:,} withheld of {summary.total:,}"
    )
    for flag, count in sorted(summary.counts_by_flag.items(), key=lambda kv: -kv[1]):
        print(f"  {flag:<28} {count:>6,}")

    check = summary.band_check
    width = check.band_width
    print(
        f"\nPR band around the {gates.MIN_CREDIBLE_PR} floor: "
        f"highest below = {_format(check.highest_pr_below_floor)}, "
        f"lowest above = {_format(check.lowest_pr_above_floor)}, "
        f"width = {_format(width)}"
    )

    # A2b is the assumption that the two PR populations stay separated. It is
    # cheap to check, so the build checks it rather than trusting it.
    if check.is_intact:
        print("  band intact — MIN_CREDIBLE_PR is not a tuned parameter on this data")
    else:
        print(
            f"  WARNING: {check.readings_within_margin:,} reading(s) within "
            f"{gates.BAND_MARGIN} of the floor. The populations are merging, so "
            "the threshold now has real cost on both sides. See ASSUMPTIONS.md A2b.",
            file=sys.stderr,
        )


def _format(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.4f}"


if __name__ == "__main__":
    raise SystemExit(main())
