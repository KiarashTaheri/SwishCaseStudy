#!/usr/bin/env python3
"""Reproduce every measured claim in the documents, from `data/` alone.

    cd backend && PYTHONPATH=. ./.venv/bin/python scripts/verify.py

Prints each claim with the figure it was written against and the figure measured
now, and exits non-zero if any of them disagree. `scripts/smoke.sh` runs it.

This exists because the submission asserts a lot of numbers, and a number in a
document that nobody can re-derive is indistinguishable from one that was made
up. Every claim tagged *Measured* in `DECISIONS.md`, `ASSUMPTIONS.md`,
`README.md` and `CLAUDE.md` should be checkable here.

**Nothing is read from `seed_data.py`.** The generator will not exist for real
telemetry, so any constant lifted out of it is overfitting to the synthetic
sample. Everything below is derived from the CSVs it produces.
"""

from __future__ import annotations

import csv
import statistics
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from swishos import economics, estimator, gates  # noqa: E402
from swishos.domain import Crew, DailyReading, Plant, PlantDayEvent  # noqa: E402
from swishos.ranking import crew_days, crew_region  # noqa: E402

DATA = Path(__file__).resolve().parent.parent.parent / "data"

GREEN, RED, YELLOW, DIM, BOLD, OFF = (
    "\033[32m",
    "\033[31m",
    "\033[33m",
    "\033[2m",
    "\033[1m",
    "\033[0m",
)

failures: list[str] = []


def check(claim: str, expected: object, measured: object, *, note: str = "") -> None:
    """Compare a documented figure against the one measured now."""
    ok = expected == measured
    mark = f"{GREEN}ok  {OFF}" if ok else f"{RED}FAIL{OFF}"
    print(f"  {mark} {claim}")
    print(f"       documented {expected!r}, measured {measured!r}")
    if note:
        print(f"       {DIM}{note}{OFF}")
    if not ok:
        failures.append(claim)


def report(label: str, value: object, note: str = "") -> None:
    """A measurement with no documented counterpart to compare against."""
    print(f"  {YELLOW}--  {OFF}{label}: {value}")
    if note:
        print(f"       {DIM}{note}{OFF}")


def section(title: str) -> None:
    print(f"\n{BOLD}{title}{OFF}")


# --------------------------------------------------------------------------- #
# Load
# --------------------------------------------------------------------------- #


def _optional(value: str) -> float | None:
    return float(value) if value.strip() else None


def load() -> tuple[
    dict[str, Plant],
    list[Crew],
    dict[str, list[DailyReading]],
    dict[str, list[PlantDayEvent]],
]:
    plants = {}
    for row in csv.DictReader((DATA / "plants.csv").open()):
        plants[row["plant_id"]] = Plant(
            plant_id=row["plant_id"],
            name=row["name"],
            region=row["region"],
            capacity_mw=float(row["capacity_mw"]),
            tariff_per_kwh=float(row["tariff_per_kwh"]),
            cleaning_cost_usd=float(row["cleaning_cost_usd"]),
            days_until_next_reset=int(row["days_until_next_reset"]),
            commissioned_on=date.fromisoformat(row["commissioned_on"]),
        )

    crews = [
        Crew(
            crew_id=row["crew_id"],
            home_base=row["home_base"],
            mw_per_day=float(row["mw_per_day"]),
            day_rate_usd=float(row["day_rate_usd"]),
        )
        for row in csv.DictReader((DATA / "crews.csv").open())
    ]

    readings: dict[str, list[DailyReading]] = defaultdict(list)
    for row in csv.DictReader((DATA / "daily.csv").open()):
        readings[row["plant_id"]].append(
            DailyReading(
                plant_id=row["plant_id"],
                reading_date=date.fromisoformat(row["date"]),
                energy_kwh=float(row["energy_kwh"]),
                expected_energy_kwh=float(row["expected_energy_kwh"]),
                pr=_optional(row["pr"]),
                soiling_loss_pct=_optional(row["soiling_loss_pct"]),
            )
        )

    events: dict[str, list[PlantDayEvent]] = defaultdict(list)
    for row in csv.DictReader((DATA / "events.csv").open()):
        events[row["plant_id"]].append(
            PlantDayEvent(
                plant_id=row["plant_id"],
                event_date=date.fromisoformat(row["date"]),
                rain_mm=float(row["rain_mm"]),
                cleaned=row["cleaned"].strip().lower() in ("1", "true", "yes"),
            )
        )
    return plants, crews, readings, events


