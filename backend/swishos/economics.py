"""Turn a soiling estimate into a dollar figure and a verdict.

The rule is the brief's own: clean when the cleaning recovers more than it costs.

    recoverable_usd = (s₀/100)·E·τ·T − C

Equivalently, clean when soiling has passed the plant's break-even threshold:

    s* = C·100/(E·τ·T)          recoverable_usd > 0  ⟺  s₀ > s*

Those are the same statement, and the code computes both because they are not
equally useful to a human. A dollar total cannot be checked by eye; "2.29 points
past where cleaning pays for itself" can, against a plant whose soiling the asset
manager can see on a chart. So `margin_pct` leads the interface and the dollars
follow it. See DECISIONS.md #5.

Why the accumulation rate `r` is absent from the value
------------------------------------------------------
Both trajectories — cleaned and not cleaned — accumulate at the same rate, so
the gap between them stays at today's level and the rate cancels:

    ∫₀ᵀ(s₀ + r·t)dt − ∫₀ᵀ(r·t)dt = s₀·T

`r` is used only to answer "how many days until this plant becomes worth
cleaning", which is a scheduling question, not a valuation one.

Why `T` is not decremented
--------------------------
`days_until_next_reset` is read as the expected remaining wait of a memoryless
process, not a countdown, so elapsed days are not subtracted. Subtracting them
was my first instinct and would have been a bug: measured per region,
`1/P(reset per day)` agrees with the stated figure in four of five regions
(Andalusia 13 vs 12.0, Queensland 7 vs 8.0, Rajasthan 22 vs 27.7, Arizona 32 vs
26.3). Atacama is the exception at 45 vs 80.0 on only 3 rain days in 240
plant-days. ASSUMPTIONS.md A6.

Why `E` is a 14-day median
--------------------------
*Measured*: `expected_energy_kwh` moves a mean of 26% day over day (within-plant
CV 20.4% across the window), so today's single value is weather, not capacity.
That is not a rounding concern — it moves the break-even threshold by a mean of
0.518pp and up to 1.219pp against the 14-day median, and recommendations in this
fleet turn on margins as thin as 0.02pp.

The defensible claim is "not one day, and not the whole record", not "14 exactly":
7, 14 and 30 days all sit within 0.23pp of each other, while 1 day is 0.518pp
away and the full 120 days 0.440pp away in the other direction as seasonal drift
leaks in. 14 sits in the flat middle. Reproduced by `scripts/verify.py`.

Every function here is pure: no I/O, no clock, no database (DDIA ch.17).
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from .domain import DailyReading, DispatchStatus, EstimateStatus, Plant
from .estimator import SoilingEstimate

# Days of `expected_energy_kwh` behind E. See the module docstring.
EXPECTED_ENERGY_WINDOW_DAYS = 14


@dataclass(frozen=True)
class PlantEconomics:
    """The commercial case for cleaning one plant, with all of its inputs.

    Every input is carried alongside the conclusion on purpose. When a cleaning
    under-recovers, the only useful question is what was believed at the time,
    and that is unanswerable from a dollar figure alone.
    """

    plant_id: str
    as_of: date
    status: DispatchStatus

    soiling_loss_pct: float | None  # s₀
    break_even_soiling_pct: float  # s*
    margin_pct: float | None  # s₀ − s*
    recoverable_usd: float | None

    cleaning_cost_usd: float  # C
    expected_energy_kwh_per_day: float  # E
    tariff_per_kwh: float  # τ
    days_until_next_reset: int  # T

    accumulation_rate_pct_per_day: float | None  # r
    days_to_break_even: float | None
    usable_days: int
    days_since_reset: int | None
    last_reset_on: date | None

    @property
    def is_actionable(self) -> bool:
        return self.status is DispatchStatus.ACTIONABLE


def evaluate(
    plant: Plant,
    estimate: SoilingEstimate,
    readings: Sequence[DailyReading],
    as_of: date,
) -> PlantEconomics:
    """Value a cleaning at `plant` given today's soiling estimate.

    `readings` supplies E only; the soiling estimate has already been through the
    quality gate. Readings after `as_of` are ignored so a backtest cannot see the
    future.
    """
    expected_energy = expected_energy_per_day(readings, as_of)
    break_even = break_even_soiling_pct(
        cleaning_cost_usd=plant.cleaning_cost_usd,
        expected_energy_kwh_per_day=expected_energy,
        tariff_per_kwh=plant.tariff_per_kwh,
        days_until_next_reset=plant.days_until_next_reset,
    )

    soiling = estimate.soiling_loss_pct
    rate = estimate.accumulation_rate_pct_per_day

    if estimate.status is not EstimateStatus.ESTIMATED or soiling is None:
        # No estimate means no verdict. The plant is still returned — with its
        # break-even threshold, which depends only on the plant, so the asset
        # manager can see what it would take — but never with a dollar figure.
        return PlantEconomics(
            plant_id=plant.plant_id,
            as_of=as_of,
            status=DispatchStatus.INSUFFICIENT_HISTORY,
            soiling_loss_pct=None,
            break_even_soiling_pct=break_even,
            margin_pct=None,
            recoverable_usd=None,
            cleaning_cost_usd=plant.cleaning_cost_usd,
            expected_energy_kwh_per_day=expected_energy,
            tariff_per_kwh=plant.tariff_per_kwh,
            days_until_next_reset=plant.days_until_next_reset,
            accumulation_rate_pct_per_day=rate,
            days_to_break_even=None,
            usable_days=estimate.usable_days,
            days_since_reset=estimate.days_since_reset,
            last_reset_on=estimate.last_reset_on,
        )

    recoverable = recoverable_usd(
        soiling_loss_pct=soiling,
        expected_energy_kwh_per_day=expected_energy,
        tariff_per_kwh=plant.tariff_per_kwh,
        days_until_next_reset=plant.days_until_next_reset,
        cleaning_cost_usd=plant.cleaning_cost_usd,
    )
    margin = soiling - break_even

    return PlantEconomics(
        plant_id=plant.plant_id,
        as_of=as_of,
        status=(
            DispatchStatus.ACTIONABLE
            if recoverable > 0
            else DispatchStatus.BELOW_BREAK_EVEN
        ),
        soiling_loss_pct=soiling,
        break_even_soiling_pct=break_even,
        margin_pct=margin,
        recoverable_usd=recoverable,
        cleaning_cost_usd=plant.cleaning_cost_usd,
        expected_energy_kwh_per_day=expected_energy,
        tariff_per_kwh=plant.tariff_per_kwh,
        days_until_next_reset=plant.days_until_next_reset,
        accumulation_rate_pct_per_day=rate,
        days_to_break_even=days_to_break_even(margin, rate),
        usable_days=estimate.usable_days,
        days_since_reset=estimate.days_since_reset,
        last_reset_on=estimate.last_reset_on,
    )


def recoverable_usd(
    *,
    soiling_loss_pct: float,
    expected_energy_kwh_per_day: float,
    tariff_per_kwh: float,
    days_until_next_reset: int,
    cleaning_cost_usd: float,
) -> float:
    """The brief's formula. `soiling_loss_pct` is a percentage, hence the /100."""
    recovered_kwh = (
        soiling_loss_pct / 100.0 * expected_energy_kwh_per_day * days_until_next_reset
    )
    return recovered_kwh * tariff_per_kwh - cleaning_cost_usd


