# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

django-stravakit (distribution name; the app is imported as `strava`) is a reusable Django app that integrates with the Strava API. It provides models for Activities and Gear, a management command for importing data, and a rich admin interface powered by django-unfold.

## Dependencies

- **Django** (5.1+) with PostgreSQL (uses `jsonb_extract_path_text`, `unaccent`)
- **stravalib** - Strava API client
- **django-unfold** - admin UI framework (provides `@action`, `@display` decorators, `RangeNumericListFilter`)

## Architecture

- **models.py** - `Activity` and `Gear` models. Both store raw API JSON in a `JSONField` alongside extracted fields. Sync status is tracked by comparing model fields against stored JSON.
- **api.py** - `StravaApi` wrapper around `stravalib.Client`. Auth credentials are read from Django settings via `getattr(settings, ...)`: `STRAVA_CLIENT_ID`, `STRAVA_CLIENT_SECRET`, `STRAVA_ACCESS_TOKEN`, `STRAVA_REFRESH_TOKEN`, `STRAVA_TOKEN_EXPIRES` (plus optional `STRAVA_RATE_LIMIT_PRIORITY`, `STRAVA_RATE_LIMIT_MAX_RETRIES`). The consuming project decides how to populate those settings (e.g. from env).
- **views.py** - Class-based views for the htmx-powered frontend pages (dashboard, activities, gear, gallery). Each view's `get_template_names()` returns an `hx/` fragment for htmx requests and the full page otherwise; all filtering/sorting/stat recalculation happens server-side.
- **querysets.py** - `ActivityQuerySet` with PostgreSQL-specific JSON queries (e.g., `gear_unsynced()` uses `jsonb_extract_path_text`).
- **admin.py** - Uses django-unfold decorators exclusively (not standard Django admin decorators). Rich display methods for pace, speed, heartrate, elevation, etc.
- **choices.py** - `SportType` as `models.TextChoices` with 56 sport types.
- **management/commands/import_strava.py** - `import_strava` command that fetches activities from API or file and creates/updates records. With no arguments it is incremental: everything newer than each athlete's latest stored activity. `--days/--after/--before` replace that cursor with an explicit window (a rescan, so it does not touch `Athlete.synced_at`), and `--missing` restricts the run to activities with no local row, which is the only cheap way to backfill gaps — see the README for the cost argument.

## Frontend layout

Templates and static files are app-namespaced (so names can't collide with another app):

- **templates/strava/pages/** - full pages: `base.html` and `dashboard/activities/gear/gallery.html`.
- **templates/strava/hx/** - htmx response fragments (no leading underscore): the `*_results.html`
  fragments returned for htmx requests, plus the `dashboard_*.html` section partials that are
  OOB-swapped into the dashboard and also `{% include %}`d by the full dashboard page.
- **templates/strava/widgets/** - reusable `{% include %}` partials (activity card, gear card,
  sport icon, `_fc_pill.html`).
- **templates/strava/tables/** - table fragments.
- **static/strava/css/** - `strava.css`.
- **static/strava/js/** - feature-split modules: `charts.js` (shared `DSCharts` SVG/canvas render
  library), `ui.js` (site-wide nav/menu/lightbox/timing, loaded by `base.html`), `dashboard-map.js`
  (Leaflet map), `dashboard.js` (records/trends/calendar wiring, activity modal, gear donut),
  `activities.js`, `gallery.js`, `gear.js`. There is no inline `<script>` in the templates.

The frontend renders only real server data — there is no client-side mock/demo data. Server data
reaches the dashboard JS through `json_script` blocks in `hx/dashboard_data.html`; when a block is
absent the section renders empty rather than fabricating values.

## Key Patterns

- Raw Strava API responses are stored in `json` JSONField; relevant fields are extracted into model fields via `read_json()` / `update_from_json()`
- Gear is lazily fetched from Strava API when first encountered via a foreign key
- Admin uses `list_select_related` and queryset annotations (`Count`, `Sum`) for performance
- All user-facing strings use `gettext_lazy` for i18n
- Search uses PostgreSQL `unaccent` extension

## License

GNU General Public License v3