# --------------------------------------------------------------------------- #
# Claims
# --------------------------------------------------------------------------- #


def verify_empty_band(readings) -> None:
    """A2b / DECISIONS.md #9 — the PR floor is a gap in the data, not a fit."""
    section("1. The performance-ratio band the quality gate relies on")
    values = [r.pr for rs in readings.values() for r in rs if r.pr is not None]
    below = [v for v in values if v < gates.MIN_CREDIBLE_PR]
    above = [v for v in values if v >= gates.MIN_CREDIBLE_PR]

    check("plant-days below the 0.5 floor", 21, len(below))
    check("plant-days above it", 1322, len(above))
    check("highest PR below the floor", 0.3899, round(max(below), 4))
    check("lowest PR above the floor", 0.8664, round(min(above), 4))
    report(
        "band width",
        round(min(above) - max(below), 4),
        "Every threshold inside this band produces an identical partition, so "
        "MIN_CREDIBLE_PR is not tuned on this data. A2b is the assumption that "
        "it stays that way off-sample.",
    )


def verify_gate_rates(readings) -> None:
    """CLAUDE.md / README.md — how much the gate withholds, and as what."""
    section("2. Quality gate rates")
    flags = Counter(
        gates.assess_reading(r).flag.value for rs in readings.values() for r in rs
    )
    total = sum(flags.values())
    withheld = total - flags["USABLE"]

    check("total plant-days", 1343, total)
    check("usable", 1137, flags["USABLE"])
    check("missing soiling baseline", 184, flags["MISSING_SOILING_BASELINE"])
    check("availability anomalies", 21, flags["AVAILABILITY_ANOMALY"])
    check("negative soiling", 1, flags["NEGATIVE_SOILING"])
    check("anomaly rate, %", 1.6, round(100 * flags["AVAILABILITY_ANOMALY"] / total, 1))
    check("withheld overall, %", 15.3, round(100 * withheld / total, 1))


def verify_plant_1003(plants, readings) -> None:
    """README.md — what the brief's formula does with ungated input."""
    section("3. The ungated formula's worst call")
    peak_value, peak_day, peak_plant = 0.0, None, None
    for plant_id, rows in readings.items():
        plant = plants[plant_id]
        for row in rows:
            if row.soiling_loss_pct is None:
                continue
            value = economics.recoverable_usd(
                soiling_loss_pct=row.soiling_loss_pct,
                # That day's own expected energy, not the 14-day median: this
                # reproduces the naive calculation, which is the point.
                expected_energy_kwh_per_day=row.expected_energy_kwh,
                tariff_per_kwh=plant.tariff_per_kwh,
                days_until_next_reset=plant.days_until_next_reset,
                cleaning_cost_usd=plant.cleaning_cost_usd,
            )
            if value > peak_value:
                peak_value, peak_day, peak_plant = value, row.reading_date, plant_id

    check("top-ranked plant, ungated", "plant_1003", peak_plant)
    check("on", "2026-07-07", peak_day.isoformat())
    check("valued at", 1498102, round(peak_value))

    row = next(r for r in readings["plant_1003"] if r.reading_date == peak_day)
    report(
        "that day's actual output",
        f"{100 * row.energy_kwh / row.expected_energy_kwh:.2f}% of expected "
        f"(pr {row.pr}, reported soiling {row.soiling_loss_pct}%)",
        "Cleaning recovers nothing here. The gate withholds it.",
    )


