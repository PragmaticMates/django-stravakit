"""Small, pure helper functions shared across the strava app.

Generic, side-effect-free utilities — formatting, geo, string and date helpers — with no
dependency on the request cycle. Split out of analytics.py so both it and the views can
share them without pulling in the heavier analytics computations.
"""
import math
import unicodedata

from django.db.models import Max
from django.utils import timezone

from strava.consts import MIN_HIKE_PACE_SEC
from strava.sports import TOP_SPORT_TYPES


def local_date(activity):
    """The activity's start date in the active timezone (dates group by local day)."""
    return timezone.localtime(activity.start_date).date()


def has_gps(activity):
    return activity.start_lat is not None


def to_float(value):
    """Parse ``value`` to a float, returning ``None`` for blank/non-numeric input
    (e.g. an empty or malformed query-string parameter)."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def distance_slider_context(public_qs, sport, params):
    """Distance-slider context (per-sport ceilings + current window) shared by the
    activities filter bar and the dashboard map filter bar.

    ``public_qs`` is the athlete's public activities. The slider bounds are keyed by
    sport selection so switching sport rescales the track (a swim tops out far below an
    ultra): the top end is the longest activity in km, rounded up to the next 5 km with a
    small floor so the track is never degenerate. ``dist_ceils`` maps every value the
    sport dropdown can emit ('all', a group key or an exact ``sport_type``) to its
    ceiling; the client reads it to rescale the slider on sport change without a
    round-trip."""
    per_sport_m = {
        row['sport_type']: row['distance__max']
        for row in public_qs.values('sport_type').annotate(Max('distance'))
    }

    def ceil_km(metres):
        return max(5, math.ceil((metres or 0) / 1000 / 5) * 5)

    dist_ceils = {'all': ceil_km(max(per_sport_m.values(), default=0))}
    for group in TOP_SPORT_TYPES:
        dist_ceils[group['key']] = ceil_km(max((per_sport_m.get(t, 0) for t in group['types']), default=0))
    for sport_type, longest in per_sport_m.items():
        dist_ceils[sport_type] = ceil_km(longest)

    dist_ceil = dist_ceils.get(sport, dist_ceils['all'])
    return {
        'dist_ceils': dist_ceils,
        'dist_ceil': dist_ceil,
        'dist_min': params.get('dist_min', '0'),
        'dist_max': params.get('dist_max', str(dist_ceil)),
    }


def gear_year_options(public_qs, gear_qs):
    """Options for the gear + year filter pills, shared by the activities filter bar and
    the dashboard map filter bar (rendered as json_script islands the pill JS reads).

    ``gear_options`` is ``[[id, label, type], …]`` — the type ('bike'/'shoe') drives the
    Bikes/Shoes sections; ``year_options`` is ``[[year, year], …]`` newest first. Only gear
    and years actually present in the passed querysets appear."""
    return {
        'gear_options': [[str(g.pk), str(g), g.gear_type] for g in gear_qs],
        'year_options': [[str(d.year), str(d.year)]
                         for d in public_qs.dates('start_date', 'year', order='DESC')],
    }


def unaccent(s):
    """Lowercase and strip diacritics — the server-side twin of the map filter's JS
    ``unaccent()`` so a filtered search here matches what the map shows."""
    normalized = unicodedata.normalize('NFD', s or '')
    return ''.join(c for c in normalized if not unicodedata.combining(c)).lower()


def fmt_pace(seconds):
    """Seconds-per-unit formatted as m:ss (a per-km or per-100m pace)."""
    m, s = divmod(int(round(seconds)), 60)
    return f'{m}:{s:02d}'


def fmt_hms(seconds):
    """Seconds as h:mm:ss, dropping the hours part when under an hour (m:ss)."""
    total = int(round(seconds))
    h, r = divmod(total, 3600)
    m, s = divmod(r, 60)
    return f'{h}:{m:02d}:{s:02d}' if h else f'{m}:{s:02d}'


def haversine_km(lat1, lng1, lat2, lng2):
    """Great-circle distance between two lat/lng points, in kilometres."""
    radius = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def home_location(activities):
    """Estimate "home" as the busiest start location. Start points are bucketed on a
    ~1 km grid (2-decimal rounding); the most-used bucket's averaged coordinates are
    returned as ``(lat, lng)``, or ``None`` when no activity has GPS."""
    clusters = {}
    for a in activities:
        if a.start_lat is None or a.start_lng is None:
            continue
        key = (round(a.start_lat, 2), round(a.start_lng, 2))
        agg = clusters.setdefault(key, [0, 0.0, 0.0])
        agg[0] += 1
        agg[1] += a.start_lat
        agg[2] += a.start_lng
    if not clusters:
        return None
    count, lat_sum, lng_sum = max(clusters.values(), key=lambda agg: agg[0])
    return lat_sum / count, lng_sum / count


def hike_pace_ok(a):
    """A genuine hike isn't faster than MIN_HIKE_PACE_SEC per km. Activities with no pace
    data (missing time/distance) are kept — there's nothing to disqualify on."""
    if not a.moving_time or not a.distance:
        return True
    return a.moving_time / (a.distance / 1000) >= MIN_HIKE_PACE_SEC
