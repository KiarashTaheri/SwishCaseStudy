"""HTTP interface. Implements `docs/api-contract.md` exactly.

    PYTHONPATH=. uvicorn swishos.api:app --port 8000

The contract was frozen before either half was built, and the frontend is
written against it, so this module has no design freedom left — its job is to
emit that shape and nothing else.

Endpoints contain no SQL and no judgement. They call `repository`, `ranking` and
`dispatch`, and translate the result to JSON. Everything that decides anything
lives in a pure function that can be tested without a database or an HTTP
client.

**The fleet view reads the snapshot, never the estimator.** ~120 people open it
in a burst after 8am, against a ranking that is a pure function of data through
yesterday and cannot change during the day. Re-deriving it per request would do
the same arithmetic 120 times for the same answer.

Two rules from the contract that are the API's to enforce:

1. **No field names a cause for a withheld day.** `quality.note` carries the
   signature and the count. The data cannot distinguish an inverter fault from
   curtailment from a metering error, and the last of those inverts the
   commercial response, so a guess here is worse than silence.
2. **No endpoint fails for want of `ANTHROPIC_API_KEY`.** Prose degrades to a
   deterministic template and says so in `source`; numbers are unaffected.
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections import defaultdict
from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import briefing, dispatch, ranking, repository
from .db import apply_schema, connect

DATABASE_PATH = Path(os.environ.get("SWISHOS_DB", "swishos.db"))

# Days of history on the plant detail view. Long enough to show two or three
# reset cycles in most regions, which is what makes a sawtooth readable as a
# sawtooth rather than as noise.
HISTORY_DAYS = 60

app = FastAPI(
    title="SwishOS — Fleet Soiling & Cleaning Advisor",
    version="1.0.0",
    summary="Where to send a cleaning crew tomorrow, and why.",
)

# The frontend dev server only. A wildcard would be one line shorter and would
# also let any page on the internet read this fleet's economics from a browser
# that can reach the API.
#
# 3001 is listed because `next dev` silently falls back to it when 3000 is
# taken, which is the normal state of any machine already running something
# there. Without it the UI loads, fails its fetch, and quietly shows the bundled
# sample — the failure mode hardest to notice, because the screen still works.
# Override with SWISHOS_CORS_ORIGINS for any other port.
DEV_ORIGINS = [
    f"http://{host}:{port}"
    for host in ("localhost", "127.0.0.1")
    for port in (3000, 3001)
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=(
        os.environ["SWISHOS_CORS_ORIGINS"].split(",")
        if os.environ.get("SWISHOS_CORS_ORIGINS")
        else DEV_ORIGINS
    ),
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def get_connection() -> Iterator[sqlite3.Connection]:
    """One connection per request, closed afterwards.

    Not a shared global: SQLite connections are not safe to use across threads,
    and FastAPI runs sync endpoints in a threadpool. WAL is what makes the read
    burst cheap — readers never block on the daily ingest write.
    """
    connection = connect(DATABASE_PATH)
    try:
        apply_schema(connection)
        yield connection
    finally:
        connection.close()


class DispatchRequest(BaseModel):
    plant_id: str = Field(min_length=1)
    as_of: date | None = Field(
        default=None,
        description="Ranking date to dispatch against. Defaults to the latest.",
    )
    crew_id: str | None = Field(
        default=None,
        description="Optional. Must be based in the plant's region. "
        "Omitted, the crew suggested by the ranking is used.",
    )


@app.get("/api/health")
def health(connection: sqlite3.Connection = Depends(get_connection)) -> dict[str, Any]:
    """Liveness plus the two facts that explain every other response.

    `as_of` is the latest row in `daily_reading`, never wall-clock time — if the
    UI and the API disagree about what "today" is, this is where it shows.
    """
    as_of = repository.latest_reading_date(connection)
    plants = connection.execute("SELECT COUNT(*) AS n FROM plant").fetchone()["n"]
    return {
        "status": "ok",
        "as_of": as_of.isoformat() if as_of else None,
        "plants": plants,
        "llm": "anthropic" if briefing.llm_available() else "template",
    }


@app.get("/api/fleet")
def fleet(
    as_of: date | None = Query(default=None),
    connection: sqlite3.Connection = Depends(get_connection),
) -> dict[str, Any]:
    """The whole decision, grouped by region. Served from the snapshot."""
    as_of = _resolve_as_of(connection, as_of)
    rows = ranking.load_snapshot(connection, as_of)
    if not rows:
        raise HTTPException(
            status_code=404,
            detail=f"No ranking stored for {as_of}. Run `python -m swishos.build`.",
        )

    dispatched = dispatch.dispatched_plant_ids(connection, as_of)
    notes = _quality_notes(connection, as_of)
    plants = {p.plant_id: p for p in repository.load_plants(connection)}
    crews_by_region: dict[str, list[dict[str, Any]]] = {}
    for crew in repository.load_crews(connection):
        crews_by_region.setdefault(ranking.crew_region(crew), []).append(
            {
                "crew_id": crew.crew_id,
                "home_base": crew.home_base,
                "mw_per_day": crew.mw_per_day,
                "day_rate_usd": crew.day_rate_usd,
            }
        )

    regions: list[dict[str, Any]] = []
    for row in rows:
        region_name = row["region"]
        if not regions or regions[-1]["region"] != region_name:
            crews = crews_by_region.get(region_name, [])
            regions.append(
                {
                    "region": region_name,
                    "crews": crews,
                    "capacity_mw_per_day": round(
                        sum(c["mw_per_day"] for c in crews), 1
                    ),
                    "recommendations": [],
                    "withheld": [],
                }
            )
        plant_row = _plant_row(row, plants[row["plant_id"]], dispatched, notes)
        # Split on rank rather than on status: rank_in_region is exactly the
        # "was recommended" flag the snapshot recorded, so the two lists cannot
        # disagree with the ordering the ranking produced.
        key = "recommendations" if row["rank_in_region"] is not None else "withheld"
        regions[-1][key].append(plant_row)

    actionable = sum(len(r["recommendations"]) for r in regions)
    total_plants = actionable + sum(len(r["withheld"]) for r in regions)
    return {
        "as_of": as_of.isoformat(),
        "summary": {
            "plants_total": total_plants,
            "actionable": actionable,
            "withheld": total_plants - actionable,
            # Summed at full precision and rounded once. Summing the
            # already-rounded row values loses a cent per plant, and a total
            # that does not match its own column is the kind of thing that
            # costs a reviewer an hour.
            "total_recoverable_usd": round(
                sum(
                    row["recoverable_usd"] or 0.0
                    for row in rows
                    if row["rank_in_region"] is not None
                ),
                2,
            ),
        },
        "regions": regions,
    }


@app.get("/api/plants/{plant_id}")
def plant_detail(
    plant_id: str,
    as_of: date | None = Query(default=None),
    connection: sqlite3.Connection = Depends(get_connection),
) -> dict[str, Any]:
    """One plant: its row, its history, and the prose for the two humans."""
    plant = repository.load_plant(connection, plant_id)
    if plant is None:
        raise HTTPException(status_code=404, detail=f"No plant {plant_id!r}.")

    as_of = _resolve_as_of(connection, as_of)
    row = ranking.load_snapshot_row(connection, as_of, plant_id)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"{plant_id} is not in the ranking for {as_of}.",
        )

    dispatched = dispatch.dispatched_plant_ids(connection, as_of)
    payload = _plant_row(row, plant, dispatched, _quality_notes(connection, as_of))
    payload["history"] = _history(connection, plant_id, as_of)

    brief = briefing.approval_briefing(payload)
    payload["briefing"] = {
        "headline": brief.headline,
        "body": brief.body,
        "source": brief.source,
    }

    existing = dispatch.list_dispatches(connection, as_of)
    match = next((d for d in existing if d.plant_id == plant_id), None)
    # The stored work order, if one exists — the document that went to the crew,
    # not a fresh generation that might read differently.
    payload["work_order"] = match.work_order if match else None
    return payload


@app.post("/api/dispatch", status_code=201)
def create_dispatch(
    request: DispatchRequest,
    connection: sqlite3.Connection = Depends(get_connection),
) -> dict[str, Any]:
    """Approve a cleaning. Immutable once written."""
    as_of = _resolve_as_of(connection, request.as_of)
    try:
        record = dispatch.create_dispatch(
            connection, request.plant_id, as_of, request.crew_id
        )
    except dispatch.DispatchRefused as refusal:
        # The rule and its status code live together on the exception, so this
        # layer never re-decides anything.
        raise HTTPException(
            status_code=refusal.status_code, detail=refusal.message
        ) from refusal
    return record.to_json()


@app.get("/api/dispatches")
def list_dispatches(
    as_of: date | None = Query(default=None),
    connection: sqlite3.Connection = Depends(get_connection),
) -> dict[str, Any]:
    """Every dispatch, newest first. The audit trail."""
    return {
        "dispatches": [r.to_json() for r in dispatch.list_dispatches(connection, as_of)]
    }


# --------------------------------------------------------------------------- #
# Serialisation
# --------------------------------------------------------------------------- #


def _plant_row(
    row: sqlite3.Row,
    plant: Any,
    dispatched: set[str],
    quality_notes: dict[str, str],
) -> dict[str, Any]:
    """A snapshot row as the contract's PlantRow.

    Rounding happens here and only here, at the edge. Values are stored at full
    precision and presented at the precision the estimate actually carries —
    two decimals on a percentage standing on a three-day median is already
    generous, and more would be false confidence.
    """
    return {
        "plant_id": row["plant_id"],
        "name": plant.name,
        "region": row["region"],
        "capacity_mw": plant.capacity_mw,
        "status": row["status"],
        "soiling_loss_pct": _round(row["soiling_loss_pct"], 2),
        "break_even_soiling_pct": _round(row["break_even_soiling_pct"], 2),
        "margin_pct": _round(row["margin_pct"], 2),
        "recoverable_usd": _round(row["recoverable_usd"], 2),
        "cleaning_cost_usd": row["cleaning_cost_usd"],
        "expected_energy_kwh_per_day": _round(row["expected_energy_kwh_per_day"], 1),
        "tariff_per_kwh": row["tariff_per_kwh"],
        "days_until_next_reset": row["days_until_next_reset"],
        "accumulation_rate_pct_per_day": _round(
            row["accumulation_rate_pct_per_day"], 3
        ),
        "days_to_break_even": _round(row["days_to_break_even"], 1),
        "days_since_reset": row["days_since_reset"],
        "last_reset_on": row["last_reset_on"],
        "usable_days": row["usable_days"],
        "quality": {
            "withheld_days_last_14": row["withheld_days_last_14"],
            "note": quality_notes.get(row["plant_id"]),
        },
        "suggested_crew": json.loads(row["suggested_crew"])
        if row["suggested_crew"]
        else None,
        "dispatched": row["plant_id"] in dispatched,
    }


# What each gate verdict looked like in the data. Signatures, not diagnoses:
# every phrase here describes a measurement, and none names a cause. See
# contract rule 1 and ASSUMPTIONS.md A3.
FLAG_SIGNATURES = {
    "AVAILABILITY_ANOMALY": "output too low to be explained by soiling",
    "MISSING_PERFORMANCE_RATIO": "no performance ratio published",
    "MISSING_SOILING_BASELINE": "no soiling baseline published",
    "NEGATIVE_SOILING": "reported soiling below zero",
}

# The flag where the data genuinely cannot tell you why, and where a reader
# would otherwise assume dirt. A plant producing 2% of expected is the case this
# whole system exists to not guess about.
#
# The other three do not get the caveat. A blank column explains itself, and a
# reported soiling of -0.01% against a PR of 0.9571 (plant_1004, 2026-09-07) is
# a clean plant and a rounding artefact — attaching "cause not determinable" to
# it would make a non-event read as an incident.
INEXPLICABLE_FLAGS = frozenset({"AVAILABILITY_ANOMALY"})


def _quality_notes(
    connection: sqlite3.Connection, as_of: date
) -> dict[str, str]:
    """Per-plant evidence about withheld readings, for the whole fleet.

    One grouped query rather than one per plant: the fleet view serves a burst
    of ~120 readers and this is the easiest N+1 in the system to write by
    accident.
    """
    window_start = (as_of - timedelta(days=13)).isoformat()
    counts: dict[str, dict[str, int]] = defaultdict(dict)
    for row in connection.execute(
        """SELECT plant_id, flag, COUNT(*) AS n
           FROM reading_quality
           WHERE date BETWEEN ? AND ? AND flag != 'USABLE'
           GROUP BY plant_id, flag""",
        (window_start, as_of.isoformat()),
    ):
        counts[row["plant_id"]][row["flag"]] = row["n"]

    notes = {}
    for plant_id, by_flag in counts.items():
        total = sum(by_flag.values())
        signatures = "; ".join(
            FLAG_SIGNATURES.get(flag, flag.lower().replace("_", " "))
            for flag in sorted(by_flag, key=lambda f: -by_flag[f])
        )
        note = f"{total} of the last 14 days withheld: {signatures}."
        if INEXPLICABLE_FLAGS & set(by_flag):
            note += " Cause not determinable from this data."
        notes[plant_id] = note
    return notes


def _history(
    connection: sqlite3.Connection, plant_id: str, as_of: date
) -> list[dict[str, Any]]:
    """Up to 60 days, oldest first, each day carrying its gate verdict.

    The flag travels with the point so the chart can draw a withheld day as a
    gap rather than as a dip. Drawing plant_1003's 98% "soiling" as a spike
    would be the same lie the quality gate exists to prevent, told in pixels.
    """
    rows = connection.execute(
        """SELECT d.date, d.soiling_loss_pct, d.pr,
                  COALESCE(q.flag, 'USABLE') AS flag,
                  e.rain_mm, e.cleaned
           FROM daily_reading d
           LEFT JOIN reading_quality q ON q.plant_id = d.plant_id AND q.date = d.date
           LEFT JOIN plant_day_event e ON e.plant_id = d.plant_id AND e.date = d.date
           WHERE d.plant_id = ? AND d.date <= ?
           ORDER BY d.date DESC
           LIMIT ?""",
        (plant_id, as_of.isoformat(), HISTORY_DAYS),
    ).fetchall()

    return [
        {
            "date": row["date"],
            "soiling_loss_pct": _round(row["soiling_loss_pct"], 2),
            "pr": _round(row["pr"], 4),
            "flag": row["flag"],
            "rain_mm": row["rain_mm"],
            "cleaned": bool(row["cleaned"]),
        }
        for row in reversed(rows)
    ]


def _resolve_as_of(connection: sqlite3.Connection, as_of: date | None) -> date:
    if as_of is not None:
        return as_of
    latest = repository.latest_reading_date(connection)
    if latest is None:
        raise HTTPException(
            status_code=503,
            detail="No readings ingested. Run `python -m swishos.build` first.",
        )
    return latest


def _round(value: float | None, places: int) -> float | None:
    return None if value is None else round(value, places)
