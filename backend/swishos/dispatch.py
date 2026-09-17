"""Record a decision to send a crew, immutably.

A dispatch is the only thing in this system that is not derived. Everything else
can be recomputed from the CSVs; this cannot, because it records that a human
looked at a recommendation and chose to spend money on it.

Two consequences shape the whole module:

1. **It stores the numbers it was approved on, not a reference to them.** The
   estimate moves every day. When a cleaning under-recovers, the only useful
   question is what was believed at the time and whether the belief was
   reasonable, and that is unanswerable from a plant id and a date. So the row
   carries a frozen copy of the snapshot, and nothing ever updates it.

2. **It reads the snapshot, never the estimator.** Re-deriving the numbers at
   dispatch time would let the record disagree with the screen the approval was
   given on — the same class of bug as recomputing a price at checkout.

Refusals are typed rather than booleans so the API can map them to status codes
without re-deciding anything. Each one exists because the alternative wastes a
truck: dispatching a plant the system does not rank, dispatching the same plant
twice in a day, or sending a crew to a region it cannot work in.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from typing import Any

from . import briefing, ranking, repository
from .domain import DispatchStatus, Plant


class DispatchRefused(Exception):
    """A dispatch that must not be recorded, with the reason the API reports.

    `status_code` lives on the exception rather than in a mapping at the API
    layer so that the rule and its consequence cannot drift apart.
    """

    status_code = 400

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class UnknownPlant(DispatchRefused):
    status_code = 404


class UnknownCrew(DispatchRefused):
    status_code = 404


class NotRanked(DispatchRefused):
    """No snapshot row for that plant and date — nothing was recommended."""

    status_code = 409


class NotActionable(DispatchRefused):
    """The plant is ranked but not worth cleaning on that date."""

    status_code = 409


class AlreadyDispatched(DispatchRefused):
    status_code = 409


class CrewOutOfRegion(DispatchRefused):
    """A crew cannot service a region it is not based in. ASSUMPTIONS.md A14."""

    status_code = 422


class NoCrewInRegion(DispatchRefused):
    status_code = 409


@dataclass(frozen=True)
class DispatchRecord:
    dispatch_id: str
    plant_id: str
    as_of: date
    created_at: str
    crew_id: str
    crew_days: float
    snapshot: dict[str, Any]
    work_order: str

    def to_json(self) -> dict[str, Any]:
        return {
            "dispatch_id": self.dispatch_id,
            "plant_id": self.plant_id,
            "as_of": self.as_of.isoformat(),
            "created_at": self.created_at,
            "crew_id": self.crew_id,
            "crew_days": round(self.crew_days, 1),
            "snapshot": self.snapshot,
            "work_order": self.work_order,
        }


# Fields copied into the frozen snapshot. Every input to the decision, and
# nothing that can be looked up later — the plant's name and region are stable,
# the numbers are not.
SNAPSHOT_FIELDS = (
    "soiling_loss_pct",
    "break_even_soiling_pct",
    "margin_pct",
    "recoverable_usd",
    "cleaning_cost_usd",
    "expected_energy_kwh_per_day",
    "tariff_per_kwh",
    "days_until_next_reset",
    "accumulation_rate_pct_per_day",
    "usable_days",
    "days_since_reset",
    "last_reset_on",
    "withheld_days_last_14",
)


def create_dispatch(
    connection: sqlite3.Connection,
    plant_id: str,
    as_of: date,
    crew_id: str | None = None,
) -> DispatchRecord:
    """Approve tomorrow's cleaning at `plant_id`, on the `as_of` ranking.

    `crew_id` is optional: omitted, the crew suggested by the ranking is used.
    Supplied, it is checked against the plant's region and refused if it is not
    based there.
    """
    plant = repository.load_plant(connection, plant_id)
    if plant is None:
        raise UnknownPlant(f"No plant {plant_id!r}.")

    row = ranking.load_snapshot_row(connection, as_of, plant_id)
    if row is None:
        raise NotRanked(
            f"{plant_id} was not ranked for {as_of}. Rebuild the snapshot for "
            "that date before dispatching against it."
        )

    status = ranking.status_of(row)
    if status is not DispatchStatus.ACTIONABLE:
        raise NotActionable(
            f"{plant_id} is {status.value} for {as_of}, so cleaning it is not "
            "expected to repay its cost. Dispatch is only offered on plants the "
            "system ranks as actionable."
        )

    crew = _resolve_crew(connection, plant, row, crew_id)

    record = DispatchRecord(
        dispatch_id=_new_dispatch_id(),
        plant_id=plant_id,
        as_of=as_of,
        # The one legitimate wall-clock call in the system. "Today" for the data
        # is the last row in daily.csv; this is different — it is when a person
        # actually pressed approve, and it is an audit fact, not an input.
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        crew_id=crew["crew_id"],
        crew_days=crew["crew_days"],
        snapshot={field: row[field] for field in SNAPSHOT_FIELDS},
        work_order="",
    )

    work_order = briefing.work_order(
        {
            "dispatch_id": record.dispatch_id,
            "plant_id": plant_id,
            "name": plant.name,
            "region": plant.region,
            "capacity_mw": plant.capacity_mw,
            "as_of": as_of.isoformat(),
            "crew_id": record.crew_id,
            "crew_days": record.crew_days,
            "snapshot": record.snapshot,
        }
    )
    record = replace(record, work_order=work_order)

    try:
        with connection:
            connection.execute(
                """INSERT INTO dispatch (dispatch_id, plant_id, as_of, created_at,
                                         crew_id, crew_days, snapshot_json, work_order)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record.dispatch_id,
                    record.plant_id,
                    record.as_of.isoformat(),
                    record.created_at,
                    record.crew_id,
                    record.crew_days,
                    json.dumps(record.snapshot),
                    record.work_order,
                ),
            )
    except sqlite3.IntegrityError as error:
        # UNIQUE (plant_id, as_of). Checking first and inserting second would
        # leave a window where two approvals both pass the check, so the schema
        # is the real guard and this translates it.
        raise AlreadyDispatched(
            f"{plant_id} already has a dispatch for {as_of}. The crew can only "
            "clean it once; a second truck is wasted."
        ) from error

    return record


