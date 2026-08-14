"""Activities-page computation: the summary totals over the filtered queryset."""
import datetime

from django.db.models import Sum


def summary(qs, today):
    """Summary totals for the activities list: count, distance, elevation, time, and how
    many fall in the current week."""
    agg = qs.aggregate(
        total_distance=Sum('distance'),
        total_elevation=Sum('total_elevation_gain'),
        total_time=Sum('moving_time'),
    )
    week_start = today - datetime.timedelta(days=today.weekday())
    return {
        'count': qs.count(),
        'distance_km': round((agg['total_distance'] or 0) / 1000),
        'elevation_m': round(agg['total_elevation'] or 0),
        'time_h': round((agg['total_time'] or 0) / 3600),
        'this_week': qs.filter(start_date__date__gte=week_start).count(),
    }
