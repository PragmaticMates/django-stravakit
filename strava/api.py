import functools
import json
import logging
import time
from datetime import datetime, timezone
from django.conf import settings

from stravalib import Client, exc
from stravalib.util.limiter import (
  DefaultRateLimiter,
  get_seconds_until_next_day,
  get_seconds_until_next_quarter,
  get_rates_from_response_headers,
)

logger = logging.getLogger("file")

# One Strava API app authenticates every athlete; the per-athlete access/refresh tokens
# live on the Athlete row (see StravaApi.__init__), not in settings.
STRAVA_CLIENT_ID = getattr(settings, "STRAVA_CLIENT_ID", None)
STRAVA_CLIENT_SECRET = getattr(settings, "STRAVA_CLIENT_SECRET", None)

# How aggressively to space out requests to stay within Strava's limits
# (https://developers.strava.com/docs/rate-limits/):
#   "high"   - no proactive throttling (burst until a limit is hit)
#   "medium" - spread requests so the short-term (15 min) limit is not exceeded
#   "low"    - spread requests so the daily limit is not exceeded
STRAVA_RATE_LIMIT_PRIORITY = getattr(settings, "STRAVA_RATE_LIMIT_PRIORITY", "medium")

# How many times to retry a request after hitting a 429 (rate limit exceeded)
# before giving up. Each retry waits until the relevant limit window resets.
STRAVA_RATE_LIMIT_MAX_RETRIES = getattr(settings, "STRAVA_RATE_LIMIT_MAX_RETRIES", 3)


def rate_limited(func):
  """Retry a Strava API call when the rate limit is exceeded.

  stravalib's limiter proactively spaces requests, but a 429 can still
  happen (e.g. the quota was consumed by another process). When it does,
  sleep until the offending limit window resets and retry, rather than
  letting the import fail.
  """

  @functools.wraps(func)
  def wrapper(*args, **kwargs):
    for attempt in range(STRAVA_RATE_LIMIT_MAX_RETRIES + 1):
      try:
        return func(*args, **kwargs)
      except (exc.RateLimitExceeded, exc.Fault) as e:
        response = getattr(e, "response", None)
        status_code = getattr(response, "status_code", None)
        is_rate_limit = isinstance(e, exc.RateLimitExceeded) or status_code == 429
        if not is_rate_limit or attempt >= STRAVA_RATE_LIMIT_MAX_RETRIES:
          raise

        wait = _seconds_until_limit_resets(response)
        logger.warning(
          f"Strava rate limit exceeded on {func.__name__}; "
          f"sleeping {wait}s before retry {attempt + 1}/{STRAVA_RATE_LIMIT_MAX_RETRIES}"
        )
        time.sleep(wait)

  return wrapper


def _seconds_until_limit_resets(response):
  """Seconds to wait before retrying after a 429, based on which limit was hit.

  Prefers the response's rate-limit headers to decide whether the short-term
  (15 min) or the daily limit was exceeded; falls back to the short-term
  window when headers are unavailable.
  """
  headers = getattr(response, "headers", None) or {}
  rates = get_rates_from_response_headers(headers, "GET")
  if rates and rates.long_usage >= rates.long_limit:
    return get_seconds_until_next_day()
  return get_seconds_until_next_quarter()


def token_syncing(func):
  """Persist any token stravalib refreshed during the call back to the athlete row.

  When an access token has expired, stravalib transparently refreshes it — rotating the
  access *and* refresh token and updating the expiry, all mutated on the client in place
  without persisting anywhere. Run in a ``finally`` (a refresh can land before the wrapped
  call itself fails) so the new credentials are written to the DB and never lost. A no-op
  for the token-less client (``athlete`` is None), e.g. during the OAuth code exchange.
  """

  @functools.wraps(func)
  def wrapper(self, *args, **kwargs):
    try:
      return func(self, *args, **kwargs)
    finally:
      self._persist_tokens()

  return wrapper


def _to_epoch(dt):
  """tz-aware datetime -> unix epoch seconds (stravalib's token_expires format)."""
  return int(dt.timestamp()) if dt else None


def _from_epoch(ts):
  """Unix epoch seconds -> tz-aware UTC datetime, or None."""
  return datetime.fromtimestamp(ts, tz=timezone.utc) if ts else None


def format_strava_error(error):
  """Human-readable summary of a Strava API failure.

  Pulls the status code, message and per-field errors out of a stravalib
  ``Fault``'s response body — e.g. a 403 with
  ``{"message": "Forbidden", "errors": [{"resource": "Application",
  "field": "Status", "code": "Inactive"}]}`` becomes
  "Forbidden — Application Status: Inactive (HTTP 403)". Falls back to the
  exception text for non-API errors (network failures, timeouts).
  """
  response = getattr(error, "response", None)
  status_code = getattr(response, "status_code", None)

  payload = {}
  if response is not None:
    try:
      payload = response.json()
    except (ValueError, AttributeError):
      payload = {}

  message = payload.get("message")
  details = ", ".join(
    " ".join(filter(None, (e.get("resource"), e.get("field")))) + f": {e.get('code')}"
    for e in (payload.get("errors") or [])
    if isinstance(e, dict) and e.get("code")
  )

  summary = " — ".join(part for part in (message, details) if part) or str(error)
  if status_code:
    summary = f"{summary} (HTTP {status_code})"
  return summary


