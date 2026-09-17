# DECISIONS

Every decision, what it cost, and what would change my mind.
Assumptions I did not verify are in `ASSUMPTIONS.md` (A1–A15). Open questions to the organisers, and
the three answered on 2026-09-16, are in `questions.md`.

Numbers cited here are reproducible from `data/` — see `verify.py`.

---

## 1. Estimate today's soiling from the current interval only, not a fixed window

**Decision.** `s₀` is the median of `soiling_loss_pct` over days since the last reset (`rain_mm ≥ 8`
or `cleaned = 1`), not over a fixed trailing 14 days. This is the segmentation step NREL's RdTools
SRR method performs before any soiling fit.

**Rejected.** *Latest row* — one bad day dispatches a truck. *Fixed 14-day median* — averages across
cleaning events. plant_1011 was cleaned on 2026-09-08 and is at 1.46%; a fixed median reports 5.88%,
above its 4.33% break-even, and recommends re-cleaning a plant cleaned six days ago. plant_1010 fails
the same way. That is 2 of 12 plants, both toward wasted dispatches.

**Cost.** Straight after a reset the interval is 1–2 days long, so the estimate is noisy exactly when
the plant is cleanest. Mitigated because a just-reset plant is far from break-even anyway.

**Falsifier.** If resets were rare relative to the window, the fixed median would be equivalent and
simpler. It isn't: median interval length across the fleet is 3–13 days.

## 2. Keep the brief's formula; fix what feeds it

**Decision.** Use `recoverable_usd = s₀·E·τ·T − C` as given. Present it as break-even days
(`C ÷ daily_recovery`) and as a break-even soiling threshold (`s* = C/(E·τ·T)`) — the same statement,
legible to a crew lead.

**Rejected.** Rewriting the integral. Under linear accumulation the gain is ∫₀ᵀ(s₀+rt)dt − ∫₀ᵀ(rt)dt
= s₀·T, which is what the brief wrote. Linearity holds — six plants keep a constant rate across both
halves of their longest dry run, and nothing exceeds 12% loss, so saturation never binds. The
structure was never the problem.

**Cost.** Inherits the formula's assumptions: instant full recovery, constant horizon, no discounting.

**Falsifier.** A plant sustaining a loss high enough to saturate, where the linear model would
overstate the gain.

## 3. Precompute the fleet ranking once daily

**Decision.** The ranking is a pure function of data through yesterday and does not change during the
day. One materialised snapshot is built after the overnight rollup lands and serves every viewer.

**Assumption, per the organisers' 2026-09-16 reply** (they asked that this be documented here): the
previous day's `daily.csv` rollup is available before the 08:00 window, and all ~120 viewers see the
same fleet-wide ranking rather than individually scoped subsets.

**Cost.** Recommendations are up to a day stale. Nobody sees intraday change. If the overnight load
fails, the fleet view silently serves yesterday.

**Falsifier.** Scoped per-user views, or a need for intraday recomputation — either makes a single
shared snapshot wrong.

## 4. SQLite

**Decision.** SQLite for source and derived tables. At the stated end state — 200 plants × 5 years of
daily rollups — that is 365,000 rows, 43.6 MB, with the fleet ranking query at 32 ms.

**Rejected.** Postgres/TimescaleDB. Correct at 15-minute resolution (~350M rows), but the brief
requires the system to run from a clean clone with no hosted services, and `sqlite3` ships with
Python.

**Cost.** One writer at a time; no concurrent ingest. No native time-series functions. Migration
means rewriting connection handling, though the SQL is largely portable.

**Falsifier.** Ingesting `readings/`, or needing concurrent writers. Either forces Postgres.

## 5. Do not ingest `readings/`

**Decision.** Use `daily.csv`, `plants.csv`, `events.csv`, `crews.csv` only.

**Rejected.** Full 15-minute ingest. The brief says it shouldn't be needed; it is 530 MB at scale
versus 7 MB.

