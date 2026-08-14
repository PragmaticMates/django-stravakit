from datetime import datetime, timedelta

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from stravakit.choices import SportType
from stravakit.consts import BIKE_LIFESPAN_KM, DETAIL_MARKER_FIELDS, GEAR_OLD_DAYS, SHOE_LIFESPAN_KM
from stravakit.querysets import ActivityQuerySet, AthleteQuerySet, GearQuerySet
from stravakit.sports import is_speed_sport, is_swim_sport, map_sport_type_for


class Activity(models.Model):
  name = models.CharField(_("name"), max_length=100)
  start_date = models.DateTimeField(_("start date"))
  sport_type = models.CharField(_("sport type"), max_length=29, choices=SportType.choices)
  # Metres. Stored as a float (Strava sends a float and every consumer works in floats);
  # no exact-decimal arithmetic is needed, so a DecimalField only added casting noise.
  distance = models.FloatField(_("distance"))
  moving_time = models.PositiveIntegerField(_("moving time"), null=True, blank=True)
  elapsed_time = models.PositiveIntegerField(_("elapsed time"), null=True, blank=True)
  total_elevation_gain = models.FloatField(_("elevation gain"), null=True, blank=True)
  average_speed = models.FloatField(_("average speed"), null=True, blank=True)
  max_speed = models.FloatField(_("max speed"), null=True, blank=True)
  average_heartrate = models.FloatField(_("average heartrate"), null=True, blank=True)
  max_heartrate = models.FloatField(_("max heartrate"), null=True, blank=True)
  calories = models.PositiveSmallIntegerField(_("calories"), null=True, blank=True)
  kudos_count = models.PositiveIntegerField(_("kudos"), default=0)
  comment_count = models.PositiveIntegerField(_("comments"), default=0)
  pr_count = models.PositiveSmallIntegerField(_("PRs"), default=0)
  achievement_count = models.PositiveSmallIntegerField(_("achievements"), default=0)
  total_photo_count = models.PositiveIntegerField(_("photos"), default=0)
  photo_url = models.URLField(_("photo URL"), max_length=500, blank=True, default="")
  start_lat = models.FloatField(_("start latitude"), null=True, blank=True)
  start_lng = models.FloatField(_("start longitude"), null=True, blank=True)
  polyline = models.TextField(_("polyline"), blank=True, default="")
  is_detailed = models.BooleanField(_("detailed"), default=False)
  # Marked private by the athlete on Strava. Hidden from every public-facing surface
  # (lists, map, records, statistics) via ActivityQuerySet.public(); the admin still
  # shows these and offers a filter for them.
  is_private = models.BooleanField(_("private"), default=False)
  gear = models.ForeignKey("Gear", on_delete=models.SET_NULL,
                           blank=True, null=True, default=None)
  # The activity's owner. Nullable because rows imported before athlete linking existed
  # have none until the next import backfills them (see stravakit_import).
  athlete = models.ForeignKey("Athlete", on_delete=models.CASCADE,
                              blank=True, null=True, default=None, related_name="activities")
  json = models.JSONField()
  objects = ActivityQuerySet.as_manager()

  class Meta:
    verbose_name = _("activity")
    verbose_name_plural = _("activities")
    get_latest_by = "start_date"
    ordering = ("-start_date",)

  def __str__(self):
      return self.name

  def get_absolute_url(self):
    return f'https://strava.com/activities/{self.id}'

  @classmethod
  def read_json(cls, json):
    primary = (json.get('photos') or {}).get('primary') or {}
    urls = primary.get('urls') or {}
    latlng = json.get('start_latlng') or []
    # Treat (0, 0) / missing coords as "no GPS" (e.g. pool swims, treadmill runs).
    has_gps = len(latlng) == 2 and bool(latlng[0] or latlng[1])
    route = json.get('map') or {}
    return {
      # 'id': json['id'],
      'name': json['name'],
      'gear_id': json['gear_id'],
      'sport_type': json['sport_type'],
      'distance': json['distance'],
      'start_date': datetime.fromisoformat(json['start_date']),
      'moving_time': json.get('moving_time'),
      'elapsed_time': json.get('elapsed_time'),
      'total_elevation_gain': json.get('total_elevation_gain'),
      'average_speed': json.get('average_speed'),
      'max_speed': json.get('max_speed'),
      'average_heartrate': json.get('average_heartrate'),
      'max_heartrate': json.get('max_heartrate'),
      # calories is a DetailedActivity-only field; Strava sends it as a whole-number float.
      'calories': round(calories) if (calories := json.get('calories')) is not None else None,
      'kudos_count': json.get('kudos_count', 0) or 0,
      'comment_count': json.get('comment_count', 0) or 0,
      'pr_count': json.get('pr_count', 0) or 0,
      'achievement_count': json.get('achievement_count', 0) or 0,
      'total_photo_count': json.get('total_photo_count', 0) or 0,
      'photo_url': urls.get('600') or urls.get('100') or '',
      'start_lat': round(float(latlng[0]), 6) if has_gps else None,
      'start_lng': round(float(latlng[1]), 6) if has_gps else None,
      'polyline': route.get('polyline') or route.get('summary_polyline') or '',
      'is_detailed': any(json.get(field) is not None for field in DETAIL_MARKER_FIELDS),
      'is_private': bool(json.get('private')),
    }

  def is_synced(self):
      conditions = [
        self.gear_id == self.json['gear_id'],
        self.sport_type == self.json['sport_type'],
      ]
      return all(conditions)
  is_synced.boolean = True

  def is_gear_synced(self):
      conditions = [
        self.gear_id == self.json['gear_id'],
      ]
      return all(conditions)
  is_gear_synced.boolean = True

  @property
  def map_sport_type(self):
    # Map sport type (trail/hike/walk/ride/swim/run/other); defined once in strava.sports.
    return map_sport_type_for(self.sport_type)

  @property
  def distance_km(self):
    return round(self.distance / 1000, 1)

  @property
  def duration(self):
    t = self.moving_time or 0
    h, r = divmod(t, 3600)
    m, s = divmod(r, 60)
    return f'{h}h {m:02d}m' if h else f'{m}m {s:02d}s'

  @property
  def is_speed_sport(self):
    # Cycling — its effort reads as speed (km/h), so cards label it "Speed" not "Pace".
    return is_speed_sport(self.sport_type)

  @property
  def is_swim_sport(self):
    # Swimming — per-100 m pace, and cards hide the (always-zero) elevation stat.
    return is_swim_sport(self.sport_type)

  @property
  def pace_parts(self):
    t = self.moving_time or 0
    d = self.distance
    if not t or not d:
      return '-', ''
    d_km = d / 1000
    if is_speed_sport(self.sport_type):
      return f'{d_km / (t / 3600):.1f}', 'km/h'
    if is_swim_sport(self.sport_type):
      pace_s = t / (d / 100)
      m, s = divmod(int(pace_s), 60)
      return f'{m}:{s:02d}', '/100m'
    pace_s = t / d_km
    m, s = divmod(int(pace_s), 60)
    return f'{m}:{s:02d}', '/km'

  @property
  def pace(self):
    val, unit = self.pace_parts
    if not unit:
      return val
    return f'{val} {unit}'

  @property
  def elevation(self):
    return round(self.total_elevation_gain or 0)

  @property
  def pb(self):
    return bool(self.pr_count)

  @property
  def has_gps(self):
    return self.start_lat is not None

  @property
  def has_heartrate(self):
    return self.average_heartrate is not None and self.max_heartrate is not None

  @property
  def best_efforts(self):
    # Strava's per-run best efforts (5k/10k/… splits) — a nested array kept in `json`
    # rather than promoted to columns; exposed here so callers don't reach into the blob.
    return self.json.get('best_efforts') or []


