"""Load the fleet CSVs into SQLite.

The CSVs are a trust boundary, so every field is parsed and validated here
rather than being handed on as a string. Downstream code receives typed domain
objects and never re-validates.

Ingest is idempotent: running it twice over the same directory leaves the same
database. That matters because the pipeline is re-runnable by design — derived
tables can be dropped and rebuilt from these ones (DDIA ch.17).

The blank-vs-zero distinction is the important one. `daily.csv` publishes empty
`pr` and `soiling_loss_pct` where no clean baseline exists yet; reading those as
0.0 would present an unmeasurable plant as a perfectly clean one.
"""

from __future__ import annotations

import csv
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .domain import Crew, DailyReading, Plant, PlantDayEvent


class IngestError(Exception):
    """A CSV row could not be parsed into a domain object.

    Always names the file, the line and the offending field, because the useful
    question when ingest fails is "which row, and what was in it".
    """


@dataclass(frozen=True)
class IngestSummary:
    plants: int
    crews: int
    daily_readings: int
    events: int


def ingest_dataset(connection: sqlite3.Connection, data_dir: Path) -> IngestSummary:
    """Load every CSV in `data_dir` into `connection`.

    Runs as a single transaction: a malformed row anywhere leaves the database
    untouched rather than half-loaded. Plants and crews load first because the
    reading and event tables reference them.
    """
    plants = read_plants(data_dir / "plants.csv")
    crews = read_crews(data_dir / "crews.csv")
    readings = read_daily_readings(data_dir / "daily.csv")
    events = read_events(data_dir / "events.csv")

    with connection:  # commits on success, rolls back on any exception
        connection.executemany(
            """INSERT OR REPLACE INTO plant
               (plant_id, name, region, capacity_mw, tariff_per_kwh,
                cleaning_cost_usd, days_until_next_reset, commissioned_on)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    p.plant_id,
                    p.name,
                    p.region,
                    p.capacity_mw,
                    p.tariff_per_kwh,
                    p.cleaning_cost_usd,
                    p.days_until_next_reset,
                    p.commissioned_on.isoformat(),
                )
                for p in plants
            ],
        )
        connection.executemany(
            """INSERT OR REPLACE INTO crew
               (crew_id, home_base, mw_per_day, day_rate_usd) VALUES (?, ?, ?, ?)""",
            [(c.crew_id, c.home_base, c.mw_per_day, c.day_rate_usd) for c in crews],
        )
        connection.executemany(
            """INSERT OR REPLACE INTO daily_reading
               (plant_id, date, energy_kwh, expected_energy_kwh, pr, soiling_loss_pct)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [
                (
                    r.plant_id,
                    r.reading_date.isoformat(),
                    r.energy_kwh,
                    r.expected_energy_kwh,
                    r.pr,
                    r.soiling_loss_pct,
                )
                for r in readings
            ],
        )
        connection.executemany(
            """INSERT OR REPLACE INTO plant_day_event
               (plant_id, date, rain_mm, cleaned) VALUES (?, ?, ?, ?)""",
            [
                (e.plant_id, e.event_date.isoformat(), e.rain_mm, int(e.cleaned))
                for e in events
            ],
        )

    return IngestSummary(
        plants=len(plants),
        crews=len(crews),
        daily_readings=len(readings),
        events=len(events),
    )


def read_plants(path: Path) -> list[Plant]:
    return [
        Plant(
            plant_id=_text(row, "plant_id", path, line),
            name=_text(row, "name", path, line),
            region=_text(row, "region", path, line),
            capacity_mw=_number(row, "capacity_mw", path, line),
            tariff_per_kwh=_number(row, "tariff_per_kwh", path, line),
            cleaning_cost_usd=_number(row, "cleaning_cost_usd", path, line),
            days_until_next_reset=_whole_number(
                row, "days_until_next_reset", path, line
            ),
            commissioned_on=_iso_date(row, "commissioned_on", path, line),
        )
        for row, line in _rows(path)
    ]


def read_crews(path: Path) -> list[Crew]:
    return [
        Crew(
            crew_id=_text(row, "crew_id", path, line),
            home_base=_text(row, "home_base", path, line),
            mw_per_day=_number(row, "mw_per_day", path, line),
            day_rate_usd=_number(row, "day_rate_usd", path, line),
        )
        for row, line in _rows(path)
    ]


def read_daily_readings(path: Path) -> list[DailyReading]:
    return [
        DailyReading(
            plant_id=_text(row, "plant_id", path, line),
            reading_date=_iso_date(row, "date", path, line),
            energy_kwh=_number(row, "energy_kwh", path, line),
            expected_energy_kwh=_number(row, "expected_energy_kwh", path, line),
            pr=_optional_number(row, "pr", path, line),
            soiling_loss_pct=_optional_number(row, "soiling_loss_pct", path, line),
        )
        for row, line in _rows(path)
    ]


def read_events(path: Path) -> list[PlantDayEvent]:
    return [
        PlantDayEvent(
            plant_id=_text(row, "plant_id", path, line),
            event_date=_iso_date(row, "date", path, line),
            rain_mm=_number(row, "rain_mm", path, line),
            cleaned=_flag(row, "cleaned", path, line),
        )
        for row, line in _rows(path)
    ]


def _rows(path: Path) -> Iterator[tuple[dict[str, str], int]]:
    """Yield each data row with its 1-based line number for error messages."""
    if not path.exists():
        raise IngestError(f"{path}: file not found; run seed_data.py first")

    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise IngestError(f"{path}: file is empty, expected a header row")
        for row in reader:
            yield row, reader.line_num


def _raw(row: dict[str, str], column: str, path: Path, line: int) -> str:
    if column not in row:
        raise IngestError(f"{path}:{line}: missing column '{column}'")
    value = row[column]
    if value is None:
        raise IngestError(f"{path}:{line}: column '{column}' has no value")
    return value.strip()


def _text(row: dict[str, str], column: str, path: Path, line: int) -> str:
    value = _raw(row, column, path, line)
    if not value:
        raise IngestError(f"{path}:{line}: column '{column}' is blank")
    return value


def _number(row: dict[str, str], column: str, path: Path, line: int) -> float:
    value = _raw(row, column, path, line)
    try:
        return float(value)
    except ValueError as error:
        raise IngestError(
            f"{path}:{line}: column '{column}' is not a number: {value!r}"
        ) from error


def _optional_number(
    row: dict[str, str], column: str, path: Path, line: int
) -> float | None:
    """Parse a column that is legitimately blank when unmeasurable.

    Blank means "not known", which is not the same as zero — see the module
    docstring. Anything non-blank must still parse.
    """
    if not _raw(row, column, path, line):
        return None
    return _number(row, column, path, line)


def _whole_number(row: dict[str, str], column: str, path: Path, line: int) -> int:
    value = _raw(row, column, path, line)
    try:
        return int(value)
    except ValueError as error:
        raise IngestError(
            f"{path}:{line}: column '{column}' is not a whole number: {value!r}"
        ) from error


def _iso_date(row: dict[str, str], column: str, path: Path, line: int) -> date:
    value = _raw(row, column, path, line)
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise IngestError(
            f"{path}:{line}: column '{column}' is not an ISO date: {value!r}"
        ) from error


def _flag(row: dict[str, str], column: str, path: Path, line: int) -> bool:
    value = _raw(row, column, path, line)
    if value not in ("0", "1"):
        raise IngestError(
            f"{path}:{line}: column '{column}' must be 0 or 1, got {value!r}"
        )
    return value == "1"
