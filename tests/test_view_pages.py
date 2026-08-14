"""Context-data tests for the list/detail/compare views.

These drive ``get_context_data`` directly (the test settings define no TEMPLATES,
so nothing is rendered) and avoid the ``q=`` search param, which needs the
PostgreSQL ``unaccent`` extension not available on SQLite.
"""
import datetime
from datetime import timezone as tz

import pytest
from django.http import Http404
from django.test import RequestFactory

from stravakit.models import Activity, Gear
from stravakit.views import (
    ActivitiesView, ActivityCardView, CompareView, DashboardView,
    GalleryView, GearView,
)


def dt(y, m, d, h=12):
    return datetime.datetime(y, m, d, h, tzinfo=tz.utc)


def make_activity(id, sport_type="Run", distance=10000, moving_time=3000,
                  elevation=100, start_date=None, gear=None, kudos=0,
                  photo_url="", name=None, calories=0, pr_count=0,
                  achievement_count=0, start_lat=None, start_lng=None,
                  is_private=False):
    return Activity.objects.create(
        id=id,
        name=name or f"Activity {id}",
        start_date=start_date or dt(2025, 6, 15),
        sport_type=sport_type,
        distance=distance,
        moving_time=moving_time,
        total_elevation_gain=elevation,
        kudos_count=kudos,
        photo_url=photo_url,
        calories=calories,
        pr_count=pr_count,
        achievement_count=achievement_count,
        start_lat=start_lat,
        start_lng=start_lng,
        gear=gear,
        is_private=is_private,
        json={"id": id},
    )


def make_gear(id, gear_type="shoe", brand="Nike", primary=False):
    return Gear.objects.create(id=id, primary=primary, brand_name=brand,
                               model_name="M", description="", gear_type=gear_type,
                               json={})


def list_context(view_cls, **params):
    """Drive a ListView's get_context_data with the given GET params."""
    view = view_cls()
    view.setup(RequestFactory().get("/", params))
    view.object_list = view.get_queryset()
    return view.get_context_data()


def template_context(view_cls, **params):
    view = view_cls()
    view.setup(RequestFactory().get("/", params))
    return view.get_context_data()


# --------------------------------------------------------------------------- #
# ActivitiesView
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
class TestActivitiesView:
    def test_summary_and_defaults(self):
        make_activity(1, "Run", distance=10000, moving_time=3600, elevation=100)
        make_activity(2, "Ride", distance=40000, moving_time=7200, elevation=200)
        ctx = list_context(ActivitiesView)
        assert ctx["active_page"] == "activities"
        assert ctx["summary"]["count"] == 2
        assert ctx["summary"]["distance_km"] == 50
        assert ctx["summary"]["elevation_m"] == 300
        assert ctx["summary"]["time_h"] == 3   # (3600+7200)/3600
        # default filter values
        assert ctx["sport"] == "all"
        assert ctx["view"] == "grid"

    def test_sport_filter_narrows_queryset(self):
        make_activity(1, "Run")
        make_activity(2, "Ride")
        ctx = list_context(ActivitiesView, sport="Run")
        assert ctx["summary"]["count"] == 1
        assert [a.id for a in ctx["activities"]] == [1]

    def test_private_activities_excluded(self):
        make_activity(1, "Run", distance=10000)
        make_activity(2, "Run", distance=99000, is_private=True)
        ctx = list_context(ActivitiesView)
        assert [a.id for a in ctx["activities"]] == [1]
        # The private activity is also kept out of the headline summary totals.
        assert ctx["summary"]["count"] == 1
        assert ctx["summary"]["distance_km"] == 10

    def test_year_and_gear_options(self):
        g = make_gear("g1")
        make_activity(1, "Run", gear=g, start_date=dt(2025, 6, 1))
        make_activity(2, "Run", start_date=dt(2024, 5, 1))
        ctx = list_context(ActivitiesView)
        # year_options: [[year, year], …] newest first, one entry per distinct year.
        assert ctx["year_options"] == [["2025", "2025"], ["2024", "2024"]]
        # gear_options: [[id, label, type], …], only gear actually attached to an activity.
        assert ctx["gear_options"] == [[str(g.pk), str(g), g.gear_type]]

    def test_sort_by_distance(self):
        make_activity(1, distance=5000)
        make_activity(2, distance=9000)
        ctx = list_context(ActivitiesView, sort="dist", dir="desc")
        assert [a.id for a in ctx["activities"]] == [2, 1]

    def test_distance_slider_defaults(self):
        # Ceiling is the longest activity (metres → km) rounded up to the next 5 km.
        make_activity(1, distance=10000)
        make_activity(2, distance=42195)
        ctx = list_context(ActivitiesView)
        assert ctx["dist_ceil"] == 45
        assert ctx["dist_min"] == "0"
        assert ctx["dist_max"] == "45"

    def test_distance_slider_has_floor_without_data(self):
        ctx = list_context(ActivitiesView)
        assert ctx["dist_ceil"] == 5

    def test_distance_slider_narrows_queryset(self):
        make_activity(1, distance=5000)
        make_activity(2, distance=25000)
        ctx = list_context(ActivitiesView, dist_min="10", dist_max="30")
        assert [a.id for a in ctx["activities"]] == [2]

    def test_distance_ceiling_is_per_sport(self):
        make_activity(1, "Run", distance=42195)
        make_activity(2, "Swim", distance=3000)
        ceils = list_context(ActivitiesView)["dist_ceils"]
        # per-sport ceilings, rounded up to the next 5 km
        assert ceils["Run"] == 45
        assert ceils["Swim"] == 5
        # a group key expands to its members' longest
        assert ceils["group-run"] == 45
        assert ceils["group-swim"] == 5
        # 'all' spans everything
        assert ceils["all"] == 45

    def test_distance_ceiling_follows_sport_selection(self):
        make_activity(1, "Run", distance=42195)
        make_activity(2, "Swim", distance=3000)
        ctx = list_context(ActivitiesView, sport="Swim")
        # the slider rescales to the selected sport, and the max handle defaults to it
        assert ctx["dist_ceil"] == 5
        assert ctx["dist_max"] == "5"


