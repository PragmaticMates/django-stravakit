"""Template access to the basemap tile URL the maps draw on (CARTO Positron).

    {% load stravakit_map %}
    <meta name="stravakit-basemap" content="{% stravakit_basemap_url %}">

CARTO's raster basemaps require an API key since 2026 — without one every tile carries an
"API KEY REQUIRED" watermark. The key lives in ``settings.STRAVA_CARTO_API_KEY`` and is
appended here, once, so the Leaflet map (dashboard-map.js) and the static card maps
(charts.js) read the same template from one ``<meta>`` in ``base.html`` instead of each
carrying a URL of its own. ``{s}``/``{z}``/``{x}``/``{y}``/``{r}`` are Leaflet's placeholders.
"""

from django import template
from django.conf import settings

register = template.Library()

BASEMAP_URL = "https://{s}.basemaps.cartocdn.com/rastertiles/light_all/{z}/{x}/{y}{r}.png"


@register.simple_tag
def stravakit_basemap_url():
    """The tile URL template, with ``?key=`` appended when a CARTO key is configured."""
    key = getattr(settings, "STRAVA_CARTO_API_KEY", None)
    return f"{BASEMAP_URL}?key={key}" if key else BASEMAP_URL