**Cost.** Real. `readings/` holds defects the rollup hides — negative overnight values on two plants,
one plant's timestamps offset 5.5 hours. More importantly it is the only thing that could separate a
genuine generation loss from a metering failure, which `daily.csv` cannot (question #3, unanswered).

**Falsifier.** Needing per-asset attribution, or being told those defects are part of the assessment.

## 6. LLM writes prose, never numbers

**Decision.** Deterministic values in, explanation out: approval briefings, work orders, a plain
restatement of why a plant is or isn't recommended. Falls back to a template without
`ANTHROPIC_API_KEY`, which the brief requires.

**Rejected.** LLM ranking, scoring, or anomaly detection. A wrong token dispatches a truck and spends
roughly what it expects to recover. Non-deterministic output also can't be unit-tested or audited
after the fact.

**Cost.** The interesting judgement stays in code, so the LLM's contribution is modest and could be
called decorative.

**Falsifier.** A task where the reasoning genuinely isn't expressible as arithmetic — free-text
constraints from the crew lead, say — would justify moving it into the loop.

## 7. Rank by dollars per crew-day

**Decision.** Order by `net ÷ (capacity_mw ÷ mw_per_day)`, not by raw net dollars. Crews are the
scarce resource; a 72 MW plant is 4–6 crew-days.

**Rejected.** Ranking by net dollars — it reorders the list wrongly (plant_1008 and plant_1006 swap).
A full scheduling optimiser (knapsack/VRP) captures little more for far more code, and the brief
warns that anything extra is extra to explain.

**Cost.** Ignores travel between regions and crew availability windows. Greedy, so not provably optimal.

**Falsifier.** Crews constrained to home regions (question #6, unanswered), or travel time large
enough to dominate cleaning time.

## 8. Partial washes: measured, not built

**Decision.** Ignore sub-8mm rainfall in the economics.

**Rejected.** Modelling it. Rain of 2–8 mm removes 33.2% of accumulated soiling (n=12; ≥8 mm gives
−100%, n=45, confirming the brief's threshold). It scales the dirty and clean paths alike, so the gap
decays and `s₀·T` overstates by 4–13% — costing plant_1000 $2,082. **It flips zero decisions.**

**Cost.** Recommendations are systematically slightly optimistic, worst in Andalusia (−12.6%) where
windows are shortest.

**Falsifier.** Any plant sitting within ~13% of break-even. Then the correction decides it.

## 9. Anomaly flagging: deferred, not built — open for revisit

**Decision.** No data-quality gate. Decision 1's interval median already absorbs isolated bad rows.

**Rejected.** A three-rule physical-plausibility gate. Tested directly: it changes `s₀` on 1 of 12
plants, by 0.42 points, on a plant nowhere near break-even. **Zero decisions change**, so it fails the
same test I applied in #8.

**What was found, for the record.** 14 plant-days contradict `soiling_loss_pct`'s stated meaning —
soiling falling 93–100% overnight with `rain_mm = 0.0` and `cleaned = 0`, one case surviving 19.7 mm
unchanged. On all 13 large drops, PR sits at 0.020–0.390 against a normal 0.92–0.98. No amount of
dust blocks 98% of sunlight. Wind removal was considered and is not present: drops are either >50
points (13 events) or <1 point (86 events, PR unchanged to three decimals) with **nothing between**.

**If revisited**, the flag should key on PR *level*, not on the day-over-day jump — the level fires on
day one of a problem, the jump only after it has ended, six days too late for plant_1003. It would be
a maintenance signal, not a cleaning one, and the value is that the fleet view doesn't go silent on a
plant losing far more than dirt ever could.

**Cost of deferring.** A plant at 2% output is silently absent from recommendations with no
explanation. `QualityFlag.AVAILABILITY_ANOMALY` in `backend/swishos/domain.py` is currently unused.

**Falsifier.** An anomaly lasting longer than half the current interval would defeat the median and
make the gate load-bearing rather than cosmetic. plant_1003's ran six days; the margin is thinner than
it looks.

## 10. `days_until_next_reset` used as a fixed horizon

**Decision.** Use the column as a constant per-plant expected horizon. Never decremented by days since
last rainfall. Confirmed by the organisers on 2026-09-16, who noted a different approach is permitted
but not expected.

**Rejected.** Estimating the rate per plant from `events.csv` — too few events (Atacama has three
wash events in 240 plant-days). Forecasting rainfall is explicitly out of scope.

**Cost.** Treating the mean of a spread-out distribution as certain. A plant can be rained on the day
after cleaning; expected value is right, variance is large and currently unshown.

**Falsifier.** Seasonal rainfall. Rajasthan's monsoon would break the memoryless reading exactly where
soiling is fastest.

## 11. Stack

**Decision.** Python/FastAPI backend, Next.js/TypeScript frontend — the stack named in the brief.

**Rejected.** Anything faster to write. "I used yours" costs nothing to defend and the brief says it
cares that it runs, not which framework.

**Cost.** Two runtimes and two dependency trees for a system one could serve from a single process.

**Falsifier.** None within the time budget.

---

## Not built

Auth · crew routing and travel time · rainfall forecasting · `readings/` ingestion · realtime updates ·
mobile crew app · tests beyond the soiling estimate and break-even arithmetic. Each was cut because it
does not change tomorrow's dispatch decision.