class Gear(models.Model):
  GEAR_TYPES = (('bike', _("bike")), ('shoe', _("shoe")))

  id = models.CharField(max_length=36, primary_key=True, editable=False)  # default=uuid.uuid4
  primary = models.BooleanField(_("primary"), default=False)
  brand_name = models.CharField(_("brand name"), max_length=30)
  model_name = models.CharField(_("model name"), max_length=50)
  description = models.CharField(_("description"), max_length=100)
  gear_type = models.CharField(_("type"), max_length=4, choices=GEAR_TYPES, default='shoe')
  # The gear's owner. Nullable for the same reason as Activity.athlete (backfilled on import).
  athlete = models.ForeignKey("Athlete", on_delete=models.CASCADE,
                              blank=True, null=True, default=None, related_name="gear")
  json = models.JSONField()
  objects = GearQuerySet.as_manager()

  def __str__(self):
      return f'{self.brand_name} {self.model_name}'

  @property
  def distance(self):
      # Private activities are excluded from the public gear mileage total.
      return self.activity_set.public().aggregate(models.Sum('distance'))['distance__sum']

  @property
  def is_old(self):
    # "Last used" ignores private activities, matching what the public gear page shows.
    last_used = self.activity_set.public().aggregate(models.Max('start_date'))['start_date__max']
    if last_used is None:
      return True
    return last_used < timezone.now() - timedelta(days=GEAR_OLD_DAYS)

  @property
  def lifespan_km(self):
    return BIKE_LIFESPAN_KM if self.gear_type == 'bike' else SHOE_LIFESPAN_KM

  @classmethod
  def read_json(cls, json):
    return {
      # 'id': json['id'],
      'primary': json['primary'],
      'brand_name': json['brand_name'],
      'model_name': json['model_name'],
      'description': json['description'] or '',
      # Per the Strava API, only bikes carry a frame_type (DetailedGear); shoes have none.
      'gear_type': 'bike' if json.get('frame_type') is not None else 'shoe',
    }


