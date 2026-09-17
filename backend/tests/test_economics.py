"""Tests for the cleaning economics.

Pure functions, so no database. The cases worth writing are the ones where being
wrong sends a truck: the break-even boundary, the accumulation rate leaking into
a value it must not appear in, and a missing estimate producing a dollar figure
anyway.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from swishos import economics
from swishos.domain import DailyReading, DispatchStatus, EstimateStatus, Plant
from swishos.estimator import SoilingEstimate

AS_OF = date(2026, 9, 14)


def plant(**overrides) -> Plant:
    defaults = dict(
        plant_id="plant_1000",
        name="Sunfield Alpha (000)",
        region="Arizona, USA",
        capacity_mw=68.9,
        tariff_per_kwh=0.078,
        cleaning_cost_usd=33072.0,
        days_until_next_reset=32,
        commissioned_on=date(2026, 1, 1),
    )
    return Plant(**{**defaults, **overrides})


def estimate(
    soiling: float | None = 5.23,
    rate: float | None = 0.245,
    status: EstimateStatus = EstimateStatus.ESTIMATED,
) -> SoilingEstimate:
    return SoilingEstimate(
        plant_id="plant_1000",
        as_of=AS_OF,
        status=status,
        soiling_loss_pct=soiling,
        accumulation_rate_pct_per_day=rate,
        usable_days=3,
        days_since_reset=24,
        last_reset_on=date(2026, 8, 21),
    )


def readings(expected: float = 451323.4, days: int = 14) -> list[DailyReading]:
    return [
        DailyReading(
            plant_id="plant_1000",
            reading_date=AS_OF - timedelta(days=i),
            energy_kwh=expected * 0.95,
            expected_energy_kwh=expected,
            pr=0.93,
            soiling_loss_pct=5.0,
        )
        for i in range(days)
    ]


class TestBreakEven:
    def test_matches_the_briefs_formula_at_the_boundary(self):
        """s* and `recoverable_usd > 0` must be the same statement.

        They are derived from each other on paper. If they ever disagree in
        code, one of the two numbers on screen is lying.
        """
        p = plant()
        star = economics.break_even_soiling_pct(
            cleaning_cost_usd=p.cleaning_cost_usd,
            expected_energy_kwh_per_day=451323.4,
            tariff_per_kwh=p.tariff_per_kwh,
            days_until_next_reset=p.days_until_next_reset,
        )
        at_threshold = economics.recoverable_usd(
            soiling_loss_pct=star,
            expected_energy_kwh_per_day=451323.4,
            tariff_per_kwh=p.tariff_per_kwh,
            days_until_next_reset=p.days_until_next_reset,
            cleaning_cost_usd=p.cleaning_cost_usd,
        )
        assert at_threshold == pytest.approx(0.0, abs=1e-6)

    def test_just_above_pays_and_just_below_does_not(self):
        p = plant()
        kwargs = dict(
            expected_energy_kwh_per_day=451323.4,
            tariff_per_kwh=p.tariff_per_kwh,
            days_until_next_reset=p.days_until_next_reset,
            cleaning_cost_usd=p.cleaning_cost_usd,
        )
        star = economics.break_even_soiling_pct(
            cleaning_cost_usd=p.cleaning_cost_usd,
            expected_energy_kwh_per_day=451323.4,
            tariff_per_kwh=p.tariff_per_kwh,
            days_until_next_reset=p.days_until_next_reset,
        )
        assert economics.recoverable_usd(soiling_loss_pct=star + 0.01, **kwargs) > 0
        assert economics.recoverable_usd(soiling_loss_pct=star - 0.01, **kwargs) < 0

    def test_degenerate_plant_never_repays(self):
        """No tariff, no horizon or no generation must not divide by zero."""
        assert (
            economics.break_even_soiling_pct(
                cleaning_cost_usd=1000.0,
                expected_energy_kwh_per_day=0.0,
                tariff_per_kwh=0.078,
                days_until_next_reset=32,
            )
            == float("inf")
        )


class TestEvaluate:
    def test_actionable_above_break_even(self):
        result = economics.evaluate(plant(), estimate(), readings(), AS_OF)
        assert result.status is DispatchStatus.ACTIONABLE
        assert result.margin_pct == pytest.approx(2.294, abs=1e-3)
        assert result.recoverable_usd == pytest.approx(25844.12, abs=0.01)
        assert result.days_to_break_even is None  # already past it

    def test_below_break_even_reports_an_arrival_date(self):
        result = economics.evaluate(
            plant(), estimate(soiling=2.0), readings(), AS_OF
        )
        assert result.status is DispatchStatus.BELOW_BREAK_EVEN
        assert result.recoverable_usd < 0
        # (2.936 - 2.0) / 0.245
        assert result.days_to_break_even == pytest.approx(3.82, abs=0.01)

    def test_rate_does_not_change_the_value(self):
        """The accumulation rate cancels out of the gain. If a future change
        makes `recoverable_usd` move with `r`, the constant-gap derivation in
        the estimator docstring has been broken. See DECISIONS.md #2."""
        slow = economics.evaluate(plant(), estimate(rate=0.01), readings(), AS_OF)
        fast = economics.evaluate(plant(), estimate(rate=5.00), readings(), AS_OF)
        assert slow.recoverable_usd == fast.recoverable_usd

    def test_no_estimate_yields_no_dollar_figure(self):
        result = economics.evaluate(
            plant(),
            estimate(soiling=None, status=EstimateStatus.INSUFFICIENT_HISTORY),
            readings(),
            AS_OF,
        )
        assert result.status is DispatchStatus.INSUFFICIENT_HISTORY
        assert result.recoverable_usd is None
        assert result.margin_pct is None
        # The threshold depends only on the plant, so it is still knowable and
        # still useful: it says what it would take.
        assert result.break_even_soiling_pct > 0

    def test_days_to_break_even_none_when_plant_is_not_getting_dirtier(self):
        """A flat or falling rate has no arrival date. Returning a negative
        number of days, or infinity, would render as false precision."""
        for rate in (0.0, -0.1, None):
            result = economics.evaluate(
                plant(), estimate(soiling=1.0, rate=rate), readings(), AS_OF
            )
            assert result.days_to_break_even is None


