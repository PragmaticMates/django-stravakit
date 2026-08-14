"""Tests for Activity / Gear display properties and API-backed helpers."""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from django.utils import timezone as dj_timezone

from stravakit.consts import BIKE_LIFESPAN_KM, SHOE_LIFESPAN_KM
from stravakit.models import Activity, Gear
from stravakit.services import sync


def activity(**overrides):
    defaults = dict(
        name="Act",
        start_date=datetime(2025, 6, 15, tzinfo=timezone.utc),
        sport_type="Run",
        distance=10000,
        moving_time=3000,
        json={},
    )
    defaults.update(overrides)
    return Activity(**defaults)


# Minimal valid Strava summary payload for exercising Activity.read_json.
READ_BASE = {
    "name": "Act", "gear_id": None, "sport_type": "Run", "distance": 1000,
    "start_date": "2025-06-15T07:00:00+00:00",
}


# --------------------------------------------------------------------------- #
# Activity.map_sport_type bucketing
# --------------------------------------------------------------------------- #
class TestActivityMapSportType:
    @pytest.mark.parametrize("sport_type,expected", [
        ("TrailRun", "trail"),
        ("Hike", "hike"),
        ("Snowshoe", "hike"),
        ("Walk", "walk"),
        ("Ride", "ride"),
        ("GravelRide", "ride"),
        ("Swim", "swim"),
        ("Run", "run"),
        ("VirtualRun", "run"),
        ("Workout", "other"),   # unlisted sports fall through to "other"
        ("Velomobile", "other"),  # no "Ride" substring → not the ride bucket
    ])
    def test_map_sport_type(self, sport_type, expected):
        assert activity(sport_type=sport_type).map_sport_type == expected


# --------------------------------------------------------------------------- #
# Distance / duration / elevation
# --------------------------------------------------------------------------- #
class TestScalars:
    def test_dist_km_rounded(self):
        # 10240 m → 10.24 km → 10.2 km (1 decimal)
        assert activity(distance=10240).distance_km == 10.2

    def test_dur_with_hours(self):
        assert activity(moving_time=3725).duration == "1h 02m"

    def test_dur_under_hour(self):
        assert activity(moving_time=125).duration == "2m 05s"

    def test_dur_zero_when_missing(self):
        assert activity(moving_time=None).duration == "0m 00s"

    def test_elev_rounds(self):
        assert activity(total_elevation_gain=123.6).elevation == 124

    def test_elev_zero_when_missing(self):
        assert activity(total_elevation_gain=None).elevation == 0


# --------------------------------------------------------------------------- #
# Pace
# --------------------------------------------------------------------------- #
class TestPace:
    def test_run_pace_per_km(self):
        # 10 km in 3000 s = 300 s/km = 5:00 /km
        val, unit = activity(sport_type="Run", distance=10000, moving_time=3000).pace_parts
        assert (val, unit) == ("5:00", "/km")

    def test_ride_pace_kmh(self):
        # 30 km in 3600 s = 30 km/h
        val, unit = activity(sport_type="Ride", distance=30000, moving_time=3600).pace_parts
        assert unit == "km/h"
        assert val == "30.0"

    def test_swim_pace_per_100m(self):
        # 2000 m in 3000 s = 150 s / 100 m = 2:30 /100m
        val, unit = activity(sport_type="Swim", distance=2000, moving_time=3000).pace_parts
        assert (val, unit) == ("2:30", "/100m")

    def test_velomobile_pace_kmh(self):
        # Pace keys off sport_type, not the map bucket: a velomobile is 'other' on the map
        # but is still cycling, so it must read as speed (km/h), not a /km pace.
        a = activity(sport_type="Velomobile", distance=30000, moving_time=3600)
        assert a.map_sport_type == "other"
        assert a.is_speed_sport is True
        assert a.pace_parts == ("30.0", "km/h")

    def test_swim_flags_and_run_defaults(self):
        assert activity(sport_type="Swim").is_swim_sport is True
        assert activity(sport_type="Run").is_speed_sport is False
        assert activity(sport_type="Run").is_swim_sport is False

    def test_no_data_returns_dash(self):
        assert activity(moving_time=0).pace_parts == ("-", "")

    def test_pace_string_joins_unit(self):
        assert activity(sport_type="Run", distance=10000, moving_time=3000).pace == "5:00 /km"

    def test_pace_string_no_unit(self):
        assert activity(moving_time=0).pace == "-"


# --------------------------------------------------------------------------- #
# Flag properties
# --------------------------------------------------------------------------- #
class TestFlags:
    def test_pb_true_false(self):
        assert activity(pr_count=1).pb is True
        assert activity(pr_count=0).pb is False

    def test_has_gps(self):
        assert activity(start_lat=48.7).has_gps is True
        assert activity(start_lat=None).has_gps is False

    def test_has_heartrate(self):
        assert activity(average_heartrate=140.0, max_heartrate=180.0).has_heartrate is True
        assert activity(average_heartrate=None, max_heartrate=180.0).has_heartrate is False

    def test_polyline_prefers_full_over_summary(self):
        # polyline is promoted by read_json (prefers the full trace over the summary).
        data = Activity.read_json({**READ_BASE, "map": {"polyline": "FULL", "summary_polyline": "SUM"}})
        assert data["polyline"] == "FULL"

    def test_polyline_falls_back_to_summary(self):
        data = Activity.read_json({**READ_BASE, "map": {"summary_polyline": "SUM"}})
        assert data["polyline"] == "SUM"

    def test_polyline_empty_without_map(self):
        assert Activity.read_json(READ_BASE)["polyline"] == ""

    def test_best_efforts_reads_json(self):
        assert activity(json={"best_efforts": [{"name": "5k"}]}).best_efforts == [{"name": "5k"}]
        assert activity(json={}).best_efforts == []

    def test_get_absolute_url(self):
        a = activity()
        a.id = 987
        assert a.get_absolute_url() == "https://strava.com/activities/987"


