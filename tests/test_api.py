"""Tests for strava.api: error formatting, token parsing and the rate-limit retry.

These don't touch the DB or a real Strava connection — the ``stravalib.Client``
is never constructed (only ``StravaApi.get_token_expiration`` is exercised, which
doesn't build a client).
"""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from stravalib import exc

from strava import api
from strava.api import StravaApi, format_strava_error, rate_limited


class FakeResponse:
    def __init__(self, status_code=None, payload=None, headers=None, raises=False):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        self._raises = raises

    def json(self):
        if self._raises:
            raise ValueError("no json")
        return self._payload


# --------------------------------------------------------------------------- #
# format_strava_error
# --------------------------------------------------------------------------- #
class TestFormatStravaError:
    def test_message_details_and_status(self):
        response = FakeResponse(status_code=403, payload={
            "message": "Forbidden",
            "errors": [{"resource": "Application", "field": "Status", "code": "Inactive"}],
        })
        error = exc.Fault("boom")
        error.response = response
        assert format_strava_error(error) == "Forbidden — Application Status: Inactive (HTTP 403)"

    def test_message_only(self):
        response = FakeResponse(status_code=401, payload={"message": "Unauthorized"})
        error = SimpleNamespace(response=response)
        assert format_strava_error(error) == "Unauthorized (HTTP 401)"

    def test_errors_without_code_are_dropped(self):
        response = FakeResponse(status_code=400, payload={
            "message": "Bad Request",
            "errors": [{"resource": "Activity", "field": "Name"}],  # no code
        })
        error = SimpleNamespace(response=response)
        assert format_strava_error(error) == "Bad Request (HTTP 400)"

    def test_non_api_error_falls_back_to_str(self):
        # A plain network error: no response attribute at all.
        error = ConnectionError("connection reset")
        assert format_strava_error(error) == "connection reset"

    def test_unparseable_body_falls_back(self):
        response = FakeResponse(status_code=500, raises=True)
        error = SimpleNamespace(response=response)
        # No payload, but the status code still gets appended to the str(error).
        assert format_strava_error(error).endswith("(HTTP 500)")


# --------------------------------------------------------------------------- #
# rate_limited decorator
# --------------------------------------------------------------------------- #
class TestRateLimited:
    def test_passes_through_on_success(self):
        calls = []

        @rate_limited
        def fn():
            calls.append(1)
            return "ok"

        assert fn() == "ok"
        assert len(calls) == 1

    def test_retries_then_succeeds(self):
        attempts = {"n": 0}

        @rate_limited
        def fn():
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise exc.RateLimitExceeded("slow down")
            return "recovered"

        with patch.object(api, "STRAVA_RATE_LIMIT_MAX_RETRIES", 3), \
             patch.object(api.time, "sleep") as sleep, \
             patch.object(api, "_seconds_until_limit_resets", return_value=1):
            assert fn() == "recovered"
        assert attempts["n"] == 2
        sleep.assert_called_once_with(1)

    def test_gives_up_after_max_retries(self):
        @rate_limited
        def fn():
            raise exc.RateLimitExceeded("nope")

        with patch.object(api, "STRAVA_RATE_LIMIT_MAX_RETRIES", 2), \
             patch.object(api.time, "sleep"), \
             patch.object(api, "_seconds_until_limit_resets", return_value=0):
            with pytest.raises(exc.RateLimitExceeded):
                fn()

    def test_non_rate_limit_fault_reraises_immediately(self):
        attempts = {"n": 0}
        fault = exc.Fault("server error")
        fault.response = FakeResponse(status_code=500)

        @rate_limited
        def fn():
            attempts["n"] += 1
            raise fault

        with patch.object(api, "STRAVA_RATE_LIMIT_MAX_RETRIES", 3), \
             patch.object(api.time, "sleep") as sleep:
            with pytest.raises(exc.Fault):
                fn()
        assert attempts["n"] == 1        # not retried
        sleep.assert_not_called()

    def test_429_fault_is_treated_as_rate_limit(self):
        attempts = {"n": 0}
        fault = exc.Fault("too many requests")
        fault.response = FakeResponse(status_code=429)

        @rate_limited
        def fn():
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise fault
            return "ok"

        with patch.object(api, "STRAVA_RATE_LIMIT_MAX_RETRIES", 3), \
             patch.object(api.time, "sleep"), \
             patch.object(api, "_seconds_until_limit_resets", return_value=0):
            assert fn() == "ok"
        assert attempts["n"] == 2


