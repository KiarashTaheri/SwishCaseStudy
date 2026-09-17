"""Tests for the region partition and the ranking.

The partition is the decision most likely to be quietly wrong: a crew mapped to
the wrong region, or silently dropped from its own, produces a ranking that
looks entirely reasonable and sends a truck across a continent.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from swishos import ranking
from swishos.domain import Crew, DailyReading, DispatchStatus, Plant, PlantDayEvent

AS_OF = date(2026, 9, 14)

CREWS = [
    Crew("crew_10", "Phoenix, AZ", 12.9, 1569.06),
    Crew("crew_11", "Jodhpur, RJ", 10.2, 2578.09),
    Crew("crew_12", "Seville, ES", 18.0, 1133.71),
    Crew("crew_13", "Antofagasta, CL", 12.1, 1842.06),
    Crew("crew_14", "Townsville, QLD", 9.4, 1771.33),
    Crew("crew_15", "Tucson, AZ", 20.1, 1379.30),
]


def plant(plant_id: str, region: str, **overrides) -> Plant:
    defaults = dict(
        name=f"Test {plant_id}",
        capacity_mw=60.0,
        tariff_per_kwh=0.078,
        cleaning_cost_usd=20_000.0,
        days_until_next_reset=32,
        commissioned_on=date(2026, 1, 1),
    )
    return Plant(plant_id=plant_id, region=region, **{**defaults, **overrides})


def history(plant_id: str, soiling: float) -> list[DailyReading]:
    return [
        DailyReading(
            plant_id=plant_id,
            reading_date=AS_OF - timedelta(days=i),
            energy_kwh=400_000.0,
            expected_energy_kwh=450_000.0,
            pr=0.93,
            soiling_loss_pct=soiling,
        )
        for i in range(14)
    ]


def events(plant_id: str) -> list[PlantDayEvent]:
    return [
        PlantDayEvent(plant_id, AS_OF - timedelta(days=i), 0.0, False) for i in range(14)
    ]


class TestRegionPartition:
    @pytest.mark.parametrize(
        ("home_base", "region"),
        [
            ("Phoenix, AZ", "Arizona, USA"),
            ("Tucson, AZ", "Arizona, USA"),
            ("Jodhpur, RJ", "Rajasthan, India"),
            ("Seville, ES", "Andalusia, Spain"),
            ("Antofagasta, CL", "Atacama, Chile"),
            ("Townsville, QLD", "Queensland, AUS"),
        ],
    )
    def test_every_home_base_maps_to_its_region(self, home_base, region):
        assert ranking.crew_region(Crew("c", home_base, 10.0, 1000.0)) == region

    def test_unmapped_base_raises_rather_than_dropping_the_crew(self):
        """A crew silently dropped makes its region look like it has no
        capacity, which is a worse failure than the build stopping."""
        with pytest.raises(ranking.UnmappedCrewError, match="Lagos, NG"):
            ranking.crew_region(Crew("crew_99", "Lagos, NG", 10.0, 1000.0))

    def test_coverage_check_is_clean_on_the_real_fleet(self):
        plants = [
            plant("p1", "Arizona, USA"),
            plant("p2", "Rajasthan, India"),
            plant("p3", "Andalusia, Spain"),
            plant("p4", "Atacama, Chile"),
            plant("p5", "Queensland, AUS"),
        ]
        assert ranking.verify_crew_coverage(plants, CREWS) == {
            "regions_without_a_crew": [],
            "crew_regions_without_a_plant": [],
        }

    def test_coverage_check_reports_a_region_with_no_crew(self):
        plants = [plant("p1", "Arizona, USA"), plant("p6", "Gujarat, India")]
        result = ranking.verify_crew_coverage(plants, CREWS)
        assert result["regions_without_a_crew"] == ["Gujarat, India"]


class TestCrewAssignment:
    def test_never_offers_a_crew_from_another_region(self):
        target = plant("p2", "Rajasthan, India")
        assignment = ranking.assign_crew(target, CREWS)
        assert assignment is not None
        assert assignment.crew_id == "crew_11"

    def test_picks_the_fastest_crew_in_the_region(self):
        """Arizona has two. Under A5 the day rate is already inside the
        cleaning cost, so cost does not vary with the choice and the only thing
        left to optimise is how much of the region's queue gets cleared."""
        assignment = ranking.assign_crew(plant("p1", "Arizona, USA"), CREWS)
        assert assignment is not None
        assert assignment.crew_id == "crew_15"  # 20.1 MW/day beats 12.9
        assert assignment.crew_days == pytest.approx(60.0 / 20.1)

    def test_returns_none_when_no_crew_is_based_in_the_region(self):
        assert ranking.assign_crew(plant("p6", "Gujarat, India"), CREWS) is None

    def test_crew_days_scale_with_capacity(self):
        crew = CREWS[-1]
        small = ranking.crew_days(plant("s", "Arizona, USA", capacity_mw=20.1), crew)
        large = ranking.crew_days(plant("l", "Arizona, USA", capacity_mw=40.2), crew)
        assert small == pytest.approx(1.0)
        assert large == pytest.approx(2.0)


