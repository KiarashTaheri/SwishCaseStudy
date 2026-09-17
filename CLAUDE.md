# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A take-home exercise (`swish_solar.md`): a fleet soiling and cleaning advisor for solar plants.
An asset manager with 200 plants decides where to send a crew tomorrow; a crew lead carries it out.

**It is scored on reasoning, not scope.** "An incomplete submission with clear reasoning scores higher
than a complete one without." Every decision must be defensible in a live session. Prefer cutting
scope over shipping something you cannot justify — anything extra built is something extra to explain.

## Commands

```bash
python3 seed_data.py --start 2026-05-18                        # regenerate data/ (12 plants x 120 days)
python3 seed_data.py --plants 200 --days 540 --start 2026-05-18 --out data_scale  # scale run, ~530 MB
```

**Always pass `--start`.** `seed_data.py:213` falls back to `date.today() - days` when it is omitted,
so the dataset is only deterministic *on a given calendar day* — the row values are seeded and stable,
but every date shifts. The committed fixtures and every date cited in the docs come from a run
starting `2026-05-18` (last row `2026-09-14`). Without the pin, a clone tomorrow reproduces none of
the cited dates.

`seed_data.py` is stdlib-only and deterministic for a given `--seed` (default `20260901`). Do not
modify it — it is supplied by the exercise; pin via the flag only. Do not commit its output.

Backend is Python/FastAPI + SQLite, frontend Next.js/TypeScript. `backend/pyproject.toml` and a
pytest suite exist; `frontend/` is scaffolded. Run the backend suite with
`cd backend && ./.venv/bin/python -m pytest -q`.

## The one thing to get right

**Some rows do not behave like dirt.** `soiling_loss_pct` **is** output lost to dirt — the brief
says so and the organisers confirmed it. Do not write that the column means something else. The
defensible claim is narrower and fully measured: soiling *accumulates*, so a loss that reverses
overnight without a wash is not a loss a wash recovers.

**Measured** (`scripts/verify.py`): gated soiling rises a median **0.240pp/day**, never more than
**1.56pp**, and has never exceeded **11.74%** on a credible reading across 1,138 plant-days. Against
that, 29 transitions move >20pp in one day — `plant_1000` goes 0.06% → 60.18% → 0.52% on consecutive
days with no rain and no crew. 21 of 1,343 plant-days (1.6%) are withheld as availability anomalies
and 206 (15.3%) in total, including one ranked at **+$1,498,102** while producing 2% of expected for
six days (plant_1003, 2026-07-07, using that day's `expected_energy_kwh`).

Consequences that propagate through the whole system:

- Rows must pass the quality gate (`QualityFlag.USABLE`) before reaching the soiling estimator.
- **Never name a cause for a gated day.** The data shows only that the loss does not behave like
  dirt. Converter fault, curtailment, maintenance and metering failure are indistinguishable in
  `daily.csv`, and the last inverts the commercial response. UI, LLM prompts and docs report
  signatures and evidence, never diagnoses. See `ASSUMPTIONS.md` A3.
- Gated days are surfaced, not silently dropped — an unexplained deficit is information the asset
  manager needs.

## Data traps

- **`pr` and `soiling_loss_pct` are nullable.** Blank where no clean baseline exists yet (11–29 rows
  per plant). Coercing to `0.0` reads as a perfect plant. `db.py` and `domain.py` both keep them
  `Optional` deliberately.
- **Rain on day *d* affects soiling on day *d+1*.** The generator updates soiling after the day's
  generation. Keying a rain effect to the same day produces nonsense (it makes a ≥8 mm wash look
  like it does nothing).
- **"Today" is the last row in `daily.csv`** (`2026-09-14` with the pinned `--start 2026-05-18`), not
  wall-clock time — and not a fixed date either, unless the start is pinned. See Commands.
- **Two plants are commissioned mid-window** with 56 and 87 days of history and almost no baseline.
- **`readings/` is not ingested** — the brief says it isn't needed, and it is 530 MB at scale.

## Architecture

Source tables (`plant`, `crew`, `daily_reading`, `plant_day_event`) mirror the CSVs verbatim and are
never mutated. Derived tables (`reading_quality`, and the snapshot) can always be dropped and
recomputed. Pipeline stages are deterministic transformations over frozen dataclasses.

```
CSV -> ingest -> quality gate -> soiling estimate -> economics -> daily snapshot -> API -> UI
```

**Precompute the ranking.** The stated constraint is ~120 people loading the fleet view after 8am.
The ranking is a pure function of data through yesterday and does not change during the day, so one
materialised snapshot serves the burst.

**LLM at the rendering boundary only.** Deterministic numbers and flags in, prose out — approval
briefings, work orders, quality narratives. Never ranking, `recoverable_usd`, anomaly detection, or
rain forecasting. Must fall back to a deterministic template without `ANTHROPIC_API_KEY`; the brief
requires the system to run without one.

## Notation

| Symbol | Meaning | Source |
|---|---|---|
| `s₀` | today's soiling loss, % of expected output | today's `soiling_loss_pct`, if it passes the gate |
| `r` | accumulation rate, percentage points/day | estimated from dry-day rises |
| `E` | expected generation, kWh/day | 14-day median of `expected_energy_kwh` — the one input improved on |
| `τ` | tariff, $/kWh | `tariff_per_kwh` |
| `T` | days until rain resets it | `days_until_next_reset` (fixed horizon, never decremented) |
| `C` | cost to clean once, $ | `cleaning_cost_usd` (all-in; do not add crew day rate) |
| `s*` | break-even soiling | `C/(E·τ·T)` |

Soiling on day *t* is `s₀ + r·t`. The decision is `s₀ > s*`. The brief's
`recoverable_usd = s₀·E·τ·T − C` is the same statement in dollars, and it is used as written.

**Which inputs get smoothed.** `s₀` is a *state* — today's gated reading, multiplied by nothing, so
there is nothing to average. A 3-day trailing median was tried and removed: it lagged a rising
quantity and skipped 24 profitable cleanings. `E` is a *rate* the formula multiplies by `T`, so it
is a 14-day median; one day's value swings 26% on average and flips `plant_1005` unaided. That
distinction — state versus rate — is the whole of the improvement on the brief's formula.

## Evidence discipline

The user requires every claim to be verifiable. Tag claims as **Measured** (reproducible from `data/`
by a command in the repo), **Consistent** (supported but not established), or **Assumed** (needs a
falsifier).

**Nothing lifted from `seed_data.py` may be treated as Measured.** The generator will not exist for
real telemetry, so any constant read out of it is overfitting to the synthetic sample. Use it to form
hypotheses, then re-derive from the CSVs. For the same reason, prefer detectors that state a physical
property and self-calibrate per plant over any fleet-wide magnitude threshold.

State negative results too — a hypothesis raised and then falsified by measurement is evidence the
method works.

## Documents

- `swish_solar.md` — the brief. Required deliverables: `README.md`, `DECISIONS.md`, `slides.pdf`,
  backend, frontend.
- `ASSUMPTIONS.md` — A1–A15, each with source, what breaks if false, and how to settle it.
- `questions.md` — seven open questions for the organisers, with the assumption being used meanwhile.
- `DECISIONS.md` — **not yet written**, though `db.py` already cites "DECISIONS.md #4". Required
  schema is four fields per decision: **Decision** (what you did), **Rejected** (what else you
  considered and why it lost), **Cost** (what this makes worse), **Falsifier** (what would change
  your mind). Graders read it before the code.
