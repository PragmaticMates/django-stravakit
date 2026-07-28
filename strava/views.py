import logging
import secrets

from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.contrib.auth.mixins import UserPassesTestMixin
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.db.models import Count, F, Max, Q, Sum
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.generic import DetailView, ListView, TemplateView

from strava import helpers, services
from strava.api import StravaApi, _from_epoch, format_strava_error
from strava.models import Activity, Athlete, Gear
from strava.sports import TOP_SPORT_TYPES, group_data, sport_matches, sport_options


logger = logging.getLogger('strava')


class AthleteScopedMixin:
    """Resolve the athlete for the request (``?athlete=<id>`` or the default) and expose it
    to the view's querysets (``self.athlete``) and template context (``athlete`` /
    ``athlete_id`` / ``athletes``, the last driving the nav switcher). Resolved lazily off
    ``self.request`` so it works whether the view runs through the full lifecycle or has its
    methods called directly (as in unit tests)."""

    @property
    def athlete(self):
        if not hasattr(self, '_athlete'):
            self._athlete = Athlete.selected(self.request)
        return self._athlete

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['athlete'] = self.athlete
        context['athlete_id'] = self.athlete.pk if self.athlete else ''
        context['athletes'] = Athlete.objects.all()
        return context


class DashboardView(AthleteScopedMixin, TemplateView):
    template_name = 'strava/pages/dashboard.html'

    def get_template_names(self):
        # An htmx request comes from the map filter controls (search + sport/gear/year
        # pills); it only needs the recomputed sections, swapped in via hx-swap-oob.
        if getattr(self.request, 'htmx', False):
            return ['strava/hx/dashboard_results.html']
        return [self.template_name]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['active_page'] = 'dashboard'

        all_activities = list(
            Activity.objects.for_athlete(self.athlete).public().select_related('gear').order_by('-start_date')
        )
        today = timezone.localdate()

        # ---- Filters (mirror the map's client-side search + sport/gear/year pills) ----
        # The map filters its markers in JS; the same filter state is posted here so every
        # section below recomputes over the matching activities. Non-GPS activities (pool
        # swims, treadmill runs) carry no marker but are still counted in the stats.
        params = self.request.GET
        q = (params.get('q') or '').strip()
        sport = params.get('sport') or 'all'
        gear = params.get('gear') or 'all'
        year = params.get('year') or 'all'
        context['q'], context['sport'], context['gear'], context['year'] = q, sport, gear, year

        # Sport / gear / year filter dropdowns: options come from every activity in the
        # data (not just GPS-mapped ones) so a GPS-less sport/gear/year still appears — the
        # map filters markers in JS but the stats sync recomputes over all of them.
        public_qs = Activity.objects.for_athlete(self.athlete).public()
        context['sport_options'] = sport_options(public_qs)
        context['sport_groups'] = group_data()
        gear_qs = (
            Gear.objects.for_athlete(self.athlete)
            .filter(activity__is_private=False).distinct().order_by('brand_name', 'model_name')
        )
        context.update(helpers.gear_year_options(public_qs, gear_qs))

        # Distance slider bounds (shared with the activities filter bar); the map filters
        # markers client-side against dist_min/dist_max, mirrored here so every section
        # recomputes over the same distance window.
        context.update(helpers.distance_slider_context(public_qs, sport, params))
        dist_min, dist_max = context['dist_min'], context['dist_max']

        activities = services.dashboard.filter_activities(all_activities, q, sport, gear, year, dist_min, dist_max)

        # ---- Totals + latest activities for the active filter ----
        context['stat'] = services.dashboard.totals(activities)
        context['latest_activity'] = activities[0] if activities else None
        context['latest_activities'] = activities[:4]

        # ---- Activity map markers (from each activity's start_latlng) ----
        # Built from every activity (the map filters them in JS); map_hidden_count counts
        # only the filtered activities without GPS so it tracks what the map displays.
        context['map_markers'], context['map_activities'] = services.analytics.map_data(all_activities)
        context['map_hidden_count'] = sum(1 for a in activities if not helpers.has_gps(a))

        context['aoty'] = services.dashboard.activity_of_year(activities, year, today)

        # ---- Personal records + running performance ----
        # Scoped by the year filter only (the widgets have their own sport tabs, which the
        # sport/gear/search filters would otherwise empty). Home is the most-used start
        # location across all activities, stable across the year filter.
        records_acts = [a for a in all_activities
                        if year == 'all' or str(helpers.local_date(a).year) == year]
        home = helpers.home_location(all_activities)
        context['records'] = services.analytics.records(records_acts, home)
        context['run_perf'] = services.analytics.run_performance(records_acts)

        # ---- Trends (weekly / monthly / yearly) + activity calendar ----
        context['trends'] = services.analytics.trends(activities, today)
        context['calendar'] = services.analytics.activity_calendar(activities, today)

        # ---- Gear health table + usage donut ----
        no_filter = not q and sport == 'all' and gear == 'all' and year == 'all'
        context['gear_health'], context['gear_usage'] = services.gear.dashboard_sections(activities, no_filter)

        # ---- "By the Numbers" — fun stats + summary, over the filtered activities ----
        context['fun_stats'], context['summary'] = services.analytics.by_the_numbers(activities)
        # The real time import_strava last refreshed this athlete (not "now").
        context['last_updated'] = self.athlete.synced_at if self.athlete else None
        return context


