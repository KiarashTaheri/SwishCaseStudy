"""Partition the fleet by region, rank within each, and materialise the result.

Regions are a hard partition, not a label
-----------------------------------------
A crew in Jodhpur cannot clean a plant in Arizona, so there is no fleet-wide
ranking to compute — there are five independent ones. This reverses an earlier
decision to rank the fleet globally by dollars per crew-day; that decision
carried "crews are constrained to home regions" as its own falsifier, and the
falsifier fired. Treating crews as one pool also understates the real constraint:
*measured*, Rajasthan needs 10.5 crew-days from a single crew, against 6.9 if
crew-days were fungible. See DECISIONS.md #7 and ASSUMPTIONS.md A14.

Ranking inside a region is by `recoverable_usd`, descending — the plant that
returns the most money first. That is deliberately *not* capacity-aware: it
answers "which plant" but not "which of these never gets done", which is a
scheduling problem over a fixed crew-day budget and the next thing to build.
Ranking by dollars per crew-day would be a half-step toward it that is harder to
explain and still wrong at the capacity boundary, so it is left out.

Nothing here is random or clock-dependent: given the same `as_of` the snapshot is
byte-identical, which is what makes it safe to cache (DDIA ch.17
"Determinism" — no non-deterministic batch operators).
"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from . import economics, estimator, gates
from .domain import Crew, DailyReading, DispatchStatus, Plant, PlantDayEvent
from .economics import PlantEconomics

# Crew home bases are "City, SUBDIVISION"; the subdivision token identifies the
# region. Keyed on the token rather than the city so that a second crew based
# anywhere in Arizona maps correctly without a code change — "Phoenix, AZ" and
# "Tucson, AZ" both resolve through "AZ".
#
# ES and CL are country codes, not subdivisions, so those two rows are really
# country-level: a second Spanish or Chilean region would collide. That is the
# falsifier, and `verify_crew_coverage()` below is what reports it rather than
# leaving it to be discovered by a misrouted truck.
CREW_BASE_REGION: dict[str, str] = {
    "AZ": "Arizona, USA",
    "RJ": "Rajasthan, India",
    "ES": "Andalusia, Spain",
    "CL": "Atacama, Chile",
    "QLD": "Queensland, AUS",
}


class UnmappedCrewError(ValueError):
    """A crew's home base does not resolve to a plant region.

    Raised rather than defaulted. A crew silently dropped from its region makes
    that region look like it has no capacity, which is a worse failure than the
    build stopping.
    """


@dataclass(frozen=True)
class CrewAssignment:
    """Which crew would do the work, and how long it would take them."""

    crew_id: str
    home_base: str
    crew_days: float


@dataclass(frozen=True)
class RankedPlant:
    """One plant's full row: identity, economics, and who would clean it."""

    plant: Plant
    economics: PlantEconomics
    suggested_crew: CrewAssignment | None
    withheld_days_last_14: int


@dataclass(frozen=True)
class RegionRanking:
    """Everything the asset manager sees for one region."""

    region: str
    crews: list[Crew]
    recommendations: list[RankedPlant]  # ACTIONABLE, best first
    withheld: list[RankedPlant]  # everything else, still visible

    @property
    def capacity_mw_per_day(self) -> float:
        return sum(c.mw_per_day for c in self.crews)

    @property
    def crew_days_outstanding(self) -> float:
        """Crew-days to clean everything currently worth cleaning here.

        The number that exposes the real constraint: it is compared against 1.0
        crew-day per crew per day, not against the region's dollar total.
        """
        return sum(
            r.suggested_crew.crew_days
            for r in self.recommendations
            if r.suggested_crew is not None
        )


@dataclass(frozen=True)
class FleetRanking:
    as_of: date
    regions: list[RegionRanking]

    @property
    def plants_total(self) -> int:
        return sum(len(r.recommendations) + len(r.withheld) for r in self.regions)

    @property
    def actionable(self) -> int:
        return sum(len(r.recommendations) for r in self.regions)

    @property
    def total_recoverable_usd(self) -> float:
        return sum(
            p.economics.recoverable_usd or 0.0
            for r in self.regions
            for p in r.recommendations
        )


