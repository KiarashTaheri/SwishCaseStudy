# DECISIONS

Every decision, what it cost, and what would change my mind.
Assumptions I did not verify are in `ASSUMPTIONS.md` (A1–A15). Open questions to the organisers, and
the three answered on 2026-09-16, are in `questions.md`.

Numbers cited here are reproducible from `data/` — see `verify.py`.

---

## 1. Estimate today's soiling from the current interval only, not a fixed window

**Decision.** `s₀` is the median of the **3 most recent gated readings since the last reset**
(`rain_mm ≥ 8` or `cleaned = 1`), not a fixed trailing 14 days. The window never crosses a reset, and
excludes the reset day's own reading — rain on day *d* only reaches generation on *d+1*, so that
reading still describes the dirty plant (measured: higher than the next day in **93 of 96** reset
events, mean 3.69pp). This is the segmentation step NREL's RdTools SRR method performs before any
soiling fit.

**Why three.** Scored over 1,126 plant-days by the dollar cost of decision errors — a false dispatch
charged what it wastes, a missed clean what it forgoes: median/1 $486,834 · **median/2 $348,907** ·
median/3 $367,390 · median/5 $435,111 · median/10 $746,138. Two is lowest, but $18k over 1,126
decisions is not resolvable at 12 plants, and a median of two values is just their mean and tolerates
no bad day. Three is the shortest window where the median has any breakdown point. The boundary rule
is the structural defence; the median is the backstop for what the gate cannot see.

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

**Confirmed the hard way.** I built a forward projection — `s₀ + r·T/2`, the forward *mean* soiling
of the uncleaned plant — and tuned the estimator to match it. That is the wrong target: cleaning
recovers the constant *gap*, not the forward mean. Scored against a centred median of gated values
inside the same reset interval, the projection measured **10–13× worse** (341 false dispatches
against 18) and was removed. The algebra and the measurement agree; my intermediate step did not.

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

## 7. Rank within region; there is no fleet-wide ranking

**Decision.** Region is a hard partition on the dispatch problem, not an attribute of it. Each crew
services only its home region, so plants compete solely against others in the same region and the
fleet view is grouped, never globally ordered. Within a region, order by `recoverable_usd`.

**This reverses the earlier decision in this slot**, which ranked fleet-wide by dollars per crew-day.
That decision's own falsifier — "crews constrained to home regions (question #6, unanswered)" — has
now fired. Every `home_base` suffix maps onto exactly one plant region: Antofagasta/CL is the Atacama
port city, Jodhpur/RJ is in Rajasthan, Seville/ES in Andalusia, Townsville/QLD in Queensland, Phoenix
and Tucson/AZ in Arizona. Five regions, six crews, Arizona holding two. Flying the Jodhpur crew to
Arizona is not a scheduling option.

**Rejected.** *A single fleet-wide crew pool.* It is not merely presentational: it reports 6.9
crew-days to clean the fleet against a true per-region bottleneck of **10.5 crew-days in Rajasthan**
— one crew, the slowest (10.2 MW/day) and dearest ($2,578/day) in the fleet, against 106.8 MW of
plant. It would also rank a Chilean plant above a Rajasthan one and then offer a crew that cannot
reach it. *Dollars per crew-day* remains the right secondary ordering under scarcity, but it is only
meaningful within a region, because crew-days are not fungible across continents. *A scheduling
optimiser* captures little more for far more code.

**Cost.** No cross-region comparison, so the interface cannot answer "where is the fleet's best
dollar" — only "where is this region's". A region whose crew is saturated is starved with no
mechanism to borrow. Travel time and availability windows within a region are still unmodelled, and
crew choice within Arizona is not arbitrary either: crew_15 dominates crew_10 outright ($69/MW
against $122/MW).

**Falsifier.** A documented multi-region remit for any crew, or mobilisation cost data showing
cross-region dispatch is actually viable. Either collapses the partition and restores a global
ranking.
## 8. Partial washes: measured, not built

**Decision.** Ignore sub-8mm rainfall in the economics.

