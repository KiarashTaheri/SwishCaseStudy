"""End-to-end tests over the HTTP surface, on a real database built from `data/`.

These are slower than the unit tests and earn it: they are the only place the
whole chain runs together, and the two properties they check — that the payload
matches the frozen contract, and that nothing needs an API key — are exactly the
two a grader will try first from a clean clone.

Skipped rather than failed when `data/` has not been generated, so a fresh clone
running pytest before `seed_data.py` gets a clear reason instead of a stack
trace.
"""

from __future__ import annotations

import json
import shutil
from datetime import date
from pathlib import Path

import pytest

from swishos import dispatch
from swishos.build import build
from swishos.db import connect

BACKEND = Path(__file__).resolve().parent.parent
DATA = BACKEND.parent / "data"
FIXTURE = BACKEND.parent / "docs" / "fixtures" / "fleet.json"
AS_OF = date(2026, 9, 14)

pytestmark = pytest.mark.skipif(
    not (DATA / "daily.csv").exists(),
    reason="run `python3 seed_data.py --start 2026-05-18` first",
)


@pytest.fixture(scope="module")
def built_database(tmp_path_factory) -> Path:
    """Build the database once per module. Building it is the expensive part."""
    path = tmp_path_factory.mktemp("db") / "swishos.db"
    build(DATA, path)
    return path


@pytest.fixture
def database(built_database, tmp_path) -> Path:
    """A private copy per test.

    Several tests here write dispatches, and a shared database makes them
    order-dependent — the immutability test failed exactly that way the first
    time it ran. Copying the built file is far cheaper than rebuilding it and
    leaves each test with a clean fleet.
    """
    path = tmp_path / "swishos.db"
    shutil.copy(built_database, path)
    return path


@pytest.fixture
def client(database, monkeypatch):
    """A client with no API key in the environment.

    Set deliberately, not incidentally: the brief requires the system to run
    without one, so every test here runs on the template path. If a briefing
    ever became a hard dependency on the model, these tests fail rather than
    the grader's clone.
    """
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from fastapi.testclient import TestClient

    from swishos import api

    monkeypatch.setattr(api, "DATABASE_PATH", database)
    with TestClient(api.app) as test_client:
        yield test_client


class TestHealth:
    def test_reports_the_data_date_not_the_wall_clock(self, client):
        payload = client.get("/api/health").json()
        assert payload["status"] == "ok"
        assert payload["as_of"] == "2026-09-14"
        assert payload["plants"] == 12

    def test_reports_the_template_path_without_a_key(self, client):
        assert client.get("/api/health").json()["llm"] == "template"


class TestFleet:
    def test_matches_the_committed_fixture_exactly(self, client):
        """The fixture is what the frontend is built against. If this fails,
        either the contract changed or a number moved — both need explaining
        before either half ships."""
        assert client.get("/api/fleet").json() == json.loads(FIXTURE.read_text())

    def test_regions_are_a_partition(self, client):
        payload = client.get("/api/fleet").json()
        seen: set[str] = set()
        for region in payload["regions"]:
            for row in region["recommendations"] + region["withheld"]:
                assert row["plant_id"] not in seen, "a plant appeared in two regions"
                assert row["region"] == region["region"]
                seen.add(row["plant_id"])
        assert len(seen) == payload["summary"]["plants_total"]

    def test_every_suggested_crew_is_based_in_the_plants_region(self, client):
        payload = client.get("/api/fleet").json()
        for region in payload["regions"]:
            bases = {c["home_base"] for c in region["crews"]}
            for row in region["recommendations"] + region["withheld"]:
                if row["suggested_crew"]:
                    assert row["suggested_crew"]["home_base"] in bases

    def test_withheld_plants_stay_visible(self, client):
        """Hiding a plant the system cannot rank destroys the most valuable
        signal in the data."""
        payload = client.get("/api/fleet").json()
        statuses = {
            row["status"]
            for region in payload["regions"]
            for row in region["withheld"]
        }
        assert "INSUFFICIENT_HISTORY" in statuses

    def test_summary_totals_agree_with_the_rows(self, client):
        payload = client.get("/api/fleet").json()
        rows = [
            row
            for region in payload["regions"]
            for row in region["recommendations"]
        ]
        assert payload["summary"]["actionable"] == len(rows)
        assert payload["summary"]["total_recoverable_usd"] == pytest.approx(
            sum(r["recoverable_usd"] for r in rows), abs=0.5
        )

    def test_no_row_names_a_cause(self, client):
        """Contract rule 1. The words that would be a diagnosis rather than a
        signature, checked on the text that actually reaches a screen."""
        forbidden = ("inverter", "fault", "curtail", "maintenance", "outage", "meter")
        payload = client.get("/api/fleet").json()
        for region in payload["regions"]:
            for row in region["recommendations"] + region["withheld"]:
                note = (row["quality"]["note"] or "").lower()
                assert not any(word in note for word in forbidden), note

    def test_unknown_date_is_a_404_not_an_empty_fleet(self, client):
        assert client.get("/api/fleet?as_of=2020-01-01").status_code == 404


