"""Year-over-year comparison matrix computation.

Pure functions over a list of ``Activity`` objects: given the activities for a sport
selection, build the numeric metric rows (one per row, one season per column) and the
signature-effort rows. Kept out of the view so the arithmetic is unit-testable and the
view stays a thin orchestrator.
"""
from strava import helpers
from strava.consts import MONTHS
from strava.sports import PACE_SPORT_TYPES

# Paces faster than this (seconds per km) are GPS/distance glitches — a corrupt near-zero
# distance or time reads as an impossibly quick pace — not real efforts; 2:30/km is already
# quicker than an elite 10k, so anything below is dropped.
MIN_PLAUSIBLE_PACE_SEC = 150


def paceable(a):
    """A foot sport (PACE_SPORT_TYPES) with a plausible /km pace (see MIN_PLAUSIBLE_PACE_SEC)."""
    if a.sport_type not in PACE_SPORT_TYPES or not a.moving_time or not a.distance:
        return False
    return a.moving_time / (a.distance / 1000) >= MIN_PLAUSIBLE_PACE_SEC


def compare_matrix(activities, home, today):
    """Build the comparison matrix for ``activities``.

    Returns ``{'years': [...], 'rows': [...], 'aoty_rows': [...]}`` — the season columns,
    the numeric metric rows, and the signature-effort rows. All empty when there's no data.
    """
    by_year = {}
    for a in activities:
        by_year.setdefault(helpers.local_date(a).year, []).append(a)

    if not by_year:
        return {'years': [], 'rows': [], 'aoty_rows': []}

    # Contiguous span so every season sits side by side, even a gap year.
    years = list(range(min(by_year), max(by_year) + 1))
    year_cols = [
        {'year': y, 'current': y == today.year,
         'tag': (f'through {MONTHS[today.month - 1]} {today.day}'
                 if y == today.year else 'full season')}
        for y in years
    ]
    return {
        'years': year_cols,
        'rows': _numeric_rows(years, by_year, today),
        'aoty_rows': _effort_rows(years, by_year, home, today),
    }


def _numeric_rows(years, by_year, today):
    ld = helpers.local_date

    def distance(acts):
        return round(sum(a.distance for a in acts) / 1000) if acts else None

    def elevation(acts):
        return round(sum((a.total_elevation_gain or 0) for a in acts)) if acts else None

    def hours(acts):
        return int(round(sum((a.moving_time or 0) for a in acts) / 3600)) if acts else None

    def count(acts):
        return len(acts) or None

    def active_days(acts):
        return len({ld(a) for a in acts}) or None

    def kudos(acts):
        return sum(a.kudos_count for a in acts) if acts else None

    def prs(acts):
        return sum(a.pr_count for a in acts) if acts else None

    def achievements(acts):
        return sum(a.achievement_count for a in acts) if acts else None

    def avg_pace(acts):
        # Distance-weighted pace for the whole year (total time / total distance),
        # not the single fastest run — a short sprint race isn't representative.
        paced = [a for a in acts if paceable(a)]
        total_km = sum(a.distance for a in paced) / 1000
        return sum(a.moving_time for a in paced) / total_km if total_km else None

    def biggest_week(acts):
        if not acts:
            return None
        daily = {}
        for a in acts:
            daily[ld(a)] = daily.get(ld(a), 0.0) + a.distance / 1000
        items = list(daily.items())
        best = 0.0
        for d0, _ in items:
            window = sum(km for d, km in items if 0 <= (d - d0).days <= 6)
            best = max(best, window)
        return round(best) or None

    # (name, unit, icon, small-unit, format, lower-is-better, value fn)
    specs = [
        ('Distance', 'kilometres', 'dist', 'km', 'int', False, distance),
        ('Elevation gain', 'metres climbed', 'elev', 'm', 'int', False, elevation),
        ('Moving time', 'hours active', 'time', 'h', 'int', False, hours),
        ('Activities', 'sessions logged', 'acts', '', 'int', False, count),
        ('Active days', 'days on the move', 'days', 'd', 'int', False, active_days),
        ('Average pace', 'lower is faster', 'pace', '/km', 'pace', True, avg_pace),
        ('Biggest week', 'peak 7-day block', 'week', 'km', 'int', False, biggest_week),
        ('Kudos received', 'from the community', 'kudos', '', 'int', False, kudos),
        ('PRs set', 'personal records', 'prs', '', 'int', False, prs),
        ('Achievements', 'badges earned', 'ach', '', 'int', False, achievements),
    ]
    rows = []
    for name, unit, icon, small, fmt, lower, fn in specs:
        values = [fn(by_year.get(y, [])) for y in years]
        if any(v is not None for v in values):
            rows.append(_numeric_row(years, values, name, unit, icon, small, fmt, lower, today))
    return rows


