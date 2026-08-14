"""Dashboard-page computation: filtering the activity set and the headline aggregates.

Mirrors the map's client-side search + sport/gear/year filters server-side so every
dashboard section recomputes over the same matching activities.
"""
from stravakit import helpers
from stravakit.sports import sport_matches


def filter_activities(all_activities, q, sport, gear, year, dist_min=None, dist_max=None):
    """The activities matching the dashboard filter state (search text, sport group, gear,
    year, distance window). Non-GPS activities (pool swims, treadmill runs) carry no marker
    but still count. The distance bounds arrive in kilometres (the slider's unit) and are
    compared against the metres stored on the row; a blank/non-numeric bound is ignored."""
    tokens = helpers.unaccent(q).split()
    lower = helpers.to_float(dist_min)
    upper = helpers.to_float(dist_max)

    def matches(a):
        haystack = helpers.unaccent(f'{a.name} {a.map_sport_type}')
        return (
            all(t in haystack for t in tokens)
            and sport_matches(sport, a.sport_type)
            and (gear == 'all' or str(a.gear_id or '') == gear)
            and (year == 'all' or str(helpers.local_date(a).year) == year)
            and (lower is None or a.distance >= lower * 1000)
            and (upper is None or a.distance <= upper * 1000)
        )

    return [a for a in all_activities if matches(a)]


def totals(activities):
    """Headline totals for the active filter."""
    total_secs = sum((a.moving_time or 0) for a in activities)
    return {
        'distance_km': round(sum(a.distance for a in activities) / 1000),
        'elev': round(sum((a.total_elevation_gain or 0) for a in activities)),
        'time_h': int(total_secs // 3600),
        'time_m': int(total_secs % 3600 // 60),
        'activities': len(activities),
        'active_days': len({helpers.local_date(a) for a in activities}),
    }


def activity_of_year(activities, year, today):
    """The biggest effort of the selected season (else overall). Ranked by calories (a
    cross-sport effort proxy) rather than distance, which isn't comparable across sports;
    summary-only activities have no calories and count as 0."""
    season_year = int(year) if year != 'all' and year.isdigit() else today.year
    year_acts = [a for a in activities if helpers.local_date(a).year == season_year]
    pool = year_acts or activities
    return max(pool, key=lambda a: a.calories or 0) if pool else None
