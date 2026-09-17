"""SQLite connection management and schema.

Why SQLite: generated at the stated end state (200 plants x 5 years), the daily
rollups are 335,585 rows, the database is 93.4 MB, and the fleet ranking query
runs in 0.22 ms. The deployment constraint is that the system runs from a clean
clone with no hosted services, and `sqlite3` ships with Python. See DECISIONS.md
#4 for the commands that reproduce those figures, what they do and do not
establish, and the conditions that would force Postgres.

The figure that matters for growth is `ranking_snapshot`, not `daily_reading`:
a snapshot row is 369 bytes and one is written per plant per day, so retaining
them for five years costs ~135 MB against the readings' 21.8 MB. Derived data
outgrows source data here, and that table is the one that needs an expiry rule.

Table layout follows DDIA ch.17's separation of source data from derived data:
`plant`, `crew`, `daily_reading` and `plant_day_event` mirror the CSVs verbatim
and are never mutated by later stages. `reading_quality` and `ranking_snapshot`
are derived output and can always be dropped and recomputed from the tables
above.

`dispatch` is the exception that proves the rule: it sits at the end of the
pipeline but is *source* data, because it records a decision a human made. It is
the only table a rebuild must not touch.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS plant (
    plant_id              TEXT    PRIMARY KEY,
    name                  TEXT    NOT NULL,
    region                TEXT    NOT NULL,
    capacity_mw           REAL    NOT NULL,
    tariff_per_kwh        REAL    NOT NULL,
    cleaning_cost_usd     REAL    NOT NULL,
    days_until_next_reset INTEGER NOT NULL,
    commissioned_on       TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS crew (
    crew_id      TEXT PRIMARY KEY,
    home_base    TEXT NOT NULL,
    mw_per_day   REAL NOT NULL,
    day_rate_usd REAL NOT NULL
);

-- pr and soiling_loss_pct are nullable on purpose: the source publishes blanks
-- where no clean baseline exists yet, and coercing those to 0.0 would read as a
-- perfectly clean plant.
CREATE TABLE IF NOT EXISTS daily_reading (
    plant_id            TEXT NOT NULL REFERENCES plant(plant_id),
    date                TEXT NOT NULL,
    energy_kwh          REAL NOT NULL,
    expected_energy_kwh REAL NOT NULL,
    pr                  REAL,
    soiling_loss_pct    REAL,
    PRIMARY KEY (plant_id, date)
);

CREATE TABLE IF NOT EXISTS plant_day_event (
    plant_id TEXT    NOT NULL REFERENCES plant(plant_id),
    date     TEXT    NOT NULL,
    rain_mm  REAL    NOT NULL,
    cleaned  INTEGER NOT NULL CHECK (cleaned IN (0, 1)),
    PRIMARY KEY (plant_id, date)
);

-- Derived from daily_reading by the quality gate. Safe to drop and rebuild.
CREATE TABLE IF NOT EXISTS reading_quality (
    plant_id TEXT NOT NULL,
    date     TEXT NOT NULL,
    flag     TEXT NOT NULL,
    detail   TEXT,
    PRIMARY KEY (plant_id, date),
    FOREIGN KEY (plant_id, date) REFERENCES daily_reading(plant_id, date)
);

-- Derived from everything above. The stated load is ~120 people opening the
-- fleet view after 8am; the ranking is a pure function of data through
-- yesterday and cannot change during the day, so it is computed once and read
-- from here. Caching with the hard part removed — the key is the date, so there
-- is no invalidation problem. Safe to drop and rebuild.
CREATE TABLE IF NOT EXISTS ranking_snapshot (
    as_of                         TEXT    NOT NULL,
    plant_id                      TEXT    NOT NULL REFERENCES plant(plant_id),
    region                        TEXT    NOT NULL,
    rank_in_region                INTEGER,
    status                        TEXT    NOT NULL,
    soiling_loss_pct              REAL,
    break_even_soiling_pct        REAL,
    margin_pct                    REAL,
    recoverable_usd               REAL,
    cleaning_cost_usd             REAL    NOT NULL,
    expected_energy_kwh_per_day   REAL    NOT NULL,
    tariff_per_kwh                REAL    NOT NULL,
    days_until_next_reset         INTEGER NOT NULL,
    accumulation_rate_pct_per_day REAL,
    days_to_break_even            REAL,
    usable_days                   INTEGER NOT NULL,
    days_since_reset              INTEGER,
    last_reset_on                 TEXT,
    withheld_days_last_14         INTEGER NOT NULL,
    suggested_crew                TEXT,
    PRIMARY KEY (as_of, plant_id)
);

-- NOT derived data, despite sitting downstream of it. A dispatch is a human
-- decision to spend money, so it cannot be recomputed from the CSVs and must
-- survive `python -m swishos.build` dropping and rebuilding everything else.
--
-- `snapshot_json` stores the numbers the decision was made on. The estimate
-- moves daily, so when a cleaning under-recovers the only useful question is
-- what was believed at the time — unanswerable without this column.
CREATE TABLE IF NOT EXISTS dispatch (
    dispatch_id   TEXT PRIMARY KEY,
    plant_id      TEXT NOT NULL REFERENCES plant(plant_id),
    as_of         TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    crew_id       TEXT NOT NULL REFERENCES crew(crew_id),
    crew_days     REAL NOT NULL,
    snapshot_json TEXT NOT NULL,
    work_order    TEXT NOT NULL,
    -- One dispatch per plant per day. The crew can only clean it once, and a
    -- double-booking is a wasted truck, so the constraint lives in the schema
    -- rather than in a check the API could forget to run.
    UNIQUE (plant_id, as_of)
);

-- The fleet view always reads the most recent days across all plants, so date
-- leads the index. Plant detail views are served by the primary key.
CREATE INDEX IF NOT EXISTS idx_daily_reading_date ON daily_reading(date);
CREATE INDEX IF NOT EXISTS idx_reading_quality_flag ON reading_quality(flag);
CREATE INDEX IF NOT EXISTS idx_snapshot_region ON ranking_snapshot(as_of, region);
CREATE INDEX IF NOT EXISTS idx_dispatch_as_of ON dispatch(as_of);
"""


def connect(database_path: Path | str) -> sqlite3.Connection:
    """Open a connection with the pragmas this system depends on.

    WAL is required, not cosmetic: readers must not block on the daily ingest
    write. Foreign keys are off by default in SQLite and must be enabled per
    connection, so the REFERENCES clauses above are inert without this.

    `check_same_thread=False` is required by how the API serves requests, and is
    safe only because of how it hands connections out. FastAPI runs a sync
    dependency and the sync endpoint that depends on it in a threadpool, and
    makes no promise they land on the same thread — so a connection opened in
    the dependency and used in the endpoint trips SQLite's default thread guard
    even though only one thread ever touches it. The guard is checking thread
    *identity*; what actually matters is concurrent *use*, and `api.py` gives
    every request its own connection and closes it when the request ends.

    This was a real bug, not a theoretical one: `GET /api/plants/{id}` failed
    intermittently in the browser while passing under curl and under the test
    suite. `tests/test_api.py::TestConcurrency` is the regression.
    """
    connection = sqlite3.connect(str(database_path), check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def apply_schema(connection: sqlite3.Connection) -> None:
    """Create tables and indexes if absent. Safe to run on every startup."""
    connection.executescript(SCHEMA)
    connection.commit()
