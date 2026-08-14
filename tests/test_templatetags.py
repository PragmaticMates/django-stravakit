"""Tests for the stravakit_athlete template tag.

The test settings define no TEMPLATES engine, so the tag's callable is exercised
directly rather than through a rendered template (mirroring test_sport_icons).
"""
import pytest

from stravakit.models import Athlete
from stravakit.templatetags.stravakit_athlete import stravakit_athlete


@pytest.mark.django_db
class TestStravaAthleteTag:
    # The tag takes the template context; with no ``request`` in it, it falls back to the
    # default athlete (the switcher's ``?athlete=`` selection only applies when a request
    # is present).
    def test_returns_none_before_import(self):
        assert stravakit_athlete({}) is None

    def test_returns_current_athlete(self):
        athlete = Athlete.store({"id": 42, "firstname": "Ada", "lastname": "Lovelace"})
        assert stravakit_athlete({}) == athlete