class StravaApi:
  def __init__(self, athlete=None):
    """Build a client for ``athlete``'s stored tokens (or a token-less client for the OAuth
    code exchange when ``athlete`` is None)."""
    self.athlete = athlete
    self.client = Client(
      access_token=(athlete.access_token or None) if athlete else None,
      refresh_token=(athlete.refresh_token or None) if athlete else None,
      token_expires=_to_epoch(athlete.token_expires_at) if athlete else None,
      rate_limiter=DefaultRateLimiter(priority=STRAVA_RATE_LIMIT_PRIORITY),
    )
    # stravalib only auto-refreshes an expired token when the protocol carries the client
    # credentials, and it sources those from os.environ at construction (which we don't set).
    # Populate them explicitly so refresh works; @token_syncing then persists the result.
    if STRAVA_CLIENT_ID:
      self.client.protocol.client_id = int(STRAVA_CLIENT_ID)
    self.client.protocol.client_secret = STRAVA_CLIENT_SECRET

  def _persist_tokens(self):
    """Write tokens stravalib may have refreshed on the client back to the athlete row."""
    if not self.athlete:
      return
    access = self.client.access_token or ""
    refresh = self.client.refresh_token or ""
    expires = _from_epoch(self.client.token_expires)
    unchanged = (access, refresh, expires) == (
      self.athlete.access_token, self.athlete.refresh_token, self.athlete.token_expires_at,
    )
    if unchanged:
      return
    self.athlete.access_token = access
    self.athlete.refresh_token = refresh
    self.athlete.token_expires_at = expires
    self.athlete.save(update_fields=["access_token", "refresh_token", "token_expires_at"])

  def authorization_url(self, redirect_uri, state, scope=None):
    """Strava OAuth authorize URL to redirect the owner to when connecting an athlete."""
    return self.client.authorization_url(
      client_id=int(STRAVA_CLIENT_ID),
      redirect_uri=redirect_uri,
      approval_prompt="auto",
      scope=scope or ["read", "activity:read_all", "profile:read_all"],
      state=state,
    )

  def exchange_code_for_token(self, code):
    """Exchange an OAuth callback ``code`` for tokens (AccessInfo:
    ``access_token`` / ``refresh_token`` / ``expires_at``)."""
    return self.client.exchange_code_for_token(
      client_id=int(STRAVA_CLIENT_ID),
      client_secret=STRAVA_CLIENT_SECRET,
      code=code,
    )

  @token_syncing
  @rate_limited
  def get_gear(self, id):
    data = json.loads(self.client.get_gear(id).model_dump_json())
    logger.info(self.get_formatted_json(data))
    return data

  @token_syncing
  @rate_limited
  def get_activity(self, id):
    data = json.loads(self.client.get_activity(id).model_dump_json())
    logger.info(self.get_formatted_json(data))
    return data

  @token_syncing
  @rate_limited
  def get_activities(self, after=None, before=None, limit=None):
    """Activity summaries from the athlete's own feed, oldest first once ``after`` is set.

    ``after``/``before`` bound the window and must be timezone-aware: stravalib converts an
    aware value to a UTC epoch, but reads a *naive* one as UTC regardless of the project's
    timezone. ``limit`` caps how many summaries are drained from the paginated iterator; it
    is deliberately not exposed on the command line, because with ``after`` set it truncates
    the *old* end of the window rather than the recent one.
    """
    activities = []

    for activity in self.client.get_activities(after=after, before=before, limit=limit):
      activities.append(json.loads(activity.model_dump_json()))
    # A count at info, the payloads at debug: a wide window is hundreds of summaries, and
    # the pretty-printed dump of all of them buries every other line in the log.
    window = "".join([
      f" after {after:%Y-%m-%d}" if after else "",
      f" before {before:%Y-%m-%d}" if before else "",
    ])
    logger.info(f"Fetched {len(activities)} activity summaries{window}")
    logger.debug(self.get_formatted_json(activities))
    return activities

  @token_syncing
  @rate_limited
  def update_activity(self, id, **kwargs):
    logger.info(f'Updating activity: {id}: {kwargs}')
    self.client.update_activity(activity_id=id, **kwargs)

  def get_formatted_json(self, data):
    if isinstance(data, str):
      data = json.loads(data)
    return json.dumps(data, indent=4, ensure_ascii=False)

  @token_syncing
  @rate_limited
  def get_athlete(self):
    data = json.loads(self.client.get_athlete().model_dump_json())
    logger.info(self.get_formatted_json(data))
    return data
