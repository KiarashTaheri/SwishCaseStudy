"""Tests for the physical-plausibility gate.

The gate is pure, so these run with no database and no fixtures. Cases are drawn
from real rows in the default dataset wherever one exists, so a failure points
at a concrete plant-day rather than an invented one.
"""

from __future__ import annotations

from datetime import date

import pytest

from swishos import gates
from swishos.domain import DailyReading, QualityFlag


def reading(
    pr: float | None = 0.93,
    soiling_loss_pct: float | None = 4.0,
    plant_id: str = "plant_1000",
    day: date = date(2026, 9, 14),
) -> DailyReading:
    return DailyReading(
        plant_id=plant_id,
        reading_date=day,
        energy_kwh=100_000.0,
        expected_energy_kwh=110_000.0,
        pr=pr,
        soiling_loss_pct=soiling_loss_pct,
    )


@pytest.mark.parametrize(
    ("pr", "soiling_loss_pct", "expected", "why"),
    [
        (0.93, 4.0, QualityFlag.USABLE, "healthy reading"),
        (None, 4.0, QualityFlag.MISSING_PERFORMANCE_RATIO, "no pr published"),
        (0.0196, 97.98, QualityFlag.AVAILABILITY_ANOMALY, "plant_1003 outage day"),
        (0.3899, 60.18, QualityFlag.AVAILABILITY_ANOMALY, "worst dropout in fleet"),
        (0.93, None, QualityFlag.MISSING_SOILING_BASELINE, "no baseline yet"),
        (0.93, -0.01, QualityFlag.NEGATIVE_SOILING, "plant_1004's single negative"),
        (0.93, 0.0, QualityFlag.USABLE, "exactly clean is not missing"),
    ],
)
def test_assess_reading_classifies(pr, soiling_loss_pct, expected, why):
    assert gates.assess_reading(reading(pr, soiling_loss_pct)).flag is expected, why


def test_availability_outranks_missing_baseline():
    """plant_1010 2026-07-09 is both: pr 0.3804 with no baseline yet.

    Reporting it as a missing baseline would hide that the plant was producing
    almost nothing, which is the more urgent fact. This ordering is why the
    gate returns 184 MISSING_SOILING_BASELINE for 185 blank rows.
    """
    assessment = gates.assess_reading(reading(pr=0.3804, soiling_loss_pct=None))
    assert assessment.flag is QualityFlag.AVAILABILITY_ANOMALY


def test_anomaly_detail_carries_the_evidence():
    detail = gates.assess_reading(reading(pr=0.0196, soiling_loss_pct=97.98)).detail
    assert "0.0196" in detail
    assert "A1/A2" in detail, "detail must point at the assumption it relies on"


def test_floor_itself_is_not_gated():
    """The comparison is strict: a reading exactly at the floor stays usable."""
    assert gates.assess_reading(reading(pr=gates.MIN_CREDIBLE_PR)).flag is (
        QualityFlag.USABLE
    )


def test_zero_soiling_survives_the_gate():
    """Guards against testing falsiness instead of None.

    0.0% loss is a perfectly clean plant. The default dataset has 185 blank
    rows and many at exactly 0.00; conflating the two would silently discard
    clean days and bias every estimate upward.
    """
    assert gates.assess_reading(reading(soiling_loss_pct=0.0)).flag is (
        QualityFlag.USABLE
    )


def test_every_reading_receives_a_verdict():
    readings = [reading(), reading(pr=None), reading(soiling_loss_pct=-1.0)]
    assert len(gates.assess_readings(readings)) == len(readings)


def test_usable_readings_filters_to_usable_only():
    readings = [reading(), reading(pr=0.1), reading(soiling_loss_pct=None)]
    assert gates.usable_readings(readings) == [readings[0]]


class TestEmptyBand:
    """Covers assumption A2b: the threshold is only free while the gap is."""

    def test_reports_the_gap_measured_in_the_default_dataset(self):
        check = gates.verify_empty_band(
            [reading(pr=0.3899), reading(pr=0.8664), reading(pr=0.95)]
        )
        assert check.highest_pr_below_floor == 0.3899
        assert check.lowest_pr_above_floor == 0.8664
        assert check.band_width == pytest.approx(0.4765)
        assert check.is_intact

    def test_detects_populations_merging_around_the_floor(self):
        check = gates.verify_empty_band([reading(pr=0.48), reading(pr=0.93)])
        assert not check.is_intact
        assert check.readings_within_margin == 1

    def test_no_gated_readings_counts_as_intact(self):
        """Nothing below the floor means nothing can be wrongly discarded."""
        check = gates.verify_empty_band([reading(pr=0.93), reading(pr=0.95)])
        assert check.highest_pr_below_floor is None
        assert check.band_width is None
        assert check.is_intact

    def test_ignores_readings_with_no_pr(self):
        check = gates.verify_empty_band([reading(pr=None), reading(pr=0.93)])
        assert check.highest_pr_below_floor is None
        assert check.lowest_pr_above_floor == 0.93