# --------------------------------------------------------------------------- #
# Activity API-backed helpers
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
class TestActivityApiHelpers:
    ACT_JSON = {
        "id": 5, "name": "Fetched", "gear_id": None, "sport_type": "Run",
        "distance": 8000, "start_date": "2025-06-15T07:00:00+00:00",
    }

    @patch("stravakit.services.sync.StravaApi")
    def test_fetch_from_api_stores_and_updates(self, mock_api_cls):
        mock_api_cls.return_value.get_activity.return_value = self.ACT_JSON
        a = Activity.objects.create(
            id=5, name="Old", start_date=datetime(2020, 1, 1, tzinfo=timezone.utc),
            sport_type="Walk", distance=0, json={},
        )
        sync.activity_fetch(a)
        a.refresh_from_db()
        mock_api_cls.return_value.get_activity.assert_called_once_with(5)
        assert a.name == "Fetched"
        assert a.sport_type == "Run"
        assert a.json == self.ACT_JSON

    @patch("stravakit.services.sync.StravaApi")
    def test_send_to_api_pushes_then_refetches(self, mock_api_cls):
        mock_api_cls.return_value.get_activity.return_value = self.ACT_JSON
        a = Activity.objects.create(
            id=5, name="Renamed", start_date=datetime(2025, 6, 15, tzinfo=timezone.utc),
            sport_type="Run", distance=8000, gear_id=None, json=self.ACT_JSON,
        )
        sync.activity_push(a)
        mock_api_cls.return_value.update_activity.assert_called_once_with(
            id=5, name="Renamed", sport_type="Run", gear_id=None,
        )
        # send_to_api ends by re-fetching the detailed payload.
        mock_api_cls.return_value.get_activity.assert_called_once_with(5)


# --------------------------------------------------------------------------- #
# Gear
# --------------------------------------------------------------------------- #
GEAR_JSON = {
    "id": "g1", "primary": True, "brand_name": "Nike",
    "model_name": "Peg", "description": "trainer",
}


@pytest.mark.django_db
class TestGear:
    def _gear(self, **overrides):
        defaults = dict(id="g1", primary=False, brand_name="Nike", model_name="Peg",
                        description="", gear_type="shoe", json=GEAR_JSON)
        defaults.update(overrides)
        return Gear.objects.create(**defaults)

    def _activity(self, id, gear, distance=5000, start_date=None):
        return Activity.objects.create(
            id=id, name=f"A{id}",
            start_date=start_date or datetime(2025, 6, 15, tzinfo=timezone.utc),
            sport_type="Run", distance=distance, gear=gear, json={},
        )

    def test_distance_sums_activities(self):
        g = self._gear()
        self._activity(1, g, distance=5000)
        self._activity(2, g, distance=3000)
        assert g.distance == 8000

    def test_lifespan_km_by_type(self):
        assert self._gear(id="s", gear_type="shoe").lifespan_km == SHOE_LIFESPAN_KM
        assert self._gear(id="b", gear_type="bike").lifespan_km == BIKE_LIFESPAN_KM

    def test_is_old_without_activities(self):
        # Never used → treated as old.
        assert self._gear().is_old is True

    def test_is_old_recent_activity(self):
        g = self._gear()
        self._activity(1, g, start_date=dj_timezone.now() - timedelta(days=10))
        assert g.is_old is False

    def test_is_old_stale_activity(self):
        g = self._gear()
        self._activity(1, g, start_date=dj_timezone.now() - timedelta(days=400))
        assert g.is_old is True

    def test_get_or_create_returns_none_for_falsy_id(self):
        assert sync.gear_ensure(gear_id=None) is None
        assert sync.gear_ensure(gear_id="") is None

    def test_get_or_create_returns_existing(self):
        g = self._gear()
        with patch("stravakit.services.sync.StravaApi") as mock_api:
            assert sync.gear_ensure(gear_id="g1").pk == g.pk
            mock_api.assert_not_called()   # no API hit when already present

    @patch("stravakit.services.sync.StravaApi")
    def test_get_or_create_fetches_when_missing(self, mock_api_cls):
        mock_api_cls.return_value.get_gear.return_value = {**GEAR_JSON, "id": "g2"}
        gear = sync.gear_ensure(gear_id="g2")
        mock_api_cls.return_value.get_gear.assert_called_once_with("g2")
        assert gear.pk == "g2"
        assert gear.brand_name == "Nike"

    @patch("stravakit.services.sync.StravaApi")
    def test_fetch_from_api_updates_fields(self, mock_api_cls):
        g = self._gear(brand_name="Old")
        mock_api_cls.return_value.get_gear.return_value = {**GEAR_JSON, "brand_name": "New"}
        sync.gear_fetch(g)
        g.refresh_from_db()
        assert g.brand_name == "New"

    def test_read_json_bike_detection(self):
        # A frame_type present → bike; absent → shoe.
        assert Gear.read_json({**GEAR_JSON, "frame_type": 3})["gear_type"] == "bike"
        assert Gear.read_json(GEAR_JSON)["gear_type"] == "shoe"
