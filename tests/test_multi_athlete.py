"""Tests for the multi-athlete additions: athlete resolution, per-athlete queryset
scoping, view scoping and OAuth token-refresh persistence.

Like the other view tests these drive the code directly (RequestFactory + method calls)
rather than going through the HTTP stack, so no template is rendered here — the minimal
TEMPLATES/urlconf in the test settings exist for the admin tests, not these.
"""
from datetime import datetime, timezone as tz
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.db import IntegrityError
from django.test import RequestFactory

from stravakit import api
from stravakit.api import StravaApi
from stravakit.models import Activity, Athlete, Gear
from stravakit.views import ActivitiesView


def _activity(id, athlete):
    return Activity.objects.create(
        id=id, name=f"A{id}", start_date=datetime(2025, 1, 1, tzinfo=tz.utc),
        sport_type="Run", distance=1000, json={"id": id}, athlete=athlete,
    )


class DumpModel:
    """Stand-in for a stravalib model exposing model_dump_json()."""
    def __init__(self, payload):
        self._payload = payload

    def model_dump_json(self):
        import json
        return json.dumps(self._payload)


@pytest.mark.django_db
class TestAthleteResolution:
    def test_default_prefers_flagged(self):
        Athlete.objects.create(id=1, json={})
        b = Athlete.objects.create(id=2, is_default=True, json={})
        assert Athlete.default() == b
        assert Athlete.current() == b

    def test_default_falls_back_to_first(self):
        a = Athlete.objects.create(id=1, json={})
        assert Athlete.default() == a

    def test_default_none_when_empty(self):
        assert Athlete.default() is None

    def test_selected_reads_athlete_param(self):
        Athlete.objects.create(id=1, is_default=True, json={})
        b = Athlete.objects.create(id=2, json={})
        req = RequestFactory().get("/", {"athlete": "2"})
        assert Athlete.selected(req) == b

    def test_selected_defaults_when_absent(self):
        a = Athlete.objects.create(id=1, is_default=True, json={})
        assert Athlete.selected(RequestFactory().get("/")) == a

    def test_selected_ignores_bogus_and_unknown_param(self):
        # A non-numeric athlete id must not raise (the pk is an integer), and an unknown or
        # blank id falls back to the default rather than 404-ing the whole page.
        a = Athlete.objects.create(id=1, is_default=True, json={})
        rf = RequestFactory()
        assert Athlete.selected(rf.get("/", {"athlete": "nope"})) == a
        assert Athlete.selected(rf.get("/", {"athlete": ""})) == a
        assert Athlete.selected(rf.get("/", {"athlete": "999"})) == a

    def test_has_tokens(self):
        assert Athlete(access_token="x", refresh_token="y").has_tokens
        assert not Athlete(access_token="x").has_tokens
        assert not Athlete().has_tokens

    def test_one_default_constraint(self):
        Athlete.objects.create(id=1, is_default=True, json={})
        with pytest.raises(IntegrityError):
            Athlete.objects.create(id=2, is_default=True, json={})


@pytest.mark.django_db
class TestForAthlete:
    def test_scopes_activities_and_gear(self):
        a = Athlete.objects.create(id=1, json={})
        b = Athlete.objects.create(id=2, json={})
        _activity(10, a)
        _activity(11, a)
        _activity(20, b)
        Gear.objects.create(id="ga", brand_name="N", model_name="P", description="", json={}, athlete=a)
        Gear.objects.create(id="gb", brand_name="A", model_name="Q", description="", json={}, athlete=b)
        assert set(Activity.objects.for_athlete(a).values_list("id", flat=True)) == {10, 11}
        assert set(Gear.objects.for_athlete(b).values_list("id", flat=True)) == {"gb"}

    def test_none_is_a_noop(self):
        a = Athlete.objects.create(id=1, json={})
        _activity(10, a)
        assert Activity.objects.for_athlete(None).count() == 1