# --------------------------------------------------------------------------- #
# GearView
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
class TestGearView:
    def test_wear_and_badges(self):
        bike = make_gear("b1", "bike", brand="Trek", primary=True)
        shoe = make_gear("s1", "shoe", brand="Nike")
        make_activity(1, "Ride", distance=6000000, gear=bike)   # 6000 km / 12000 = 50%
        make_activity(2, "Run", distance=700000, gear=shoe)     # 700 km / 700 = 100% retired
        ctx = list_context(GearView)
        by_id = {g.id: g for g in ctx["gear_list"]}
        assert by_id["b1"].wear_pct == 50
        assert by_id["b1"].badge_label == "Primary"
        assert by_id["s1"].wear_pct == 100
        assert by_id["s1"].is_retired is True
        assert by_id["s1"].badge_label == "Retired"

    def test_summary_counts(self):
        make_gear("b1", "bike")
        make_gear("s1", "shoe")
        make_gear("s2", "shoe")
        ctx = list_context(GearView)
        assert ctx["summary"]["bikes"] == 1
        assert ctx["summary"]["shoes"] == 2
        assert ctx["total_items"] == 3

    def test_type_filter(self):
        make_gear("b1", "bike")
        make_gear("s1", "shoe")
        ctx = list_context(GearView, type="bike")
        assert [g.id for g in ctx["gear_list"]] == ["b1"]

    def test_replace_soon_badge_for_worn_shoe(self):
        shoe = make_gear("s1", "shoe")
        make_activity(1, "Run", distance=560000, gear=shoe)   # 560/700 = 80% → alert
        ctx = list_context(GearView)
        g = ctx["gear_list"][0]
        assert g.wear_pct == 80
        assert g.badge_label == "Replace soon"

    def test_private_activities_not_counted_in_gear_stats(self):
        shoe = make_gear("s1", "shoe")
        make_activity(1, "Run", distance=100000, gear=shoe)                    # 100 km public
        make_activity(2, "Run", distance=600000, gear=shoe, is_private=True)   # private, ignored
        g = {x.id: x for x in list_context(GearView)["gear_list"]}["s1"]
        assert g.activity_count == 1
        assert g.distance_km == 100


