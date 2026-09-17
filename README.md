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

**The input is the defect, not the algebra.** `soiling_loss_pct` is a total performance deficit
against the last post-wash baseline, so everything that suppresses output lands in it. Fed to the
brief's formula unchanged it ranks plant_1003 at **+$1,498,102** while the plant is producing 2% of
expected — cleaning recovers nothing there. The quality gate withholds readings that cannot be
soiling (1.6% of plant-days as availability anomalies, 15.3% withheld overall) before anything
reaches the economics.

**It never names a cause.** The data shows only that a deficit *is not soiling*. Inverter fault,
curtailment, maintenance and metering failure are indistinguishable in `daily.csv`, and the last of
those inverts the commercial response. Withheld days are surfaced with their evidence and no
diagnosis — a plant producing almost nothing is more urgent than any cleaning recommendation, so it
stays visible rather than being filtered out.

**Regions are a hard partition.** Every crew's home base maps onto exactly one plant region, so a
crew services only its own region and plants compete only against others in theirs. There is no
fleet-wide ranking. Treating crews as one pool understates the real bottleneck — Rajasthan needs
10.5 crew-days from a single crew, against 6.9 if crew-days were fungible.

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