class RefreshView(UserPassesTestMixin, DashboardView):
    """Footer refresh button (POST): run the ``import_strava`` management command to
    pull the latest activities from the Strava API, then re-render every dashboard
    section as out-of-band swaps (plus the footer timestamp) so the page updates in
    place. GET is not allowed — the button always posts.

    Restricted to logged-in superusers (the button is hidden for everyone else, and
    this guards the endpoint against direct requests) — importing hits the Strava API
    and writes to the database, so it isn't a public action."""

    raise_exception = True  # 403 for non-superusers instead of a login redirect
    http_method_names = ['post']

    def test_func(self):
        return self.request.user.is_superuser
    template_name = 'strava/hx/dashboard_refresh.html'
    error_template_name = 'strava/hx/dashboard_refresh_error.html'

    def get_template_names(self):
        return [self.template_name]

    def post(self, request, *args, **kwargs):
        try:
            call_command('import_strava')
        except Exception as error:
            # The Strava API can reject the import (inactive app, expired token, rate
            # limit, outage). Surface the reason in the footer instead of a 500 that
            # would leave the button spinning with no feedback.
            logger.exception('Strava import from the dashboard refresh button failed')
            return render(request, self.error_template_name, {'error': format_strava_error(error)})
        context = self.get_context_data()
        return self.render_to_response(context)


