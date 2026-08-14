"""Single source of truth for the sport filter taxonomy.

The three sport filters (dashboard map pill, activities page, gallery) all share
one dropdown: a flat list of every sport present in the data, preceded by a
"Top sports" category of four grouped meta-sports. Group membership is derived
from ``SportType`` here so the server-side filter (``for_sport_selection``), the
dashboard's in-Python filter (``sport_matches``) and the client-side dropdown
(``sport-filter.js``, fed via ``group_data``) can never drift apart.

A filter value is one of: ``'all'``, a group key (``'group-run'`` …) or an exact
``sport_type`` (``'Run'``, ``'TrailRun'`` …).
"""

from django.utils.translation import gettext_lazy as _

from stravakit.choices import SportType


def _is_cycling(sport_type):
    return "Ride" in sport_type or sport_type in ("Velomobile", "Handcycle")


# --------------------------------------------------------------------------- #
# Broad activity categories
# --------------------------------------------------------------------------- #
# The coarse bucket a sport falls in, used for map-marker styling (Activity.map_sport_type).
# Each sport maps to exactly one bucket: the first matching rule wins, and anything unmatched
# is DEFAULT_MAP_SPORT_TYPE ('other') — the grab-bag for sports (Yoga, Tennis, AlpineSki,
# Velomobile …) that have no dedicated bucket, so they get their own marker colour rather
# than borrowing 'run's. A rule is either a substring test ("contains") or an explicit
# membership set ("values"). This is the single source of truth behind Activity.map_sport_type.
MAP_SPORT_TYPES = (
    ("trail", {"contains": "Trail"}),
    ("hike", {"values": ("Hike", "Snowshoe")}),
    ("walk", {"values": ("Walk",)}),
    ("ride", {"contains": "Ride"}),
    ("swim", {"contains": "Swim"}),
    ("run", {"values": ("Run", "VirtualRun")}),
)
DEFAULT_MAP_SPORT_TYPE = "other"


def _rule_matches(rule, sport_type):
    if "contains" in rule:
        return rule["contains"] in sport_type
    return sport_type in rule["values"]


def map_sport_type_for(sport_type):
    """The map sport type ('trail'/'hike'/'walk'/'ride'/'swim'/'run'/'other') for a sport_type."""
    for name, rule in MAP_SPORT_TYPES:
        if _rule_matches(rule, sport_type):
            return name
    return DEFAULT_MAP_SPORT_TYPE


# --------------------------------------------------------------------------- #
# Pace / speed semantics
# --------------------------------------------------------------------------- #
# How an activity's effort reads on screen — keyed off sport_type, independent of the
# map-colour bucket: cycling is shown as speed (km/h), swimming as a per-100 m pace, and
# everything else as a per-km pace. Kept here (not derived from MAP_SPORT_TYPES) so map
# styling and pace display can evolve separately.
def is_speed_sport(sport_type):
    """Cycling — shown as km/h rather than a per-distance pace (includes velomobile/handcycle)."""
    return _is_cycling(sport_type)


def is_swim_sport(sport_type):
    """Swimming — shown as a per-100 m pace."""
    return "Swim" in sport_type


# Sport types with a meaningful "/km" pace, eligible for the fastest-pace effort row and the
# run-performance ranking. A deliberate curation of foot sports (not a derived rule): rides
# use km/h, swims /100 m, and miscellaneous sports have no comparable per-km pace.
PACE_SPORT_TYPES = {"Run", "TrailRun", "VirtualRun", "Hike", "Snowshoe", "Walk"}


# Exact sport types per personal-records / compare tab. An explicit allow-list (rather
# than the coarse categories above, whose "other" catch-all would swallow every unlisted
# sport) keeps unrelated fast activities out of the running/cycling PRs. Cycling is limited
# to conventional bikes: e-bikes (motor assistance), velomobiles and handcycles (very
# different mechanics/aerodynamics) would all unfairly distort the records.
RECORDS_SPORT_TYPES = {
    "Running": {"Run", "TrailRun", "VirtualRun"},
    "Cycling": {"Ride", "GravelRide", "MountainBikeRide", "VirtualRide"},
    "Hiking": {"Hike", "Snowshoe", "Walk"},
    "Swimming": {"Swim"},
}


# Ordered "Top sports" groups. ``icon`` names a glyph in sport-filter.js.
TOP_SPORT_TYPES = [
    {"key": "group-run", "label": _("Running"), "icon": "run", "types": ["Run", "TrailRun", "VirtualRun"]},
    {"key": "group-ride", "label": _("Cycling"), "icon": "ride",
     "types": [s for s in SportType.values if _is_cycling(s)]},
    {"key": "group-walk", "label": _("Walking"), "icon": "hike", "types": ["Hike", "Walk", "Snowshoe"]},
    {"key": "group-swim", "label": _("Swimming"), "icon": "swim",
     "types": [s for s in SportType.values if "Swim" in s]},
]

_GROUP_BY_KEY = {group["key"]: group for group in TOP_SPORT_TYPES}


def types_for(value):
    """A filter value's sport types: a group key expands to its members, anything
    else (an exact sport_type) maps to itself."""
    group = _GROUP_BY_KEY.get(value)
    return group["types"] if group else [value]


def sport_matches(value, sport_type):
    """Whether a single ``sport_type`` satisfies the filter ``value``."""
    return not value or value == "all" or sport_type in types_for(value)


def group_data():
    """JSON-safe group definitions for ``json_script`` (labels forced to str). Each
    carries its ``glyph`` (SVG markup) so the client dropdown never holds its own icons."""
    from stravakit.sport_icons import GROUP_GLYPHS  # local import: sport_icons imports us

    return [
        {"key": g["key"], "label": str(g["label"]), "icon": g["icon"],
         "glyph": GROUP_GLYPHS[g["icon"]], "types": g["types"]}
        for g in TOP_SPORT_TYPES
    ]


def sport_options(queryset):
    """``[[sport_type, label, glyph], …]`` for the distinct sports present in
    ``queryset``, sorted by label — the flat "All sports" section of the dropdown.
    The third element is the sport's SVG glyph so the client carries no icon copy."""
    from stravakit.sport_icons import icon_for  # local import: sport_icons imports us

    # order_by("sport_type") overrides the model's default ordering, which would
    # otherwise leak into the SELECT and defeat .distinct() (duplicate rows).
    types = queryset.order_by("sport_type").values_list("sport_type", flat=True).distinct()
    options = [[t, SportType(t).label, icon_for(t)] for t in types if t]
    options.sort(key=lambda option: option[1])
    return options
