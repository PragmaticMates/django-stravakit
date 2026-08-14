import datetime
from datetime import timezone as tz
from types import SimpleNamespace

import pytest
from django.test import RequestFactory

from stravakit import helpers
from stravakit.models import Activity, Gear
from stravakit.views import DashboardView


def dt(year, month, day, hour=12):
    """A timezone-aware datetime at midday UTC (so localtime stays on the same date)."""
    return datetime.datetime(year, month, day, hour, tzinfo=tz.utc)


def make_activity(id, sport_type="Run", distance=10000, start_date=None,
                  moving_time=3000, elevation=100, max_speed=4.0,
                  average_heartrate=150.0, kudos=0, photos=0,
                  start_lat=None, start_lng=None, gear=None, name=None,
                  best_efforts=None, calories=0, achievement_count=0, pr_count=0):
    json = {"id": id, "calories": calories,
            "achievement_count": achievement_count, "pr_count": pr_count}
    if best_efforts is not None:
        json["best_efforts"] = best_efforts
    return Activity.objects.create(
        id=id,
        name=name or f"Activity {id}",
        start_date=start_date or dt(2025, 6, 15),
        sport_type=sport_type,
        distance=distance,
        moving_time=moving_time,
        total_elevation_gain=elevation,
        max_speed=max_speed,
        average_heartrate=average_heartrate,
        kudos_count=kudos,
        total_photo_count=photos,
        # calories / achievement / PR counts are promoted model fields (the summary
        # and AOTY read them directly, not from `json`).
        calories=calories,
        achievement_count=achievement_count,
        pr_count=pr_count,
        start_lat=start_lat,
        start_lng=start_lng,
        gear=gear,
        json=json,
    )


def dashboard_context(**params):
    """Render DashboardView's context for the given GET filter params."""
    view = DashboardView()
    view.request = RequestFactory().get("/", params)
    view.kwargs = {}
    return view.get_context_data()


# --------------------------------------------------------------------------- #
# Pure helpers (no DB)
# --------------------------------------------------------------------------- #
class TestHaversine:
    def test_zero_distance(self):
        assert helpers.haversine_km(48.7, 21.2, 48.7, 21.2) == pytest.approx(0, abs=1e-6)

    def test_kosice_to_vienna(self):
        # ~360 km apart
        d = helpers.haversine_km(48.72, 21.26, 48.21, 16.37)
        assert 350 < d < 375


class TestHomeLocation:
    def test_none_without_gps(self):
        acts = [SimpleNamespace(start_lat=None, start_lng=None)]
        assert helpers.home_location(acts) is None

    def test_busiest_cluster_wins(self):
        acts = [
            SimpleNamespace(start_lat=48.720, start_lng=21.258),
            SimpleNamespace(start_lat=48.721, start_lng=21.262),
            SimpleNamespace(start_lat=48.719, start_lng=21.260),
            SimpleNamespace(start_lat=48.210, start_lng=16.370),  # lone outlier
        ]
        lat, lng = helpers.home_location(acts)
        assert lat == pytest.approx(48.72, abs=0.01)
        assert lng == pytest.approx(21.26, abs=0.01)

    def test_skips_activities_without_gps(self):
        # Activities missing coords are ignored rather than crashing the clustering.
        acts = [
            SimpleNamespace(start_lat=None, start_lng=None),
            SimpleNamespace(start_lat=48.720, start_lng=21.258),
            SimpleNamespace(start_lat=48.721, start_lng=21.262),
        ]
        lat, lng = helpers.home_location(acts)
        assert lat == pytest.approx(48.72, abs=0.01)


class TestFormatters:
    def test_fmt_pace(self):
        assert helpers.fmt_pace(330) == "5:30"
        assert helpers.fmt_pace(112) == "1:52"

    def test_fmt_hms_under_hour(self):
        assert helpers.fmt_hms(1665) == "27:45"

    def test_fmt_hms_over_hour(self):
        assert helpers.fmt_hms(14683) == "4:04:43"


# --------------------------------------------------------------------------- #
# Filters (stat band)
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
class TestFilters:
    def _seed(self):
        make_activity(1, "Run", distance=10000, start_date=dt(2025, 6, 15), name="Morning Run")
        make_activity(2, "Ride", distance=40000, start_date=dt(2025, 7, 1), name="Evening Ride")
        make_activity(3, "Run", distance=8000, start_date=dt(2024, 5, 1), name="Trail Loop")

    def test_no_filter_counts_all(self):
        self._seed()
        stat = dashboard_context()["stat"]
        assert stat["activities"] == 3
        assert stat["distance_km"] == round((10000 + 40000 + 8000) / 1000)

    def test_year_filter(self):
        self._seed()
        stat = dashboard_context(year="2025")["stat"]
        assert stat["activities"] == 2
        assert stat["distance_km"] == round((10000 + 40000) / 1000)

    def test_sport_filter(self):
        self._seed()
        stat = dashboard_context(sport="Run")["stat"]
        assert stat["activities"] == 2

    def test_search_filter(self):
        self._seed()
        stat = dashboard_context(q="morning")["stat"]
        assert stat["activities"] == 1

    def test_gear_filter(self):
        gear = Gear.objects.create(id="g1", primary=False, brand_name="Nike",
                                   model_name="Peg", description="", json={})
        make_activity(1, "Run", gear=gear)
        make_activity(2, "Run")
        stat = dashboard_context(gear="g1")["stat"]
        assert stat["activities"] == 1


