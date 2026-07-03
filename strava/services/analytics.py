"""Pure analytics over collections of ``Activity`` objects.

Everything here is framework-light, side-effect-free, and independent of the request
cycle: it takes activities (usually an already-filtered list) and returns plain
dicts/lists ready for a template context. Keeping the arithmetic out of the views makes
it unit-testable directly and lets the dashboard and compare pages share one
implementation instead of reaching into each other's view classes.
"""
import datetime

from django.utils import timezone

from strava.consts import (
    CO2_KG_PER_KM, EARTH_CIRCUMFERENCE_KM, EVEREST_HEIGHT_M, MAP_MARKER_LIMIT,
    MARATHON_KM, MAX_RIDE_AVG_KMH, MAX_RIDE_TOP_KMH, MONTHS,
    RIEGEL_EXP, RIEGEL_MAX_RATIO, RUN_PERF_DISTANCES,
)
from strava.helpers import fmt_hms, fmt_pace, has_gps, haversine_km, hike_pace_ok, local_date
from strava.sports import RECORDS_SPORT_TYPES


# --------------------------------------------------------------------------- #
# Personal records
# --------------------------------------------------------------------------- #
def _rec(label, activity, value, unit):
    return {'label': label, 'value': value, 'unit': unit, 'id': activity.pk}


def records(activities, home=None):
    """Personal records grouped by the four sport tabs (Running / Cycling / Hiking /
    Swimming). Returns ``{tab: [record, ...]}`` where each record is a
    ``{'label', 'value', 'unit', 'id'}`` dict — ``id`` is the pk of the activity that
    holds the record, so clicking the row opens that activity's card. ``home`` is the
    (lat, lng) the "furthest from home" record measures against."""
    return {
        name: _sport_records(name, [a for a in activities if a.sport_type in sports], home)
        for name, sports in RECORDS_SPORT_TYPES.items()
    }


def _sport_records(name, acts, home=None):
    if not acts:
        return []
    recs = []

    # Longest distance. For hiking, ignore run-paced activities (likely mis-tagged).
    longest_pool = [a for a in acts if hike_pace_ok(a)] if name == 'Hiking' else acts
    if longest_pool:
        longest = max(longest_pool, key=lambda a: a.distance)
        recs.append(_rec('Longest', longest, f'{longest.distance / 1000:.1f}', 'km'))

    # Fastest — avg speed for rides, per-100m for swims, avg pace otherwise. Derived from
    # distance/time (like Activity.pace_parts) to avoid relying on the raw API speed
    # units. Hiking again drops run-paced activities.
    moving = [a for a in acts if a.moving_time and a.distance]
    if name == 'Hiking':
        moving = [a for a in moving if hike_pace_ok(a)]
    if name == 'Cycling':
        # Drop rides whose average speed exceeds MAX_RIDE_AVG_KMH — GPS glitches or
        # mis-tagged motorized activities, not real cycling PRs.
        rides = [a for a in moving
                 if (a.distance / 1000) / (a.moving_time / 3600) <= MAX_RIDE_AVG_KMH]
        if rides:
            best = max(rides, key=lambda a: a.distance / a.moving_time)
            kmh = (best.distance / 1000) / (best.moving_time / 3600)
            recs.append(_rec('Fastest (avg. speed)', best, f'{kmh:.1f}', 'km/h'))
    elif name == 'Swimming':
        if moving:
            best = min(moving, key=lambda a: a.moving_time / (a.distance / 100))
            recs.append(_rec('Fastest (per 100 m)', best,
                             fmt_pace(best.moving_time / (best.distance / 100)), '/100m'))
    else:
        if moving:
            best = min(moving, key=lambda a: a.moving_time / (a.distance / 1000))
            recs.append(_rec('Fastest (avg. pace)', best,
                             fmt_pace(best.moving_time / (best.distance / 1000)), '/km'))

    # Most elevation (not meaningful for swimming)
    if name != 'Swimming':
        climbs = [a for a in acts if a.total_elevation_gain]
        if climbs:
            best = max(climbs, key=lambda a: a.total_elevation_gain)
            recs.append(_rec('Most Elevation', best, f'{best.total_elevation_gain:,.0f}', 'm'))

    # Top speed only for cycling (descents legitimately hit 50–70 km/h). For other sports
    # the GPS max_speed is dominated by noisy spikes — a single bad fix on a slow run
    # reads as 50+ km/h — so show the reliable longest moving time instead.
    if name == 'Cycling':
        speeds = [a for a in acts if a.max_speed and a.max_speed * 3.6 <= MAX_RIDE_TOP_KMH]
        if speeds:
            best = max(speeds, key=lambda a: a.max_speed)
            recs.append(_rec('Top Speed', best, f'{best.max_speed * 3.6:.1f}', 'km/h'))
    else:
        timed = [a for a in acts if a.moving_time]
        if timed:
            best = max(timed, key=lambda a: a.moving_time)
            recs.append(_rec('Longest Time', best, best.duration, ''))

    # Furthest from home — the activity starting farthest from the usual start point.
    if home:
        located = [a for a in acts if a.start_lat is not None and a.start_lng is not None]
        if located:
            best = max(located, key=lambda a: haversine_km(
                home[0], home[1], a.start_lat, a.start_lng))
            dist = haversine_km(home[0], home[1], best.start_lat, best.start_lng)
            recs.append(_rec('Furthest from Home', best, f'{dist:,.0f}', 'km'))

    return recs


