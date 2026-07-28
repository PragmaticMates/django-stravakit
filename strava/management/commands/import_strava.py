import logging

import os
import json
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from strava.api import StravaApi
from strava.models import Activity, Athlete
from strava.services import sync

logger = logging.getLogger("file")


class Command(BaseCommand):
    help = "Reads athlete data from Strava"

    def handle(self, *args, **options):
        # self.import_activities_from_file()
        self.import_activities_from_api()

    def import_activities_from_file(self):
        file_path = "/data/strava/activities.json"

        # Check if the file exists
        if not os.path.exists(file_path):
            logger.error(self.style.ERROR(f"File not found: {file_path}"))
            return

        with open(file_path, "r", encoding="utf-8") as file:
            activities = json.load(file)

        self.create_activities(activities)

    def import_activities_from_api(self):
        # Import each connected athlete's activities with their own token. An athlete is
        # "connected" once the OAuth flow has stored tokens on their row. (Legacy unowned
        # rows are attributed once, in migration 0011, not here.)
        athletes = list(Athlete.objects.connected())
        if not athletes:
            raise CommandError("No connected athletes to import — run the OAuth connect flow first.")

        for athlete in athletes:
            api = StravaApi(athlete)
            # Refresh the athlete profile (nav name/avatar/counts) on every import.
            Athlete.store(api.get_athlete())
            latest = Activity.objects.for_athlete(athlete).order_by('-start_date').first()
            after = latest.start_date if latest else None
            for summary in api.get_activities(after=after):
                self.create_activity_from_json(api.get_activity(summary['id']), athlete, api)
            # Record the successful sync time for this athlete (dashboard "Last updated").
            Athlete.objects.filter(pk=athlete.pk).update(synced_at=timezone.now())

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
