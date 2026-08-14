from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from stravakit.models import Activity, Athlete, Gear
from stravakit.services import sync


ACTIVITY_JSON = {
    "id": 12345,
    "name": "Morning Run",
    "gear_id": "g123",
    "sport_type": "Run",
    "distance": 5000.50,
    "start_date": "2024-06-15T07:30:00+00:00",
}

GEAR_JSON = {
    "id": "g123",
    "primary": True,
    "brand_name": "Nike",
    "model_name": "Pegasus 40",
    "description": "Daily trainer",
}


class TestActivityReadJson:
    def test_parses_json_dict(self):
        result = Activity.read_json(ACTIVITY_JSON)
        assert result["name"] == "Morning Run"
        assert result["gear_id"] == "g123"
        assert result["sport_type"] == "Run"
        assert result["distance"] == 5000.50
        assert result["start_date"] == datetime.fromisoformat("2024-06-15T07:30:00+00:00")

    def test_null_gear_id(self):
        json_data = {**ACTIVITY_JSON, "gear_id": None}
        result = Activity.read_json(json_data)
        assert result["gear_id"] is None

    def test_private_flag_promoted(self):
        assert Activity.read_json({**ACTIVITY_JSON, "private": True})["is_private"] is True
        assert Activity.read_json({**ACTIVITY_JSON, "private": False})["is_private"] is False

    def test_private_defaults_false_when_missing(self):
        # SummaryActivity JSON without a `private` key is treated as public.
        assert Activity.read_json(ACTIVITY_JSON)["is_private"] is False


@pytest.mark.django_db
class TestActivityStr:
    def test_returns_name(self):
        activity = Activity.objects.create(
            id=1,
            name="Evening Ride",
            start_date=datetime(2024, 6, 15, tzinfo=timezone.utc),
            sport_type="Ride",
            distance=10000,
            json=ACTIVITY_JSON,
        )
        assert str(activity) == "Evening Ride"


@pytest.mark.django_db
class TestActivityIsSynced:
    def test_synced_when_matching(self):
        activity = Activity(
            name="Morning Run",
            start_date=datetime(2024, 6, 15, tzinfo=timezone.utc),
            sport_type="Run",
            distance=5000.50,
            gear_id="g123",
            json=ACTIVITY_JSON,
        )
        assert activity.is_synced() is True

    def test_not_synced_when_gear_differs(self):
        activity = Activity(
            name="Morning Run",
            start_date=datetime(2024, 6, 15, tzinfo=timezone.utc),
            sport_type="Run",
            distance=5000.50,
            gear_id="g999",
            json=ACTIVITY_JSON,
        )
        assert activity.is_synced() is False

    def test_not_synced_when_sport_type_differs(self):
        activity = Activity(
            name="Morning Run",
            start_date=datetime(2024, 6, 15, tzinfo=timezone.utc),
            sport_type="Walk",
            distance=5000.50,
            gear_id="g123",
            json=ACTIVITY_JSON,
        )
        assert activity.is_synced() is False


@pytest.mark.django_db
class TestActivityIsGearSynced:
    def test_synced_when_gear_matches(self):
        activity = Activity(
            name="Morning Run",
            start_date=datetime(2024, 6, 15, tzinfo=timezone.utc),
            sport_type="Walk",  # sport differs but gear matches
            distance=5000.50,
            gear_id="g123",
            json=ACTIVITY_JSON,
        )
        assert activity.is_gear_synced() is True

    def test_not_synced_when_gear_differs(self):
        activity = Activity(
            name="Morning Run",
            start_date=datetime(2024, 6, 15, tzinfo=timezone.utc),
            sport_type="Run",
            distance=5000.50,
            gear_id="g999",
            json=ACTIVITY_JSON,
        )
        assert activity.is_gear_synced() is False


