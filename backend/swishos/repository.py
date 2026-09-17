"""Reads of the source tables, for the ranking and serving paths.

This is the only module besides `db`, `ingest` and `quality` that knows SQLite
exists. Everything above it — the estimator, the economics, the ranking — is
pure functions over frozen domain objects, which is what lets them be tested
without a database. The API endpoints call this; they contain no SQL.

Hand-written SQL rather than an ORM: the ingest and gate layers already are, and
a second data-access idiom in the same package costs more to explain than the
queries here cost to write. See DECISIONS.md #4.

`quality.py` keeps its own reader for `daily_reading` because it belongs next to
the gate that consumes it; this module reuses it rather than duplicating it.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from collections.abc import Sequence
from datetime import date

from .domain import Crew, DailyReading, Plant, PlantDayEvent
from .quality import load_daily_readings


def load_plants(connection: sqlite3.Connection) -> list[Plant]:
    return [
        Plant(
            plant_id=row["plant_id"],
            name=row["name"],
            region=row["region"],
            capacity_mw=row["capacity_mw"],
            tariff_per_kwh=row["tariff_per_kwh"],
            cleaning_cost_usd=row["cleaning_cost_usd"],
            days_until_next_reset=row["days_until_next_reset"],
            commissioned_on=date.fromisoformat(row["commissioned_on"]),
        )
        for row in connection.execute("SELECT * FROM plant ORDER BY plant_id")
    ]


def load_plant(connection: sqlite3.Connection, plant_id: str) -> Plant | None:
    return next((p for p in load_plants(connection) if p.plant_id == plant_id), None)


def load_crews(connection: sqlite3.Connection) -> list[Crew]:
    return [
        Crew(
            crew_id=row["crew_id"],
            home_base=row["home_base"],
            mw_per_day=row["mw_per_day"],
            day_rate_usd=row["day_rate_usd"],
        )
        for row in connection.execute("SELECT * FROM crew ORDER BY crew_id")
    ]


def load_events(
    connection: sqlite3.Connection, plant_id: str | None = None
) -> list[PlantDayEvent]:
    """Rain and cleaning events, oldest first.

    Order matters: `find_last_reset` scans for the most recent reset and the
    estimator's window walks backwards from today, neither of which is correct
    on an arbitrary order. SQLite promises no ordering without an ORDER BY.
    """
    query = "SELECT plant_id, date, rain_mm, cleaned FROM plant_day_event"
    parameters: tuple[str, ...] = ()
    if plant_id is not None:
        query += " WHERE plant_id = ?"
        parameters = (plant_id,)
    query += " ORDER BY plant_id, date"

    return [
        PlantDayEvent(
            plant_id=row["plant_id"],
            event_date=date.fromisoformat(row["date"]),
            rain_mm=row["rain_mm"],
            cleaned=bool(row["cleaned"]),
        )
        for row in connection.execute(query, parameters)
    ]


def readings_by_plant(
    connection: sqlite3.Connection,
) -> dict[str, Sequence[DailyReading]]:
    grouped: dict[str, list[DailyReading]] = defaultdict(list)
    for reading in load_daily_readings(connection):
        grouped[reading.plant_id].append(reading)
    return grouped


def events_by_plant(
    connection: sqlite3.Connection,
) -> dict[str, Sequence[PlantDayEvent]]:
    grouped: dict[str, list[PlantDayEvent]] = defaultdict(list)
    for event in load_events(connection):
        grouped[event.plant_id].append(event)
    return grouped


def latest_reading_date(connection: sqlite3.Connection) -> date | None:
    """"Today" for the whole system.

    The last row in `daily.csv`, never `date.today()`. The dataset is generated
    relative to a chosen start date, so wall-clock time is a different question
    from the one this data can answer — and a system that changed its answer at
    midnight would be untestable.
    """
    row = connection.execute("SELECT MAX(date) AS latest FROM daily_reading").fetchone()
    return date.fromisoformat(row["latest"]) if row and row["latest"] else None
