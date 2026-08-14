"""Template access to the current Strava athlete (nav name/avatar/counts).

    {% load stravakit_athlete %}
    {% stravakit_athlete as athlete %}
    {{ athlete.full_name }}

Returns None before the first import, so templates guard with `{% if athlete %}`.
Using a tag (rather than a context processor) keeps this self-contained in the app —
the consuming project needs no TEMPLATES settings change.
"""

from django import template

from stravakit.models import Athlete

register = template.Library()


@register.simple_tag(takes_context=True)
def stravakit_athlete(context):
    """The athlete the frontend renders for this request — the ``?athlete=<id>`` selection
    if present, else the default athlete — or None before the first import."""
    request = context.get("request")
    if request is not None:
        return Athlete.selected(request)
    return Athlete.current()
