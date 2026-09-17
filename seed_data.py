#!/usr/bin/env python3
"""
SwishOS Stage-2 take-home — synthetic solar fleet generator.

Deterministic for a given --seed, so every candidate gets identical data.

    python seed_data.py                                          # 12 plants x 120 days
    python seed_data.py --plants 200 --days 540 --out data_scale # scale run (Part 4)

Outputs (under --out, default ./data):
    plants.csv                 one row per plant
    crews.csv                  cleaning crews
    events.csv                 per plant-day: rain_mm, cleaned
    readings/plant_<id>.csv    15-minute interval telemetry

Stdlib only. No dependencies.
"""

import argparse
import csv
import math
import os
import random
from datetime import date, datetime, timedelta

# name, soiling %/day, daily rain prob, tariff $/kWh, cleaning $/MW, typical days to a
# natural (rainfall) reset. The reset figure is derived from the rain probability and
# capped at 45 days; past that, cleaning is driven by rota rather than by weather.
REGIONS = [
    ("Arizona, USA",       0.18, 0.04, 0.078, 480, 32),
    ("Rajasthan, India",   0.35, 0.06, 0.045, 260, 22),
    ("Andalusia, Spain",   0.12, 0.10, 0.092, 520, 13),
    ("Atacama, Chile",     0.28, 0.01, 0.061, 610, 45),
    ("Queensland, AUS",    0.09, 0.18, 0.085, 540, 7),
]

FIRST_NAMES = ["Sunfield", "Highmesa", "Talara", "Kestrel", "Ardent", "Lumen",
               "Vellore", "Bright Fork", "Sandhill", "Corvus", "Meridian", "Aster"]
SUFFIXES = ["Alpha", "Beta", "Gamma", "Delta", "I", "II", "III", "North", "South", "West"]

INTERVALS_PER_DAY = 96  # 15-minute
MINUTES = 15


def clearsky_fraction(doy: int, hour_float: float) -> float:
    """Crude but stable clear-sky irradiance shape, 0..1."""
    seasonal = 1.2 * math.sin(2 * math.pi * (doy - 80) / 365.0)
    sunrise, sunset = 6.5 - seasonal, 17.5 + seasonal
    if hour_float <= sunrise or hour_float >= sunset:
        return 0.0
    return math.sin(math.pi * (hour_float - sunrise) / (sunset - sunrise))


def build_plants(n, rng, start: date, days: int):
    plants = []
    for i in range(n):
        region, soil_rate, rain_p, tariff, clean_per_mw, reset_days = REGIONS[i % len(REGIONS)]
        cap = round(rng.uniform(4.0, 85.0), 1)
        name = f"{FIRST_NAMES[i % len(FIRST_NAMES)]} {SUFFIXES[(i // len(FIRST_NAMES)) % len(SUFFIXES)]}"
        commissioned = start - timedelta(days=rng.randint(400, 2000))
        if i % 5 == 0 and i > 0:
            commissioned = start + timedelta(days=int(days * rng.uniform(0.25, 0.55)))
        plants.append({
            "plant_id": f"plant_{1000 + i}",
            "name": f"{name} ({i:03d})",
            "region": region,
            "capacity_mw": cap,
            "tariff_per_kwh": tariff,
            "cleaning_cost_usd": round(cap * clean_per_mw, 2),
            "days_until_next_reset": reset_days,
            "commissioned_on": commissioned.isoformat(),
            "_soil_rate": soil_rate * rng.uniform(0.7, 1.4),
            "_rain_p": rain_p,
            "_avail": rng.uniform(0.965, 0.995),
            "_idx": i,
        })
    return plants


def build_crews(rng, n=6):
    bases = ["Phoenix, AZ", "Jodhpur, RJ", "Seville, ES", "Antofagasta, CL",
             "Townsville, QLD", "Tucson, AZ"]
    return [{
        "crew_id": f"crew_{10 + i}",
        "home_base": bases[i % len(bases)],
        "mw_per_day": round(rng.uniform(6.0, 22.0), 1),
        "day_rate_usd": round(rng.uniform(900, 2600), 2),
    } for i in range(n)]