def _numeric_row(years, values, name, unit, icon, small, fmt, lower, today):
    present = [v for v in values if v is not None]
    best_val = (min if lower else max)(present)
    vmax, vmin = max(present), min(present)
    first_idx = next(i for i, v in enumerate(values) if v is not None)
    best_idx = values.index(best_val)  # first year holding the best value (ties → earliest)

    cells = []
    for i, (year, v) in enumerate(zip(years, values)):
        current = year == today.year
        if v is None:
            cells.append({'has': False, 'current': current})
            continue
        if lower:
            # Lower is better (pace): the fastest year fills the bar; slower years
            # shrink toward a 30% floor so the spread stays legible.
            width = 100.0 if vmax == vmin else 30 + (vmax - v) / (vmax - vmin) * 70
        else:
            width = 100.0 if vmax == 0 else v / vmax * 100
        if i == first_idx:
            delta = {'kind': 'base'}
        elif values[i - 1] is None:
            delta = {'kind': 'none'}
        else:
            delta = _delta(values[i - 1], v, lower)
        cells.append({
            'has': True, 'current': current, 'best': i == best_idx,
            'display': _fmt_value(v, fmt), 'small': small,
            'w': round(width, 1), 'delta': delta,
        })
    return {'name': name, 'unit': unit, 'icon': icon, 'cells': cells}


def _delta(prev, value, lower):
    """Year-on-year change badge. For pace (lower-better) the change is shown in
    seconds and a drop counts as improvement; otherwise it's a percentage."""
    if lower:
        diff = int(round(value - prev))
        if diff < 0:
            return {'dir': 'up', 'text': f'−{abs(diff)}s'}
        if diff > 0:
            return {'dir': 'down', 'text': f'+{diff}s'}
        return {'dir': 'up', 'text': '0s'}
    if prev == 0:
        return {'dir': 'up' if value >= 0 else 'down', 'text': '—'}
    pct = round((value - prev) / prev * 100)
    return {'dir': 'up' if value >= prev else 'down',
            'text': f'{"+" if pct >= 0 else "−"}{abs(pct)}%'}


def _fmt_value(value, fmt):
    if fmt == 'pace':
        return helpers.fmt_pace(value)
    return f'{value:,}'


def _effort_rows(years, by_year, home, today):
    """Signature-effort rows: the standout activity per year for a handful of
    superlatives, shown as name + a compact stat line."""
    def dist_seg(a):
        return {'v': f'{a.distance_km:.1f}', 'u': 'km'}

    def elev_seg(a):
        return {'v': f'{a.elevation:,}', 'u': 'm'}

    def pace_of(a):
        return a.moving_time / (a.distance / 1000)

    def build(icon, name, unit, pick, segs, valid=None):
        cells, any_present = [], False
        for y in years:
            acts = by_year.get(y, [])
            if valid:
                acts = [a for a in acts if valid(a)]
            current = y == today.year
            if not acts:
                cells.append({'current': current})
                continue
            any_present = True
            best = pick(acts)
            cells.append({'current': current, 'id': best.pk, 'photo': best.photo_url,
                          'title': best.name, 'segments': segs(best)})
        return {'icon': icon, 'name': name, 'unit': unit, 'cells': cells} if any_present else None

    haversine = helpers.haversine_km
    rows = [
        build('trophy', 'Activity of the year', 'signature effort',
              lambda acts: max(acts, key=lambda a: a.calories or 0),
              lambda a: [dist_seg(a), elev_seg(a)]),
        build('longest', 'Longest activity', 'biggest single outing',
              lambda acts: max(acts, key=lambda a: a.distance),
              lambda a: [dist_seg(a), elev_seg(a)]),
        build('climb', 'Most elevation', 'single climb',
              lambda acts: max(acts, key=lambda a: a.total_elevation_gain or 0),
              lambda a: [elev_seg(a), dist_seg(a)],
              valid=lambda a: a.total_elevation_gain),
    ]
    if home:
        rows.append(build(
            'pin', 'Furthest from home', 'travel effort',
            lambda acts: max(acts, key=lambda a: haversine(home[0], home[1], a.start_lat, a.start_lng)),
            lambda a: [{'v': f'{round(haversine(home[0], home[1], a.start_lat, a.start_lng)):,}',
                        'u': 'km away'}],
            valid=lambda a: a.start_lat is not None and a.start_lng is not None))
    rows.append(build(
        'bolt', 'Fastest avg pace', 'quickest effort',
        lambda acts: min(acts, key=pace_of),
        lambda a: [{'v': helpers.fmt_pace(pace_of(a)), 'u': '/km'}, dist_seg(a)],
        valid=paceable))
    return [r for r in rows if r]
