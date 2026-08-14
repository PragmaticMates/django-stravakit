import io
import json as json_lib
from datetime import date, datetime, timezone
from unittest.mock import mock_open, patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone as django_timezone

from stravakit.management.commands.import_strava import Command
from stravakit.models import Activity, Athlete, Gear


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

ACTIVITY_JSON_1 = {
    "id": 100,
    "name": "Morning Run",
    "gear_id": None,
    "sport_type": "Run",
    "distance": 5000,
    "start_date": "2024-06-15T07:30:00+00:00",
}

ACTIVITY_JSON_2 = {
    "id": 200,
    "name": "Evening Ride",
    "gear_id": None,
    "sport_type": "Ride",
    "distance": 20000,
    "start_date": "2024-06-16T18:00:00+00:00",
}


def _connect_athlete(athlete_id=42):
    """Pre-create the connected (token-holding, default) athlete the import loops over.

    The command imports each already-connected athlete rather than auto-creating one from a
    global token, so tests seed the athlete first; ``get_athlete`` (id 42) then upserts it."""
    return Athlete.objects.create(
        id=athlete_id, access_token="tok", refresh_token="ref", is_default=True, json={},
    )


@pytest.mark.django_db
class TestImportStrava:
    @patch("stravakit.services.sync.gear_ensure", return_value=None)
    @patch("stravakit.management.commands.import_strava.StravaApi")
    def test_creates_activities(self, mock_api_cls, mock_gear):
        _connect_athlete()
        mock_api_cls.return_value.get_athlete.return_value = ATHLETE_JSON
        mock_api_cls.return_value.get_activities.return_value = [
            ACTIVITY_JSON_1,
            ACTIVITY_JSON_2,
        ]
        # The command fetches the detailed activity per summary id.
        details = {100: ACTIVITY_JSON_1, 200: ACTIVITY_JSON_2}
        mock_api_cls.return_value.get_activity.side_effect = lambda activity_id: details[activity_id]

        call_command("import_strava")

        assert Activity.objects.count() == 2
        a1 = Activity.objects.get(id=100)
        assert a1.name == "Morning Run"
        assert a1.sport_type == "Run"

        a2 = Activity.objects.get(id=200)
        assert a2.name == "Evening Ride"
        assert a2.sport_type == "Ride"

        # Imported activities are linked to the synced athlete.
        assert a1.athlete_id == 42
        assert a2.athlete_id == 42

    @patch("stravakit.services.sync.gear_ensure", return_value=None)
    @patch("stravakit.management.commands.import_strava.StravaApi")
    def test_imports_athlete(self, mock_api_cls, mock_gear):
        _connect_athlete()
        mock_api_cls.return_value.get_athlete.return_value = ATHLETE_JSON
        mock_api_cls.return_value.get_activities.return_value = []

        call_command("import_strava")

        athlete = Athlete.objects.get(id=42)
        assert athlete.full_name == "Ada Lovelace"
        assert athlete.follower_count == 12
        assert Athlete.current() == athlete

    def test_raises_without_connected_athletes(self):
        # No OAuth-connected athlete → the command fails loudly (surfaced to the refresh
        # button / admin action) rather than silently importing nothing.
        Athlete.objects.create(id=42, json={})  # exists but not connected (no tokens)
        with pytest.raises(CommandError):
            call_command("import_strava")

    @patch("stravakit.services.sync.gear_ensure", return_value=None)
    @patch("stravakit.management.commands.import_strava.StravaApi")
    def test_incremental_passes_after(self, mock_api_cls, mock_gear):
        athlete = _connect_athlete()
        # An existing activity owned by this athlete so their .exists()/.latest() is found
        # (the incremental "after" is computed per athlete).
        Activity.objects.create(
            id=100,
            name="Morning Run",
            start_date=datetime(2024, 6, 15, 7, 30, tzinfo=timezone.utc),
            sport_type="Run",
            distance=5000,
            json=ACTIVITY_JSON_1,
            athlete=athlete,
        )

        mock_api_cls.return_value.get_athlete.return_value = ATHLETE_JSON
        mock_api_cls.return_value.get_activities.return_value = []

        call_command("import_strava")

        mock_api_cls.return_value.get_activities.assert_called_once_with(
            after=datetime(2024, 6, 15, 7, 30, tzinfo=timezone.utc), before=None
        )

    @patch("stravakit.services.sync.gear_ensure", return_value=None)
    @patch("stravakit.management.commands.import_strava.StravaApi")
    def test_updates_existing_activity(self, mock_api_cls, mock_gear):
        _connect_athlete()
        Activity.objects.create(
            id=100,
            name="Old Name",
            start_date=datetime(2024, 6, 15, 7, 30, tzinfo=timezone.utc),
            sport_type="Run",
            distance=5000,
            json=ACTIVITY_JSON_1,
        )

        mock_api_cls.return_value.get_athlete.return_value = ATHLETE_JSON
        updated_json = {**ACTIVITY_JSON_1, "name": "Renamed Run"}
        mock_api_cls.return_value.get_activities.return_value = [updated_json]
        mock_api_cls.return_value.get_activity.side_effect = lambda activity_id: updated_json

        call_command("import_strava")

        assert Activity.objects.count() == 1
        assert Activity.objects.get(id=100).name == "Renamed Run"