# --------------------------------------------------------------------------- #
# Running performance (best efforts + Riegel projection)
# --------------------------------------------------------------------------- #
def run_performance(activities):
    """Per-distance running performance from Strava ``best_efforts``.

    Returns a row per RUN_PERF_DISTANCES with the actual best time at that distance (and
    the activity that set it, for the click-to-open card) plus a Riegel estimate range
    projected from the athlete's best efforts at every recorded distance. Best/estimate
    are ``'—'`` when there's nothing to compute."""
    runs = [a for a in activities if a.sport_type in RECORDS_SPORT_TYPES['Running']]

    best_by_name = {}   # lowercased effort name -> (elapsed_seconds, activity_pk)
    predictors = {}     # effort distance (m) -> fastest elapsed_seconds seen
    for a in runs:
        for e in a.best_efforts:
            t, d = e.get('elapsed_time'), e.get('distance')
            if not isinstance(t, (int, float)) or not t or not d:
                continue
            name = (e.get('name') or '').lower()
            if name not in best_by_name or t < best_by_name[name][0]:
                best_by_name[name] = (t, a.pk)
            if d not in predictors or t < predictors[d]:
                predictors[d] = t

    perf = []
    for label, key, dist in RUN_PERF_DISTANCES:
        row = {'dist': label, 'best': '—', 'best_id': None, 'est': '—', 'est_pace': '—'}
        if key in best_by_name:
            t, pk = best_by_name[key]
            row['best'], row['best_id'] = fmt_hms(t), pk
        # Only project from predictors within a sensible extrapolation window;
        # short splits (e.g. a 1 km burst) would otherwise yield unrealistically
        # fast long-distance estimates.
        projections = [pt * (dist / pd) ** RIEGEL_EXP
                       for pd, pt in predictors.items()
                       if 1 / RIEGEL_MAX_RATIO <= dist / pd <= RIEGEL_MAX_RATIO]
        if projections:
            est = min(projections)
            row['est'] = f'{fmt_hms(est * 0.975)} – {fmt_hms(est * 1.025)}'
            row['est_pace'] = f'{fmt_pace(est / (dist / 1000))}/km'
        perf.append(row)
    return perf


# --------------------------------------------------------------------------- #
# "By the Numbers"
# --------------------------------------------------------------------------- #
def by_the_numbers(activities):
    """Fun-stat and summary tallies for the "By the Numbers" cards. Returns
    ``(fun_stats, summary)`` dicts. Calories / achievements / PR counts come from promoted
    model fields, computed over whatever (already-filtered) activities are passed in."""
    total_km = sum(a.distance for a in activities) / 1000
    total_elev = sum((a.total_elevation_gain or 0) for a in activities)
    cycling_km = sum(a.distance for a in activities
                     if a.sport_type in RECORDS_SPORT_TYPES['Cycling']) / 1000

    # Heart rate averaged across activities, weighted by moving time.
    hr = [a for a in activities if a.average_heartrate and a.moving_time]
    avg_hr = (round(sum(a.average_heartrate * a.moving_time for a in hr)
                    / sum(a.moving_time for a in hr)) if hr else 0)

    fun_stats = {
        'around_earth': f'{total_km / EARTH_CIRCUMFERENCE_KM * 100:.1f}%',
        'everest': f'{total_elev / EVEREST_HEIGHT_M:.1f}x',
        'co2_saved': f'{round(cycling_km * CO2_KG_PER_KM):,} kg',
        'marathons': f'{round(total_km / MARATHON_KM):,}',
    }
    summary = {
        'photos': sum(a.total_photo_count for a in activities),
        'calories': sum((a.calories or 0) for a in activities),
        'kudos': sum(a.kudos_count for a in activities),
        'avg_hr': avg_hr,
        'achievements': sum(a.achievement_count for a in activities),
        'prs': sum(a.pr_count for a in activities),
    }
    return fun_stats, summary