def crew_region(crew: Crew) -> str:
    """The one region a crew can work in, from its home base."""
    _, _, token = crew.home_base.rpartition(",")
    key = token.strip().upper()
    if key not in CREW_BASE_REGION:
        raise UnmappedCrewError(
            f"crew {crew.crew_id} is based in {crew.home_base!r}, whose region "
            f"token {key!r} is not in CREW_BASE_REGION. Add it there — a crew "
            "cannot be assigned to a region it has no mapping for."
        )
    return CREW_BASE_REGION[key]


def crew_days(plant: Plant, crew: Crew) -> float:
    """Days for one crew to clean one plant, from its throughput.

    Fractional on purpose. Rounding up per plant would hide the difference
    between a region that is comfortably within capacity and one that is not.
    """
    if crew.mw_per_day <= 0:
        return float("inf")
    return plant.capacity_mw / crew.mw_per_day


def assign_crew(plant: Plant, crews: Sequence[Crew]) -> CrewAssignment | None:
    """Pick the crew for a plant from those based in its region.

    The fastest crew, not the cheapest. Under ASSUMPTIONS.md A5 the day rate is
    already inside `cleaning_cost_usd`, so cost does not vary with the choice and
    the only thing left to optimise is how much of the region's queue gets
    cleared. If A5 turns out to be wrong the day rate becomes additive and this
    should become a cost comparison — which is exactly the second-order effect
    A5's falsifier is about.
    """
    candidates = [c for c in crews if crew_region(c) == plant.region]
    if not candidates:
        return None
    best = min(candidates, key=lambda c: (crew_days(plant, c), c.crew_id))
    return CrewAssignment(
        crew_id=best.crew_id,
        home_base=best.home_base,
        crew_days=crew_days(plant, best),
    )


def verify_crew_coverage(
    plants: Iterable[Plant], crews: Iterable[Crew]
) -> dict[str, list[str]]:
    """Report regions with no crew and crews whose region has no plants.

    Checked rather than assumed: the one-to-one mapping between home bases and
    regions holds on this dataset, and the whole partition rests on it. Returns
    empty lists when intact.
    """
    plant_regions = {p.region for p in plants}
    crew_regions = {crew_region(c) for c in crews}
    return {
        "regions_without_a_crew": sorted(plant_regions - crew_regions),
        "crew_regions_without_a_plant": sorted(crew_regions - plant_regions),
    }


def rank_fleet(
    plants: Sequence[Plant],
    crews: Sequence[Crew],
    readings_by_plant: dict[str, Sequence[DailyReading]],
    events_by_plant: dict[str, Sequence[PlantDayEvent]],
    as_of: date,
) -> FleetRanking:
    """Estimate, value and rank every plant, grouped by region."""
    crews_by_region: dict[str, list[Crew]] = defaultdict(list)
    for crew in crews:
        crews_by_region[crew_region(crew)].append(crew)

    rows_by_region: dict[str, list[RankedPlant]] = defaultdict(list)
    for plant in plants:
        readings = readings_by_plant.get(plant.plant_id, ())
        events = events_by_plant.get(plant.plant_id, ())
        estimate = estimator.estimate_soiling(plant, readings, events, as_of)
        case = economics.evaluate(plant, estimate, readings, as_of)
        rows_by_region[plant.region].append(
            RankedPlant(
                plant=plant,
                economics=case,
                suggested_crew=assign_crew(plant, crews_by_region[plant.region]),
                withheld_days_last_14=_withheld_days_last_14(readings, as_of),
            )
        )

    regions = []
    for region in sorted(rows_by_region):
        rows = rows_by_region[region]
        actionable = [r for r in rows if r.economics.is_actionable]
        rest = [r for r in rows if not r.economics.is_actionable]
        regions.append(
            RegionRanking(
                region=region,
                crews=sorted(crews_by_region[region], key=lambda c: c.crew_id),
                # Descending dollars, then plant_id so that ties are stable
                # across runs — an unstable order would make the snapshot
                # non-deterministic for no reason.
                recommendations=sorted(
                    actionable,
                    key=lambda r: (-(r.economics.recoverable_usd or 0.0), r.plant.plant_id),
                ),
                # Not ranked by dollars: these have none. Ordered by how close
                # they are to being worth cleaning, so the asset manager reads
                # "next week's list" from the top. INSUFFICIENT_HISTORY has no
                # margin and sorts last.
                withheld=sorted(rest, key=_withheld_sort_key),
            )
        )
    return FleetRanking(as_of=as_of, regions=regions)


