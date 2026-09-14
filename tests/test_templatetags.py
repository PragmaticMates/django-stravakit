"""Tests for the stravakit_athlete template tag.

The test settings define no TEMPLATES engine, so the tag's callable is exercised
directly rather than through a rendered template (mirroring test_sport_icons).
"""
import pytest
from django.template import Context, Template
from django.test import override_settings

from stravakit.models import Athlete
from stravakit.templatetags.stravakit_athlete import stravakit_athlete
from stravakit.templatetags.stravakit_map import BASEMAP_URL, stravakit_basemap_url


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


class TestBasemapUrlTag:
    # CARTO watermarks every tile served without a key, so the key has to reach both the
    # Leaflet map and the static card maps — they read it from one <meta> in base.html.
    @override_settings(STRAVA_CARTO_API_KEY="abc123")
    def test_appends_key(self):
        assert stravakit_basemap_url() == f"{BASEMAP_URL}?key=abc123"

    @override_settings(STRAVA_CARTO_API_KEY=None)
    def test_keyless_without_setting(self):
        assert stravakit_basemap_url() == BASEMAP_URL
        assert "?" not in BASEMAP_URL

    @override_settings(STRAVA_CARTO_API_KEY="")
    def test_blank_key_is_no_key(self):
        assert stravakit_basemap_url() == BASEMAP_URL

    @override_settings(STRAVA_CARTO_API_KEY="abc123")
    def test_keeps_leaflet_placeholders(self):
        # Leaflet substitutes these itself; the key must not disturb them.
        rendered = Template("{% load stravakit_map %}{% stravakit_basemap_url %}").render(Context())
        for placeholder in ("{s}", "{z}", "{x}", "{y}", "{r}"):
            assert placeholder in rendered
        assert rendered.endswith("?key=abc123")
