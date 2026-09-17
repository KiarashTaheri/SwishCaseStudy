"""Estimate s₀ — today's soiling — for one plant.

What this must estimate, and what it must not
---------------------------------------------
Cleaning does not recover the *forward mean* soiling. Both trajectories, cleaned
and uncleaned, accumulate at the same rate `r`, so the gap between them stays
constant at today's level:

    ∫₀ᵀ(s₀ + r·t)dt − ∫₀ᵀ(r·t)dt = s₀·T

The benefit is `s₀·T`, which is exactly the brief's formula. So the job here is
to estimate **today's soiling**, nothing more. Projecting the estimate forward by
`r·T/2` — the forward mean of the uncleaned plant — double-counts accumulation
that cancels out of the difference. Measured, it is 10–13× worse and dispatches
on almost everything (341 false calls against 18). See DECISIONS.md #2.

Choosing the window
-------------------
Scored over 1,126 plant-days against a centred median of gated values inside the
same reset interval (a low-noise view of today, using future data as evaluation
only). A false dispatch is charged the money it wastes, a missed clean the money
it forgoes:

    estimator     ranked  false  missed   error cost
    median/1        1126     25       2     $486,834
    median/2        1028     19      14     $348,907   <- lowest
    median/3         938     18      25     $367,390   <- shipped
    median/5         783     17      48     $435,111
    median/10        497     15     107     $746,138

Three, not two: the two are within 5% of each other and $18k over 1,126
decisions is not resolvable at 12 plants, but a median of two values is just
their mean and tolerates no bad day at all. Three is the shortest window where
the median has any breakdown point. Ten is included to show that the fixed
14-day window is materially worse — it misses 107 profitable cleanings.

Median rather than mean: behind the quality gate the two are indistinguishable
(MAE 1.832 against 1.831), because the gate has already removed the outliers a
median would resist. It is kept as insurance against the partial-fault blind
spot the gate cannot see (ASSUMPTIONS.md A2b), not because it measurably wins.

The window never crosses a reset. A window spanning one averages a dirty plant
with a clean one: on plant_1010 that is a $52,052 swing on a single day's
recommendation.

Every function is pure and sees only data at or before `as_of` — no lookahead,
no clock, no I/O (DDIA ch.17 "Determinism").
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from . import gates
from .domain import DailyReading, EstimateStatus, Plant, PlantDayEvent

# Rainfall that resets the panels. Brief: "roughly 8mm or more washes the panels
# clean". Treated as a full reset — measured residual is 1.37% (ASSUMPTIONS.md A7).
RESET_RAIN_MM = 8.0

# Usable days since the last reset required to estimate. See the module docstring.
WINDOW_DAYS = 3


@dataclass(frozen=True)
class SoilingEstimate:
    """s₀ for one plant, plus the evidence behind it.

    `accumulation_rate_pct_per_day` is reported for planning — it answers "how
    many days until this plant crosses break-even" — and is deliberately absent
    from the value calculation, where it cancels.
    """

    plant_id: str
    as_of: date
    status: EstimateStatus
    soiling_loss_pct: float | None
    accumulation_rate_pct_per_day: float | None
    usable_days: int
    days_since_reset: int | None
    last_reset_on: date | None

    @property
    def is_rankable(self) -> bool:
        return self.status is EstimateStatus.ESTIMATED


def estimate_soiling(
    plant: Plant,
    readings: Sequence[DailyReading],
    events: Sequence[PlantDayEvent],
    as_of: date,
) -> SoilingEstimate:
    """Estimate one plant's soiling as of `as_of`.

    `readings` and `events` may cover any span; anything after `as_of` is ignored
    so a backtest cannot see the future. Both must be for a single plant.
    """
    history = [r for r in readings if r.reading_date <= as_of]
    past_events = [e for e in events if e.event_date <= as_of]
    last_reset = find_last_reset(past_events, as_of)

    window = _window_since_reset(history, last_reset)
    rate = fit_accumulation_rate(history, past_events)
    days_since_reset = (as_of - last_reset).days if last_reset else None

    status = (
        EstimateStatus.ESTIMATED
        if len(window) >= WINDOW_DAYS
        else EstimateStatus.INSUFFICIENT_HISTORY
    )
    return SoilingEstimate(
        plant_id=plant.plant_id,
        as_of=as_of,
        status=status,
        soiling_loss_pct=(
            statistics.median(window) if status is EstimateStatus.ESTIMATED else None
        ),
        accumulation_rate_pct_per_day=rate,
        usable_days=len(window),
        days_since_reset=days_since_reset,
        last_reset_on=last_reset,
    )


def find_last_reset(events: Sequence[PlantDayEvent], as_of: date) -> date | None:
    """Most recent day on or before `as_of` when the panels were reset.

    The reset day's own reading still describes the dirty plant — rain on day d
    shows up in soiling on day d+1 — so callers must exclude it from the window.
    """
    resets = [
        e.event_date
        for e in events
        if e.event_date <= as_of and (e.rain_mm >= RESET_RAIN_MM or e.cleaned)
    ]
    return max(resets) if resets else None


def fit_accumulation_rate(
    readings: Sequence[DailyReading], events: Sequence[PlantDayEvent]
) -> float | None:
    """Points of soiling gained per day, from consecutive undisturbed days.

    Median of day-over-day changes rather than a regression slope: it needs no
    window choice, tolerates the occasional bad pair, and only requires that most
    days be ordinary. Pairs spanning any rainfall or cleaning are excluded, since
    those reflect washing rather than accumulation.

    Not used to value a cleaning (it cancels — see the module docstring). Used to
    tell the asset manager how soon a plant will become worth cleaning.
    """
    disturbed = {
        e.event_date for e in events if e.rain_mm >= RESET_RAIN_MM or e.cleaned
    }
    usable = {r.reading_date: r for r in gates.usable_readings(readings)}

    deltas: list[float] = []
    for reading in readings:
        today = reading.reading_date
        yesterday = today - timedelta(days=1)
        if today in disturbed or yesterday in disturbed:
            continue
        if today not in usable or yesterday not in usable:
            continue
        current, previous = usable[today].soiling_loss_pct, usable[yesterday].soiling_loss_pct
        if current is None or previous is None:
            continue
        deltas.append(current - previous)

    return statistics.median(deltas) if deltas else None


def _window_since_reset(
    readings: Sequence[DailyReading], last_reset: date | None
) -> list[float]:
    """Most recent usable soiling values since the reset, newest first.

    Capped at WINDOW_DAYS. Readings on or before the reset day are excluded: the
    reset day's reading is taken before the wash takes effect, so it describes a
    plant that no longer exists.
    """
    values: list[float] = []
    for reading in sorted(readings, key=lambda r: r.reading_date, reverse=True):
        if last_reset is not None and reading.reading_date <= last_reset:
            break
        if not gates.assess_reading(reading).is_usable:
            continue
        if reading.soiling_loss_pct is None:  # unreachable via the gate; belt and braces
            continue
        values.append(reading.soiling_loss_pct)
        if len(values) == WINDOW_DAYS:
            break
    return values


def estimate_fleet(
    plants: Iterable[Plant],
    readings_by_plant: dict[str, Sequence[DailyReading]],
    events_by_plant: dict[str, Sequence[PlantDayEvent]],
    as_of: date,
) -> list[SoilingEstimate]:
    """Estimate every plant. Plants with no data still get a verdict."""
    return [
        estimate_soiling(
            plant,
            readings_by_plant.get(plant.plant_id, ()),
            events_by_plant.get(plant.plant_id, ()),
            as_of,
        )
        for plant in plants
    ]