def verify_reset_boundary(readings, events) -> None:
    """DECISIONS.md #1 — why the reset day's own reading is excluded."""
    section("4. The reset-day boundary")
    total, higher, gaps = 0, 0, []
    for plant_id, rows in readings.items():
        by_date = {r.reading_date: r for r in rows}
        for event in events[plant_id]:
            if not (event.rain_mm >= estimator.RESET_RAIN_MM or event.cleaned):
                continue
            today = by_date.get(event.event_date)
            tomorrow = by_date.get(event.event_date + timedelta(days=1))
            if today is None or tomorrow is None:
                continue
            if today.soiling_loss_pct is None or tomorrow.soiling_loss_pct is None:
                continue
            total += 1
            gap = today.soiling_loss_pct - tomorrow.soiling_loss_pct
            gaps.append(gap)
            if gap > 0:
                higher += 1

    check("reset events with readings on both days", 96, total)
    check("where the reset day reads higher than the next", 93, higher)
    check("mean drop, percentage points", 3.69, round(statistics.mean(gaps), 2))
    report(
        "reading",
        "the reset day's value describes the plant before the wash took effect",
        "Including it in the window averages a dirty plant with a clean one.",
    )


def verify_window_sweep(plants, readings, events) -> None:
    """DECISIONS.md #2 / estimator docstring — why the window is 3 days.

    Scored against a centred median of gated values inside the same reset
    interval: a low-noise view of what today's soiling really was, using future
    readings for evaluation only and never as an input.

    A false dispatch is charged what it wastes; a missed clean what it forgoes.
    The denominator is common to all windows — a plant the estimator will not
    rank is simply not dispatched.
    """
    section("5. Estimator window sweep")
    print(f"       {DIM}scoring 5 window lengths over every plant-day — a moment{OFF}")

    rows = []
    original = estimator.WINDOW_DAYS
    try:
        for window in (1, 2, 3, 5, 10):
            estimator.WINDOW_DAYS = window
            rows.append(_score_window(plants, readings, events))
    finally:
        estimator.WINDOW_DAYS = original

    print(f"\n       {'window':>8} {'ranked':>8} {'false':>7} {'missed':>8} {'error cost':>13}")
    for window, (ranked, false, missed, cost) in zip((1, 2, 3, 5, 10), rows):
        marker = "  <- shipped" if window == original else ""
        print(
            f"       {'median/' + str(window):>8} {ranked:>8} {false:>7} "
            f"{missed:>8} ${cost:>12,.0f}{marker}"
        )

    shipped = rows[2]
    check("median/3 ranked plant-days", 938, shipped[0])
    check("median/3 false dispatches", 18, shipped[1])
    check("median/3 missed cleanings", 25, shipped[2])
    check("median/3 error cost", 367390, round(shipped[3]))
    report(
        "why 3 and not 2",
        f"median/2 costs ${rows[1][3]:,.0f}, ${shipped[3] - rows[1][3]:,.0f} less",
        "A median of two values is their mean and tolerates no bad day. Three "
        "is the shortest window where the median has any breakdown point, and "
        "the gap is not resolvable at 12 plants.",
    )


def _score_window(plants, readings, events) -> tuple[int, int, int, float]:
    ranked = false_dispatches = missed = 0
    cost = 0.0
    for plant_id, rows in readings.items():
        plant = plants[plant_id]
        truth = _truth_series(rows, events[plant_id])
        for row in rows:
            actual = truth.get(row.reading_date)
            if actual is None:
                continue

            expected_energy = economics.expected_energy_per_day(rows, row.reading_date)
            value = lambda s: economics.recoverable_usd(  # noqa: E731
                soiling_loss_pct=s,
                expected_energy_kwh_per_day=expected_energy,
                tariff_per_kwh=plant.tariff_per_kwh,
                days_until_next_reset=plant.days_until_next_reset,
                cleaning_cost_usd=plant.cleaning_cost_usd,
            )
            true_value = value(actual)

            estimate = estimator.estimate_soiling(
                plant, rows, events[plant_id], row.reading_date
            )
            if estimate.soiling_loss_pct is None:
                # Not ranked, so not dispatched. If it was really worth cleaning
                # that is a miss, charged like any other.
                if true_value > 0:
                    missed += 1
                    cost += true_value
                continue

            ranked += 1
            if value(estimate.soiling_loss_pct) > 0:
                if true_value <= 0:
                    false_dispatches += 1
                    cost += -true_value  # money spent that was never there
            elif true_value > 0:
                missed += 1
                cost += true_value
    return ranked, false_dispatches, missed, cost