# --------------------------------------------------------------------------- #
# GalleryView
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
class TestGalleryView:
    def test_only_activities_with_photos(self):
        make_activity(1, "Run", photo_url="http://x/1.jpg")
        make_activity(2, "Run", photo_url="")   # excluded
        ctx = list_context(GalleryView)
        assert ctx["count"] == 1
        assert [a.id for a in ctx["photos"]] == [1]

    def test_private_activities_excluded(self):
        make_activity(1, "Run", photo_url="http://x/1.jpg")
        make_activity(2, "Run", photo_url="http://x/2.jpg", is_private=True)   # excluded
        ctx = list_context(GalleryView)
        assert [a.id for a in ctx["photos"]] == [1]

    def test_sort_oldest(self):
        make_activity(1, photo_url="http://x/1.jpg", start_date=dt(2025, 6, 1))
        make_activity(2, photo_url="http://x/2.jpg", start_date=dt(2024, 6, 1))
        ctx = list_context(GalleryView, sort="oldest")
        assert [a.id for a in ctx["photos"]] == [2, 1]

    def test_sort_kudos(self):
        make_activity(1, photo_url="http://x/1.jpg", kudos=2)
        make_activity(2, photo_url="http://x/2.jpg", kudos=9)
        ctx = list_context(GalleryView, sort="kudos")
        assert [a.id for a in ctx["photos"]] == [2, 1]

    def test_year_filter(self):
        make_activity(1, photo_url="http://x/1.jpg", start_date=dt(2025, 6, 1))
        make_activity(2, photo_url="http://x/2.jpg", start_date=dt(2024, 6, 1))
        ctx = list_context(GalleryView, year="2025")
        assert [a.id for a in ctx["photos"]] == [1]
        assert ctx["year_list"] == [2025, 2024]


# --------------------------------------------------------------------------- #
# CompareView
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
class TestCompareView:
    def test_empty_when_no_activities(self):
        ctx = template_context(CompareView)
        assert ctx["years"] == []
        assert ctx["rows"] == []
        assert ctx["aoty_rows"] == []

    def test_contiguous_year_span(self):
        make_activity(1, "Run", start_date=dt(2023, 6, 1))
        make_activity(2, "Run", start_date=dt(2025, 6, 1))   # gap at 2024
        ctx = template_context(CompareView)
        assert [y["year"] for y in ctx["years"]] == [2023, 2024, 2025]

    def test_private_activities_excluded(self):
        make_activity(1, "Run", start_date=dt(2024, 6, 1))
        make_activity(2, "Run", start_date=dt(2025, 6, 1), is_private=True)   # excluded
        ctx = template_context(CompareView)
        # Only the public activity's season is present — no 2025 column from the private one.
        assert [y["year"] for y in ctx["years"]] == [2024]

    def test_numeric_rows_present(self):
        make_activity(1, "Run", distance=10000, elevation=100, moving_time=3600,
                      start_date=dt(2024, 6, 1), kudos=5)
        make_activity(2, "Run", distance=20000, elevation=200, moving_time=7200,
                      start_date=dt(2025, 6, 1), kudos=10)
        ctx = template_context(CompareView)
        names = {row["name"] for row in ctx["rows"]}
        assert "Distance" in names
        assert "Elevation gain" in names
        distance_row = next(r for r in ctx["rows"] if r["name"] == "Distance")
        # 2025 (20 km) is the best year → its cell is flagged best and fills the bar.
        assert distance_row["cells"][1]["best"] is True
        assert distance_row["cells"][1]["w"] == 100.0

    def test_sport_segments_only_present_groups(self):
        make_activity(1, "Run", start_date=dt(2025, 6, 1))
        ctx = template_context(CompareView)
        keys = {s["key"] for s in ctx["sport_seg"]}
        assert "all" in keys
        assert "group-run" in keys
        assert "group-swim" not in keys   # no swims in the data

    def test_effort_rows_name_standout_activity(self):
        make_activity(1, "Run", distance=15000, calories=900, name="Big One",
                      start_date=dt(2025, 6, 1))
        make_activity(2, "Run", distance=5000, calories=200, name="Small",
                      start_date=dt(2025, 7, 1))
        ctx = template_context(CompareView)
        aoty = next(r for r in ctx["aoty_rows"] if r["name"] == "Activity of the year")
        # Highest-calorie activity of 2025 is "Big One".
        assert aoty["cells"][0]["title"] == "Big One"

    def test_furthest_from_home_effort_row(self):
        # A home cluster in Košice plus one far-away outlier.
        make_activity(1, "Run", start_lat=48.720, start_lng=21.258, name="Home A",
                      start_date=dt(2025, 6, 1))
        make_activity(2, "Run", start_lat=48.721, start_lng=21.262, name="Home B",
                      start_date=dt(2025, 6, 2))
        make_activity(3, "Run", start_lat=48.210, start_lng=16.370, name="Vienna Trip",
                      start_date=dt(2025, 6, 3))
        ctx = template_context(CompareView)
        furthest = next(r for r in ctx["aoty_rows"] if r["name"] == "Furthest from home")
        assert furthest["cells"][0]["title"] == "Vienna Trip"

    def test_pace_deltas_and_ride_excluded(self):
        # Three run seasons at different paces; a ride is not paceable and is ignored.
        make_activity(1, "Run", distance=10000, moving_time=3600, start_date=dt(2023, 6, 1))  # 6:00/km
        make_activity(2, "Run", distance=10000, moving_time=3000, start_date=dt(2024, 6, 1))  # 5:00/km (faster)
        make_activity(3, "Run", distance=10000, moving_time=3300, start_date=dt(2025, 6, 1))  # 5:30/km (slower)
        make_activity(4, "Ride", distance=40000, moving_time=3600, start_date=dt(2025, 6, 2))  # excluded from pace
        ctx = template_context(CompareView)
        pace_row = next(r for r in ctx["rows"] if r["name"] == "Average pace")
        # 2024 improved on 2023 (down 60 s/km) → "up"; 2025 regressed on 2024 → "down".
        assert pace_row["cells"][1]["delta"]["dir"] == "up"
        assert pace_row["cells"][1]["delta"]["text"] == "−60s"
        assert pace_row["cells"][2]["delta"]["dir"] == "down"
        assert pace_row["cells"][2]["delta"]["text"] == "+30s"

    def test_zero_baseline_delta_shows_dash(self):
        # Year one has no PRs, year two does → the delta from 0 is shown as "—".
        make_activity(1, "Run", start_date=dt(2024, 6, 1), pr_count=0)
        make_activity(2, "Run", start_date=dt(2025, 6, 1), pr_count=3)
        ctx = template_context(CompareView)
        prs_row = next(r for r in ctx["rows"] if r["name"] == "PRs set")
        assert prs_row["cells"][1]["delta"]["text"] == "—"


