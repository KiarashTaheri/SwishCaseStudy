"""Apply the quality gate and materialise its verdicts.

Thin orchestration only: read readings, call the pure functions in `gates`,
write the result. All judgement lives in `gates`; all SQL lives here. That split
is what lets the gate be tested without a database.

`reading_quality` is derived data in the DDIA ch.17 sense — it holds no
information that cannot be recomputed from `daily_reading`, so it is rebuilt
wholesale on every run rather than patched incrementally.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import date

from . import gates
from .domain import DailyReading, QualityAssessment, QualityFlag


@dataclass(frozen=True)
class GateSummary:
    """Outcome of a gate run, for logging and for the ingest report."""

    counts_by_flag: dict[str, int]
    band_check: gates.EmptyBandCheck

    @property
    def total(self) -> int:
        return sum(self.counts_by_flag.values())

    @property
    def usable(self) -> int:
        return self.counts_by_flag.get(QualityFlag.USABLE.value, 0)

    @property
    def withheld(self) -> int:
        return self.total - self.usable


def apply_quality_gate(connection: sqlite3.Connection) -> GateSummary:
    """Assess every stored reading and replace the derived quality table."""
    readings = load_daily_readings(connection)
    assessments = gates.assess_readings(readings)

    with connection:
        connection.execute("DELETE FROM reading_quality")
        connection.executemany(
            """INSERT INTO reading_quality (plant_id, date, flag, detail)
               VALUES (?, ?, ?, ?)""",
            [
                (a.plant_id, a.reading_date.isoformat(), a.flag.value, a.detail)
                for a in assessments
            ],
        )

    return GateSummary(
        counts_by_flag=dict(Counter(a.flag.value for a in assessments)),
        band_check=gates.verify_empty_band(readings),
    )


def load_daily_readings(
    connection: sqlite3.Connection, plant_id: str | None = None
) -> list[DailyReading]:
    """Read stored readings, oldest first.

    Ordered by date because every downstream consumer — the estimator's
    since-last-reset window especially — depends on chronological order, and
    SQLite gives no ordering guarantee without an explicit ORDER BY.
    """
    query = """SELECT plant_id, date, energy_kwh, expected_energy_kwh,
                      pr, soiling_loss_pct
               FROM daily_reading"""
    parameters: tuple[str, ...] = ()
    if plant_id is not None:
        query += " WHERE plant_id = ?"
        parameters = (plant_id,)
    query += " ORDER BY plant_id, date"

    return [
        DailyReading(
            plant_id=row["plant_id"],
            reading_date=date.fromisoformat(row["date"]),
            energy_kwh=row["energy_kwh"],
            expected_energy_kwh=row["expected_energy_kwh"],
            pr=row["pr"],
            soiling_loss_pct=row["soiling_loss_pct"],
        )
        for row in connection.execute(query, parameters)
    ]


def load_assessments(
    connection: sqlite3.Connection, plant_id: str | None = None
) -> list[QualityAssessment]:
    """Read stored gate verdicts, oldest first."""
    query = "SELECT plant_id, date, flag, detail FROM reading_quality"
    parameters: tuple[str, ...] = ()
    if plant_id is not None:
        query += " WHERE plant_id = ?"
        parameters = (plant_id,)
    query += " ORDER BY plant_id, date"

    return [
        QualityAssessment(
            plant_id=row["plant_id"],
            reading_date=date.fromisoformat(row["date"]),
            flag=QualityFlag(row["flag"]),
            detail=row["detail"],
        )
        for row in connection.execute(query, parameters)
    ]
