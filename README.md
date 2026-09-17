# SwishOS — Fleet Soiling & Cleaning Advisor

Decides where to send a cleaning crew tomorrow, for an asset manager with 200 solar plants, and
produces the work order that carries the decision out.

**Read [`DECISIONS.md`](./DECISIONS.md) first** — it covers what was built, what was rejected, what
each choice costs, and what would change my mind. [`ASSUMPTIONS.md`](./ASSUMPTIONS.md) lists what I
did not verify. [`questions.md`](./questions.md) holds the open questions for the organisers.

---

## Run it

Four commands from a clean clone. Python ≥ 3.11 and Node ≥ 18.

```bash
# 1. Generate the dataset — the --start flag is required, see below
python3 seed_data.py --start 2026-05-18

# 2. Backend: install, build the database, serve on :8000
cd backend
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
PYTHONPATH=. ./.venv/bin/python -m swishos.build --data ../data --db swishos.db
PYTHONPATH=. ./.venv/bin/uvicorn swishos.api:app --port 8000

# 3. Frontend: install and serve on :3000 (in a second terminal)
cd frontend && npm install && npm run dev
```

Open <http://localhost:3000>.

**No API key needed.** The LLM step writes the approval briefing and the crew work order. Without
`ANTHROPIC_API_KEY` it falls back to a deterministic template and reports `"source": "template"`;
nothing else changes. Set the key to enable it.

**The frontend runs without the backend.** If the API is unreachable it serves a bundled sample and
says so in a banner, so the UI can be demonstrated on its own.

### Verify the numbers

```bash
cd backend && PYTHONPATH=. ./.venv/bin/python scripts/verify.py
```

Reproduces, from `data/` alone, every measurement cited in `DECISIONS.md` — the performance-ratio
gap the quality gate relies on, the reset-day boundary, the estimator window sweep, and the gate
rates.

```bash
cd backend && ./.venv/bin/python -m pytest -q
```

### Why `--start` is not optional

`seed_data.py:213` falls back to `date.today() - days` when `--start` is omitted, so the generator is
deterministic **only on a given calendar day**. Row values are seeded and stable, but every date
shifts. Verified: `--start 2026-05-18` reproduces the committed fixtures byte-identically across all
four CSVs; an unpinned run a day later produces `2026-05-19 → 2026-09-15` instead of
`2026-05-18 → 2026-09-14`, and matches none of the dates cited in the documents.

"Today" throughout the system means the last row in `daily.csv`, never wall-clock time.

---

## What it does

```
CSV → ingest → quality gate → soiling estimate → economics → daily snapshot → API → UI
```

**Some rows do not behave like dirt.** `soiling_loss_pct` is output lost to dirt, as the brief
says. But soiling accumulates: it moves a median of **0.240pp/day**, never more than **1.56pp**, and
has never exceeded **11.74%** on a credible reading. Against that, 29 transitions move more than
20pp overnight — `plant_1000` goes 0.06% → 60.18% → 0.52% on consecutive days with no rain and no
crew. **A loss that reverses overnight without a wash is not a loss a wash recovers.** Fed to the
formula unchanged, the worst of these ranks plant_1003 at **+$1,498,102** while it produces 2% of
expected. The quality gate withholds those readings before anything reaches the economics.

**It never names a cause.** Inverter fault, curtailment, maintenance and metering failure are
indistinguishable in `daily.csv`, and the last of those inverts the commercial response. Withheld
days are surfaced with their evidence and no diagnosis — a plant producing almost nothing is more
urgent than any cleaning recommendation, so it stays visible rather than being filtered out.

**One input is improved on, and only one.** The brief's formula is used as written, with today's
`soiling_loss_pct` — it is a *state*, and multiplying it by nothing means there is nothing to
average. `expected_energy_kwh` is a *rate* the formula multiplies by up to 45 days, so it uses a
14-day median instead of today's weather: measured, one day's value swings 26% on average, and
`plant_1005`'s entire verdict turns on today being 19% dimmer than typical.

**Regions are a hard partition.** Every crew's home base maps onto exactly one plant region, so a
crew services only its own region and plants compete only against others in theirs. There is no
fleet-wide ranking. Treating crews as one pool understates the real bottleneck — Rajasthan needs
10.5 days from a single crew, against the 6.9 a pooled model reports for the whole fleet — 1.51x
optimistic.

**The decision is the brief's own.** Clean when `recoverable_usd = s₀·E·τ·T − C > 0`. Equivalently,
when soiling passes the plant's break-even threshold `s* = C/(E·τ·T)`. The interface leads with the
margin over that threshold rather than the dollar figure, because "2.29 points past where cleaning
pays for itself" is something a human can check and a dollar total is not.

**The LLM sits at the rendering boundary only** — computed numbers and flags in, prose out. It never
ranks, never computes a value, never detects an anomaly. Acting on a recommendation dispatches a
truck and spends roughly what it expects to recover, which demands an auditable, reproducible number.

---

## Layout

| Path | |
|---|---|
| `backend/swishos/` | ingest, quality gate, estimator, economics, ranking, snapshot, dispatch, briefing, API |
| `backend/scripts/verify.py` | reproduces every measured claim from `data/` |
| `backend/tests/` | pytest suite |
| `frontend/` | Next.js + TypeScript interface |
| `docs/api-contract.md` | frozen backend/frontend contract |
| `docs/fixtures/` | real payloads generated from the pipeline |

`data/` and `data_scale/` are generated and not committed, per the brief.