def simulate_plant(p, start: date, days: int, rng):
    """Yield (events_rows, reading_rows) for one plant."""
    idx = p["_idx"]
    commissioned = date.fromisoformat(p["commissioned_on"])
    soiling = rng.uniform(0.0, 2.5)
    days_since_reset = rng.randint(0, 20)

    stuck_start = rng.randint(20, max(21, days - 30)) if idx % 17 == 3 else None
    stuck_len = 6
    missing_days = set()
    if idx % 13 == 5:
        m0 = rng.randint(10, max(11, days - 10))
        missing_days = {m0, m0 + 1, m0 + 2}
    tz_shift_min = 330 if idx % 11 == 7 else 0
    neg_spikes = (idx % 7 == 2)

    events, readings, daily = [], [], []

    for d in range(days):
        day = start + timedelta(days=d)
        if day < commissioned or d in missing_days:
            continue
        day_actual = day_expected = 0.0

        rained = rng.random() < p["_rain_p"]
        rain_mm = round(rng.uniform(0.5, 34.0), 1) if rained else 0.0

        # cleaning happens on a rough rota, more often where soiling is fast
        cleaned = soiling > rng.uniform(4.5, 9.0) and rng.random() < 0.35

        cloud = max(0.25, min(1.0, rng.gauss(0.88, 0.14)))
        if rained:
            cloud = min(cloud, rng.uniform(0.25, 0.55))

        doy = day.timetuple().tm_yday
        in_stuck = stuck_start is not None and stuck_start <= d < stuck_start + stuck_len
        avail = 0.02 if in_stuck else (p["_avail"] * (0.4 if rng.random() < 0.01 else 1.0))

        for k in range(INTERVALS_PER_DAY):
            hour_f = k * MINUTES / 60.0
            frac = clearsky_fraction(doy, hour_f)
            ghi = 1000.0 * frac * cloud * rng.uniform(0.96, 1.04)
            temp = 14 + 16 * frac + 6 * math.sin(2 * math.pi * (doy - 100) / 365.0) + rng.gauss(0, 1.2)

            # temperature derate, ~-0.4 %/degC above 25
            derate = 1.0 - max(0.0, (temp - 25.0)) * 0.004
            expected = p["capacity_mw"] * 1000.0 * frac * cloud * derate * (MINUTES / 60.0)
            actual = expected * (1 - soiling / 100.0) * avail * rng.uniform(0.985, 1.005)

            if neg_spikes and frac == 0.0 and rng.random() < 0.0015:
                actual = -round(rng.uniform(5, 60), 2)

            ts = datetime.combine(day, datetime.min.time()) + timedelta(
                minutes=k * MINUTES + tz_shift_min)
            readings.append([
                p["plant_id"],
                ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                round(ghi, 1),
                round(temp, 1),
                round(max(0.0, expected), 3),
                round(actual, 3),
            ])
            day_actual += actual
            day_expected += max(0.0, expected)

        events.append([p["plant_id"], day.isoformat(), rain_mm, int(cleaned)])
        daily.append({
            "date": day.isoformat(),
            "actual": day_actual,
            "expected": day_expected,
            "reset": bool(cleaned or rain_mm >= 8.0),
        })

        # soiling dynamics
        if cleaned:
            soiling, days_since_reset = rng.uniform(0.0, 0.3), 0
        elif rain_mm >= 8.0:
            soiling, days_since_reset = soiling * rng.uniform(0.05, 0.25), 0
        elif rain_mm >= 2.0:
            soiling *= rng.uniform(0.6, 0.85)
            days_since_reset = 0
        else:
            days_since_reset += 1
            soiling = min(14.0, soiling + p["_soil_rate"] * rng.uniform(0.7, 1.3))

    # Daily rollup, derived from the telemetry.
    for row in daily:
        row["pr"] = (row["actual"] / row["expected"]) if row["expected"] > 0 else None

    daily_rows = []
    baseline = None
    for i, row in enumerate(daily):
        if row["reset"]:
            window = [r["pr"] for r in daily[i:i + 4] if r["pr"] is not None]
            if window:
                baseline = max(window)
        if row["pr"] is None or baseline in (None, 0):
            loss = None
        else:
            loss = (baseline - row["pr"]) / baseline * 100.0
        daily_rows.append([
            p["plant_id"],
            row["date"],
            round(row["actual"], 2),
            round(row["expected"], 2),
            round(row["pr"], 4) if row["pr"] is not None else "",
            round(loss, 2) if loss is not None else "",
        ])

    return events, readings, daily_rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plants", type=int, default=12)
    ap.add_argument("--days", type=int, default=120)
    ap.add_argument("--seed", type=int, default=20260901)
    ap.add_argument("--out", default="data")
    ap.add_argument("--start", default=None, help="YYYY-MM-DD; default = today - days")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    start = date.fromisoformat(args.start) if args.start else date.today() - timedelta(days=args.days)

    os.makedirs(os.path.join(args.out, "readings"), exist_ok=True)
    plants = build_plants(args.plants, rng, start, args.days)
    crews = build_crews(rng)

    pub_cols = ["plant_id", "name", "region", "capacity_mw", "tariff_per_kwh",
                "cleaning_cost_usd", "days_until_next_reset", "commissioned_on"]
    with open(os.path.join(args.out, "plants.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(pub_cols)
        for p in plants:
            w.writerow([p[c] for c in pub_cols])

    with open(os.path.join(args.out, "crews.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["crew_id", "home_base", "mw_per_day", "day_rate_usd"])
        for c in crews:
            w.writerow([c["crew_id"], c["home_base"], c["mw_per_day"], c["day_rate_usd"]])

    total_rows = 0
    df = open(os.path.join(args.out, "daily.csv"), "w", newline="")
    dw = csv.writer(df)
    dw.writerow(["plant_id", "date", "energy_kwh", "expected_energy_kwh",
                 "pr", "soiling_loss_pct"])
    with open(os.path.join(args.out, "events.csv"), "w", newline="") as ef:
        ew = csv.writer(ef)
        ew.writerow(["plant_id", "date", "rain_mm", "cleaned"])
        for p in plants:
            events, readings, daily_rows = simulate_plant(p, start, args.days, rng)
            ew.writerows(events)
            dw.writerows(daily_rows)
            path = os.path.join(args.out, "readings", f"{p['plant_id']}.csv")
            with open(path, "w", newline="") as rf:
                rw = csv.writer(rf)
                rw.writerow(["plant_id", "interval_start_utc", "ghi_w_m2",
                             "ambient_temp_c", "expected_energy_kwh", "actual_energy_kwh"])
                rw.writerows(readings)
            total_rows += len(readings)

    df.close()
    print(f"wrote {len(plants)} plants, {total_rows:,} interval rows -> {args.out}/")
    print(f"seed={args.seed} start={start} days={args.days}")


if __name__ == "__main__":
    main()