def _withheld_sort_key(row: RankedPlant) -> tuple[int, float, str]:
    margin = row.economics.margin_pct
    if margin is None:
        return (1, 0.0, row.plant.plant_id)
    return (0, -margin, row.plant.plant_id)


def _withheld_days_last_14(readings: Sequence[DailyReading], as_of: date) -> int:
    """How many of the last 14 readings the gate refused.

    Surfaced on every row because it is the honest confidence signal: an estimate
    standing on three usable days out of fourteen is not the same object as one
    standing on fourteen, and the dollar figure alone cannot tell them apart.
    """
    window_start = as_of - timedelta(days=13)
    window = [r for r in readings if window_start <= r.reading_date <= as_of]
    return sum(1 for r in window if not gates.assess_reading(r).is_usable)


# --------------------------------------------------------------------------- #
# Materialisation
# --------------------------------------------------------------------------- #
# `ranking_snapshot` is declared in `db.py` with the rest of the schema. The
# rationale for materialising it at all — ~120 people opening the fleet view
# after 8am, against a ranking that cannot change during the day — is recorded
# there, next to the table it justifies.


def build_snapshot(connection: sqlite3.Connection, ranking: FleetRanking) -> int:
    """Replace the snapshot for `ranking.as_of`. Returns rows written.

    Derived data: dropped and rewritten for that date rather than patched, so a
    partial run can never leave a half-updated ranking behind.
    """
    rows = []
    for region in ranking.regions:
        ordered = [(i + 1, r) for i, r in enumerate(region.recommendations)]
        ordered += [(None, r) for r in region.withheld]
        for rank, row in ordered:
            economics_ = row.economics
            rows.append(
                (
                    ranking.as_of.isoformat(),
                    row.plant.plant_id,
                    region.region,
                    rank,
                    economics_.status.value,
                    economics_.soiling_loss_pct,
                    _finite(economics_.break_even_soiling_pct),
                    economics_.margin_pct,
                    economics_.recoverable_usd,
                    economics_.cleaning_cost_usd,
                    economics_.expected_energy_kwh_per_day,
                    economics_.tariff_per_kwh,
                    economics_.days_until_next_reset,
                    economics_.accumulation_rate_pct_per_day,
                    economics_.days_to_break_even,
                    economics_.usable_days,
                    economics_.days_since_reset,
                    economics_.last_reset_on.isoformat()
                    if economics_.last_reset_on
                    else None,
                    row.withheld_days_last_14,
                    json.dumps(
                        {
                            "crew_id": row.suggested_crew.crew_id,
                            "home_base": row.suggested_crew.home_base,
                            "crew_days": round(row.suggested_crew.crew_days, 1),
                        }
                    )
                    if row.suggested_crew
                    else None,
                )
            )

    with connection:
        connection.execute(
            "DELETE FROM ranking_snapshot WHERE as_of = ?", (ranking.as_of.isoformat(),)
        )
        connection.executemany(
            f"""INSERT INTO ranking_snapshot VALUES ({",".join("?" * 20)})""", rows
        )
    return len(rows)


def _finite(value: float) -> float | None:
    """SQLite stores infinity, JSON cannot represent it. Normalise at the edge."""
    return None if value == float("inf") else value


def snapshot_dates(connection: sqlite3.Connection) -> list[date]:
    return [
        date.fromisoformat(row[0])
        for row in connection.execute(
            "SELECT DISTINCT as_of FROM ranking_snapshot ORDER BY as_of DESC"
        )
    ]


def load_snapshot(connection: sqlite3.Connection, as_of: date) -> list[sqlite3.Row]:
    """Snapshot rows for one day: recommendations in rank order, then the rest."""
    return list(
        connection.execute(
            """SELECT * FROM ranking_snapshot
               WHERE as_of = ?
               ORDER BY region,
                        rank_in_region IS NULL, rank_in_region,
                        margin_pct IS NULL, margin_pct DESC,
                        plant_id""",
            (as_of.isoformat(),),
        )
    )


def load_snapshot_row(
    connection: sqlite3.Connection, as_of: date, plant_id: str
) -> sqlite3.Row | None:
    return connection.execute(
        "SELECT * FROM ranking_snapshot WHERE as_of = ? AND plant_id = ?",
        (as_of.isoformat(), plant_id),
    ).fetchone()


def status_of(row: sqlite3.Row) -> DispatchStatus:
    return DispatchStatus(row["status"])
