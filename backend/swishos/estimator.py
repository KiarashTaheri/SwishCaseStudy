"""Read today's soiling for one plant, and how fast it is accumulating.

What this does, and why it is so small
--------------------------------------
`s₀` is today's gated `soiling_loss_pct`. That is the brief's own input, and
after an earlier detour it is the one I can defend.

The detour is worth recording, because it was two mistakes in a row. First I
projected soiling forward by `r·T/2` — the forward *mean* of the uncleaned
plant. That is wrong on paper: both trajectories, cleaned and uncleaned,
accumulate at the same rate, so the gap between them stays at today's level and
the rate cancels out of the difference:

    ∫₀ᵀ(s₀ + r·t)dt − ∫₀ᵀ(r·t)dt = s₀·T

Measured, the projection was 10–13× worse and dispatched on almost everything.
So I removed it and replaced it with a 3-day trailing median — smoothing rather
than projecting. That was also wrong, in the opposite direction: a *trailing*
median lags. Soiling climbs a median 0.240pp/day, so a 3-day median describes
the plant as it was a day ago, reads too clean, and skips cleanings worth doing.
Measured on plant_1000 on 2026-08-01, it read 0.65pp low, fell below break-even,
and passed on a $6,414 gain. 24 plant-days go that way.

Both detours shared a cause: I was smoothing a quantity that does not need it.
`soiling_loss_pct` is a **state** — what the plant's deficit is today — and the
quality gate has already removed the readings that are not credible as dirt.
What remains moves 0.240pp on a median day and never more than 1.56pp. There is
no noise left for a median to defend against, only lag for it to introduce.

Contrast `expected_energy_kwh`, which the formula multiplies by `T` and which
therefore *does* get smoothed — see `economics.py`. One is a state measured
today; the other is a rate projected over a month. They are different
quantities and they get different treatment. That distinction is the whole of
this decision.

What is still computed here
---------------------------
`r`, the accumulation rate, and the last reset date. Neither values a cleaning —
`r` cancels, as above. They answer the asset manager's other question, "how soon
will this plant be worth cleaning", and they give the interface its context.

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


@dataclass(frozen=True)
class SoilingEstimate:
    """Today's soiling for one plant, plus the evidence behind it.

    `accumulation_rate_pct_per_day` is reported for planning and is deliberately
    absent from the value calculation, where it cancels.
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
    """Today's soiling at `plant`, or a refusal with its reason.

    `readings` and `events` may cover any span; anything after `as_of` is ignored
    so a backtest cannot see the future. Both must be for a single plant.
    """
    history = [r for r in readings if r.reading_date <= as_of]
    past_events = [e for e in events if e.event_date <= as_of]
    last_reset = find_last_reset(past_events, as_of)

    today = next((r for r in history if r.reading_date == as_of), None)
    usable = today is not None and gates.assess_reading(today).is_usable
    # `usable` implies a non-None soiling value — the gate rejects blanks — but
    # the check is repeated so a future gate change cannot make this unsound
    # silently.
    soiling = today.soiling_loss_pct if usable and today is not None else None

    return SoilingEstimate(
        plant_id=plant.plant_id,
        as_of=as_of,
        status=(
            EstimateStatus.ESTIMATED
            if soiling is not None
            else EstimateStatus.NO_USABLE_READING
        ),
        soiling_loss_pct=soiling,
        accumulation_rate_pct_per_day=fit_accumulation_rate(history, past_events),
        usable_days=1 if soiling is not None else 0,
        days_since_reset=(as_of - last_reset).days if last_reset else None,
        last_reset_on=last_reset,
    )


def find_last_reset(events: Sequence[PlantDayEvent], as_of: date) -> date | None:
    """Most recent day on or before `as_of` when the panels were reset.

    Rain on day d shows up in soiling on day d+1, so the reset day's own reading
    still describes the dirty plant. That mattered a great deal when the estimate
    spanned several days; with a single day it does not, because the published
    `soiling_loss_pct` is re-baselined at the reset and today's value is already
    the post-wash one. Kept for the interface, which shows how long a plant has
    been accumulating.
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
        current = usable[today].soiling_loss_pct
        previous = usable[yesterday].soiling_loss_pct
        if current is None or previous is None:
            continue
        deltas.append(current - previous)

    return statistics.median(deltas) if deltas else None


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