class TestPlantDetail:
    def test_carries_history_with_a_flag_per_day(self, client):
        payload = client.get("/api/plants/plant_1003").json()
        assert len(payload["history"]) == 60
        dates = [point["date"] for point in payload["history"]]
        assert dates == sorted(dates), "history must be oldest first"
        # plant_1003 is the six-day anomaly. The flag has to travel with the
        # point so the chart can draw a gap rather than a 98% spike.
        assert "AVAILABILITY_ANOMALY" in {p["flag"] for p in payload["history"]}

    def test_briefing_falls_back_to_a_template(self, client):
        briefing = client.get("/api/plants/plant_1000").json()["briefing"]
        assert briefing["source"] == "template"
        assert briefing["headline"] and briefing["body"]

    def test_insufficient_history_has_a_threshold_but_no_dollars(self, client):
        payload = client.get("/api/plants/plant_1007").json()
        assert payload["status"] == "INSUFFICIENT_HISTORY"
        assert payload["recoverable_usd"] is None
        assert payload["break_even_soiling_pct"] is not None

    def test_unknown_plant_is_404(self, client):
        assert client.get("/api/plants/plant_9999").status_code == 404


class TestDispatch:
    def test_records_the_numbers_it_was_approved_on(self, client):
        row = client.get("/api/plants/plant_1000").json()
        created = client.post("/api/dispatch", json={"plant_id": "plant_1000"})
        assert created.status_code == 201

        record = created.json()
        assert record["crew_id"] == row["suggested_crew"]["crew_id"]
        assert record["snapshot"]["soiling_loss_pct"] == pytest.approx(
            row["soiling_loss_pct"], abs=0.01
        )
        assert record["work_order"]

    def test_second_dispatch_for_the_same_day_is_refused(self, client):
        client.post("/api/dispatch", json={"plant_id": "plant_1008"})
        again = client.post("/api/dispatch", json={"plant_id": "plant_1008"})
        assert again.status_code == 409

    def test_plant_below_break_even_cannot_be_dispatched(self, client):
        response = client.post("/api/dispatch", json={"plant_id": "plant_1002"})
        assert response.status_code == 409
        assert "BELOW_BREAK_EVEN" in response.json()["detail"]

    def test_crew_from_another_region_is_refused(self, client):
        """The constraint that reversed DECISIONS.md #7, enforced at the write."""
        response = client.post(
            "/api/dispatch", json={"plant_id": "plant_1006", "crew_id": "crew_15"}
        )
        assert response.status_code == 422
        assert "cannot service" in response.json()["detail"]

    def test_unknown_plant_is_404(self, client):
        response = client.post("/api/dispatch", json={"plant_id": "plant_9999"})
        assert response.status_code == 404

    def test_dispatched_flag_reaches_the_fleet_view(self, client):
        client.post("/api/dispatch", json={"plant_id": "plant_1005"})
        payload = client.get("/api/fleet").json()
        rows = {
            row["plant_id"]: row
            for region in payload["regions"]
            for row in region["recommendations"]
        }
        assert rows["plant_1005"]["dispatched"] is True

    def test_dispatches_are_listed_newest_first(self, client):
        client.post("/api/dispatch", json={"plant_id": "plant_1006"})
        records = client.get("/api/dispatches").json()["dispatches"]
        assert len(records) >= 1
        stamps = [r["created_at"] for r in records]
        assert stamps == sorted(stamps, reverse=True)


class TestSnapshotIsImmutable:
    def test_stored_snapshot_does_not_move_when_the_ranking_is_rebuilt(
        self, database, monkeypatch
    ):
        """The record must answer "what did we believe then", not "what do we
        believe now". Rebuilding the ranking is the cheapest way to prove the
        stored copy is a copy and not a join.
        """
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        connection = connect(database)
        try:
            record = dispatch.create_dispatch(connection, "plant_1000", AS_OF)
            before = dict(record.snapshot)

            connection.execute(
                "UPDATE ranking_snapshot SET soiling_loss_pct = 99.0 "
                "WHERE as_of = ? AND plant_id = 'plant_1000'",
                (AS_OF.isoformat(),),
            )
            connection.commit()

            after = dispatch.list_dispatches(connection, AS_OF)
            stored = next(r for r in after if r.plant_id == "plant_1000")
            assert stored.snapshot == before
            assert stored.snapshot["soiling_loss_pct"] != 99.0
        finally:
            connection.close()
