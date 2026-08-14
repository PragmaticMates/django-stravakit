"""Tests for ActivityQuerySet / GearQuerySet filter and sort helpers.

The PostgreSQL-only methods (``search`` — uses ``unaccent``; ``gear_unsynced`` /
``summary_only`` / ``detailed`` — use ``jsonb_extract_path_text``) can't run on
the SQLite test backend and are exercised against the real database in the
consuming project instead. Everything here is portable ORM.
"""
from datetime import datetime, timezone

import pytest

from stravakit.models import Activity, Gear


def make(id, sport_type="Run", distance=5000, moving_time=1800,
         elevation=100, calories=None, start_date=None, gear_id=None, is_private=False):
    return Activity.objects.create(
        id=id,
        name=f"Activity {id}",
        start_date=start_date or datetime(2025, 6, 15, 12, tzinfo=timezone.utc),
        sport_type=sport_type,
        distance=distance,
        moving_time=moving_time,
        total_elevation_gain=elevation,
        calories=calories,
        gear_id=gear_id,
        is_private=is_private,
        json={},
    )


def ids(qs):
    return [a.id for a in qs]


@pytest.mark.django_db
class TestForSport:
    def test_all_returns_everything(self):
        make(1, "Run")
        make(2, "Ride")
        assert set(ids(Activity.objects.for_sport("all"))) == {1, 2}

    def test_empty_returns_everything(self):
        make(1, "Run")
        assert ids(Activity.objects.for_sport("")) == [1]
        assert ids(Activity.objects.for_sport(None)) == [1]

    def test_exact_sport(self):
        make(1, "Run")
        make(2, "Ride")
        assert ids(Activity.objects.for_sport("Run")) == [1]


@pytest.mark.django_db
class TestForSportSelection:
    def test_group_expands_to_members(self):
        make(1, "Run")
        make(2, "TrailRun")
        make(3, "Ride")
        # group-run covers Run / TrailRun / VirtualRun
        assert set(ids(Activity.objects.for_sport_selection("group-run"))) == {1, 2}

    def test_exact_sport_type(self):
        make(1, "Run")
        make(2, "TrailRun")
        assert ids(Activity.objects.for_sport_selection("TrailRun")) == [2]

    def test_all_passthrough(self):
        make(1, "Run")
        make(2, "Ride")
        assert set(ids(Activity.objects.for_sport_selection("all"))) == {1, 2}
        assert set(ids(Activity.objects.for_sport_selection(None))) == {1, 2}


@pytest.mark.django_db
class TestPublic:
    def test_excludes_private_activities(self):
        make(1, is_private=False)
        make(2, is_private=True)
        make(3, is_private=False)
        assert set(ids(Activity.objects.public())) == {1, 3}

    def test_chains_with_other_filters(self):
        make(1, "Run", is_private=False)
        make(2, "Run", is_private=True)
        make(3, "Ride", is_private=False)
        assert ids(Activity.objects.public().for_sport("Run")) == [1]


@pytest.mark.django_db
class TestForGear:
    def _gear(self, id):
        return Gear.objects.create(id=id, primary=False, brand_name="B",
                                   model_name="M", description="", json={})

    def test_filters_by_gear(self):
        g = self._gear("g1")
        make(1, gear_id=g.id)
        make(2)
        assert ids(Activity.objects.for_gear("g1")) == [1]

    def test_all_and_empty_passthrough(self):
        self._gear("g1")
        make(1, gear_id="g1")
        make(2)
        assert set(ids(Activity.objects.for_gear("all"))) == {1, 2}
        assert set(ids(Activity.objects.for_gear(None))) == {1, 2}


@pytest.mark.django_db
class TestForYear:
    def test_filters_by_year(self):
        make(1, start_date=datetime(2025, 6, 1, 12, tzinfo=timezone.utc))
        make(2, start_date=datetime(2024, 6, 1, 12, tzinfo=timezone.utc))
        assert ids(Activity.objects.for_year("2025")) == [1]

    def test_all_and_bad_input_passthrough(self):
        make(1, start_date=datetime(2025, 6, 1, 12, tzinfo=timezone.utc))
        assert ids(Activity.objects.for_year("all")) == [1]
        # A non-numeric year is ignored rather than raising.
        assert ids(Activity.objects.for_year("not-a-year")) == [1]