def _truth_series(rows, event_log) -> dict[date, float]:
    """Centred median of gated soiling inside the same reset interval.

    Uses future readings, so it is only ever an evaluation target — never an
    input to anything the system ships.
    """
    resets = {
        e.event_date for e in event_log if e.rain_mm >= estimator.RESET_RAIN_MM or e.cleaned
    }
    usable = {
        r.reading_date: r.soiling_loss_pct
        for r in gates.usable_readings(rows)
        if r.soiling_loss_pct is not None
    }

    truth = {}
    for row in rows:
        day = row.reading_date
        window = []
        for offset in range(-3, 4):
            other = day + timedelta(days=offset)
            if other not in usable:
                continue
            # Never cross a reset: a value from the other side of a wash
            # describes a different plant.
            low, high = min(day, other), max(day, other)
            span = [low + timedelta(days=i + 1) for i in range((high - low).days)]
            if any(d in resets for d in span):
                continue
            window.append(usable[other])
        if window:
            truth[day] = statistics.median(window)
    return truth


def verify_expected_energy_window(plants, readings) -> None:
    """economics.py — why E is a 14-day median and not today's value."""
    section("6. The expected-energy window behind E")
    changes = []
    for rows in readings.values():
        for previous, current in zip(rows, rows[1:]):
            if previous.expected_energy_kwh > 0:
                changes.append(
                    abs(current.expected_energy_kwh - previous.expected_energy_kwh)
                    / previous.expected_energy_kwh
                )
    check(
        "mean day-over-day change in expected_energy_kwh, %",
        26.0,
        round(100 * statistics.mean(changes), 1),
    )

    as_of = max(r.reading_date for rows in readings.values() for r in rows)
    base, spreads = {}, {}
    for window in (14, 1, 7, 30, 120):
        deltas = []
        for plant_id, rows in readings.items():
            plant = plants[plant_id]
            values = [
                r.expected_energy_kwh
                for r in rows
                if as_of - timedelta(days=window - 1) <= r.reading_date <= as_of
            ]
            star = economics.break_even_soiling_pct(
                cleaning_cost_usd=plant.cleaning_cost_usd,
                expected_energy_kwh_per_day=statistics.median(values),
                tariff_per_kwh=plant.tariff_per_kwh,
                days_until_next_reset=plant.days_until_next_reset,
            )
            if window == 14:
                base[plant_id] = star
            else:
                deltas.append(abs(star - base[plant_id]))
        if deltas:
            spreads[window] = (statistics.mean(deltas), max(deltas))

    print(f"\n       {'window':>8} {'mean |s* - s*(14d)|':>22} {'max':>8}")
    for window, (mean_delta, worst) in spreads.items():
        print(f"       {str(window) + 'd':>8} {mean_delta:>22.3f} {worst:>8.3f}")

    check(
        "worst single-day shift in break-even vs 14 days, pp",
        1.219,
        round(spreads[1][1], 3),
    )
    report(
        "why not 1 day",
        "recommendations in this fleet turn on margins as thin as 0.02pp",
        "7, 14 and 30 days sit within 0.23pp of each other; 1 day and the full "
        "record are the outliers. 14 is the flat middle, not a fitted value.",
    )


def verify_coverage(plants, readings, events) -> None:
    """Slide 3 / DECISIONS.md — how often the system declines to rank."""
    section("7. Coverage: how often there is no opinion")
    no_opinion = Counter()
    total = 0
    for plant_id, rows in readings.items():
        plant = plants[plant_id]
        first = min(r.reading_date for r in rows)
        for row in rows:
            total += 1
            estimate = estimator.estimate_soiling(
                plant, rows, events[plant_id], row.reading_date
            )
            if estimate.soiling_loss_pct is not None:
                continue
            if (
                estimate.last_reset_on is not None
                and (row.reading_date - estimate.last_reset_on).days
                <= estimator.WINDOW_DAYS
            ):
                no_opinion["reset within 3 days (correct — the plant is clean)"] += 1
            elif (row.reading_date - first).days < estimator.WINDOW_DAYS:
                no_opinion["first days of history"] += 1
            else:
                no_opinion["withheld readings inside the window (blind spot)"] += 1

    declined = sum(no_opinion.values())
    check("plant-days with no rankable estimate", 455, declined)
    check("as a share of all plant-days, %", 33.9, round(100 * declined / total, 1))
    for reason, count in no_opinion.most_common():
        report(reason, count)
    blind = no_opinion["withheld readings inside the window (blind spot)"]
    check("the blind spot alone, %", 11.7, round(100 * blind / total, 1))


