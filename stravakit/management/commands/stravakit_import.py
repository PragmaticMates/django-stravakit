import logging

import argparse
import os
import json
from datetime import datetime, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from stravakit.api import StravaApi
from stravakit.models import Activity, Athlete
from stravakit.services import sync

logger = logging.getLogger("file")


def parse_window_datetime(value):
    """A ``--after``/``--before`` value as an aware datetime.

    A naive value is read in the project's current timezone — "since 1 January" means local
    midnight, which is what whoever typed it meant. stravalib would otherwise take a naive
    datetime for UTC and quietly shift the window.
    """
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError(f"'{value}' is not a valid date — use YYYY-MM-DD")

    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


class Command(BaseCommand):
    help = (
        "Reads athlete data from Strava. With no arguments this is the incremental import: "
        "each athlete's activities since the newest one already stored. A window "
        "(--days/--after/--before) rescans history instead, which is the only way to pick up "
        "an activity that was uploaded, backdated or made public after the incremental "
        "cursor had already moved past it."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--days", type=int, default=None, metavar="N",
            help="Rescan a window of the last N days (ending at --before, else now).")
        parser.add_argument(
            "--after", type=parse_window_datetime, default=None, metavar="DATE",
            help="Only activities started after DATE (YYYY-MM-DD). Not usable with --days.")
        parser.add_argument(
            "--before", type=parse_window_datetime, default=None, metavar="DATE",
            help="Only activities started before DATE (YYYY-MM-DD).")
        parser.add_argument(
            "--missing", action="store_true",
            help="Only import activities with no local row yet; ones already stored are "
                 "skipped without spending a detail API call on them.")
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Report what would be imported without fetching details or writing.")

    def handle(self, *args, **options):
        # self.import_activities_from_file()
        after, before = self.resolve_window(options)
        self.import_activities_from_api(
            after=after,
            before=before,
            missing_only=options["missing"],
            dry_run=options["dry_run"],
        )

    def resolve_window(self, options):
        """The ``(after, before)`` bounds for this run; both ``None`` means incremental."""
        days = options.get("days")
        after = options.get("after")
        before = options.get("before")

        # call_command(**kwargs) skips argparse's type= converters, so a programmatic caller
        # can hand us the raw strings the command line would have parsed.
        after = parse_window_datetime(after) if isinstance(after, str) else after
        before = parse_window_datetime(before) if isinstance(before, str) else before

        if days is not None and after is not None:
            raise CommandError("--days and --after both set the start of the window; use one.")

        if days is not None:
            if days <= 0:
                raise CommandError("--days must be a positive number of days.")
            end = before or timezone.now()
            after = end - timedelta(days=days)

        if after and before and after >= before:
            raise CommandError(
                f"--after ({after:%Y-%m-%d %H:%M}) must be earlier than "
                f"--before ({before:%Y-%m-%d %H:%M})."
            )

        return after, before

    def import_activities_from_file(self):
        file_path = "/data/strava/activities.json"

        # Check if the file exists
        if not os.path.exists(file_path):
            logger.error(self.style.ERROR(f"File not found: {file_path}"))
            return

        with open(file_path, "r", encoding="utf-8") as file:
            activities = json.load(file)

        self.create_activities(activities)

    def import_activities_from_api(self, *, after=None, before=None, missing_only=False,
                                   dry_run=False):
        # Import each connected athlete's activities with their own token. An athlete is
        # "connected" once the OAuth flow has stored tokens on their row. (Legacy unowned
        # rows are attributed once, in migration 0011, not here.)
        athletes = list(Athlete.objects.connected())
        if not athletes:
            raise CommandError("No connected athletes to import — run the OAuth connect flow first.")

        # An explicit window replaces the per-athlete cursor, and marks this run as a
        # historical rescan rather than a catch-up — so it must not move `synced_at`, which
        # the dashboard shows as "Last updated".
        windowed = after is not None or before is not None
        self.stdout.write(self.describe_run(after, before, missing_only, dry_run))

        found_total = skipped_total = created_total = updated_total = 0

        for athlete in athletes:
            api = StravaApi(athlete)
            # Refresh the athlete profile (nav name/avatar/counts) on every import.
            if not dry_run:
                Athlete.store(api.get_athlete())

            athlete_after = after
            if not windowed:
                latest = Activity.objects.for_athlete(athlete).order_by('-start_date').first()
                athlete_after = latest.start_date if latest else None

            summaries = api.get_activities(after=athlete_after, before=before)
            found = len(summaries)
            if missing_only:
                summaries = self.only_missing(summaries)
            skipped = found - len(summaries)

            found_total += found
            skipped_total += skipped
            self.stdout.write(
                f"{athlete} ({athlete.pk}): {found} summaries, {skipped} already stored, "
                f"{len(summaries)} to fetch"
            )

            for summary in summaries:
                self.stdout.write(f"  {'would import' if dry_run else '+'} {self.describe(summary)}")
                if dry_run:
                    continue
                _activity, created = self.create_activity_from_json(
                    api.get_activity(summary['id']), athlete, api)
                if created:
                    created_total += 1
                else:
                    updated_total += 1

            # Record the successful sync time for this athlete (dashboard "Last updated").
            if not windowed and not dry_run:
                Athlete.objects.filter(pk=athlete.pk).update(synced_at=timezone.now())

        self.stdout.write(self.style.SUCCESS(
            f"Done: {len(athletes)} athlete(s), {found_total} summaries, {skipped_total} skipped, "
            f"{created_total} imported, {updated_total} updated"
            + (" (dry run — nothing written)" if dry_run else "")
        ))

    def only_missing(self, summaries):
        """The summaries with no local row yet.

        The lookup is deliberately *not* scoped to the athlete: ``Activity.id`` is Strava's
        globally unique activity id and our primary key, so an id present in the table is
        that activity, whoever owns the row. Scoping it would treat the legacy
        ``athlete=NULL`` rows as missing and spend a detail call re-fetching each of them on
        every run — exactly the cost this option exists to avoid. The flip side is that
        --missing will not backfill ownership of those rows (migration 0011 did that); a
        windowed run *without* --missing still refreshes them.
        """
        ids = [summary["id"] for summary in summaries]
        known = set(Activity.objects.filter(id__in=ids).values_list("id", flat=True))
        return [summary for summary in summaries if summary["id"] not in known]

    def describe_run(self, after, before, missing_only, dry_run):
        if after and before:
            window = f"{after:%Y-%m-%d} → {before:%Y-%m-%d}"
        elif after:
            window = f"since {after:%Y-%m-%d}"
        elif before:
            window = f"until {before:%Y-%m-%d}"
        else:
            window = "incremental (since each athlete's latest activity)"

        flags = "".join([
            ", missing only" if missing_only else "",
            ", dry run" if dry_run else "",
        ])
        return f"Strava import: {window}{flags}"

    def describe(self, summary):
        started = str(summary.get("start_date", ""))[:16].replace("T", " ")
        return f"{summary['id']}  {started}  {summary.get('sport_type', ''):<12} {summary.get('name', '')}"

    def create_activities(self, activities, athlete=None):
        for activity in activities:
            self.create_activity_from_json(activity, athlete)

    def create_activity_from_json(self, json_data, athlete=None, api=None):
        data = Activity.read_json(json_data)
        data['json'] = json_data
        data['athlete'] = athlete

        sync.gear_ensure(gear_id=data.get('gear_id'), api=api, athlete=athlete)
        activity, created = Activity.objects.update_or_create(
            id=json_data["id"],
            defaults=data,
        )

        if created:
            logger.info(f"Added: {activity}")
        else:
            logger.info(f"Skipped (exists): {activity}")

        return activity, created