class ActivitiesView(AthleteScopedMixin, ListView):
    model = Activity
    template_name = 'strava/pages/activities.html'
    context_object_name = 'activities'

    def get_template_names(self):
        if getattr(self.request, 'htmx', False):
            return ['strava/hx/activities_results.html']
        return [self.template_name]

    def get_queryset(self):
        params = self.request.GET
        return (
            Activity.objects.for_athlete(self.athlete)
            .public()
            .select_related('gear')
            .search(params.get('q'))
            .for_sport_selection(params.get('sport'))
            .for_gear(params.get('gear'))
            .for_year(params.get('year'))
            .for_distance(params.get('dist_min'), params.get('dist_max'))
            .sorted_by(params.get('sort'), params.get('dir', 'desc'))
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['active_page'] = 'activities'

        params = self.request.GET
        context['q'] = params.get('q', '')
        context['sport'] = params.get('sport', 'all')
        context['gear'] = params.get('gear', 'all')
        context['year'] = params.get('year', 'all')
        context['sort'] = params.get('sort', '')
        context['dir'] = params.get('dir', 'desc')
        context['view'] = params.get('view', 'grid')

        # Sport / gear / year filter pills — the same reusable controls (and option
        # sources) as the dashboard map filter bar.
        public_qs = Activity.objects.for_athlete(self.athlete).public()
        context['sport_options'] = sport_options(public_qs)
        context['sport_groups'] = group_data()
        gear_qs = (
            Gear.objects.for_athlete(self.athlete)
            .filter(activity__is_private=False).distinct().order_by('brand_name', 'model_name')
        )
        context.update(helpers.gear_year_options(public_qs, gear_qs))
        context.update(helpers.distance_slider_context(public_qs, context['sport'], params))
        context['summary'] = services.activities.summary(self.object_list, timezone.now().date())
        return context


class GearView(AthleteScopedMixin, ListView):
    model = Gear
    template_name = 'strava/pages/gear.html'
    context_object_name = 'gear_list'

    def get_template_names(self):
        if getattr(self.request, 'htmx', False):
            return ['strava/hx/gear_results.html']
        return [self.template_name]

    def get_queryset(self):
        params = self.request.GET
        return (
            Gear.objects.for_athlete(self.athlete)
            .annotate(
                # Gear stats are public-facing, so private activities don't count toward
                # a gear's ride count, mileage or last-used date.
                activity_count=Count('activity', filter=Q(activity__is_private=False)),
                distance_sum=Sum('activity__distance', filter=Q(activity__is_private=False)),
                last_activity=Max('activity__start_date', filter=Q(activity__is_private=False)),
            )
            .search(params.get('q'))
            .of_type(params.get('type'))
            .by_age(params.get('age'))
            .sorted_by(params.get('sort'), params.get('dir', 'asc'))
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['active_page'] = 'gear'

        params = self.request.GET
        context['q'] = params.get('q', '')
        context['type'] = params.get('type', 'all')
        context['age'] = params.get('age', 'all')
        context['sort'] = params.get('sort', '')
        context['dir'] = params.get('dir', 'asc')

        gear_list, bikes, shoes, summary = services.gear.page(list(context['gear_list']))
        context['gear_list'] = gear_list
        context['bikes'] = bikes
        context['shoes'] = shoes
        context['total_items'] = len(gear_list)
        context['summary'] = summary
        return context


class GalleryView(AthleteScopedMixin, ListView):
    model = Activity
    template_name = 'strava/pages/gallery.html'
    context_object_name = 'photos'

    def get_template_names(self):
        if getattr(self.request, 'htmx', False):
            return ['strava/hx/gallery_results.html']
        return [self.template_name]

    def get_queryset(self):
        params = self.request.GET
        # A gallery item is an activity with a primary photo; filter that in SQL.
        qs = (
            Activity.objects.for_athlete(self.athlete)
            .public()
            .exclude(photo_url='')
            .search(params.get('q'))
            .for_sport_selection(params.get('sport'))
            .for_year(params.get('year'))
        )
        sort = params.get('sort', 'newest')
        if sort == 'oldest':
            return qs.order_by('start_date')
        if sort == 'kudos':
            return qs.order_by(F('kudos_count').desc(nulls_last=True), '-start_date')
        return qs.order_by('-start_date')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['active_page'] = 'gallery'

        params = self.request.GET
        context['q'] = params.get('q', '')
        context['sport'] = params.get('sport', 'all')
        context['year'] = params.get('year', 'all')
        context['sort'] = params.get('sort', 'newest')

        # Photo presence is now filtered in the queryset (photo_url), so the list is ready.
        photos = list(context['photos'])
        context['photos'] = photos
        context['count'] = len(photos)
        scoped = Activity.objects.for_athlete(self.athlete).public()
        context['year_list'] = [d.year for d in scoped.dates('start_date', 'year', order='DESC')]
        context['sport_options'] = sport_options(scoped.exclude(photo_url=''))
        context['sport_groups'] = group_data()
        return context


class CompareView(AthleteScopedMixin, TemplateView):
    """Year-over-year comparison matrix: one metric per row, one season per column.

    Each numeric row is scaled into a bar (relative to the row's best year) and
    carries a year-on-year delta; the best year gets a crown, the current year is
    highlighted. A trailing block of "signature effort" rows names the standout
    activity per year (activity of the year, longest, biggest climb, …). The single
    control is a sport filter, wired via htmx to re-render just the matrix body."""

    template_name = 'strava/pages/compare.html'

    def get_template_names(self):
        # A sport-filter click posts here via htmx; it only needs the matrix body
        # (filter bar + table), swapped into #cmp-body.
        if getattr(self.request, 'htmx', False):
            return ['strava/hx/compare_body.html']
        return [self.template_name]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['active_page'] = 'compare'

        sport = self.request.GET.get('sport') or 'all'
        context['sport'] = sport

        all_activities = list(Activity.objects.for_athlete(self.athlete).public().select_related('gear'))
        activities = [a for a in all_activities if sport_matches(sport, a.sport_type)]

        # Sport filter: "All sports" plus the top-sport groups actually present in the
        # data (an empty group would filter to nothing, so it's hidden).
        present = {a.sport_type for a in all_activities}
        seg = [{'key': 'all', 'label': 'All sports', 'icon': 'all', 'active': sport == 'all'}]
        for group in TOP_SPORT_TYPES:
            if present.intersection(group['types']):
                seg.append({'key': group['key'], 'label': str(group['label']),
                            'icon': group['icon'], 'active': sport == group['key']})
        context['sport_seg'] = seg

        home = helpers.home_location(all_activities)
        context.update(services.compare.compare_matrix(activities, home, timezone.localdate()))
        return context


class ActivityCardView(DetailView):
    """Render a single activity's float card, fetched lazily when its map marker is
    clicked. Keeps the dashboard from server-rendering a card for every marker up
    front (which dominated page load once the marker cap was raised)."""
    model = Activity
    template_name = 'strava/widgets/activity.html'
    context_object_name = 'activity'

    def get_queryset(self):
        # Not athlete-scoped: cards are fetched by PK from JS (which doesn't carry the
        # selected athlete), and every athlete here is owner-curated public data anyway.
        # Still public()-filtered so a private activity can't be surfaced by its PK.
        return Activity.objects.public().select_related('gear')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['show_close'] = True  # card is shown standalone (visible, with a close button)
        # Cards opened from a map marker (?map=1) drop the redundant route trace — the
        # route is already drawn on the map behind the card — and show a full-bleed photo.
        context['map_card'] = self.request.GET.get('map') == '1'
        return context


@user_passes_test(lambda u: u.is_superuser)
def oauth_connect(request):
    """Kick off the Strava OAuth flow to connect (or reconnect) an athlete. Superuser-only —
    connecting an athlete grants this site API access to their account. Stores a random
    ``state`` in the session so the callback can reject forged/replayed redirects."""
    state = secrets.token_urlsafe(24)
    request.session['strava_oauth_state'] = state
    redirect_uri = request.build_absolute_uri(reverse('strava:oauth_callback'))
    return redirect(StravaApi().authorization_url(redirect_uri, state))


@user_passes_test(lambda u: u.is_superuser)
def oauth_callback(request):
    """Strava redirects here after the owner authorizes (or cancels). Verifies ``state``,
    exchanges the code for tokens, stores the athlete and their tokens, and marks the first
    connected athlete as the default."""
    if request.GET.get('error'):
        messages.error(request, _("Strava connection cancelled."))
        return redirect('admin:strava_athlete_changelist')

    # Reject a missing/blank stored state too: without this an attacker-forged callback in a
    # session that never started the flow would pass the check (None == None).
    expected_state = request.session.pop('strava_oauth_state', None)
    if not expected_state or request.GET.get('state') != expected_state:
        return HttpResponseBadRequest("Invalid OAuth state")

    api = StravaApi()
    try:
        info = api.exchange_code_for_token(request.GET['code'])
        api.client.access_token = info['access_token']
        athlete = Athlete.store(api.get_athlete())
    except Exception as error:
        logger.exception("Strava OAuth token exchange failed")
        messages.error(request, _("Connecting to Strava failed — %(error)s")
                       % {"error": format_strava_error(error)})
        return redirect('admin:strava_athlete_changelist')

    athlete.access_token = info['access_token']
    athlete.refresh_token = info['refresh_token']
    athlete.token_expires_at = _from_epoch(info['expires_at'])
    athlete.scope = request.GET.get('scope', '')
    # Become the default only if none exists. Guard the check-then-set against the partial
    # unique constraint: if a concurrent connect wins the race, keep this athlete's tokens
    # but not the default flag rather than 500 on IntegrityError.
    try:
        with transaction.atomic():
            if not Athlete.objects.filter(is_default=True).exclude(pk=athlete.pk).exists():
                athlete.is_default = True
            athlete.save()
    except IntegrityError:
        athlete.is_default = False
        athlete.save()
    messages.success(request, _("Connected %(athlete)s.") % {"athlete": athlete})
    return redirect('admin:strava_athlete_change', athlete.pk)