class TestRankFleet:
    def build(self, plants):
        return ranking.rank_fleet(
            plants,
            CREWS,
            {p.plant_id: history(p.plant_id, 8.0) for p in plants},
            {p.plant_id: events(p.plant_id) for p in plants},
            AS_OF,
        )

    def test_plants_compete_only_inside_their_region(self):
        """The key property: a very valuable Arizona plant must not push a
        Rajasthan plant down a list, because the two never compete for a crew."""
        fleet = self.build(
            [
                plant("az", "Arizona, USA", capacity_mw=200.0),
                plant("rj", "Rajasthan, India"),
            ]
        )
        by_region = {r.region: r for r in fleet.regions}
        assert [p.plant.plant_id for p in by_region["Arizona, USA"].recommendations] == ["az"]
        assert [p.plant.plant_id for p in by_region["Rajasthan, India"].recommendations] == ["rj"]

    def test_recommendations_are_ordered_by_dollars_descending(self):
        fleet = self.build(
            [
                plant("small", "Arizona, USA", cleaning_cost_usd=25_000.0),
                plant("big", "Arizona, USA", cleaning_cost_usd=1_000.0),
            ]
        )
        region = fleet.regions[0]
        values = [p.economics.recoverable_usd for p in region.recommendations]
        assert values == sorted(values, reverse=True)
        assert region.recommendations[0].plant.plant_id == "big"

    def test_ranking_is_deterministic(self):
        """The snapshot is cached by date, so an unstable order would serve
        different answers to different people on the same morning."""
        plants = [plant(f"p{i}", "Arizona, USA") for i in range(6)]
        first = [p.plant.plant_id for p in self.build(plants).regions[0].recommendations]
        second = [p.plant.plant_id for p in self.build(plants).regions[0].recommendations]
        assert first == second

    def test_withheld_plants_are_returned_not_dropped(self):
        """A plant the system has no opinion about is information the asset
        manager needs, not a row to filter out."""
        plants = [plant("clean", "Arizona, USA", cleaning_cost_usd=10_000_000.0)]
        fleet = self.build(plants)
        region = fleet.regions[0]
        assert region.recommendations == []
        assert [p.plant.plant_id for p in region.withheld] == ["clean"]
        assert region.withheld[0].economics.status is DispatchStatus.BELOW_BREAK_EVEN

    def test_crew_days_outstanding_exposes_the_bottleneck(self):
        """The number that shows a region cannot finish its own queue."""
        plants = [plant(f"p{i}", "Rajasthan, India", capacity_mw=54.0) for i in range(3)]
        region = self.build(plants).regions[0]
        assert region.crew_days_outstanding == pytest.approx(3 * 54.0 / 10.2)
        assert region.capacity_mw_per_day == 10.2