# --------------------------------------------------------------------------- #
# Trends + activity calendar
# --------------------------------------------------------------------------- #
def trends(activities, today):
    """Weekly / monthly / yearly rollups (distance, elevation, hours, activity count and
    distance-weighted pace) as ``{'weekly': [...], 'monthly': [...], 'yearly': [...]}``.
    Weekly is capped to the last 52 weeks; the current year is flagged ``partial``."""

    weekly, monthly, yearly = {}, {}, {}
    for a in activities:
        d = local_date(a)
        km = a.distance / 1000
        elev = a.total_elevation_gain or 0
        secs = a.moving_time or 0
        wk = d - datetime.timedelta(days=d.weekday())
        for buckets, key in ((weekly, wk), (monthly, (d.year, d.month)), (yearly, d.year)):
            b = buckets.setdefault(key, {'km': 0.0, 'elev': 0.0, 'secs': 0.0, 'acts': 0})
            b['km'] += km
            b['elev'] += elev
            b['secs'] += secs
            b['acts'] += 1

    zero = {'km': 0.0, 'elev': 0.0, 'secs': 0.0, 'acts': 0}

    def week_keys(buckets):
        if not buckets:
            return []
        ks = sorted(buckets)
        d, hi, out = ks[0], ks[-1], []
        while d <= hi:
            out.append(d)
            d += datetime.timedelta(days=7)
        return out

    def month_keys(buckets):
        if not buckets:
            return []
        ks = sorted(buckets)
        (y, m), (hy, hm) = ks[0], ks[-1]
        out = []
        while (y, m) <= (hy, hm):
            out.append((y, m))
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        return out

    def year_keys(buckets):
        if not buckets:
            return []
        ks = sorted(buckets)
        return list(range(ks[0], ks[-1] + 1))

    def rows(keys, buckets, label, partial=None):
        out = []
        for key in keys:
            b = buckets.get(key, zero)
            out.append({
                'label': label(key),
                'km': round(b['km']),
                'elev': round(b['elev']),
                'hours': round(b['secs'] / 3600, 1),
                'acts': b['acts'],
                'pace': round((b['secs'] / 60) / b['km'], 2) if b['km'] else 0,
                **({'partial': True} if partial and partial(key) else {}),
            })
        return out

    return {
        'weekly': rows(week_keys(weekly), weekly, lambda k: f'{MONTHS[k.month - 1]} {k.day}')[-52:],
        'monthly': rows(month_keys(monthly), monthly, lambda k: f"{MONTHS[k[1] - 1]} '{str(k[0])[2:]}"),
        'yearly': rows(year_keys(yearly), yearly, str, partial=lambda y: y == today.year),
    }


def activity_calendar(activities, today):
    """Every week from the earliest activity through the current week as
    ``[{'label', 'dots': [0|1|2, ...7]}, ...]`` — a dot per day at intensity 0/1/2
    (no activity / one / two-or-more), for the dashboard heat strip. The dashboard
    renders a five-week window and pages back/forward through the full range."""

    day_counts = {}
    for a in activities:
        d = local_date(a)
        day_counts[d] = day_counts.get(d, 0) + 1

    this_week = today - datetime.timedelta(days=today.weekday())
    if day_counts:
        first = min(day_counts)
        ws = first - datetime.timedelta(days=first.weekday())
    else:
        # No activities: still show the trailing five weeks so the strip isn't blank.
        ws = this_week - datetime.timedelta(weeks=4)

    weeks = []
    while ws <= this_week:
        we = ws + datetime.timedelta(days=6)
        dots = []
        for i in range(7):
            c = day_counts.get(ws + datetime.timedelta(days=i), 0)
            dots.append(2 if c >= 2 else 1 if c == 1 else 0)
        end = f'{we.day}' if we.month == ws.month else f'{MONTHS[we.month - 1]} {we.day}'
        weeks.append({'label': f'{MONTHS[ws.month - 1]} {ws.day} – {end}', 'dots': dots})
        ws += datetime.timedelta(weeks=1)
    return weeks


# --------------------------------------------------------------------------- #
# Map markers
# --------------------------------------------------------------------------- #
def map_data(activities):
    """Collect map markers and their activities from ``start_latlng``.

    Returns ``(markers, map_activities)`` where ``markers`` is a list of marker dicts the
    Leaflet map plots (the encoded ``polyline`` is drawn as the route when a marker is
    clicked; ``sport_type``/``gear``/``year`` back the filter pills; ``id`` lazily fetches
    the activity's card), and ``map_activities`` are the matching ``Activity`` objects in
    the same order. Both are capped at ``MAP_MARKER_LIMIT``. GPS-less activities (pool
    swims, treadmill runs, …) carry no marker."""
    markers, map_activities = [], []
    for a in activities:
        if has_gps(a):
            markers.append({
                'id': a.pk,  # for lazily fetching the activity's card on marker click
                'lat': a.start_lat,
                'lng': a.start_lng,
                'map_sport_type': a.map_sport_type,
                'distance': a.distance_km,  # km, for the distance range filter
                'title': f'{a.name} · {a.distance_km} km',
                'polyline': a.polyline,
                'sport_type': a.sport_type,
                'sport_label': a.get_sport_type_display(),
                'gear': str(a.gear_id) if a.gear_id else '',
                'year': timezone.localtime(a.start_date).year,
            })
            map_activities.append(a)
        if len(markers) >= MAP_MARKER_LIMIT:
            break
    return markers, map_activities