# --------------------------------------------------------------------------- #
# _seconds_until_limit_resets
# --------------------------------------------------------------------------- #
class TestSecondsUntilLimitResets:
    def test_daily_limit_hit_waits_until_next_day(self):
        rates = SimpleNamespace(long_usage=1000, long_limit=1000)
        with patch.object(api, "get_rates_from_response_headers", return_value=rates), \
             patch.object(api, "get_seconds_until_next_day", return_value=3600) as day, \
             patch.object(api, "get_seconds_until_next_quarter", return_value=60):
            assert api._seconds_until_limit_resets(FakeResponse(headers={"x": "y"})) == 3600
            day.assert_called_once()

    def test_short_limit_waits_until_next_quarter(self):
        rates = SimpleNamespace(long_usage=10, long_limit=1000)
        with patch.object(api, "get_rates_from_response_headers", return_value=rates), \
             patch.object(api, "get_seconds_until_next_quarter", return_value=45) as quarter:
            assert api._seconds_until_limit_resets(FakeResponse(headers={"x": "y"})) == 45
            quarter.assert_called_once()

    def test_missing_headers_falls_back_to_quarter(self):
        with patch.object(api, "get_rates_from_response_headers", return_value=None), \
             patch.object(api, "get_seconds_until_next_quarter", return_value=30):
            # response with no headers attribute at all
            assert api._seconds_until_limit_resets(SimpleNamespace()) == 30


# --------------------------------------------------------------------------- #
# StravaApi client-wrapping methods (stravalib.Client mocked out)
# --------------------------------------------------------------------------- #
class Model:
    """Stand-in for a stravalib model: exposes model_dump_json()."""
    def __init__(self, payload):
        self._payload = payload

    def model_dump_json(self):
        import json as _json
        return _json.dumps(self._payload)


class TestStravaApiClient:
    def _api(self, client):
        # A real stravalib Client carries a .protocol (StravaApi arms auto-refresh on it);
        # the SimpleNamespace stand-ins don't, so give them one.
        client.protocol = SimpleNamespace()
        with patch.object(api, "Client", return_value=client), \
             patch.object(api, "DefaultRateLimiter"):
            return StravaApi()

    def test_get_gear_returns_parsed_json(self):
        client = SimpleNamespace(get_gear=lambda id: Model({"id": id, "brand_name": "Nike"}))
        result = self._api(client).get_gear("g1")
        assert result == {"id": "g1", "brand_name": "Nike"}

    def test_get_activity_returns_parsed_json(self):
        client = SimpleNamespace(get_activity=lambda id: Model({"id": id, "name": "Run"}))
        result = self._api(client).get_activity(42)
        assert result == {"id": 42, "name": "Run"}

    def test_get_activities_serialises_each(self):
        activities = [Model({"id": 1}), Model({"id": 2})]
        client = SimpleNamespace(
            get_activities=lambda after=None, before=None, limit=None: iter(activities))
        result = self._api(client).get_activities()
        assert result == [{"id": 1}, {"id": 2}]

    def test_get_activities_forwards_window(self):
        # The window is the whole point of a backfill run — guard against a refactor
        # quietly dropping a bound and rescanning everything (or nothing).
        calls = {}

        def fake(after=None, before=None, limit=None):
            calls.update({"after": after, "before": before, "limit": limit})
            return iter([])

        after = datetime(2026, 1, 1, tzinfo=timezone.utc)
        before = datetime(2026, 4, 1, tzinfo=timezone.utc)
        self._api(SimpleNamespace(get_activities=fake)).get_activities(
            after=after, before=before, limit=5)
        assert calls == {"after": after, "before": before, "limit": 5}

    def test_update_activity_forwards_kwargs(self):
        calls = {}
        client = SimpleNamespace(
            update_activity=lambda activity_id, **kw: calls.update({"id": activity_id, **kw}))
        self._api(client).update_activity(id=7, name="New", sport_type="Run")
        assert calls == {"id": 7, "name": "New", "sport_type": "Run"}

    def test_get_athlete_returns_parsed_json(self):
        client = SimpleNamespace(get_athlete=lambda: Model({"id": 42, "firstname": "Erik"}))
        result = self._api(client).get_athlete()
        assert result == {"id": 42, "firstname": "Erik"}

    def test_get_formatted_json_indents(self):
        api_obj = self._api(SimpleNamespace())
        out = api_obj.get_formatted_json({"a": 1})
        assert out == '{\n    "a": 1\n}'

    def test_get_formatted_json_accepts_json_string(self):
        api_obj = self._api(SimpleNamespace())
        out = api_obj.get_formatted_json('{"a": 1}')
        assert out == '{\n    "a": 1\n}'