class Athlete(models.Model):
  """The Strava athlete whose activities this app displays.

  The app is single-athlete, so the frontend reads the one athlete via
  ``Athlete.current()`` — the nav name, avatar and follower/following counts come
  from here instead of being hardcoded. Populated by ``stravakit_import`` (and the
  dashboard refresh button) from the authenticated athlete on the Strava API.
  """

  # `id` is the default auto PK with Strava's integer athlete id assigned into it on
  # import (same pattern as Activity) — Gear needs a custom CharField PK only because its
  # Strava ids are strings ("b1234567").
  firstname = models.CharField(_("first name"), max_length=50, blank=True, default="")
  lastname = models.CharField(_("last name"), max_length=50, blank=True, default="")
  profile = models.URLField(_("avatar URL"), max_length=500, blank=True, default="")
  city = models.CharField(_("city"), max_length=100, blank=True, default="")
  country = models.CharField(_("country"), max_length=100, blank=True, default="")
  follower_count = models.PositiveIntegerField(_("followers"), null=True, blank=True)
  friend_count = models.PositiveIntegerField(_("following"), null=True, blank=True)
  # Per-athlete OAuth credentials. Populated by the OAuth connect flow (see strava.views);
  # refreshed access/refresh tokens are written back here after each API call by StravaApi.
  # Blank until the athlete is connected — `stravakit_import` skips athletes without tokens.
  access_token = models.CharField(_("access token"), max_length=100, blank=True, default="")
  refresh_token = models.CharField(_("refresh token"), max_length=100, blank=True, default="")
  token_expires_at = models.DateTimeField(_("token expires at"), null=True, blank=True)
  scope = models.CharField(_("scope"), max_length=200, blank=True, default="")
  # When stravakit_import last refreshed this athlete's data — shown as the dashboard's
  # "Last updated". Null until the first successful import.
  synced_at = models.DateTimeField(_("last synced at"), null=True, blank=True)
  # The athlete rendered at the site root. Exactly one row is default (enforced below);
  # the frontend switcher overrides it per request.
  is_default = models.BooleanField(_("default"), default=False)
  json = models.JSONField()
  objects = AthleteQuerySet.as_manager()

  class Meta:
    verbose_name = _("athlete")
    verbose_name_plural = _("athletes")
    constraints = [
      # At most one default athlete (a partial unique index over the `True` rows only).
      models.UniqueConstraint(
        fields=["is_default"], condition=models.Q(is_default=True), name="one_default_athlete",
      ),
    ]

  def __str__(self):
    return self.full_name or str(self.id)

  @property
  def full_name(self):
    return f"{self.firstname} {self.lastname}".strip()

  @property
  def location(self):
    return ", ".join(part for part in (self.city, self.country) if part)

  @property
  def has_tokens(self):
    """Whether this athlete has been connected via OAuth (so imports can run for them)."""
    return bool(self.access_token and self.refresh_token)

  @property
  def profile_url(self):
    return f"https://www.strava.com/athletes/{self.id}"

  @property
  def followers_url(self):
    return f"https://www.strava.com/athletes/{self.id}/follows?type=followers"

  @property
  def following_url(self):
    return f"https://www.strava.com/athletes/{self.id}/follows?type=following"

  @classmethod
  def default(cls):
    """The athlete shown at the site root — the one flagged default, else the first row."""
    return cls.objects.filter(is_default=True).first() or cls.objects.first()

  @classmethod
  def selected(cls, request):
    """The athlete for this request: a valid ``?athlete=<pk>`` selection, else the default."""
    pk = (request.GET.get("athlete") or "").strip()
    if pk:
      try:
        athlete = cls.objects.filter(pk=pk).first()
      except (ValueError, TypeError):
        # ``athlete`` isn't a valid PK (the id is an integer) — fall back to the default.
        athlete = None
      if athlete:
        return athlete
    return cls.default()

  @classmethod
  def current(cls):
    """The athlete the frontend renders by default, or None before the first import."""
    return cls.default()

  @classmethod
  def read_json(cls, json):
    return {
      'firstname': json.get('firstname') or '',
      'lastname': json.get('lastname') or '',
      # A real (non-default) avatar; Strava sends a relative placeholder otherwise.
      'profile': (json.get('profile') or '') if str(json.get('profile') or '').startswith('http') else '',
      'city': json.get('city') or '',
      'country': json.get('country') or '',
      'follower_count': json.get('follower_count'),
      'friend_count': json.get('friend_count'),
    }

  @classmethod
  def store(cls, json_data):
    """Create/update the athlete from a Strava athlete payload."""
    data = cls.read_json(json_data)
    data['json'] = json_data
    athlete, _created = cls.objects.update_or_create(id=json_data['id'], defaults=data)
    return athlete

  def update_from_json(self):
    for attr, value in Athlete.read_json(self.json).items():
      setattr(self, attr, value)
    self.save()
