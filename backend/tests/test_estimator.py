"""Tests for the soiling reading and the accumulation rate.

Pure functions, so no database. What is left to test after the estimator was
reduced to "today's gated reading" is narrow but load-bearing: that a withheld
day produces no estimate rather than a plausible-looking wrong one, that nothing
peeks at tomorrow, and that the accumulation rate excludes the days a wash
touched.
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


class TestTodaysReading:
    def test_uses_todays_value(self):
        result = estimator.estimate_soiling(
            plant(), readings(1.0, 2.0, 3.0), events(3), day(2)
        )
        assert result.status is EstimateStatus.ESTIMATED
        assert result.soiling_loss_pct == 3.0

    def test_ignores_readings_after_as_of(self):
        """A backtest must not see tomorrow."""
        result = estimator.estimate_soiling(
            plant(), readings(1.0, 2.0, 99.0), events(3), day(1)
        )
        assert result.soiling_loss_pct == 2.0

    def test_withheld_day_yields_no_estimate(self):
        """The gate's verdict has to survive into the estimate. A plant at 96%
        reported loss and pr 0.036 must produce no number at all — a wrong
        number here buys a cleaning that recovers nothing."""
        history = readings(1.0, 2.0)
        history.append(
            DailyReading(
                plant_id="plant_1010",
                reading_date=day(2),
                energy_kwh=4_000.0,
                expected_energy_kwh=110_000.0,
                pr=0.036,
                soiling_loss_pct=96.0,
            )
        )
        result = estimator.estimate_soiling(plant(), history, events(3), day(2))
        assert result.status is EstimateStatus.NO_USABLE_READING
        assert result.soiling_loss_pct is None
        assert result.usable_days == 0

    def test_blank_baseline_yields_no_estimate(self):
        result = estimator.estimate_soiling(
            plant(), readings(1.0, None), events(2), day(1)
        )
        assert result.status is EstimateStatus.NO_USABLE_READING
        assert result.soiling_loss_pct is None

    def test_missing_day_yields_no_estimate(self):
        """No row for today at all, rather than an unusable one."""
        result = estimator.estimate_soiling(
            plant(), readings(1.0, 2.0), events(5), day(4)
        )
        assert result.status is EstimateStatus.NO_USABLE_READING


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
        assert estimator.find_last_reset(events(5, rain_on={4: 20.0}), day(2)) is None

    def test_days_since_reset_is_reported(self):
        result = estimator.estimate_soiling(
            plant(), readings(5.0, 0.1, 0.4, 0.7), events(4, rain_on={1: 24.4}), day(3)
        )
        assert result.last_reset_on == day(1)
        assert result.days_since_reset == 2
        # The day after a wash is no longer a special case: the published value
        # is already re-baselined, so today's reading is the post-wash one.
        assert result.soiling_loss_pct == 0.7


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

    def test_is_reported_even_when_today_is_withheld(self):
        """The rate answers 'how soon will this be worth cleaning', so it is
        still useful on a plant whose reading today was withheld."""
        history = readings(1.0, 1.2, 1.4)
        history.append(
            DailyReading(
                plant_id="plant_1010",
                reading_date=day(3),
                energy_kwh=4_000.0,
                expected_energy_kwh=110_000.0,
                pr=0.036,
                soiling_loss_pct=96.0,
            )
        )
        result = estimator.estimate_soiling(plant(), history, events(4), day(3))
        assert result.status is EstimateStatus.NO_USABLE_READING
        assert result.accumulation_rate_pct_per_day == pytest.approx(0.2)
