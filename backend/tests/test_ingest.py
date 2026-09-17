"""Tests for the CSV trust boundary and the ingest/gate pipeline.

Fixtures are written to disk rather than mocked: the behaviour under test is
parsing real files, and a mock would only assert that the mock was called.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from swishos.db import apply_schema, connect
from swishos.domain import QualityFlag
from swishos.ingest import IngestError, ingest_dataset, read_daily_readings
from swishos.quality import apply_quality_gate, load_daily_readings

PLANTS = """plant_id,name,region,capacity_mw,tariff_per_kwh,cleaning_cost_usd,days_until_next_reset,commissioned_on
plant_1000,Sunfield Alpha (000),"Arizona, USA",68.9,0.078,33072.0,32,2025-03-02
"""

CREWS = """crew_id,home_base,mw_per_day,day_rate_usd
crew_10,"Phoenix, AZ",12.9,1569.06
"""

# Row 2 carries a blank pr and a blank soiling_loss_pct, exactly as daily.csv
# does before a plant has a clean baseline.
DAILY = """plant_id,date,energy_kwh,expected_energy_kwh,pr,soiling_loss_pct
plant_1000,2026-09-13,100000.0,110000.0,0.9091,4.0
plant_1000,2026-09-14,90000.0,110000.0,,
"""

EVENTS = """plant_id,date,rain_mm,cleaned
plant_1000,2026-09-13,0.0,0
plant_1000,2026-09-14,12.5,1
"""


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    for name, body in (
        ("plants.csv", PLANTS),
        ("crews.csv", CREWS),
        ("daily.csv", DAILY),
        ("events.csv", EVENTS),
    ):
        (tmp_path / name).write_text(body)
    return tmp_path


@pytest.fixture
def connection(tmp_path: Path):
    conn = connect(tmp_path / "test.db")
    apply_schema(conn)
    yield conn
    conn.close()


def test_blank_numeric_columns_become_none_not_zero(data_dir: Path):
    """The distinction the whole gate depends on.

    A blank soiling loss means "unmeasurable"; 0.0 means "perfectly clean".
    Coercing the first into the second would present an unknown plant as an
    ideal one.
    """
    readings = read_daily_readings(data_dir / "daily.csv")
    assert readings[1].pr is None
    assert readings[1].soiling_loss_pct is None
    assert readings[0].pr == 0.9091


def test_reads_typed_domain_objects(data_dir: Path):
    readings = read_daily_readings(data_dir / "daily.csv")
    assert readings[0].reading_date == date(2026, 9, 13)
    assert isinstance(readings[0].energy_kwh, float)


def test_ingest_counts_every_row(connection, data_dir: Path):
    summary = ingest_dataset(connection, data_dir)
    assert (summary.plants, summary.crews, summary.daily_readings, summary.events) == (
        1,
        1,
        2,
        2,
    )


def test_ingest_is_idempotent(connection, data_dir: Path):
    """Re-running must not duplicate rows — the pipeline is rebuilt, not appended."""
    ingest_dataset(connection, data_dir)
    ingest_dataset(connection, data_dir)
    count = connection.execute("SELECT COUNT(*) FROM daily_reading").fetchone()[0]
    assert count == 2


def test_gate_materialises_one_verdict_per_reading(connection, data_dir: Path):
    ingest_dataset(connection, data_dir)
    summary = apply_quality_gate(connection)
    assert summary.total == 2
    assert summary.counts_by_flag[QualityFlag.USABLE.value] == 1
    assert summary.counts_by_flag[QualityFlag.MISSING_PERFORMANCE_RATIO.value] == 1


def test_gate_rebuild_replaces_rather_than_appends(connection, data_dir: Path):
    ingest_dataset(connection, data_dir)
    apply_quality_gate(connection)
    apply_quality_gate(connection)
    count = connection.execute("SELECT COUNT(*) FROM reading_quality").fetchone()[0]
    assert count == 2


def test_readings_load_in_chronological_order(connection, data_dir: Path):
    """The since-last-reset window is order-dependent and SQLite guarantees none."""
    ingest_dataset(connection, data_dir)
    dates = [r.reading_date for r in load_daily_readings(connection)]
    assert dates == sorted(dates)


class TestRejectsMalformedInput:
    """Every failure names the file, the line and the column."""

    def test_missing_file(self, tmp_path: Path):
        with pytest.raises(IngestError, match="file not found"):
            read_daily_readings(tmp_path / "daily.csv")

    def test_non_numeric_value(self, data_dir: Path):
        (data_dir / "daily.csv").write_text(
            DAILY.replace("100000.0,110000.0", "not_a_number,110000.0")
        )
        with pytest.raises(IngestError, match=r"daily\.csv:2.*energy_kwh"):
            read_daily_readings(data_dir / "daily.csv")

    def test_malformed_date(self, data_dir: Path):
        (data_dir / "daily.csv").write_text(DAILY.replace("2026-09-13", "13-09-2026"))
        with pytest.raises(IngestError, match="not an ISO date"):
            read_daily_readings(data_dir / "daily.csv")

    def test_missing_column(self, data_dir: Path):
        (data_dir / "daily.csv").write_text(DAILY.replace(",pr,", ","))
        with pytest.raises(IngestError, match="missing column 'pr'"):
            read_daily_readings(data_dir / "daily.csv")

    def test_blank_required_field(self, data_dir: Path):
        (data_dir / "daily.csv").write_text(DAILY.replace("plant_1000,2026-09-13", ",2026-09-13"))
        with pytest.raises(IngestError, match="is blank"):
            read_daily_readings(data_dir / "daily.csv")

    def test_cleaned_flag_must_be_zero_or_one(self, connection, data_dir: Path):
        from swishos.ingest import read_events

        (data_dir / "events.csv").write_text(EVENTS.replace("12.5,1", "12.5,yes"))
        with pytest.raises(IngestError, match="must be 0 or 1"):
            read_events(data_dir / "events.csv")

    def test_reading_for_unknown_plant_is_rejected(self, connection, data_dir: Path):
        """Foreign keys are enabled explicitly; without the pragma this passes."""
        import sqlite3

        (data_dir / "daily.csv").write_text(DAILY.replace("plant_1000", "plant_9999"))
        with pytest.raises(sqlite3.IntegrityError):
            ingest_dataset(connection, data_dir)

    def test_failed_ingest_leaves_no_partial_state(self, connection, data_dir: Path):
        """A malformed row must roll the whole transaction back."""
        import sqlite3

        (data_dir / "daily.csv").write_text(DAILY.replace("plant_1000", "plant_9999"))
        with pytest.raises(sqlite3.IntegrityError):
            ingest_dataset(connection, data_dir)
        count = connection.execute("SELECT COUNT(*) FROM plant").fetchone()[0]
        assert count == 0