@pytest.mark.django_db
class TestImportWindow:
    """--days/--after/--before replace the incremental cursor with an explicit window."""

    def _api(self, mock_api_cls):
        mock_api_cls.return_value.get_athlete.return_value = ATHLETE_JSON
        mock_api_cls.return_value.get_activities.return_value = []
        return mock_api_cls.return_value

    def _stored_activity(self, athlete):
        return Activity.objects.create(
            id=100, name="Morning Run", start_date=datetime(2024, 6, 15, 7, 30, tzinfo=timezone.utc),
            sport_type="Run", distance=5000, json=ACTIVITY_JSON_1, athlete=athlete,
        )

    @patch("stravakit.services.sync.gear_ensure", return_value=None)
    @patch("stravakit.management.commands.import_strava.StravaApi")
    def test_days_overrides_the_cursor(self, mock_api_cls, mock_gear):
        athlete = _connect_athlete()
        self._stored_activity(athlete)
        api = self._api(mock_api_cls)

        call_command("import_strava", "--days", "90")

        kwargs = api.get_activities.call_args.kwargs
        assert kwargs["before"] is None
        # Not the stored activity's start_date — the whole point of the window.
        assert kwargs["after"] != datetime(2024, 6, 15, 7, 30, tzinfo=timezone.utc)
        assert django_timezone.is_aware(kwargs["after"])
        assert (django_timezone.now() - kwargs["after"]).days == 90

    @patch("stravakit.services.sync.gear_ensure", return_value=None)
    @patch("stravakit.management.commands.import_strava.StravaApi")
    def test_days_counts_back_from_before(self, mock_api_cls, mock_gear):
        _connect_athlete()
        api = self._api(mock_api_cls)

        call_command("import_strava", "--days", "30", "--before", "2025-01-01")

        kwargs = api.get_activities.call_args.kwargs
        assert (kwargs["before"] - kwargs["after"]).days == 30
        assert kwargs["before"].date() == date(2025, 1, 1)

    @patch("stravakit.services.sync.gear_ensure", return_value=None)
    @patch("stravakit.management.commands.import_strava.StravaApi")
    def test_explicit_bounds_are_aware(self, mock_api_cls, mock_gear):
        _connect_athlete()
        api = self._api(mock_api_cls)

        call_command("import_strava", "--after", "2025-01-01", "--before", "2025-02-01")

        kwargs = api.get_activities.call_args.kwargs
        # Naive input is read in the project timezone, never handed to stravalib naive.
        assert django_timezone.is_aware(kwargs["after"])
        assert django_timezone.is_aware(kwargs["before"])

    @patch("stravakit.services.sync.gear_ensure", return_value=None)
    @patch("stravakit.management.commands.import_strava.StravaApi")
    def test_windowed_run_leaves_synced_at_alone(self, mock_api_cls, mock_gear):
        athlete = _connect_athlete()
        self._api(mock_api_cls)

        call_command("import_strava", "--days", "90")

        athlete.refresh_from_db()
        # A historical rescan is not "last updated" — the dashboard footer must stay honest.
        assert athlete.synced_at is None

    @patch("stravakit.services.sync.gear_ensure", return_value=None)
    @patch("stravakit.management.commands.import_strava.StravaApi")
    def test_default_run_sets_synced_at(self, mock_api_cls, mock_gear):
        athlete = _connect_athlete()
        self._api(mock_api_cls)

        call_command("import_strava")

        athlete.refresh_from_db()
        assert athlete.synced_at is not None

    @pytest.mark.parametrize("argv", [
        ["--days", "30", "--after", "2025-01-01"],   # both set the start of the window
        ["--days", "0"],
        ["--after", "2025-02-01", "--before", "2025-01-01"],
        ["--after", "notadate"],
    ])
    def test_invalid_window_raises(self, argv):
        _connect_athlete()
        with pytest.raises(CommandError):
            call_command("import_strava", *argv)


