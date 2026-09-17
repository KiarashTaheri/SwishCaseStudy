# API contract

Frozen interface between backend and frontend. Both are built against this and against
`docs/fixtures/fleet.json`, which holds a real payload generated from the default dataset
(`python -m swishos.build`), not invented numbers.

Base URL: `http://127.0.0.1:8000`. CORS allows `http://localhost:3000`.

**Two rules that override convenience:**

1. **Never name a cause for a withheld day.** `soiling_loss_pct` is output lost to dirt, as the
   brief says — but some rows report a loss that behaves nothing like dirt, moving 60pp overnight
   and back the next morning. Inverter fault, curtailment, maintenance and metering failure are
   indistinguishable in `daily.csv`, and the last inverts the commercial response. API fields, UI
   copy and LLM output report evidence and signatures, never a diagnosis. See `ASSUMPTIONS.md` A3.
2. **The system runs without `ANTHROPIC_API_KEY`.** Every LLM-backed field falls back to a
   deterministic template and reports `"source": "template"`. No endpoint may fail for want of a key.

---

## `GET /api/health`

```json
{ "status": "ok", "as_of": "2026-09-14", "plants": 12, "llm": "template" }
```

`llm` is `"anthropic"` or `"template"`. `as_of` is the latest date in `daily_reading` — **not**
wall-clock time.

---

## `GET /api/fleet`

Optional `?as_of=YYYY-MM-DD`, defaulting to the latest day. Served from the precomputed snapshot.

Shape is exactly `docs/fixtures/fleet.json`:

```jsonc
{
  "as_of": "2026-09-14",
  "summary": {
    "plants_total": 12,
    "actionable": 4,
    "withheld": 8,
    "total_recoverable_usd": 38184.81
  },
  "regions": [
    {
      "region": "Arizona, USA",
      "crews": [
        { "crew_id": "crew_15", "home_base": "Tucson, AZ", "mw_per_day": 20.1, "day_rate_usd": 1379.3 }
      ],
      "capacity_mw_per_day": 33.0,
      "recommendations": [ /* PlantRow, ranked by recoverable_usd desc */ ],
      "withheld":        [ /* PlantRow, everything not actionable */ ]
    }
  ]
}
```

**Regions are a hard partition, not a label.** A crew services only its home region — `crews.csv`
home bases map one-to-one onto plant regions (Antofagasta→Atacama, Jodhpur→Rajasthan,
Seville→Andalusia, Townsville→Queensland, Phoenix/Tucson→Arizona). Plants compete only against
others in their own region, so there is no global ranking and the UI must not present one.
See `ASSUMPTIONS.md` A14.

### PlantRow

```jsonc
{
  "plant_id": "plant_1000",
  "name": "Sunfield Alpha (000)",
  "region": "Arizona, USA",
  "capacity_mw": 68.9,

  "status": "ACTIONABLE",           // | BELOW_BREAK_EVEN | NO_USABLE_READING

  "soiling_loss_pct": 5.23,          // s0, today's gated reading. null when withheld
  "break_even_soiling_pct": 2.94,    // s* = C*100/(E*tau*T). Always present
  "margin_pct": 2.29,                // s0 - s*. The primary column
  "recoverable_usd": 25844.0,        // s0*E*tau*T/100 - C. null when s0 is null

  "cleaning_cost_usd": 33072.0,
  "expected_energy_kwh_per_day": 451323.4,   // E, 14-day median — see below
  "tariff_per_kwh": 0.078,
  "days_until_next_reset": 32,               // T, fixed horizon, never decremented

  "accumulation_rate_pct_per_day": 0.245,    // r. Not used to value a cleaning
  "days_to_break_even": null,                // (s*-s0)/r when below. null when above or unknown
  "days_since_reset": 24,
  "last_reset_on": "2026-08-21",
  "usable_days": 1,                          // readings behind s0 (today's, or 0)

  "quality": {
    "withheld_days_last_14": 0,
    "note": null                             // evidence only, never a diagnosis
  },
  "suggested_crew": { "crew_id": "crew_15", "home_base": "Tucson, AZ", "crew_days": 3.4 },
  "dispatched": false
}
```

