# Questions

Seven questions about the exercise. Each one would change what I build.

**I'm proceeding on the assumptions below — no answer needed unless one is wrong.**
Replying with just the question numbers I've got wrong is enough.

I haven't asked about anything the brief leaves to me (which persona gets a screen, how I decompose
the system, framework choice) — those are mine to decide and defend.

| # | Question | What I'm assuming |
|---|---|---|
| 1 | Is `soiling_loss_pct` soiling, or total deficit? | Total deficit — so I gate out non-soiling days |
| 2 | Is `days_until_next_reset` a fixed horizon or a countdown? | Fixed horizon, never decremented |
| 3 | How to treat plants commissioned mid-window? | Show them, flagged low-confidence |
| 4 | Should `readings/` be used at all? | No — skipping it, per the brief |
| 5 | Demonstrate the 200-plant run, or is the default enough? | Design for it, validate on the default |
| 6 | Are crews constrained to their home region? | No — any crew, any plant |
| 7 | Who are the ~120 people at 8am? | All seeing one shared fleet view |

---

## Data semantics

### 1. Is `soiling_loss_pct` intended as soiling only, or total performance deficit?

**What I see** — It's a deficit against a post-wash baseline, so anything suppressing output lands in
it. About 2% of plant-days sit at 60% or 98% loss, reverse the next day with no rain and no crew, and
in one case persist through 19.7 mm of rainfall.

**Assuming** — Those are not soiling. I exclude them from the cleaning economics and flag them.

### 2. Am I reading `days_until_next_reset` as a fixed expected horizon, correctly?

**What I see** — A static per-plant constant. The brief says use the column, and that forecasting
rainfall is out of scope.

**Assuming** — It means "on average this plant runs T days before rain resets it." I never decrement
it by days since last rainfall.

### 3. Should plants commissioned partway through the window be excluded, or caveated?

**What I see** — Two plants start mid-window (2026-07-21, 2026-06-20), leaving 56 and 87 days, with
very little history before their first baseline.

**Assuming** — An asset manager would rather see a caveated row than a silently missing plant.

### 4. Should `readings/` be used at all, or is it genuinely optional?

**What I see** — The brief says I shouldn't need it. But it holds defects the daily rollup hides:
negative overnight values on two plants, and one plant's timestamps offset by 5.5 hours.

**Assuming** — Genuinely optional. Not ingesting it.

## Scope

### 5. Should the submission demonstrate the 200-plant × 540-day run?

**What I see** — The brief offers it "if useful." 530 MB is a different exercise from 7 MB, and it
changes storage and precomputation choices.

**Assuming** — Design so it works at that scale, validate against the default dataset.

### 6. Should crews be constrained to their home region?

**What I see** — `crews.csv` gives each crew a home base matching the plant regions, but there's no
distance, travel time or mobilisation data.

**Assuming** — Any crew can reach any plant. I rank on $ per crew-day.

### 7. Who are the ~120 people loading the fleet view after 8am?

**What I see** — The brief names one asset manager and one crew lead. 120 is a third group.

**Assuming** — They all see the same fleet-wide ranking, so one precomputed daily snapshot serves
everyone. This is the only constraint driving my architecture, so I'd rather not guess.

---

## Resolved from the data — not asking

**Do `cleaning_cost_usd` and `crews.day_rate_usd` double-count the same labour?**

No. `cleaning_cost_usd` is $260–610/MW across the fleet; crew labour alone is $63–253/MW. The 5–9×
gap indicates `cleaning_cost_usd` is all-in, so I use it alone and don't add the day rate. Noted in
case that reading is wrong.