def _resolve_crew(
    connection: sqlite3.Connection,
    plant: Plant,
    row: sqlite3.Row,
    crew_id: str | None,
) -> dict[str, Any]:
    """Which crew does the work, and how long it takes them.

    Omitted, the ranking's suggestion is taken as stored — the same value the
    approval was given against. Supplied, the crew is re-checked against the
    plant's region here rather than trusted, because this is the only place a
    caller can choose one.
    """
    if crew_id is None:
        suggested = json.loads(row["suggested_crew"]) if row["suggested_crew"] else None
        if suggested is None:
            raise NoCrewInRegion(
                f"No crew is based in {plant.region}, so {plant.plant_id} cannot "
                "be scheduled. See ASSUMPTIONS.md A14."
            )
        return suggested

    crew = next(
        (c for c in repository.load_crews(connection) if c.crew_id == crew_id), None
    )
    if crew is None:
        raise UnknownCrew(f"No crew {crew_id!r}.")

    crew_region = ranking.crew_region(crew)
    if crew_region != plant.region:
        raise CrewOutOfRegion(
            f"Crew {crew_id} is based in {crew.home_base} ({crew_region}) and "
            f"cannot service a plant in {plant.region}."
        )
    return {
        "crew_id": crew.crew_id,
        "home_base": crew.home_base,
        "crew_days": round(ranking.crew_days(plant, crew), 1),
    }


def list_dispatches(
    connection: sqlite3.Connection, as_of: date | None = None
) -> list[DispatchRecord]:
    """Dispatch history, newest first."""
    query = "SELECT * FROM dispatch"
    parameters: tuple[str, ...] = ()
    if as_of is not None:
        query += " WHERE as_of = ?"
        parameters = (as_of.isoformat(),)
    query += " ORDER BY created_at DESC, dispatch_id DESC"

    return [_record(row) for row in connection.execute(query, parameters)]


def dispatched_plant_ids(connection: sqlite3.Connection, as_of: date) -> set[str]:
    """Plants already dispatched for a date.

    One query for the whole fleet view rather than one per row — the fleet
    endpoint serves ~120 people in a burst and a per-plant lookup there is the
    easiest N+1 in the system to write by accident.
    """
    return {
        row["plant_id"]
        for row in connection.execute(
            "SELECT plant_id FROM dispatch WHERE as_of = ?", (as_of.isoformat(),)
        )
    }


def _record(row: sqlite3.Row) -> DispatchRecord:
    return DispatchRecord(
        dispatch_id=row["dispatch_id"],
        plant_id=row["plant_id"],
        as_of=date.fromisoformat(row["as_of"]),
        created_at=row["created_at"],
        crew_id=row["crew_id"],
        crew_days=row["crew_days"],
        snapshot=json.loads(row["snapshot_json"]),
        work_order=row["work_order"],
    )


def _new_dispatch_id() -> str:
    """Time-ordered id: `d_` + UTC timestamp + random suffix.

    Sortable by creation without reading `created_at`, and unguessable enough
    that an id in a URL is not an invitation to enumerate the fleet's spend.
    """
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return f"d_{stamp}_{secrets.token_hex(4)}"