def verify_crew_regions(plants, crews) -> None:
    """DECISIONS.md #7 / A14 — what region-binding costs.

    The comparison is **elapsed days**, not crew-days. Pooled, every crew can
    work any plant, so the fleet finishes in total-capacity / total-throughput.
    Region-bound, the fleet cannot finish before its slowest region does, and
    that floor is what a pooled model hides.
    """
    section("8. Crew regions and the real bottleneck")
    by_region: dict[str, list[Crew]] = defaultdict(list)
    for crew in crews:
        by_region[crew_region(crew)].append(crew)

    # Elapsed days per region: the region's work divided by the throughput of
    # the crews actually based there.
    elapsed = {}
    for region, region_crews in by_region.items():
        work = sum(p.capacity_mw for p in plants.values() if p.region == region)
        elapsed[region] = work / sum(c.mw_per_day for c in region_crews)

    fleet_capacity = sum(p.capacity_mw for p in plants.values())
    fleet_throughput = sum(c.mw_per_day for c in crews)
    pooled = fleet_capacity / fleet_throughput
    bottleneck = max(elapsed, key=elapsed.get)

    print(f"\n       {'region':<20} {'elapsed days':>13} {'crews':>7} {'MW/day':>8}")
    for region in sorted(elapsed, key=elapsed.get, reverse=True):
        print(
            f"       {region:<20} {elapsed[region]:>13.1f} "
            f"{len(by_region[region]):>7} "
            f"{sum(c.mw_per_day for c in by_region[region]):>8.1f}"
        )

    check("days to clean the fleet, crews pooled", 6.9, round(pooled, 1))
    check("the slowest region, crews region-bound", 10.5, round(elapsed[bottleneck], 1))
    check("which region that is", "Rajasthan, India", bottleneck)
    report(
        "the error a pooled model makes",
        f"{elapsed[bottleneck] / pooled:.2f}x optimistic",
        "The fleet cannot finish before its slowest region does. Rajasthan's "
        "106.8 MW is served by one crew at 10.2 MW/day — the slowest and "
        "dearest in the fleet — so pooling reports 6.9 days against a real "
        "floor of 10.5.",
    )
    report(
        "Rajasthan as crew-days",
        f"{sum(min(crew_days(p, c) for c in by_region[bottleneck]) for p in plants.values() if p.region == bottleneck):.1f}",
        "Equal to the elapsed figure here only because the region has exactly "
        "one crew. Arizona has two, so its elapsed days and crew-days differ.",
    )


def main() -> int:
    if not (DATA / "daily.csv").exists():
        print(
            f"{RED}No data at {DATA}.{OFF}\n"
            "Run: python3 seed_data.py --start 2026-05-18",
            file=sys.stderr,
        )
        return 2

    plants, crews, readings, events = load()
    print(
        f"{BOLD}Verifying documented claims against {DATA}{OFF}\n"
        f"{DIM}{len(plants)} plants, "
        f"{sum(len(r) for r in readings.values()):,} plant-days, "
        f"{min(r.reading_date for rs in readings.values() for r in rs)} to "
        f"{max(r.reading_date for rs in readings.values() for r in rs)}{OFF}"
    )

    verify_empty_band(readings)
    verify_gate_rates(readings)
    verify_plant_1003(plants, readings)
    verify_reset_boundary(readings, events)
    verify_window_sweep(plants, readings, events)
    verify_expected_energy_window(plants, readings)
    verify_coverage(plants, readings, events)
    verify_crew_regions(plants, crews)

    print()
    if failures:
        print(f"{RED}{BOLD}{len(failures)} claim(s) no longer reproduce:{OFF}")
        for claim in failures:
            print(f"  - {claim}")
        print(
            f"{DIM}Either the data changed (is --start pinned to 2026-05-18?) or "
            f"a document is wrong. Fix the document, not this script.{OFF}"
        )
        return 1

    print(f"{GREEN}{BOLD}Every documented claim reproduces.{OFF}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
