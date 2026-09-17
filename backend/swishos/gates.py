"""Physical-plausibility gates for daily plant readings.

`soiling_loss_pct` cannot be used as delivered. In the default dataset it
reports 97.98% loss for six consecutive days on plant_1003 (PR ~ 0.0196), which
would rank that plant first in the fleet and send a crew to it.

What the data shows, and what it does not
-----------------------------------------
Measured: PR across the 1,343 plant-days of the default dataset is bimodal with
an empty band — 21 readings at or below 0.3899, 1,322 at or above 0.8664, and
nothing between.

That measurement establishes only that there are *two populations*. It does not
show which population is soiling. The attribution — that the lower one is an
availability fault rather than dirt — rests on ASSUMPTIONS.md A1 (the brief's
statement that soiling only resets on rain or cleaning) and A2. This module
gates on that basis; it does not claim to have proved it.

The gate also does not diagnose *why* a reading is unusable. Inverter faults,
curtailment, transformer trips, comms dropouts and planned maintenance are
indistinguishable in this dataset (A3), and the cleaning decision only needs
"this reading cannot inform a soiling estimate".

Purity
------
Every function here is pure: no I/O, no clock, no database. Running the gate
twice on the same input must give the same answer — DDIA ch.17 "Determinism",
and its named anti-pattern "Non-deterministic Batch Operators".
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .domain import DailyReading, QualityAssessment, QualityFlag

# Performance ratio below which a reading is not treated as soiling.
#
# Not a tuned parameter *on this dataset*: nothing lies between 0.3899 and
# 0.8664, so every value inside that band produces an identical partition and
# the result does not depend on where the cut is placed. 0.5 is the round
# number in the middle.
#
# That freedom is a property of this sample, not a law — see A2b. If the two
# populations ever merge, this stops being free and starts discarding real
# soiling as the floor rises. `verify_empty_band` exists to detect that.
MIN_CREDIBLE_PR = 0.5

# How close a reading may come to the floor before the A2b assumption is
# considered at risk. The nearest reading in the default dataset sits 0.1101
# below the floor (0.3899) and the nearest above sits 0.3664 clear (0.8664), so
# nothing is within this margin today. A reading appearing inside it means the
# two populations have begun to merge and the threshold needs re-justifying.
BAND_MARGIN = 0.05


@dataclass(frozen=True)
class EmptyBandCheck:
    """Evidence for or against assumption A2b on a given set of readings."""

    highest_pr_below_floor: float | None
    lowest_pr_above_floor: float | None
    readings_within_margin: int

    @property
    def band_width(self) -> float | None:
        """Gap between the two populations, or None if either side is empty."""
        if self.highest_pr_below_floor is None or self.lowest_pr_above_floor is None:
            return None
        return self.lowest_pr_above_floor - self.highest_pr_below_floor

    @property
    def is_intact(self) -> bool:
        """True while no reading crowds the floor.

        An empty lower population also counts as intact: it means nothing was
        gated at all, so the threshold cannot be discarding soiling.
        """
        return self.readings_within_margin == 0


def assess_reading(reading: DailyReading) -> QualityAssessment:
    """Decide whether one plant-day may inform a soiling estimate.

    Checks run in order of severity rather than order of discovery: a plant
    generating almost nothing is an operational problem whether or not it also
    lacks a baseline, so the availability verdict must win. Reporting such a day
    as "missing baseline" would bury the more important signal.

    Returns a verdict for every input. Readings are never dropped here — callers
    filter on `is_usable`, and withheld rows stay visible to the interface.
    """
    if reading.pr is None:
        return _flag(
            reading,
            QualityFlag.MISSING_PERFORMANCE_RATIO,
            "no performance ratio published for this day",
        )

    if reading.pr < MIN_CREDIBLE_PR:
        return _flag(
            reading,
            QualityFlag.AVAILABILITY_ANOMALY,
            f"pr {reading.pr:.4f} falls in the population this system does not "
            f"attribute to soiling (floor {MIN_CREDIBLE_PR}, ASSUMPTIONS.md A1/A2); "
            "cause unknown and not inferable from this data",
        )

    if reading.soiling_loss_pct is None:
        return _flag(
            reading,
            QualityFlag.MISSING_SOILING_BASELINE,
            "no clean baseline established yet for this plant",
        )

    if reading.soiling_loss_pct < 0.0:
        return _flag(
            reading,
            QualityFlag.NEGATIVE_SOILING,
            f"soiling loss {reading.soiling_loss_pct:.2f}% is negative; the plant "
            "out-produced its own clean baseline, so the baseline is unreliable",
        )

    return _flag(reading, QualityFlag.USABLE, None)


def assess_readings(readings: Iterable[DailyReading]) -> list[QualityAssessment]:
    """Assess many readings. Input order is preserved."""
    return [assess_reading(reading) for reading in readings]


def usable_readings(readings: Iterable[DailyReading]) -> list[DailyReading]:
    """Filter to readings the estimator is allowed to see."""
    return [reading for reading in readings if assess_reading(reading).is_usable]


def verify_empty_band(readings: Iterable[DailyReading]) -> EmptyBandCheck:
    """Re-measure the gap that justifies `MIN_CREDIBLE_PR` (ASSUMPTIONS.md A2b).

    The threshold is only free of cost while the two PR populations stay
    separated. Rather than assume that holds for data this system has not seen,
    ingest runs this check and reports when the band closes.

    Readings with no PR are ignored: they are gated on a different branch and
    say nothing about where the populations sit.
    """
    below: list[float] = []
    above: list[float] = []

    for reading in readings:
        if reading.pr is None:
            continue
        (below if reading.pr < MIN_CREDIBLE_PR else above).append(reading.pr)

    within_margin = sum(
        1 for pr in below + above if abs(pr - MIN_CREDIBLE_PR) <= BAND_MARGIN
    )

    return EmptyBandCheck(
        highest_pr_below_floor=max(below) if below else None,
        lowest_pr_above_floor=min(above) if above else None,
        readings_within_margin=within_margin,
    )


def _flag(
    reading: DailyReading, flag: QualityFlag, detail: str | None
) -> QualityAssessment:
    return QualityAssessment(
        plant_id=reading.plant_id,
        reading_date=reading.reading_date,
        flag=flag,
        detail=detail,
    )