# --------------------------------------------------------------------------- #
# Activity of the year
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
class TestActivityOfTheYear:
    def _seed(self):
        # Longest activity overall sits in 2024; 2025's longest is shorter.
        make_activity(1, "Run", distance=12000, start_date=dt(2025, 6, 15), name="2025 Long Run")
        make_activity(2, "Run", distance=8000, start_date=dt(2025, 3, 1), name="2025 Short Run")
        make_activity(3, "Ride", distance=40000, start_date=dt(2024, 7, 1), name="2024 Big Ride")

    def test_year_filter_scopes_aoty(self):
        self._seed()
        # 2025 selected: longest of 2025 only, not the longer 2024 ride.
        assert dashboard_context(year="2025")["aoty"].pk == 1
        # 2024 selected: the big ride.
        assert dashboard_context(year="2024")["aoty"].pk == 3


# --------------------------------------------------------------------------- #
# "By the Numbers" stats
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
class TestByTheNumbers:
    def test_summary_totals(self):
        make_activity(1, "Run", kudos=5, photos=1, calories=600, achievement_count=2, pr_count=1)
        make_activity(2, "Ride", kudos=10, photos=2, calories=1200, achievement_count=1, pr_count=0)
        summary = dashboard_context()["summary"]
        assert summary["kudos"] == 15
        assert summary["photos"] == 3
        assert summary["calories"] == 1800
        assert summary["achievements"] == 3
        assert summary["prs"] == 1

    def test_summary_respects_filter(self):
        make_activity(1, "Run", kudos=5, start_date=dt(2025, 6, 1))
        make_activity(2, "Run", kudos=10, start_date=dt(2024, 6, 1))
        assert dashboard_context(year="2025")["summary"]["kudos"] == 5

    def test_avg_hr_time_weighted(self):
        make_activity(1, "Run", moving_time=3600, average_heartrate=160.0)
        make_activity(2, "Run", moving_time=1200, average_heartrate=140.0)
        # (160*3600 + 140*1200) / 4800 = 155
        assert dashboard_context()["summary"]["avg_hr"] == 155

    def test_avg_hr_zero_without_data(self):
        make_activity(1, "Run", average_heartrate=None)
        assert dashboard_context()["summary"]["avg_hr"] == 0

    def test_fun_stats_equivalents(self):
        make_activity(1, "Run", distance=42195, elevation=8849)
        fun = dashboard_context()["fun_stats"]
        assert fun["everest"] == "1.0x"
        assert fun["marathons"] == "1"
        assert fun["around_earth"] == "0.1%"

    def test_co2_only_counts_cycling(self):
        make_activity(1, "Ride", distance=100000)   # 100 km * 0.12 = 12 kg
        make_activity(2, "Run", distance=100000)    # runs don't count
        assert dashboard_context()["fun_stats"]["co2_saved"] == "12 kg"


