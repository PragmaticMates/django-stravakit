"""Template access to the shared sport glyphs (stravakit/sport_icons.py).

    {% load stravakit_icons %}
    {{ activity.sport_type|sport_glyph }}   {# per-sport icon, group/run fallback #}
    {{ opt.icon|group_glyph }}              {# a "Top sports" group glyph by name #}
"""

from django import template
from django.utils.safestring import mark_safe

from stravakit.sport_icons import GROUP_GLYPHS, icon_html

register = template.Library()


@register.filter
def sport_glyph(sport_type):
    """SVG glyph for a ``sport_type`` (its own icon, else its group's, else run)."""
    return icon_html(sport_type)


@register.filter
def group_glyph(name):
    """SVG glyph for a sport-filter group icon name (``run``/``ride``/``hike``/``swim``);
    anything else (e.g. the ``all`` reset) renders nothing."""
    return mark_safe(GROUP_GLYPHS.get(name, ""))  # noqa: S308 — trusted static SVG constants
