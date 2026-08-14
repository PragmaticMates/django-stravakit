"""Tests for the changelist-level admin actions on ActivityAdmin.

These drive the action methods directly rather than through the admin HTTP stack — what
matters is which options reach ``stravakit_import`` and what the operator is told afterwards,
not unfold's button rendering.
"""
import io
from unittest.mock import patch

import pytest
from django.contrib import admin, messages
from django.test import RequestFactory

from stravakit.admin import ActivityAdmin
from stravakit.models import Activity


@pytest.fixture
def activity_admin():
    return ActivityAdmin(Activity, admin.site)


@pytest.fixture
def request_():
    # With a referer the action redirects back without resolving a URL name — the test
    # settings define no urlconf (see tests/test_multi_athlete.py), and the admin always
    # sends one in practice.
    return RequestFactory().get("/admin/stravakit/activity/", HTTP_REFERER="/admin/stravakit/activity/")


class TestImportActions:
    def test_stravakit_import_runs_the_incremental_import(self, activity_admin, request_):
        with patch("stravakit.admin.call_command") as call_command, \
             patch.object(ActivityAdmin, "message_user"):
            activity_admin.stravakit_import(request_)

        # No window and no --missing: byte-for-byte the behaviour this button always had.
        assert call_command.call_args.args == ("stravakit_import",)
        assert set(call_command.call_args.kwargs) == {"stdout"}

    def test_import_missing_passes_the_window(self, activity_admin, request_):
        with patch("stravakit.admin.call_command") as call_command, \
             patch.object(ActivityAdmin, "message_user"):
            activity_admin.stravakit_import_missing(request_)

        kwargs = call_command.call_args.kwargs
        assert (kwargs["days"], kwargs["missing"]) == (90, True)

    def test_both_actions_are_offered(self, activity_admin):
        assert "stravakit_import" in activity_admin.actions_list
        assert "stravakit_import_missing" in activity_admin.actions_list

    def test_failure_is_reported_not_raised(self, activity_admin, request_):
        # A rejected import (expired token, rate limit, outage) must reach the operator as
        # a message rather than a 500.
        with patch("stravakit.admin.call_command", side_effect=Exception("boom")), \
             patch.object(ActivityAdmin, "message_user") as message_user:
            activity_admin.stravakit_import_missing(request_)

        assert message_user.call_args.kwargs["level"] == messages.ERROR

    def test_summary_reports_what_happened(self, activity_admin, request_):
        def fake(_name, stdout=None, **options):
            stdout.write("Erik (1): 38 summaries, 38 already stored, 0 to fetch\n")
            stdout.write("Done: 1 athlete(s), 38 summaries, 38 skipped, 0 imported, 0 updated\n")

        with patch("stravakit.admin.call_command", side_effect=fake), \
             patch.object(ActivityAdmin, "message_user") as message_user:
            activity_admin.stravakit_import_missing(request_)

        message = message_user.call_args.args[1]
        assert "0 imported" in message
        assert message_user.call_args.kwargs["level"] == messages.SUCCESS

    def test_summary_survives_a_silent_command(self, activity_admin):
        # Nothing on stdout still has to produce a usable message.
        assert activity_admin.import_summary(io.StringIO())
