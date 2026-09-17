# ASSUMPTIONS

Assumptions I made and did not verify. Listed because each would change what I built if it were wrong.

Same field format as [`DECISIONS.md`](./DECISIONS.md), with **Source** added so every belief carries
its provenance — *brief* (the exercise's own prose taken as fact), *inferred* (my reasoning), or
*measured* (evidence stated so it can be judged rather than trusted).

Referenced from the decision log as `[A#]`.

---

### A1 — Soiling decreases only at a reset event; it never self-removes

| Field | |
|---|---|
| **Assumption** | Soiling loss can only fall when rain ≥ 8mm falls or a crew cleans. Any other decrease is a measurement artefact. |
| **Source** | *Brief*, Background: "It builds gradually, resets when it rains, and resets fully when a crew cleans." I converted that prose into a hard invariant. |
| **Rejected** | Treating `soiling_loss_pct` as authoritative. It ranks a plant reporting 97.98% loss first in the fleet and sends a crew to clean panels that are not dirty. |
| **Cost** | The most load-bearing assumption in the system — the whole quality gate rests on it. If false, the 11 measured overnight recoveries (>20% loss → <10% next day, `rain_mm = 0.0`, `cleaned = 0`) are genuine, the gate discards real data, and the advisor under-dispatches silently. |
| **Falsifier** | Availability or O&M records showing those plant-days were healthy. One afternoon with whoever owns the SCADA history. The first question I would email. |

---

### A2 — The low-PR population is not recoverable by cleaning

| Field | |
|---|---|
| **Assumption** | The lower of the two PR populations represents availability faults, not dirt. |
| **Source** | *Inferred* from A1, plus a *measured* distribution: across 1,343 plant-days, 21 readings sit at or below PR 0.3899, 1,322 at or above 0.8664, and nothing falls between. The measurement establishes there are two populations; it does not say which is soiling. That attribution is A1, and generalising from the 13 individually-demonstrated cases to all 21 sub-floor readings is this assumption doing the work. `gates.py` must not state it as fact. |
| **Rejected** | Statistical outlier detection (z-score, IQR, rolling MAD) — needs tuning, carries no physical meaning, and would flag genuinely fast-soiling Rajasthan plants alongside real faults. |
| **Cost** | The gate throws away the most valuable plants in the fleet — the ones showing the largest apparent losses. |
| **Falsifier** | A confirmed soiling event below PR 0.5 with no availability fault. |

---

### A2b — The empty band around PR 0.5 persists beyond the default dataset

| Field | |
|---|---|
| **Assumption** | The gap between the two PR populations stays empty on other datasets, so `MIN_CREDIBLE_PR = 0.5` remains a free choice rather than a tuned one. |
| **Source** | *Inferred.* Measured on 12 plants × 120 days only. The threshold is defensible *because* nothing lies between 0.3899 and 0.8664 — any cut inside that range yields the same partition. That is a property of this sample, not a law. |
| **Rejected** | Hard-coding 0.5 and saying nothing. It would hide the fact that the justification is sample-dependent. |
| **Cost** | On the 200-plant/540-day run, or on real telemetry, the distribution may be continuous. The threshold then acquires cost on both sides: a partial fault at PR 0.6 passes the gate and inflates an estimate, while raising the floor to catch it starts eating genuine soiling. The higher the floor, the more dirt discarded. |
| **Falsifier** | Cheap enough that the system checks rather than assumes. `gates.verify_empty_band()` recomputes the gap for whatever data is loaded and reports the nearest reading either side; ingest warns when the band closes. A monitored invariant, not a silent dependency. |

---

### A3 — The root cause of a gated day does not need to be known

| Field | |
|---|---|
| **Assumption** | Knowing a reading is not recoverable by cleaning is sufficient; the underlying fault need not be identified. |
| **Source** | *Inferred*, scoping choice. Nothing in `daily.csv`, `events.csv` or `plants.csv` distinguishes an inverter fault from curtailment, a transformer trip, a comms dropout or planned maintenance. |
| **Rejected** | Naming a cause in the interface. I cannot see one, and asserting an unverifiable root cause is worse than reporting an unexplained anomaly. |
| **Cost** | If some causes *are* cleaning-recoverable, treating the whole population as uninformative discards real value. |
| **Falsifier** | Fault codes, which this dataset does not contain. |

---

### A4 — A gated day carries no usable soiling information

| Field | |
|---|---|
| **Assumption** | Rejected days are treated as missing, not as zero — they neither raise nor lower the estimate. |
| **Source** | *Inferred.* A plant can be faulty and dirty simultaneously; no attempt is made to recover the soiling component underneath a fault. |
| **Rejected** | Interpolating across gated days. It would invent data precisely where the instrument is known to be unreliable. |
| **Cost** | A plant with a long fault — `plant_1003`, six days — loses six days of history, and its estimate rests on fewer samples than the window length implies. |
| **Falsifier** | A method separating availability loss from soiling loss within a single day, which needs the intra-day telemetry this system does not ingest. |

---

### A5 — `cleaning_cost_usd` is all-in and already includes crew labour

| Field | |
|---|---|
| **Assumption** | Crew `day_rate_usd` is already inside `cleaning_cost_usd` and must not be added again. |
| **Source** | *Not stated anywhere in the brief* — a guess, and the one I am least comfortable with. *Measured* evidence below is genuinely ambiguous. |
| **Rejected** | Adding `day_rate_usd` on top. If crew cost were additional, Rajasthan cleaning would cost nearly double its stated figure, which seems unlikely — but the evidence does not settle it. |
| **Cost** | *Measured*: adding each plant's suggested crew-days at its region's day rate flips **3 of the 5 current recommendations** negative, and takes the fleet total from **$44,719 to $28,554**. The ambiguity does not merely shift the numbers; it removes most of tomorrow's dispatch list. Table below. |
| **Falsifier** | One email. The brief invites questions and this is what I would spend one on. |

What each recommendation is worth if the day rate turns out to be additive:

| Plant | Recoverable | Suggested crew | Crew cost | Net if A5 is wrong |
|---|---|---|---|---|
| `plant_1000` | $29,674 | 3.4 d × $1,379 | $4,690 | +$24,985 |
| `plant_1008` | $8,911 | 2.9 d × $1,842 | $5,342 | +$3,569 |
| `plant_1006` | $4,259 | 5.3 d × $2,578 | $13,664 | **−$9,405** |
| `plant_1005` | $1,692 | 3.0 d × $1,379 | $4,138 | **−$2,445** |
| `plant_1001` | $182 | 4.7 d × $2,578 | $12,117 | **−$11,935** |

Implied crew cost (`day_rate_usd / mw_per_day`) against `cleaning_cost_usd / capacity_mw`:

| Region | Crew $/MW | Cleaning $/MW | Crew as share |
|---|---|---|---|
| Andalusia, Spain | 63 | 520 | 12% |
| Arizona, USA | 69 – 122 | 480 | 14 – 25% |
| Atacama, Chile | 152 | 610 | 25% |
| Queensland, AUS | 188 | 540 | 35% |
| **Rajasthan, India** | **253** | **260** | **97%** |

A ratio ranging from 12% to 97% cannot be inferred either way.

---

### A6 — `days_until_next_reset` is the expected wait of a memoryless process

| Field | |
|---|---|
| **Assumption** | The column is an expected remaining wait that does not shrink as days elapse, so elapsed days must **not** be subtracted from it. |
| **Source** | *Inferred* — the column is described only as "typical days before rainfall washes this plant clean by itself." *Measured* support below. Observed gap distributions also show mean ≈ stdev (Queensland 6.8/6.2, Arizona 16.8/12.8), consistent with a geometric process. |
| **Rejected** | Subtracting days since the last reset. This was my first instinct — `plant_1000` is 24 days into a stated 32-day cycle, so only ~8 days of benefit appear to remain. The measurement below shows that would have been a bug, not an improvement. |
| **Cost** | If the column is instead a deterministic countdown, every plant late in its cycle is over-valued; `plant_1000` would fall by roughly three quarters. Atacama's estimate rests on 3 rain days in 240 plant-days and is too thin to trust in either direction. |
| **Falsifier** | The 540-day scale run supplies enough rain events, including for Atacama. |

`1/P(reset per day)` over rain-only resets, computed across all plant-days so it is not right-censored
by the 120-day window:

| Region | Stated | 1/P(reset/day) | |
|---|---|---|---|
| Andalusia, Spain | 13 | 12.0 | agrees |
| Arizona, USA | 32 | 26.3 | agrees |
| Rajasthan, India | 22 | 27.7 | agrees |
| Queensland, AUS | 7 | 8.0 | agrees |
| Atacama, Chile | 45 | 80.0 | **diverges** |

---

### A7 — Rain ≥ 8mm resets soiling completely

| Field | |
|---|---|
| **Assumption** | A rain event of 8mm or more returns the plant to a clean baseline. |
| **Source** | *Brief* — "roughly 8mm or more washes the panels clean." *Measured* evidence partly contradicts it: across 73 rain-reset events, mean residual `soiling_loss_pct` the following day is **1.37%**, not zero. Most land at 0.00 but some leave residue. |
| **Rejected** | Modelling partial washing as a function of rainfall depth. More parameters, and the bias it corrects is around one percentage point. |
| **Cost** | Estimation windows begin slightly dirty, biasing the median down by roughly a point — in the conservative direction, so it is accepted rather than modelled. |
| **Falsifier** | Residual loss after rain resets growing large enough to change a ranking. Measurable directly on the scale run. |

---

### A8 — The `soiling_loss_pct` baseline is sound wherever the gate passes it

| Field | |
|---|---|
| **Assumption** | The published loss column is trustworthy on days the gate does not reject. |
| **Source** | *Inferred.* The brief does not document how the baseline is derived, saying only "Blank where there is no clean baseline to compare against yet." I consume the column as given. |
| **Rejected** | Recomputing soiling from `pr` against an independently derived post-reset baseline. It removes the dependency entirely and is the right answer; rejected for the four-hour budget, and high on the list of what to build next. |
| **Cost** | *Measured* risk: three reset events coincide with days the gate rejects — `plant_1000` 2026-07-18 (`cleaned=1`, loss 62.23), `plant_1011` 2026-06-06 (`cleaned=1`, loss 62.91), `plant_1003` 2026-07-08 (19.7mm rain, mid-outage). If a baseline is anchored on such a day, every later loss value is wrong, and the gate will not catch it because subsequent days look normal. Systematic and silent. |
| **Falsifier** | Recomputing the baseline independently and comparing against the published column. |

---

### A9 — A cleaning visit completes fast enough that the reset is effectively instant

| Field | |
|---|---|
| **Assumption** | Soiling drops to zero on the dispatch date. |
| **Source** | *Inferred* — and the *measured* data argues against it. Dividing plant capacity by the nearest regional crew's `mw_per_day`, **10 of 12 plants need more than one crew-day**: `plant_1009` 6.3, `plant_1003` 6.0, `plant_1006` 5.3, `plant_1001` 4.7. Only `plant_1007` (0.2) and `plant_1011` (0.6) fit inside a day. |
| **Rejected** | Multi-day job modelling with crew calendars. It is the correct treatment and I explicitly chose not to build it inside four hours. |
| **Cost** | "Send a crew tomorrow" is really "start tomorrow, finish in six days." Recoverable value is overstated by however long the job runs, and a crew committed for six days cannot take the second-ranked job. **Known false today**, not merely at risk. |
| **Falsifier** | Already falsified in direction; what is missing is the scheduling model that would handle it. |

---

### A10 — `expected_energy_kwh` is correctly weather-corrected

| Field | |
|---|---|
| **Assumption** | Irradiance and temperature correction in the source data is unbiased. |
| **Source** | *Brief* — "Already corrected for irradiance and temperature." |
| **Rejected** | Deriving expected energy from the raw `readings/` telemetry. That is 96× the data volume to re-derive a column I was told is already correct. |
| **Cost** | If the correction is biased, PR is biased, so soiling loss is biased, so every dollar figure is biased — and nothing downstream would reveal it. |
| **Falsifier** | An independent irradiance reference for the same sites. None exists in this dataset. |

---

### A11 — `events.csv` records every cleaning and every rainfall

| Field | |
|---|---|
| **Assumption** | The event log is complete, so "days since last reset" is correct. |
| **Source** | *Inferred* from it being presented as the event log. |
| **Rejected** | Inferring resets from PR jumps instead of the event log. Worth adding as a cross-check rather than a replacement. |
| **Cost** | Small, and smaller than it was. While the estimator ran a multi-day window, an unrecorded reset let that window average a dirty plant with a clean one — the failure that justified a reset-boundary rule. Deleting the window (Decision 2) deleted that exposure with it: `s₀` is today's gated reading, and a plant washed yesterday simply reads clean today, which is correct whether or not the wash was logged. What remains is `r`, `days_since_reset` and `last_reset_on`. *Measured*: discarding `events.csv` **entirely** moves `r` by at most **0.035 pp/day** (`plant_1009`, 0.065 → 0.030) and never by more than 0.025 on any plant the system currently recommends — the median over day-over-day pairs absorbs the spurious negative. `r` does not value a cleaning (it cancels), so nothing here reaches `recoverable_usd`. It reaches "how soon does this become worth cleaning", and the interface's stated reset date. |
| **Falsifier** | A PR jump with no corresponding event row. Detectable, and a good addition to the gate. |

---

### A12 — Tariff is flat, with no curtailment, degradation or PPA structure

| Field | |
|---|---|
| **Assumption** | Recovered energy is worth `kWh × tariff_per_kwh` at any hour. |
| **Source** | *Brief* supplies a single `tariff_per_kwh` per plant. |
| **Rejected** | Time-of-day price weighting. No price curve is supplied. |
| **Cost** | Plants with time-of-day pricing rank differently. Soiling losses concentrate at midday, typically when power is worth least, so this likely biases the ranking **high**. |
| **Falsifier** | The actual PPA or market price curve for any one plant. |

---

### A13 — The asset manager is optimising recovered dollars

| Field | |
|---|---|
| **Assumption** | Ranking by `recoverable_usd` matches how the spend is actually approved. |
| **Source** | *Brief* — "She approves the spend." |
| **Rejected** | A multi-objective view including water and truck miles. No data supports weighting them. |
| **Cost** | If water use, truck miles, contractual SLAs or carbon reporting constrain the decision, a pure dollar ranking is the wrong objective function and the interface shows the wrong column. |
| **Falsifier** | Ten minutes with the asset manager. |

---

### A14 — Crews serve only their own region, and are otherwise interchangeable

| Field | |
|---|---|
| **Assumption** | A crew services only plants in its home region. Within a region, crews differ only by `mw_per_day` and `day_rate_usd`. Region is therefore a hard partition on the dispatch problem, not an attribute of it. |
| **Source** | *Measured*, and unambiguous: every `home_base` suffix maps onto exactly one plant region — Antofagasta/CL is the Atacama port city, Jodhpur/RJ is in Rajasthan, Seville/ES in Andalusia, Townsville/QLD in Queensland, Phoenix and Tucson/AZ in Arizona. Five regions, six crews, Arizona holding two. Flying crew_11 from Jodhpur to clean an Arizona plant is not a scheduling option. |
| **Rejected** | A single fleet-wide crew pool. It yields 6.9 crew-days to clean everything, against a true per-region bottleneck of **10.5 crew-days in Rajasthan** — optimistic by more than a third. It would also rank a Chilean plant above a Rajasthan one and then offer a crew that cannot reach it. Also rejected: a travel-time or routing model, since no distances are supplied. |
| **Cost** | Capacity must be checked per region, so no global "dollars per crew-day" ranking is valid — plants only compete against others in their own region. Rajasthan is structurally squeezed: one crew, the slowest (10.2 MW/day) and the most expensive ($2,578/day) in the fleet, against 106.8 MW of plant. Within Arizona, crew_15 dominates crew_10 outright ($69/MW against $122/MW), so crew choice is not arbitrary either. Skills, certifications, equipment and water access remain unmodelled. |
| **Falsifier** | A crew with a documented multi-region remit, or any crew attribute beyond throughput and rate that constrains which plants it can service. |

---

### A15 — The last day in the data is "today", and the decision is for tomorrow

| Field | |
|---|---|
| **Assumption** | No reporting lag between telemetry and the advisor. |
| **Source** | *Inferred.* Data ends 2026-09-14; the exercise is dated 2026-09-15. |
| **Rejected** | Hard-coding a lag. I have no basis for choosing one. |
| **Cost** | If a lag exists, every estimate is stale by its length, and fast-soiling plants (Rajasthan, ~0.35%/day) drift furthest. |
| **Falsifier** | The actual telemetry arrival schedule. |