class TestExpectedEnergy:
    def test_uses_the_trailing_window_not_today(self):
        history = readings(expected=100_000.0, days=14)
        history[0] = DailyReading(  # today is overcast
            plant_id="plant_1000",
            reading_date=AS_OF,
            energy_kwh=5_000.0,
            expected_energy_kwh=10_000.0,
            pr=0.93,
            soiling_loss_pct=5.0,
        )
        assert economics.expected_energy_per_day(history, AS_OF) == 100_000.0

    def test_ignores_readings_after_as_of(self):
        history = readings(expected=100_000.0, days=14)
        history.append(
            DailyReading(
                plant_id="plant_1000",
                reading_date=AS_OF + timedelta(days=1),
                energy_kwh=0.0,
                expected_energy_kwh=999_999.0,
                pr=0.93,
                soiling_loss_pct=5.0,
            )
        )
        assert economics.expected_energy_per_day(history, AS_OF) == 100_000.0

    def test_is_not_filtered_by_the_quality_gate(self):
        """`expected_energy_kwh` is a modelled capacity figure, so it survives
        the faults that make `pr` and `soiling_loss_pct` unusable. Gating it
        would leave plant_1003 — six consecutive withheld days — estimating E
        from a window that ended nearly a week earlier.
        """
        history = readings(expected=100_000.0, days=14)
        broken = [
            DailyReading(
                plant_id="plant_1000",
                reading_date=r.reading_date,
                energy_kwh=2_000.0,
                expected_energy_kwh=r.expected_energy_kwh,
                pr=0.0196,  # availability anomaly
                soiling_loss_pct=97.99,
            )
            for r in history[:6]
        ]
        assert (
            economics.expected_energy_per_day(broken + history[6:], AS_OF) == 100_000.0
        )

    def test_falls_back_to_full_history_rather_than_zero(self):
        """An empty window must not silently make break-even infinite."""
        old = [
            DailyReading(
                plant_id="plant_1000",
                reading_date=AS_OF - timedelta(days=90),
                energy_kwh=1.0,
                expected_energy_kwh=50_000.0,
                pr=0.9,
                soiling_loss_pct=1.0,
            )
        ]
        assert economics.expected_energy_per_day(old, AS_OF) == 50_000.0