@pytest.mark.django_db
class TestImportMissing:
    """--missing spends a detail API call only on activities with no local row."""

    def _api(self, mock_api_cls, summaries):
        api = mock_api_cls.return_value
        api.get_athlete.return_value = ATHLETE_JSON
        api.get_activities.return_value = summaries
        details = {activity["id"]: activity for activity in summaries}
        api.get_activity.side_effect = lambda activity_id: details[activity_id]
        return api

    @patch("stravakit.services.sync.gear_ensure", return_value=None)
    @patch("stravakit.management.commands.import_strava.StravaApi")
    def test_skips_ids_already_stored(self, mock_api_cls, mock_gear):
        athlete = _connect_athlete()
        Activity.objects.create(
            id=100, name="Morning Run", start_date=datetime(2024, 6, 15, 7, 30, tzinfo=timezone.utc),
            sport_type="Run", distance=5000, json=ACTIVITY_JSON_1, athlete=athlete,
        )
        api = self._api(mock_api_cls, [ACTIVITY_JSON_1, ACTIVITY_JSON_2])

        call_command("import_strava", "--days", "90", "--missing")

        api.get_activity.assert_called_once_with(200)
        assert Activity.objects.count() == 2

    @patch("stravakit.services.sync.gear_ensure", return_value=None)
    @patch("stravakit.management.commands.import_strava.StravaApi")
    def test_rows_owned_by_nobody_count_as_known(self, mock_api_cls, mock_gear):
        # Legacy rows carry no athlete. Scoping the diff per athlete would call them
        # missing and re-fetch them on every single run — the cost --missing exists to avoid.
        _connect_athlete()
        Activity.objects.create(
            id=100, name="Morning Run", start_date=datetime(2024, 6, 15, 7, 30, tzinfo=timezone.utc),
            sport_type="Run", distance=5000, json=ACTIVITY_JSON_1, athlete=None,
        )
        api = self._api(mock_api_cls, [ACTIVITY_JSON_1])

        call_command("import_strava", "--days", "90", "--missing")

        api.get_activity.assert_not_called()

    @patch("stravakit.services.sync.gear_ensure", return_value=None)
    @patch("stravakit.management.commands.import_strava.StravaApi")
    def test_imports_activity_older_than_the_cursor(self, mock_api_cls, mock_gear):
        # The bug this option exists for: an activity backdated behind the newest stored
        # one is invisible to the incremental import forever.
        athlete = _connect_athlete()
        Activity.objects.create(
            id=200, name="Evening Ride", start_date=datetime(2024, 6, 16, 18, 0, tzinfo=timezone.utc),
            sport_type="Ride", distance=20000, json=ACTIVITY_JSON_2, athlete=athlete,
        )
        api = self._api(mock_api_cls, [ACTIVITY_JSON_1, ACTIVITY_JSON_2])

        call_command("import_strava", "--days", "90", "--missing")

        api.get_activity.assert_called_once_with(100)
        assert Activity.objects.filter(id=100).exists()

    @patch("stravakit.services.sync.gear_ensure", return_value=None)
    @patch("stravakit.management.commands.import_strava.StravaApi")
    def test_gear_is_resolved_only_for_missing(self, mock_api_cls, mock_gear):
        athlete = _connect_athlete()
        # gear_ensure is mocked, so the rows it would have created have to exist already
        # for the activity's gear FK to resolve.
        for gear_id in ("g1", "g2"):
            Gear.objects.create(id=gear_id, brand_name="B", model_name="M", description="",
                                json={})
        Activity.objects.create(
            id=100, name="Morning Run", start_date=datetime(2024, 6, 15, 7, 30, tzinfo=timezone.utc),
            sport_type="Run", distance=5000, json=ACTIVITY_JSON_1, athlete=athlete,
        )
        self._api(mock_api_cls, [
            {**ACTIVITY_JSON_1, "gear_id": "g1"},
            {**ACTIVITY_JSON_2, "gear_id": "g2"},
        ])

        call_command("import_strava", "--days", "90", "--missing")

        assert mock_gear.call_count == 1
        assert mock_gear.call_args.kwargs["gear_id"] == "g2"

    @patch("stravakit.services.sync.gear_ensure", return_value=None)
    @patch("stravakit.management.commands.import_strava.StravaApi")
    def test_nothing_missing_costs_no_detail_calls(self, mock_api_cls, mock_gear):
        athlete = _connect_athlete()
        Activity.objects.create(
            id=100, name="Morning Run", start_date=datetime(2024, 6, 15, 7, 30, tzinfo=timezone.utc),
            sport_type="Run", distance=5000, json=ACTIVITY_JSON_1, athlete=athlete,
        )
        api = self._api(mock_api_cls, [ACTIVITY_JSON_1])

        call_command("import_strava", "--days", "90", "--missing")

        api.get_activity.assert_not_called()

    @patch("stravakit.services.sync.gear_ensure", return_value=None)
    @patch("stravakit.management.commands.import_strava.StravaApi")
    def test_dry_run_writes_nothing(self, mock_api_cls, mock_gear):
        athlete = _connect_athlete()
        api = self._api(mock_api_cls, [ACTIVITY_JSON_1])
        out = io.StringIO()

        call_command("import_strava", "--days", "90", "--missing", "--dry-run", stdout=out)

        assert Activity.objects.count() == 0
        api.get_activity.assert_not_called()
        api.get_athlete.assert_not_called()
        athlete.refresh_from_db()
        assert athlete.synced_at is None
        assert "100" in out.getvalue()


@pytest.mark.django_db
class TestImportFromFile:
    @patch("stravakit.services.sync.gear_ensure", return_value=None)
    def test_creates_activities_from_file(self, mock_gear):
        payload = json_lib.dumps([ACTIVITY_JSON_1, ACTIVITY_JSON_2])
        with patch("stravakit.management.commands.import_strava.os.path.exists", return_value=True), \
             patch("builtins.open", mock_open(read_data=payload)):
            Command().import_activities_from_file()

        assert Activity.objects.count() == 2
        assert Activity.objects.get(id=100).name == "Morning Run"

    def test_missing_file_creates_nothing(self):
        with patch("stravakit.management.commands.import_strava.os.path.exists", return_value=False):
            Command().import_activities_from_file()
        assert Activity.objects.count() == 0
