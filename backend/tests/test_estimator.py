"""Tests for the soiling estimator.

Pure functions, so no database. The cases that matter are the ones that cost
money: windows crossing a reset, gated days leaking in, and lookahead.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from swishos import estimator
from swishos.domain import DailyReading, EstimateStatus, Plant, PlantDayEvent

START = date(2026, 9, 1)


def plant(days_until_next_reset: int = 32) -> Plant:
    return Plant(
        plant_id="plant_1010",
        name="Meridian Alpha (010)",
        region="Arizona, USA",
        capacity_mw=72.9,
        tariff_per_kwh=0.078,
        cleaning_cost_usd=34992.0,
        days_until_next_reset=days_until_next_reset,
        commissioned_on=date(2026, 6, 20),
    )


def readings(*soiling: float | None, pr: float = 0.93) -> list[DailyReading]:
    """One reading per day from START, in order."""
    return [
        DailyReading(
            plant_id="plant_1010",
            reading_date=START + timedelta(days=i),
            energy_kwh=100_000.0,
            expected_energy_kwh=110_000.0,
            pr=pr,
            soiling_loss_pct=value,
        )
        for i, value in enumerate(soiling)
    ]


def events(
    count: int,
    rain_on: dict[int, float] | None = None,
    cleaned_on: set[int] | None = None,
) -> list[PlantDayEvent]:
    rain_on = rain_on or {}
    cleaned_on = cleaned_on or set()
    return [
        PlantDayEvent(
            plant_id="plant_1010",
            event_date=START + timedelta(days=i),
            rain_mm=rain_on.get(i, 0.0),
            cleaned=i in cleaned_on,
        )
        for i in range(count)
    ]


def day(offset: int) -> date:
    return START + timedelta(days=offset)


class TestFindLastReset:
    def test_heavy_rain_resets(self):
        assert estimator.find_last_reset(events(5, rain_on={2: 12.0}), day(4)) == day(2)

    def test_light_rain_does_not_reset(self):
        assert estimator.find_last_reset(events(5, rain_on={2: 7.9}), day(4)) is None

    def test_cleaning_resets(self):
        assert estimator.find_last_reset(events(5, cleaned_on={3}), day(4)) == day(3)

    def test_returns_none_when_never_reset(self):
        assert estimator.find_last_reset(events(5), day(4)) is None

    def test_ignores_resets_after_as_of(self):
        """A backtest must not see tomorrow's rain."""
        assert estimator.find_last_reset(events(5, rain_on={4: 20.0}), day(2)) is None


class TestWindow:
    def test_requires_three_usable_days(self):
        result = estimator.estimate_soiling(
            plant(), readings(1.0, 2.0), events(2), day(1)
        )
        assert result.status is EstimateStatus.INSUFFICIENT_HISTORY
        assert result.usable_days == 2
        assert result.soiling_loss_pct is None

    def test_takes_the_three_most_recent_days(self):
        result = estimator.estimate_soiling(
            plant(), readings(1.0, 2.0, 3.0, 4.0, 5.0), events(5), day(4)
        )
        assert result.status is EstimateStatus.ESTIMATED
        assert result.soiling_loss_pct == 4.0  # median of the newest three: 5, 4, 3

    def test_gated_days_are_skipped_not_counted(self):
        history = readings(1.0, 2.0, 3.0, 4.0, 5.0)
        history[3] = DailyReading(
            plant_id="plant_1010",
            reading_date=history[3].reading_date,
            energy_kwh=4_000.0,
            expected_energy_kwh=110_000.0,
            pr=0.036,  # availability anomaly
            soiling_loss_pct=96.0,
        )
        result = estimator.estimate_soiling(plant(), history, events(5), day(4))
        assert result.soiling_loss_pct == 3.0  # median of 5, 3, 2 — the 96.0 never enters

    def test_ignores_readings_after_as_of(self):
        result = estimator.estimate_soiling(
            plant(), readings(1.0, 2.0, 3.0, 4.0, 99.0), events(5), day(3)
        )
        assert result.soiling_loss_pct == 3.0  # median of 4, 3, 2


class TestResetBoundary:
    """plant_1010's real numbers: cleaned with 24.4mm of rain on 2026-09-10.

    The reading stamped on the reset day still describes the dirty plant — the
    wash only reaches the next day's generation. Including it, a naive three-day
    median on the following day returns 6.22% against a 3.10% break-even, claims
    +$35,238 recoverable, and dispatches a $34,992 cleaning to a plant cleaned
    the day before.
    """

    HISTORY = (6.22, 6.28, 0.0, 0.25, 0.46, 0.63)
    EVENTS_KWARGS = {"rain_on": {1: 24.4}, "cleaned_on": {1}}

    def history(self):
        return readings(*self.HISTORY), events(6, **self.EVENTS_KWARGS)

    def test_reset_day_reading_is_excluded(self):
        history, event_log = self.history()
        result = estimator.estimate_soiling(plant(), history, event_log, day(3))
        assert result.last_reset_on == day(1)
        assert result.usable_days == 2, "only the two days after the wash may count"
        assert result.status is EstimateStatus.INSUFFICIENT_HISTORY

    def test_holds_the_day_after_a_reset(self):
        """The dangerous day: a naive window here is majority pre-reset."""
        history, event_log = self.history()
        result = estimator.estimate_soiling(plant(), history, event_log, day(2))
        assert result.usable_days == 1
        assert result.status is EstimateStatus.INSUFFICIENT_HISTORY
        assert result.soiling_loss_pct is None

    def test_estimates_once_three_clean_days_exist(self):
        history, event_log = self.history()
        result = estimator.estimate_soiling(plant(), history, event_log, day(4))
        assert result.status is EstimateStatus.ESTIMATED
        assert result.soiling_loss_pct == 0.25  # median of 0.46, 0.25, 0.0
        assert result.days_since_reset == 3

    def test_never_returns_a_pre_reset_value(self):
        history, event_log = self.history()
        for offset in range(2, 6):
            result = estimator.estimate_soiling(plant(), history, event_log, day(offset))
            if result.soiling_loss_pct is not None:
                assert result.soiling_loss_pct < 1.0, (
                    f"day {offset} leaked a pre-wash reading"
                )


class TestAccumulationRate:
    def test_measures_median_daily_rise(self):
        assert estimator.fit_accumulation_rate(
            readings(1.0, 1.2, 1.4, 1.6), events(4)
        ) == pytest.approx(0.2)

    def test_excludes_pairs_spanning_a_reset(self):
        """Without this the washing day reads as a huge negative accumulation."""
        assert estimator.fit_accumulation_rate(
            readings(5.0, 5.3, 0.1, 0.4, 0.7), events(5, rain_on={2: 15.0})
        ) == pytest.approx(0.3)

    def test_returns_none_without_usable_pairs(self):
        assert estimator.fit_accumulation_rate(readings(1.0), events(1)) is None

    def test_is_reported_even_when_the_estimate_is_withheld(self):
        """The rate answers 'how soon will this be worth cleaning', so it is
        still useful on a plant too freshly reset to rank."""
        result = estimator.estimate_soiling(
            plant(), readings(1.0, 1.2), events(2), day(1)
        )
        assert result.status is EstimateStatus.INSUFFICIENT_HISTORY
        assert result.accumulation_rate_pct_per_day == pytest.approx(0.2)