# --------------------------------------------------------------------------- #
# ActivityCardView
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
class TestActivityCardView:
    def _ctx(self, pk, **params):
        view = ActivityCardView()
        view.setup(RequestFactory().get("/", params), pk=pk)
        view.object = view.get_object()
        return view.get_context_data()

    def test_default_card_flags(self):
        make_activity(7)
        ctx = self._ctx(7)
        assert ctx["show_close"] is True
        assert ctx["map_card"] is False
        assert ctx["activity"].pk == 7

    def test_map_card_flag(self):
        make_activity(7)
        ctx = self._ctx(7, map="1")
        assert ctx["map_card"] is True

    def test_private_activity_card_not_found(self):
        # A private activity must not be reachable by its PK from the map-card endpoint.
        make_activity(7, is_private=True)
        view = ActivityCardView()
        view.setup(RequestFactory().get("/"), pk=7)
        with pytest.raises(Http404):
            view.get_object()


# --------------------------------------------------------------------------- #
# htmx template selection — each view returns an hx/ fragment for htmx requests
# and the full page otherwise.
# --------------------------------------------------------------------------- #
class TestTemplateSelection:
    @pytest.mark.parametrize("view_cls,full,fragment", [
        (DashboardView, "stravakit/pages/dashboard.html", "stravakit/hx/dashboard_results.html"),
        (ActivitiesView, "stravakit/pages/activities.html", "stravakit/hx/activities_results.html"),
        (GearView, "stravakit/pages/gear.html", "stravakit/hx/gear_results.html"),
        (GalleryView, "stravakit/pages/gallery.html", "stravakit/hx/gallery_results.html"),
        (CompareView, "stravakit/pages/compare.html", "stravakit/hx/compare_body.html"),
    ])
    def test_full_vs_fragment(self, view_cls, full, fragment):
        view = view_cls()
        view.setup(RequestFactory().get("/"))
        # Non-htmx request → full page.
        assert view.get_template_names() == [full]
        # htmx request → fragment.
        view.request.htmx = True
        assert view.get_template_names() == [fragment]
