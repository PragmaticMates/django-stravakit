# django-stravakit

Reusable Django app for Strava API integration. Provides models for Activities and Gear, a management command for importing data, and a rich admin interface powered by [django-unfold](https://github.com/unfoldadmin/django-unfold).

## Requirements

- Python 3.10+
- Django 5.1+
- PostgreSQL (uses `jsonb_extract_path_text`, `unaccent`)

Python dependencies (installed automatically):

- [stravalib](https://github.com/stravalib/stravalib) — Strava API client (also provides the rate limiter)
- [django-unfold](https://github.com/unfoldadmin/django-unfold) — admin UI framework
- [django-htmx](https://github.com/adamchainz/django-htmx) — htmx integration for the frontend pages

## Installation

```bash
pip install django-stravakit
```

The distribution is `django-stravakit`; the app it installs is imported as `stravakit`.

Add `stravakit`, `django.contrib.humanize` and `django_htmx` to `INSTALLED_APPS`, and the htmx middleware to `MIDDLEWARE`:

```python
INSTALLED_APPS = [
    # ...
    "unfold",
    "django.contrib.humanize",
    "django_htmx",
    "stravakit",
]

MIDDLEWARE = [
    # ...
    "django_htmx.middleware.HtmxMiddleware",
]
```

The activities page uses [htmx](https://htmx.org/) (via
[django-htmx](https://github.com/adamchainz/django-htmx)) for server-side filtering, sorting and
stat calculation. The htmx runtime is served by `{% htmx_script %}` — no CDN required.

Wire up the URLs in your project's `urls.py` to expose the frontend pages:

```python
from django.urls import include, path

urlpatterns = [
    # ...
    path("strava/", include("stravakit.urls", namespace="stravakit")),
]
```

Run migrations:

```bash
python manage.py migrate
```

## Configuration

Add your Strava API credentials to your Django settings (the app reads them via
`getattr(settings, ...)`). Source them however you like — e.g. from environment variables:

```python
# settings.py
STRAVA_CLIENT_ID = "..."
STRAVA_CLIENT_SECRET = "..."
STRAVA_ACCESS_TOKEN = "..."
STRAVA_REFRESH_TOKEN = "..."
STRAVA_TOKEN_EXPIRES = "..."  # optional, format: 2024-01-01T00:00:00Z
```

### Rate limiting

API calls respect [Strava's rate limits](https://developers.strava.com/docs/rate-limits/).
Requests are proactively spaced out to stay within the limits, and any `429`
(rate limit exceeded) response is retried after sleeping until the offending
limit window resets. Two optional settings tune this behaviour:

```python
# settings.py
STRAVA_RATE_LIMIT_PRIORITY = "medium"  # optional, one of: high, medium, low (default: medium)
STRAVA_RATE_LIMIT_MAX_RETRIES = 3      # optional, retries after a 429 (default: 3)
```

- `high` — no proactive throttling (burst until a limit is hit)
- `medium` — spread requests so the short-term (15 min) limit is not exceeded
- `low` — spread requests so the daily limit is not exceeded

## Usage

### Import activities

Import activities from the Strava API:

```bash
python manage.py stravakit_import
```

The command fetches all activities newer than the latest one in the database. On first run, it imports all available activities.

#### Backfilling activities the incremental import missed

Because the cursor is "newer than the latest one stored", an activity that appears *behind*
it — uploaded a day late, backdated by hand, or made public after the importer had already
passed — is never picked up. Rescan a window to find those:

```bash
python manage.py stravakit_import --days 90 --missing            # last 90 days, gaps only
python manage.py stravakit_import --days 90 --missing --dry-run  # report, change nothing
python manage.py stravakit_import --after 2025-01-01 --before 2025-04-01
```

| Option | Meaning |
| --- | --- |
| `--days N` | Window of the last N days (counted back from `--before`, else now). |
| `--after DATE` | Explicit window start, `YYYY-MM-DD`. Not usable with `--days`. |
| `--before DATE` | Explicit window end. |
| `--missing` | Import only activities with no local row; skip the rest without spending a detail API call on them. |
| `--dry-run` | List what would be imported; fetch no details and write nothing. |

`--missing` is what makes a routine rescan cheap: a 90-day window is one list request plus
one detail request per genuinely missing activity, so a week where nothing was missed costs
2–3 requests. Without it the same window re-fetches every activity in range, which for 90
days sits right at Strava's 100-requests-per-15-minutes limit — use that only when you
actually want to refresh stored rows (names, kudos, gear links).

A windowed run deliberately leaves `Athlete.synced_at` alone: rescanning history is not the
same as being up to date, and that field is what the dashboard shows as "Last updated".

For a long historical backfill, walk it in chunks (`--days 90 --before <date>`) rather than
opening one enormous window, so a single run can't exhaust the daily quota.

### Pages

The app ships a set of htmx-powered pages (registered under the `stravakit` URL namespace).
All filtering, sorting and stat recalculation happens server-side and is swapped in
without a full page reload.

- **Dashboard** (`stravakit:dashboard`) — headline stats, "By the Numbers" totals,
  personal records (including "Furthest from Home"), run-performance breakdown, gear
  summary, the latest activity, and an activity map. The map controls (search +
  sport/gear/year filters) recompute every section live.
- **Activities** (`stravakit:activities`) — searchable, sortable list of activities with
  filtering by sport, gear and month, a summary band (distance, elevation, time, this
  week) and grid/table views.
- **Gear** (`stravakit:gear`) — gear cards showing usage, wear level and replacement alerts.
- **Gallery** (`stravakit:gallery`) — photo gallery of activities that have images.

### Admin interface

The app registers `Activity` and `Gear` models in the Django admin with:

- Filtering by sport type, gear, distance range, and sync status
- Display of pace, speed, heartrate, elevation, and time
- Actions to import, fetch, and sync activities with the Strava API
- Full-text search with PostgreSQL `unaccent` support

### Models

**Activity** - Stores Strava activities with extracted fields (name, sport type, distance, start date, gear) and the raw API JSON response.

**Gear** - Stores gear details (brand, model, description). Automatically fetched from the API when first referenced by an activity.

**Athlete** - Stores the authenticated athlete's profile (name, avatar, city/country, follower and following counts). Populated by `stravakit_import` (and the dashboard refresh button) so the site chrome shows the real athlete instead of a hardcoded name. The frontend reads it via `Athlete.current()`; the app is single-athlete.

`Activity` and `Gear` carry a nullable `athlete` foreign key (`on_delete=CASCADE`) identifying their owner. It's set during import; rows imported before athlete linking existed are backfilled to the athlete on the next import.

### Customising the site chrome

The nav name, avatar and follower/following counts are driven by the imported `Athlete` — nothing is hardcoded. The two branding elements in `stravakit/pages/base.html` are exposed as template blocks, so a consuming project can override them by extending the base template:

- `{% block brand %}` — the name shown in the page `<title>` (defaults to `django-stravakit`)
- `{% block logo %}` — the header logo SVG

## License

[GNU General Public License v3](LICENSE)
