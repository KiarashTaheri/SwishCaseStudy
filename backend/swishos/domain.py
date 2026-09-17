"""Domain types for the fleet soiling advisor.

These types are the contract between the ingest layer, the quality gates and
everything downstream. They are deliberately immutable: the pipeline is a chain
of deterministic transformations (DDIA ch.17), and frozen inputs make it
impossible for a later stage to mutate an earlier stage's output in place.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum


class QualityFlag(str, Enum):
    """Outcome of the physical-plausibility gate for a single plant-day.

    Only `USABLE` rows may feed the soiling estimator. Every other member
    records *why* a row was withheld, because the reason is itself information
    the asset manager needs — a plant excluded for an availability anomaly is an
    operational problem, not merely a gap in the data.
    """

    USABLE = "USABLE"
    MISSING_PERFORMANCE_RATIO = "MISSING_PERFORMANCE_RATIO"
    MISSING_SOILING_BASELINE = "MISSING_SOILING_BASELINE"
    AVAILABILITY_ANOMALY = "AVAILABILITY_ANOMALY"
    NEGATIVE_SOILING = "NEGATIVE_SOILING"


class EstimateStatus(str, Enum):
    """Whether a plant can be ranked today, and why not when it cannot.

    `NO_USABLE_READING` is a real answer, not an error: today's reading was
    either blank — no clean baseline to compare against yet — or withheld by the
    quality gate. Saying so is better than ranking a plant on a number the gate
    has already judged not credible as dirt.
    """

    ESTIMATED = "ESTIMATED"
    NO_USABLE_READING = "NO_USABLE_READING"


class DispatchStatus(str, Enum):
    """Whether a plant is worth cleaning tomorrow.

    Three values rather than a boolean, because "no" has two very different
    meanings to the asset manager: `BELOW_BREAK_EVEN` is a plant the system
    understands and is telling her to wait on, while `NO_USABLE_READING` is a
    plant it has no opinion about. Collapsing them would hide the second, which
    is the one she may need to act on by other means.
    """

    ACTIONABLE = "ACTIONABLE"
    BELOW_BREAK_EVEN = "BELOW_BREAK_EVEN"
    NO_USABLE_READING = "NO_USABLE_READING"


@dataclass(frozen=True)
class Plant:
    plant_id: str
    name: str
    region: str
    capacity_mw: float
    tariff_per_kwh: float
    cleaning_cost_usd: float
    days_until_next_reset: int
    commissioned_on: date


@dataclass(frozen=True)
class Crew:
    crew_id: str
    home_base: str
    mw_per_day: float
    day_rate_usd: float


@dataclass(frozen=True)
class DailyReading:
    """One plant-day from `daily.csv`, exactly as delivered.

    `pr` and `soiling_loss_pct` are Optional because the source publishes blanks
    where no clean baseline exists yet. Representing that as None rather than
    0.0 is what stops a missing baseline being silently read as a perfect plant.
    """

    plant_id: str
    reading_date: date
    energy_kwh: float
    expected_energy_kwh: float
    pr: float | None
    soiling_loss_pct: float | None


@dataclass(frozen=True)
class PlantDayEvent:
    """Weather and crew activity for one plant-day, from `events.csv`."""

    plant_id: str
    event_date: date
    rain_mm: float
    cleaned: bool


@dataclass(frozen=True)
class QualityAssessment:
    """A gate verdict for one plant-day, plus the evidence behind it."""

    plant_id: str
    reading_date: date
    flag: QualityFlag
    detail: str | None

    @property
    def is_usable(self) -> bool:
        return self.flag is QualityFlag.USABLE