@pytest.mark.django_db
class TestBackfillIsPrivate:
    def _run(self):
        # Exercise the 0012 data-migration function against the current models (its only
        # apps usage is get_model + .objects, which the live registry satisfies).
        import importlib
        from django.apps import apps as global_apps
        mod = importlib.import_module("stravakit.migrations.0012_activity_is_private")
        mod.backfill_is_private(global_apps, None)

    def test_backfills_from_stored_json(self):
        private = Activity.objects.create(
            id=1, name="Secret", start_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
            sport_type="Run", distance=1000, json={"id": 1, "private": True},
        )
        public = Activity.objects.create(
            id=2, name="Public", start_date=datetime(2024, 1, 2, tzinfo=timezone.utc),
            sport_type="Run", distance=1000, json={"id": 2, "private": False},
        )
        # A legacy row whose JSON predates the `private` key is treated as public.
        legacy = Activity.objects.create(
            id=3, name="Legacy", start_date=datetime(2024, 1, 3, tzinfo=timezone.utc),
            sport_type="Run", distance=1000, json={"id": 3},
        )

        self._run()

        private.refresh_from_db()
        public.refresh_from_db()
        legacy.refresh_from_db()
        assert private.is_private is True
        assert public.is_private is False
        assert legacy.is_private is False


class TestActivityDetailed:
    # `is_detailed` is a promoted boolean column computed by read_json at import time,
    # from the DetailedActivity-only marker fields.
    def test_summary_only_is_not_detailed(self):
        # SummaryActivity JSON omits the detail-only fields entirely.
        assert Activity.read_json(ACTIVITY_JSON)["is_detailed"] is False

    def test_null_detail_fields_is_not_detailed(self):
        # stravalib serialises detail fields as null for summary-sourced activities.
        json_data = {**ACTIVITY_JSON, "calories": None, "embed_token": None,
                     "description": None, "device_name": None}
        assert Activity.read_json(json_data)["is_detailed"] is False

    def test_calories_makes_it_detailed(self):
        json_data = {**ACTIVITY_JSON, "calories": 0}
        assert Activity.read_json(json_data)["is_detailed"] is True

    def test_embed_token_makes_it_detailed(self):
        json_data = {**ACTIVITY_JSON, "embed_token": "abc123"}
        assert Activity.read_json(json_data)["is_detailed"] is True


@pytest.mark.django_db
class TestActivityUpdateFromJson:
    @patch("stravakit.services.sync.StravaApi")
    def test_updates_fields_from_json(self, mock_api_cls):
        gear = Gear.objects.create(
            id="g123",
            primary=True,
            brand_name="Nike",
            model_name="Pegasus 40",
            description="Daily trainer",
            json=GEAR_JSON,
        )
        activity = Activity.objects.create(
            id=1,
            name="Old Name",
            start_date=datetime(2020, 1, 1, tzinfo=timezone.utc),
            sport_type="Walk",
            distance=0,
            json=ACTIVITY_JSON,
        )
        sync.activity_apply_json(activity)
        activity.refresh_from_db()

        assert activity.name == "Morning Run"
        assert activity.sport_type == "Run"
        assert activity.distance == 5000.50
        assert activity.gear_id == "g123"
        # API should not be called since gear already exists
        mock_api_cls.assert_not_called()

    @patch("stravakit.services.sync.StravaApi")
    def test_fetches_gear_from_api_when_missing(self, mock_api_cls):
        mock_api_cls.return_value.get_gear.return_value = GEAR_JSON

        activity = Activity.objects.create(
            id=2,
            name="Old Name",
            start_date=datetime(2020, 1, 1, tzinfo=timezone.utc),
            sport_type="Walk",
            distance=0,
            json=ACTIVITY_JSON,
        )
        sync.activity_apply_json(activity)

        mock_api_cls.return_value.get_gear.assert_called_once_with("g123")
        assert Gear.objects.filter(id="g123").exists()


class TestGearReadJson:
    def test_parses_json_dict(self):
        result = Gear.read_json(GEAR_JSON)
        assert result["primary"] is True
        assert result["brand_name"] == "Nike"
        assert result["model_name"] == "Pegasus 40"
        assert result["description"] == "Daily trainer"

    def test_null_description_becomes_empty(self):
        json_data = {**GEAR_JSON, "description": None}
        result = Gear.read_json(json_data)
        assert result["description"] == ""


@pytest.mark.django_db
class TestGearStr:
    def test_returns_brand_model(self):
        gear = Gear.objects.create(
            id="g1",
            primary=False,
            brand_name="Adidas",
            model_name="Ultraboost",
            description="",
            json=GEAR_JSON,
        )
        assert str(gear) == "Adidas Ultraboost"


ATHLETE_JSON = {
    "id": 42,
    "firstname": "Ada",
    "lastname": "Lovelace",
    "profile": "https://example.com/avatar.jpg",
    "city": "London",
    "country": "UK",
    "follower_count": 12,
    "friend_count": 7,
}