@pytest.mark.django_db
class TestForMonth:
    def test_filters_by_year_month(self):
        make(1, start_date=datetime(2025, 6, 15, 12, tzinfo=timezone.utc))
        make(2, start_date=datetime(2025, 7, 15, 12, tzinfo=timezone.utc))
        assert ids(Activity.objects.for_month("2025-06")) == [1]

    def test_all_and_malformed_passthrough(self):
        make(1, start_date=datetime(2025, 6, 15, 12, tzinfo=timezone.utc))
        assert ids(Activity.objects.for_month("all")) == [1]
        assert ids(Activity.objects.for_month("garbage")) == [1]
        assert ids(Activity.objects.for_month(None)) == [1]


@pytest.mark.django_db
class TestForDistance:
    def test_range_filters_in_km_inclusive(self):
        # Bounds arrive in km; rows store metres. Both edges are inclusive.
        make(1, distance=3000)
        make(2, distance=10000)
        make(3, distance=25000)
        make(4, distance=42195)
        assert set(ids(Activity.objects.for_distance("10", "42"))) == {2, 3}

    def test_one_sided_ranges(self):
        make(1, distance=3000)
        make(2, distance=25000)
        # Only a lower bound.
        assert ids(Activity.objects.for_distance("10", None)) == [2]
        # Only an upper bound.
        assert ids(Activity.objects.for_distance(None, "10")) == [1]

    def test_blank_and_non_numeric_bounds_ignored(self):
        make(1, distance=3000)
        make(2, distance=25000)
        assert set(ids(Activity.objects.for_distance(None, None))) == {1, 2}
        assert set(ids(Activity.objects.for_distance("", ""))) == {1, 2}
        assert set(ids(Activity.objects.for_distance("junk", "junk"))) == {1, 2}


@pytest.mark.django_db
class TestActivitySortedBy:
    def test_sort_by_distance_desc(self):
        make(1, distance=5000)
        make(2, distance=9000)
        make(3, distance=1000)
        assert ids(Activity.objects.sorted_by("dist", "desc")) == [2, 1, 3]

    def test_sort_by_distance_asc(self):
        make(1, distance=5000)
        make(2, distance=9000)
        make(3, distance=1000)
        assert ids(Activity.objects.sorted_by("dist", "asc")) == [3, 1, 2]

    def test_sort_by_calories_nulls_last(self):
        make(1, calories=200)
        make(2, calories=None)
        make(3, calories=800)
        # nulls sort last regardless of direction
        assert ids(Activity.objects.sorted_by("cal", "desc")) == [3, 1, 2]

    def test_sort_by_pace(self):
        # pace = moving_time / distance (lower is faster)
        make(1, distance=10000, moving_time=3000)   # 0.30 s/m
        make(2, distance=10000, moving_time=6000)   # 0.60 s/m
        assert ids(Activity.objects.sorted_by("pace", "asc")) == [1, 2]

    def test_unknown_key_is_noop(self):
        make(2)
        make(1)
        # Falls back to the model's default -start_date ordering (same date → -id here
        # is not guaranteed, so just assert the set is unchanged and nothing raised).
        assert set(ids(Activity.objects.sorted_by("bogus"))) == {1, 2}


@pytest.mark.django_db
class TestGearQuerySet:
    def _gear(self, id, gear_type, brand="Brand"):
        return Gear.objects.create(id=id, primary=False, brand_name=brand,
                                   model_name="M", description="", json={},
                                   gear_type=gear_type)

    def test_of_type_filters(self):
        self._gear("b1", "bike")
        self._gear("s1", "shoe")
        assert [g.id for g in Gear.objects.of_type("bike")] == ["b1"]
        assert [g.id for g in Gear.objects.of_type("shoe")] == ["s1"]

    def test_of_type_unknown_passthrough(self):
        self._gear("b1", "bike")
        self._gear("s1", "shoe")
        assert {g.id for g in Gear.objects.of_type("all")} == {"b1", "s1"}

    def test_sorted_by_name(self):
        self._gear("g1", "shoe", brand="Zeta")
        self._gear("g2", "shoe", brand="Alpha")
        assert [g.id for g in Gear.objects.sorted_by("name", "asc")] == ["g2", "g1"]

    def test_sorted_by_unknown_key_defaults(self):
        # Unknown key falls back to (-primary, brand_name, model_name).
        Gear.objects.create(id="g1", primary=False, brand_name="Beta",
                            model_name="M", description="", json={})
        Gear.objects.create(id="g2", primary=True, brand_name="Zeta",
                            model_name="M", description="", json={})
        # primary gear (g2) sorts first despite the later brand name.
        assert [g.id for g in Gear.objects.sorted_by("nope")] == ["g2", "g1"]