**Rejected.** Modelling it. Rain of 2–8 mm removes 33.2% of accumulated soiling (n=12; ≥8 mm gives
−100%, n=45, confirming the brief's threshold). It scales the dirty and clean paths alike, so the gap
decays and `s₀·T` overstates by 4–13% — costing plant_1000 $2,082. **It flips zero decisions.**

**Cost.** Recommendations are systematically slightly optimistic, worst in Andalusia (−12.6%) where
windows are shortest.

**Falsifier.** Any plant sitting within ~13% of break-even. Then the correction decides it.

## 9. Physical-plausibility gate on every reading — reversed from "deferred"

**Decision.** Withhold any plant-day with `pr < 0.5` before it reaches the estimator, label it
`AVAILABILITY_ANOMALY`, and surface it rather than drop it. Measured on the pinned dataset: 21 of
1,343 plant-days (1.6%) withheld as anomalies, 206 (15.3%) withheld in total once missing baselines
are counted.

**This reverses the earlier decision in this slot**, which deferred the gate because it moved `s₀` on
1 of 12 plants by 0.42 points and changed zero decisions. Two things overturned it. First, that
decision's own falsifier fired: it required "an anomaly lasting longer than half the current
interval", and plant_1003's ran six days — long enough to defeat the interval median outright. Second,
the earlier note predicted the fix exactly — *"the flag should key on PR level, not on the
day-over-day jump; the level fires on day one, the jump only after it has ended, six days too late."*
That is precisely what shipped.

**Why the threshold is not tuned.** The PR distribution is bimodal with an empty band: 21 readings at
or below **0.3899**, 1,322 at or above **0.8664**, and nothing between. Every cut inside that band
produces an identical partition, so the result does not depend on where it is placed. Corroboration:
of the 13 unexplained day-over-day soiling improvements above 1pp — improvements no rain and no
cleaning can account for — every one has a prior-day PR between 0.0198 and 0.3853, already below the
floor. The other 63 are all ≤ 0.240pp, which is noise.

**What the measurement does *not* show.** It establishes two populations, not which one is soiling.
That attribution rests on the brief's own statement that soiling only resets on rain or cleaning
(`ASSUMPTIONS.md` A1–A2), and the code says so rather than asserting it as fact. The gate also never
names a cause: inverter fault, curtailment, maintenance and metering failure are indistinguishable
here, and the last inverts the commercial response (A3).

**Rejected.** *Trusting `soiling_loss_pct`* — it ranks plant_1003 at **+$1,498,102** while the plant
produces 2% of expected. *Statistical outlier detection* (z-score, IQR, rolling MAD) — needs tuning,
carries no physical meaning, and would flag genuinely fast-soiling Rajasthan plants alongside real
faults. *A day-over-day jump rule* — fires only after the anomaly ends. *Silent dropping* — a plant
producing almost nothing is more urgent than any cleaning recommendation.

**Cost.** Blind to *partial* availability loss: a plant at 70% availability presents identically to
one at 30% soiling and passes the gate. A genuine soiling event below PR 0.5 would be withheld,
which I accept — at observed accumulation rates that state is months away and would be a maintenance
incident long before a cleaning decision.

**Falsifier.** A confirmed soiling event below PR 0.5 with no availability fault. Separately, the
empty band is measured on 12 plants × 120 days only; if the populations merge, the threshold stops
being free and starts discarding real soiling. Rather than assume, `gates.verify_empty_band()`
re-measures the gap on every build and warns when it closes (`ASSUMPTIONS.md` A2b).
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
Taken as the default rather than argued on technical merit: the live session is reviewers opening
files and asking why, and a familiar idiom spends none of that conversation on framework choice.

**Rejected.** *Vite + React* — fewer moving parts, no SSR machinery for one screen. Saves perhaps ten
minutes and costs a README paragraph justifying the deviation, plus a port if this ever lands in the
real SwishOS. *A single FastAPI process serving server-rendered HTML* — genuinely the smallest thing
that works, one runtime, no CORS, no contract to keep in sync; it directly eliminates the cost below.
It loses because it forfeits the typed contract between the ranking payload and the interface, and
dispatch correctness lives in that contract. *Next.js full-stack, no Python* — one runtime, and the
honest answer to the cost below; it loses because the domain logic is statistical (gating, medians
over reset-bounded windows, economics) and Python is where that is natural to write and test.

**Cost.** Two runtimes, two dependency trees, two dev servers, a CORS boundary, and an API contract
to keep in sync, for a system one process could serve. The real cost is setup surface: every extra
step is a way the clean clone fails on the reviewer's machine, and a system that does not boot scores
nothing regardless of what is inside it.

**Falsifier.** If a clean clone cannot run with roughly `pip install -r requirements.txt`,
`npm install` and two start commands, the two-runtime cost has outgrown the familiarity benefit and I
collapse to a single FastAPI process serving a prebuilt static bundle. Conversely, auth or a second
screen would make Next.js earn its place rather than being overhead.

---

## Not built

Auth · crew routing and travel time · rainfall forecasting · `readings/` ingestion · realtime updates ·
mobile crew app · tests beyond the soiling estimate and break-even arithmetic. Each was cut because it
does not change tomorrow's dispatch decision.
