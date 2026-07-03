"""Gear aggregation and display computation.

``dashboard_sections`` powers the dashboard's gear-health table + usage donut over the
currently filtered activities; ``gear_page`` decorates the gear-list page's already-queried
gear with wear/badge display fields and its summary totals.
"""
from strava.models import Gear

# Donut slice colours (fill, hover) cycled across the gear used in the active filter.
DONUT_PALETTE = [
    ('#EBE6F2', '#7C4DB8'),
    ('#D5E5D3', '#3A8050'),
    ('#BDD8ED', '#007FB6'),
    ('#F5D0BC', '#FC5200'),
    ('#F3E1C7', '#C98A1B'),
    ('#E6D4E8', '#9B4DCA'),
]


def dashboard_sections(activities, no_filter):
    """Gear health rows + usage-donut slices, aggregated over the filtered activities
    (not DB-wide totals) so gear stats track the active filter like every other section.
    With no active filter, gear unused for over a year is hidden."""
    gear_acts, gear_dist = {}, {}
    for a in activities:
        if a.gear_id:
            gear_acts[a.gear_id] = gear_acts.get(a.gear_id, 0) + 1
            gear_dist[a.gear_id] = gear_dist.get(a.gear_id, 0) + a.distance
    gears = list(Gear.objects.all())
    if no_filter:
        gears = [g for g in gears if not g.is_old]
    for g in gears:
        g.activity_count = gear_acts.get(g.pk, 0)
        g.distance_sum = gear_dist.get(g.pk, 0)
        g.distance_km = round((g.distance_sum or 0) / 1000)
        g.wear_pct = min(100, round(g.distance_km / g.lifespan_km * 100)) if g.lifespan_km else 0
        g.wear_alert = 75 <= g.wear_pct < 100
    if not no_filter:
        # Under an active filter, only show gear used by the matching activities.
        gears = [g for g in gears if g.activity_count]
    gear_health = sorted(gears, key=lambda g: g.activity_count, reverse=True)

    used = sorted((g for g in gears if g.activity_count), key=lambda g: g.activity_count, reverse=True)
    gear_usage = [
        {
            'name': str(g),
            'acts': g.activity_count,
            'dist': g.distance_km,
            'color': DONUT_PALETTE[i % len(DONUT_PALETTE)][0],
            'hoverColor': DONUT_PALETTE[i % len(DONUT_PALETTE)][1],
        }
        for i, g in enumerate(used)
    ]
    return gear_health, gear_usage


def page(gear_list):
    """Decorate the gear-list page's gear with wear/badge display fields and split them
    into bikes/shoes. Returns ``(gear_list, bikes, shoes, summary)``."""
    for g in gear_list:
        g.distance_km = round((g.distance_sum or 0) / 1000)
        g.wear_pct = min(100, round(g.distance_km / g.lifespan_km * 100)) if g.lifespan_km else 0
        g.wear_class = 'wear-low' if g.wear_pct < 40 else 'wear-mid' if g.wear_pct < 75 else 'wear-high'
        g.is_retired = g.wear_pct >= 100
        if g.is_retired:
            g.badge_class, g.badge_label = 'badge-retired', 'Retired'
        elif g.primary:
            g.badge_class, g.badge_label = 'badge-primary', 'Primary'
        elif g.wear_pct >= 75:
            g.badge_class = 'badge-alert'
            g.badge_label = 'Service due' if g.gear_type == 'bike' else 'Replace soon'
        else:
            g.badge_class = g.badge_label = ''

    bikes = [g for g in gear_list if g.gear_type == 'bike']
    shoes = [g for g in gear_list if g.gear_type == 'shoe']
    summary = {
        'bikes': len(bikes),
        'shoes': len(shoes),
        'total_km': sum(g.distance_km for g in gear_list),
        'activities': sum(g.activity_count for g in gear_list),
    }
    return gear_list, bikes, shoes, summary
