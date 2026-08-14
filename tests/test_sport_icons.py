"""Tests for the sport-glyph resolver (stravakit.sport_icons)."""
from django.utils.safestring import SafeString

from stravakit import sport_icons
from stravakit.sport_icons import icon_for, icon_html


class TestIconFor:
    def test_returns_own_icon(self):
        assert icon_for("Run") == sport_icons.SPORT_ICONS["Run"]

    def test_uniconed_sport_falls_back_to_run_glyph(self):
        # Crossfit has no bespoke glyph and belongs to no group → generic run glyph.
        assert icon_for("Crossfit") == sport_icons.GROUP_GLYPHS["run"]


class TestGroupIconName:
    def test_grouped_sport_returns_group_icon(self):
        # Run belongs to the running group.
        assert sport_icons._group_icon_name("Run") == "run"
        assert sport_icons._group_icon_name("Swim") == "swim"

    def test_ungrouped_sport_defaults_to_run(self):
        assert sport_icons._group_icon_name("Crossfit") == "run"


class TestIconHtml:
    def test_is_marked_safe(self):
        out = icon_html("Run")
        assert isinstance(out, SafeString)
        assert out == sport_icons.SPORT_ICONS["Run"]