@pytest.mark.django_db
class TestViewScoping:
    def test_activities_view_scopes_to_selected_athlete(self):
        a = Athlete.objects.create(id=1, is_default=True, json={})
        b = Athlete.objects.create(id=2, json={})
        _activity(10, a)
        _activity(20, b)
        _activity(21, b)
        view = ActivitiesView()
        view.request = RequestFactory().get("/", {"athlete": "2"})
        assert set(view.get_queryset().values_list("id", flat=True)) == {20, 21}

    def test_context_exposes_switcher_data(self):
        a = Athlete.objects.create(id=1, is_default=True, json={})
        Athlete.objects.create(id=2, json={})
        view = ActivitiesView()
        view.request = RequestFactory().get("/")
        view.object_list = view.get_queryset()
        ctx = view.get_context_data()
        assert ctx["athlete"] == a
        assert ctx["athlete_id"] == a.pk
        assert ctx["athletes"].count() == 2


@pytest.mark.django_db
class TestSeedMigration:
    def _run(self):
        # Exercise the 0011 data-migration function against the current models (its only
        # apps usage is get_model + .objects, which the live registry satisfies).
        import importlib
        from django.apps import apps as global_apps
        mod = importlib.import_module("stravakit.migrations.0011_seed_default_athlete")
        mod.seed_default_athlete(global_apps, None)

    def test_marks_default_and_backfills_unowned_rows(self):
        athlete = Athlete.objects.create(id=1, json={})
        act = Activity.objects.create(
            id=1, name="Legacy", start_date=datetime(2024, 1, 1, tzinfo=tz.utc),
            sport_type="Run", distance=1000, json={"id": 1},
        )
        gear = Gear.objects.create(id="g1", brand_name="N", model_name="P", description="", json={})
        assert act.athlete_id is None and gear.athlete_id is None

        self._run()

        athlete.refresh_from_db()
        act.refresh_from_db()
        gear.refresh_from_db()
        assert athlete.is_default is True
        assert act.athlete_id == 1
        assert gear.athlete_id == 1

    def test_no_athlete_is_a_noop(self):
        self._run()  # empty DB → must not raise
        assert Athlete.objects.count() == 0


@pytest.mark.django_db
class TestTokenPersistence:
    def _client(self, **tokens):
        return SimpleNamespace(protocol=SimpleNamespace(), **tokens)

    def test_refreshed_tokens_saved_to_athlete(self):
        athlete = Athlete.objects.create(
            id=1, access_token="old", refresh_token="oldref",
            token_expires_at=datetime(2000, 1, 1, tzinfo=tz.utc), json={},
        )
        # A client whose tokens changed mid-call, as stravalib mutates them after a refresh.
        client = self._client(
            access_token="new", refresh_token="newref",
            token_expires=int(datetime(2030, 1, 1, tzinfo=tz.utc).timestamp()),
            get_athlete=lambda: DumpModel({"id": 1, "firstname": "Ada"}),
        )
        with patch.object(api, "Client", return_value=client), patch.object(api, "DefaultRateLimiter"):
            sapi = StravaApi(athlete)
        sapi.get_athlete()  # any wrapped call triggers _persist_tokens via @token_syncing

        athlete.refresh_from_db()
        assert athlete.access_token == "new"
        assert athlete.refresh_token == "newref"
        assert athlete.token_expires_at.year == 2030

    def test_no_write_when_tokens_unchanged(self):
        expires = datetime(2030, 1, 1, tzinfo=tz.utc)
        athlete = Athlete.objects.create(
            id=1, access_token="same", refresh_token="ref", token_expires_at=expires, json={},
        )
        client = self._client(
            access_token="same", refresh_token="ref",
            token_expires=int(expires.timestamp()),
            get_gear=lambda id: DumpModel({"id": id}),
        )
        with patch.object(api, "Client", return_value=client), patch.object(api, "DefaultRateLimiter"):
            sapi = StravaApi(athlete)
        with patch.object(Athlete, "save") as save:
            sapi.get_gear("g1")
            save.assert_not_called()

    def test_token_less_client_never_persists(self):
        # The OAuth-exchange client has no athlete, so wrapped calls must not try to save.
        client = self._client(access_token="x", refresh_token="y", token_expires=0,
                              get_athlete=lambda: DumpModel({"id": 9}))
        with patch.object(api, "Client", return_value=client), patch.object(api, "DefaultRateLimiter"):
            sapi = StravaApi()
        assert sapi.get_athlete() == {"id": 9}  # no AttributeError from a missing athlete