**Two inputs, treated differently.** `soiling_loss_pct` is a *state* — today's gated reading,
used exactly as the brief supplies it. `expected_energy_kwh_per_day` is a *rate* the formula
multiplies by `days_until_next_reset`, so it is a 14-day median rather than today's weather;
measured, one day's value swings up to 25% and flips `plant_1005` on its own.

**`margin_pct` is the headline, not `recoverable_usd`.** "2.29 points past where cleaning pays for
itself" is checkable by a human; a dollar figure is not. Dollars are secondary.

**Statuses**

| Status | Meaning | UI treatment |
|---|---|---|
| `ACTIONABLE` | `recoverable_usd > 0` | Ranked, dispatchable |
| `BELOW_BREAK_EVEN` | Estimated, not yet worth cleaning | Listed with `days_to_break_even` |
| `NO_USABLE_READING` | Today's reading is blank or withheld by the gate | Listed, not dispatchable, no false precision |

Real cases in the fixture worth handling deliberately: `plant_1005` is `ACTIONABLE` at **+0.02pp /
$224** — inside the noise, so the UI should show it as marginal rather than as a confident call.
`plant_1001` is below break-even but crosses in **1.1 days**. Queensland's break-even is ~14%
because rain resets every 7 days, so nothing there is ever worth cleaning.

---

## `GET /api/plants/{plant_id}`

PlantRow, plus:

```jsonc
{
  "history": [
    { "date": "2026-09-14", "soiling_loss_pct": 0.63, "pr": 0.9809,
      "flag": "USABLE", "rain_mm": 0.0, "cleaned": false }
  ],
  "briefing": { "headline": "...", "body": "...", "source": "template" },
  "work_order": "..."
}
```

`history` is up to 60 days, oldest first, including withheld days with their `flag` so the chart can
show them as gaps rather than dips. `flag` is one of `USABLE`, `AVAILABILITY_ANOMALY`,
`MISSING_SOILING_BASELINE`, `MISSING_PERFORMANCE_RATIO`, `NEGATIVE_SOILING`.

404 when the plant does not exist.

---

## `POST /api/dispatch`

```jsonc
// request
{ "plant_id": "plant_1000", "as_of": "2026-09-14", "crew_id": "crew_15" }  // crew_id optional
```

```jsonc
// 201 response
{
  "dispatch_id": "d_01H...",
  "plant_id": "plant_1000",
  "as_of": "2026-09-14",
  "created_at": "2026-09-16T09:12:04Z",
  "crew_id": "crew_15",
  "crew_days": 3.4,
  "snapshot": {
    "soiling_loss_pct": 5.23, "break_even_soiling_pct": 2.94, "margin_pct": 2.29,
    "recoverable_usd": 25844.0, "cleaning_cost_usd": 33072.0,
    "expected_energy_kwh_per_day": 468693.0, "tariff_per_kwh": 0.078,
    "days_until_next_reset": 32, "usable_days": 3, "last_reset_on": "2026-08-21"
  },
  "work_order": "..."
}
```

The record is **immutable** and stores the inputs that produced it. The estimate moves daily; when a
cleaning under-recovers, the only useful question is what was believed at the time and whether the
belief was reasonable. That is unanswerable without the snapshot.

Errors: `404` unknown plant, `409` if the plant is not `ACTIONABLE` for that `as_of`, `409` if
already dispatched for that `as_of`, `422` if `crew_id` is not based in the plant's region.

## `GET /api/dispatches`

`{ "dispatches": [ /* newest first */ ] }`

---

## Frontend notes

- Build against `docs/fixtures/fleet.json` so the UI works before the API exists.
- One screen, for the asset manager. The crew lead's work order is generated output, not a second UI.
- Withheld plants stay visible. A plant producing almost nothing is more urgent than any cleaning
  recommendation, and hiding it destroys the most valuable signal in the data.
- Currency to the dollar, soiling and margin to 2dp, never more precision than the estimate carries.