# --------------------------------------------------------------------------- #
# Personal records
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
class TestRecords:
    def _labels(self, records, tab):
        return {r["label"]: r for r in records[tab]}

    def test_furthest_from_home(self):
        make_activity(1, "Run", start_lat=48.720, start_lng=21.258)
        make_activity(2, "Run", start_lat=48.721, start_lng=21.262)
        make_activity(3, "Run", start_lat=48.719, start_lng=21.260)
        make_activity(99, "Run", start_lat=48.210, start_lng=16.370)
        records = dashboard_context()["records"]
        furthest = self._labels(records, "Running")["Furthest from Home"]
        assert furthest["id"] == 99

    def test_ebike_excluded_from_cycling(self):
        make_activity(1, "Ride", distance=40000)
        make_activity(2, "EBikeRide", distance=90000)
        records = dashboard_context()["records"]
        assert self._labels(records, "Cycling")["Longest"]["id"] == 1

    def test_alpineski_not_in_any_tab(self):
        make_activity(1, "Run", distance=10000)
        make_activity(2, "AlpineSki", distance=20000, moving_time=600)
        records = dashboard_context()["records"]
        ids = {r["id"] for tab in records.values() for r in tab}
        assert 2 not in ids

    def test_fast_avg_speed_ride_excluded(self):
        make_activity(1, "Ride", distance=70000, moving_time=3600)   # 70 km/h
        make_activity(2, "Ride", distance=32000, moving_time=3600)   # 32 km/h
        records = dashboard_context()["records"]
        assert self._labels(records, "Cycling")["Fastest (avg. speed)"]["id"] == 2

    def test_top_speed_glitch_excluded(self):
        make_activity(1, "Ride", distance=32000, moving_time=3600, max_speed=33.33)  # 120 km/h
        make_activity(2, "Ride", distance=32000, moving_time=3600, max_speed=20.0)   # 72 km/h
        records = dashboard_context()["records"]
        assert self._labels(records, "Cycling")["Top Speed"]["id"] == 2

    def test_hike_without_pace_data_is_kept(self):
        # A hike missing moving_time can't be disqualified on pace, so it still
        # competes for the longest-hike record.
        make_activity(1, "Hike", distance=25000, moving_time=None)
        make_activity(2, "Hike", distance=10000, moving_time=12000)
        records = dashboard_context()["records"]
        assert self._labels(records, "Hiking")["Longest"]["id"] == 1

    def test_swimming_fastest_per_100m(self):
        make_activity(1, "Swim", distance=2000, moving_time=3000)   # 2:30 /100m
        make_activity(2, "Swim", distance=1000, moving_time=2000)   # 3:20 /100m
        records = dashboard_context()["records"]
        fastest = self._labels(records, "Swimming")["Fastest (per 100 m)"]
        assert fastest["id"] == 1

    def test_run_paced_hike_excluded_from_longest(self):
        make_activity(1, "Hike", distance=30000, moving_time=9000)    # 5:00/km
        make_activity(2, "Hike", distance=20000, moving_time=10800)   # 9:00/km
        records = dashboard_context()["records"]
        assert self._labels(records, "Hiking")["Longest"]["id"] == 2

    def test_scoped_to_year_not_sport(self):
        make_activity(1, "Run", distance=10000, start_date=dt(2025, 6, 1))
        make_activity(2, "Ride", distance=40000, start_date=dt(2025, 6, 2))
        make_activity(3, "Run", distance=99000, start_date=dt(2024, 6, 1))
        # Sport filter must not empty the other tabs' records.
        assert dashboard_context(sport="Ride")["records"]["Running"]
        # Year filter does scope: 2025 excludes the longer 2024 run.
        records = dashboard_context(year="2025")["records"]
        assert self._labels(records, "Running")["Longest"]["id"] == 1


# --------------------------------------------------------------------------- #
# Running performance (best efforts)
# --------------------------------------------------------------------------- #
BEST_EFFORTS = [
    {"name": "5K", "elapsed_time": 1665, "distance": 5000.0},
    {"name": "10K", "elapsed_time": 3341, "distance": 10000.0},
    {"name": "Half-Marathon", "elapsed_time": 7084, "distance": 21097.0},
    {"name": "Marathon", "elapsed_time": 14683, "distance": 42195.0},
]


@pytest.mark.django_db
class TestRunPerformance:
    def _rows(self, ctx):
        return {r["dist"]: r for r in ctx["run_perf"]}

    def test_best_times_and_link(self):
        make_activity(1, "Run", distance=42195, best_efforts=BEST_EFFORTS)
        rows = self._rows(dashboard_context())
        assert rows["5 km"]["best"] == "27:45"
        assert rows["5 km"]["best_id"] == 1
        assert rows["Marathon"]["best"] == "4:04:43"
        assert rows["5 km"]["est"] != "—"

    def test_missing_distance_shows_dash(self):
        make_activity(1, "Run", distance=6000,
                      best_efforts=[{"name": "5K", "elapsed_time": 1500, "distance": 5000.0}])
        rows = self._rows(dashboard_context())
        assert rows["5 km"]["best"] == "25:00"
        assert rows["Marathon"]["best"] == "—"
        assert rows["Marathon"]["best_id"] is None

    def test_year_scoped(self):
        make_activity(1, "Run", distance=42195, start_date=dt(2025, 6, 1),
                      best_efforts=[{"name": "5K", "elapsed_time": 1500, "distance": 5000.0}])
        make_activity(2, "Run", distance=42195, start_date=dt(2024, 6, 1),
                      best_efforts=[{"name": "5K", "elapsed_time": 1200, "distance": 5000.0}])
        rows = self._rows(dashboard_context(year="2025"))
        assert rows["5 km"]["best"] == "25:00"  # 2025 effort, not 2024's faster one

    def test_malformed_best_efforts_are_skipped(self):
        # Entries with a null/zero time or missing distance don't count and don't crash.
        make_activity(1, "Run", distance=5000, best_efforts=[
            {"name": "5K", "elapsed_time": None, "distance": 5000.0},   # null time
            {"name": "10K", "elapsed_time": 0, "distance": 10000.0},    # zero time
            {"name": "Marathon", "elapsed_time": 9000, "distance": None},  # no distance
        ])
        rows = self._rows(dashboard_context())
        assert rows["5 km"]["best"] == "—"
        assert rows["10 km"]["best"] == "—"
