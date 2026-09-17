# DECISIONS

Every decision, what it cost, and what would change my mind.
Assumptions I did not verify are in `ASSUMPTIONS.md` (A1–A15). Open questions to the organisers, and
the three answered on 2026-09-16, are in `questions.md`.

Numbers cited here are reproducible from `data/` — see `verify.py`.

---

## 1. Use the brief's formula, and improve exactly one of its two inputs

**Decision.** `recoverable_usd = s₀·E·τ·T − C`, as the brief wrote it. Presented as a break-even
soiling threshold `s* = C/(E·τ·T)` and the margin over it, which is the same statement in a form a
human can check. One input is changed:

| Input | Treatment | Why |
|---|---|---|
| `s₀` — `soiling_loss_pct` | **today's gated reading, as supplied** | a *state*. The formula multiplies it by nothing, so there is nothing to average over. |
| `E` — `expected_energy_kwh` | **14-day median** | a *rate*. The formula multiplies it by `T` (up to 45 days), so it needs a typical day, not today's weather. |

That distinction is the whole improvement, and it is the only place the brief's arithmetic is
touched. *Measured*: `expected_energy_kwh` moves a mean of **26% day over day**; on 2026-09-14 it
runs 25% above typical at plant_1001 and 19% below at plant_1005 — and plant_1005's verdict turns on
that alone, −$4,164 on today's dim reading against +$1,692 on a typical day. Whether a plant is
worth cleaning should not depend on whether today was cloudy. The window length barely matters,
which is the point: 7, 14 and 30 days sit within 0.23pp of each other on break-even, while 1 day is
0.518pp away and the full record 0.440pp away as seasonal drift leaks in.

**Rejected.** *Smoothing `s₀` as well.* I shipped a 3-day trailing median of gated readings before
measuring it properly — see #2. *Rewriting the integral.* Under linear accumulation the gain is
∫₀ᵀ(s₀+rt)dt − ∫₀ᵀ(rt)dt = s₀·T, exactly what the brief wrote. Linearity holds: six plants keep a
constant rate across both halves of their longest dry run, and nothing exceeds 12% loss, so
saturation never binds. *Adding a `days_until_next_reset` countdown* — see A6; four of five regions
confirm the column is an expected wait, not a countdown.

**Cost.** `s₀` now rests on a single reading, so one bad day that passes the gate goes straight into
the economics with nothing behind it. The gate is the only defence, which is why A2b's monitoring
exists. Inherits the formula's assumptions: instant full recovery, fixed horizon, no discounting.

**Falsifier.** A partial fault — a plant at PR 0.6, below any plausible soiling but above the gate's
floor — would pass into `s₀` unchallenged and buy a cleaning that recovers nothing. A single month
of real PR with maintenance tickets attached would show whether that band is populated. Separately,
if `expected_energy_kwh` were already a rolling figure rather than a daily one, the 14-day median
would be redundant.

## 2. Two estimators built, measured, and deleted

**Decision.** Both attempts to improve `s₀` were removed after measurement. Recording them because
they were the two most expensive hours of the build and the reasoning is the deliverable.

**Attempt one — forward projection.** I computed `s₀ + r·T/2`, the forward *mean* soiling of the
uncleaned plant, and tuned the estimator against it. Wrong target: cleaning recovers the constant
*gap* between the cleaned and uncleaned trajectories, not the forward mean, and both accumulate at
the same rate so `r` cancels. Scored against a centred median of gated values inside the same reset
interval, the projection measured **10–13× worse** — 341 false dispatches against 18.

**Attempt two — a 3-day trailing median.** Having removed the projection I replaced it with
smoothing, which fails in the opposite direction. A trailing median *lags* a rising quantity. Gated
soiling climbs a median **0.240pp/day**, so a 3-day median describes the plant as it was a day ago
and reads too clean. *Measured*: plant_1000 on 2026-08-01 read 0.65pp low, fell below break-even,
and passed on a **$6,414** gain. **24 plant-days** go that way. It also cost coverage — the window
needed three usable days since the last reset, so it declined to rank **455 of 1,343** plant-days
(66.1% coverage) against 206 (84.7%) now, and **269 of those refusals were plants that had simply
been washed recently**: clean plants, described as unknowable.

**What both had in common.** I was smoothing a quantity that does not need it. Behind the quality
gate there is no noise left for a median to defend against — gated soiling never moves more than
1.56pp in a day — only lag for it to introduce.

**Rejected.** *Keeping the 3-day median and justifying it as robustness.* A median of three tolerates
one bad value, which is real insurance; but the gate already removes the values it would be
insuring against, so it is paying twice for one defence and taking a measurable loss to do it.

**Cost.** Two parameters and a reset-boundary rule were deleted along with the estimator, and with
them a genuine protection: the 3-day median would have absorbed a single bad reading that slipped
past the gate. That protection is now entirely the gate's job.

**Falsifier.** A bad reading passing the gate and reaching a dispatch. If that happens, the answer is
a better gate — a per-plant detector calibrated against that plant's own post-wash baseline — not a
median reinstated on top of a gate that let it through.

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

**Why withholding them is right, without disputing what the column means.** `soiling_loss_pct` is
output lost to dirt — the brief says so, and the organisers confirmed it when asked. The gate does
not need that claim overturned. It rests on something narrower and fully measured: **soiling
accumulates.** Gated soiling rises a median 0.240pp/day, never more than 1.56pp in a day, and has
never exceeded 11.74% on a credible reading across 1,138 plant-days. Against that, 29 transitions
move more than 20pp overnight — plant_1000 goes 0.06% → 60.18% → 0.52% on consecutive days with no
rain and no crew.

**A loss that reverses overnight without a wash is not a loss a wash recovers.** That is the whole
argument, it needs no claim about what caused anything, and it survives the organisers' answer. An
earlier draft of this log argued instead that the column "is not soiling"; that was a stronger claim
than the evidence supports and than the brief allows, and it has been withdrawn.

The gate still never names a cause: inverter fault, curtailment, maintenance and metering failure
are indistinguishable here, and the last inverts the commercial response (A3).

**Rejected.** *Trusting `soiling_loss_pct`* — it ranks plant_1003 at **+$1,498,102** while the plant
produces 2% of expected. *Statistical outlier detection* (z-score, IQR, rolling MAD) — needs tuning,
carries no physical meaning, and would flag genuinely fast-soiling Rajasthan plants alongside real
faults. *A day-over-day jump rule* — fires only after the anomaly ends. *Silent dropping* — a plant
producing almost nothing is more urgent than any cleaning recommendation.

**Cost.** Blind to *partial* availability loss: a plant at 70% availability presents identically to
one at 30% soiling and passes the gate. That cost rose when the 3-day median was removed (#2) — the
gate is now the only thing standing between a bad reading and a dispatch. A genuine soiling event below PR 0.5 would be withheld,
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