def break_even_soiling_pct(
    *,
    cleaning_cost_usd: float,
    expected_energy_kwh_per_day: float,
    tariff_per_kwh: float,
    days_until_next_reset: int,
) -> float:
    """Soiling at which a cleaning exactly pays for itself, in percentage points.

    A property of the plant alone — it does not move with today's reading — which
    is why the interface can show it as a fixed line to measure soiling against.
    """
    revenue_per_point = (
        expected_energy_kwh_per_day / 100.0 * tariff_per_kwh * days_until_next_reset
    )
    if revenue_per_point <= 0:
        # A plant with no expected generation, no tariff or no horizon can never
        # repay a cleaning. Returning infinity keeps every comparison downstream
        # well-defined instead of raising on a degenerate row.
        return float("inf")
    return cleaning_cost_usd / revenue_per_point


def days_to_break_even(margin_pct: float, rate_pct_per_day: float | None) -> float | None:
    """Days until a plant below break-even crosses it, at the measured rate.

    None when the plant is already past it, when no rate could be measured, or
    when the rate is not positive — a plant that is not getting dirtier has no
    arrival date, and inventing one would be false precision.
    """
    if margin_pct >= 0:
        return None
    if rate_pct_per_day is None or rate_pct_per_day <= 0:
        return None
    return -margin_pct / rate_pct_per_day


def expected_energy_per_day(readings: Sequence[DailyReading], as_of: date) -> float:
    """E — median `expected_energy_kwh` over the trailing window.

    Deliberately *not* filtered through the quality gate. `expected_energy_kwh`
    is a modelled figure for what the plant should have produced, so it survives
    the faults that make a reading's `pr` and `soiling_loss_pct` unusable. Gating
    it would discard capacity information that is still correct, and on
    `plant_1003` — six consecutive withheld days — would leave the estimate
    resting on a window that ended nearly a week earlier.

    Median rather than mean: `expected_energy_kwh` has a hard floor at zero and
    no ceiling, so overcast-to-clear runs skew a mean upward.
    """
    window_start = as_of - timedelta(days=EXPECTED_ENERGY_WINDOW_DAYS - 1)
    values = [
        r.expected_energy_kwh
        for r in readings
        if window_start <= r.reading_date <= as_of
    ]
    if not values:
        # Falls back to the whole history rather than to zero: a plant with no
        # readings in the window still has a capacity, and zero would silently
        # make its break-even infinite.
        values = [r.expected_energy_kwh for r in readings if r.reading_date <= as_of]
    return statistics.median(values) if values else 0.0