class TestAthleteReadJson:
    def test_parses_json_dict(self):
        result = Athlete.read_json(ATHLETE_JSON)
        assert result["firstname"] == "Ada"
        assert result["lastname"] == "Lovelace"
        assert result["profile"] == "https://example.com/avatar.jpg"
        assert result["follower_count"] == 12
        assert result["friend_count"] == 7

    def test_missing_fields_default_safely(self):
        result = Athlete.read_json({"id": 1})
        assert result["firstname"] == ""
        assert result["profile"] == ""
        assert result["follower_count"] is None

    def test_relative_placeholder_avatar_is_dropped(self):
        # Strava sends a relative placeholder (e.g. "avatar/athlete/large.png") when the
        # athlete has no custom photo; only absolute URLs are kept.
        result = Athlete.read_json({**ATHLETE_JSON, "profile": "avatar/athlete/large.png"})
        assert result["profile"] == ""


@pytest.mark.django_db
class TestAthleteStore:
    def test_creates_then_updates_in_place(self):
        athlete = Athlete.store(ATHLETE_JSON)
        assert athlete.pk == 42
        assert athlete.full_name == "Ada Lovelace"

        # Re-importing the same athlete id updates the row rather than duplicating it.
        Athlete.store({**ATHLETE_JSON, "firstname": "Augusta", "follower_count": 99})
        assert Athlete.objects.count() == 1
        athlete.refresh_from_db()
        assert athlete.firstname == "Augusta"
        assert athlete.follower_count == 99

    def test_sync_from_api_stores_fetched_athlete(self):
        # athlete_sync refreshes an already-connected athlete using their stored token.
        existing = Athlete.objects.create(id=42, access_token="x", refresh_token="y", json={})
        with patch("stravakit.services.sync.StravaApi") as mock_api_cls:
            mock_api_cls.return_value.get_athlete.return_value = ATHLETE_JSON
            athlete = sync.athlete_sync(existing)
        assert athlete.pk == 42
        assert Athlete.current() == athlete


@pytest.mark.django_db
class TestAthleteProperties:
    def test_current_is_none_before_import(self):
        assert Athlete.current() is None

    def test_full_name_and_location_and_urls(self):
        athlete = Athlete.store(ATHLETE_JSON)
        assert athlete.full_name == "Ada Lovelace"
        assert athlete.location == "London, UK"
        assert athlete.profile_url == "https://www.strava.com/athletes/42"
        assert athlete.followers_url == "https://www.strava.com/athletes/42/follows?type=followers"
        assert athlete.following_url == "https://www.strava.com/athletes/42/follows?type=following"

    def test_str_falls_back_to_id_without_name(self):
        athlete = Athlete.store({"id": 7})
        assert str(athlete) == "7"


@pytest.mark.django_db
class TestAthleteOwnership:
    def test_activity_and_gear_reverse_relations(self):
        athlete = Athlete.store(ATHLETE_JSON)
        gear = Gear.objects.create(id="g1", primary=False, brand_name="Nike",
                                   model_name="Pegasus", description="", json={},
                                   athlete=athlete)
        activity = Activity.objects.create(
            id=1, name="Run", start_date=datetime(2024, 6, 15, tzinfo=timezone.utc),
            sport_type="Run", distance=5000, json={"id": 1}, athlete=athlete, gear=gear,
        )
        assert list(athlete.activities.all()) == [activity]
        assert list(athlete.gear.all()) == [gear]

    def test_get_or_create_sets_gear_owner(self):
        athlete = Athlete.store(ATHLETE_JSON)
        with patch("stravakit.services.sync.StravaApi") as mock_api_cls:
            mock_api_cls.return_value.get_gear.return_value = GEAR_JSON
            gear = sync.gear_ensure(gear_id="g123", athlete=athlete)
        assert gear.athlete_id == athlete.pk

    def test_deleting_athlete_cascades_to_owned_rows(self):
        athlete = Athlete.store(ATHLETE_JSON)
        Activity.objects.create(
            id=1, name="Run", start_date=datetime(2024, 6, 15, tzinfo=timezone.utc),
            sport_type="Run", distance=5000, json={"id": 1}, athlete=athlete,
        )
        Gear.objects.create(id="g1", primary=False, brand_name="Nike", model_name="M",
                            description="", json={}, athlete=athlete)
        athlete.delete()
        assert Activity.objects.count() == 0
        assert Gear.objects.count() == 0
