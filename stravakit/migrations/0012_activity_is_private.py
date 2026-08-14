from django.db import migrations, models


def backfill_is_private(apps, schema_editor):
    """Populate the new `is_private` column from each activity's stored JSON, so existing
    rows match what read_json now writes on import (Strava's `private` flag)."""
    Activity = apps.get_model("stravakit", "Activity")
    batch = []
    for a in Activity.objects.all().iterator():
        a.is_private = bool((a.json or {}).get("private"))
        batch.append(a)
    if batch:
        Activity.objects.bulk_update(batch, ["is_private"], batch_size=500)


class Migration(migrations.Migration):

    dependencies = [
        ("stravakit", "0011_seed_default_athlete"),
    ]

    operations = [
        migrations.AddField(
            model_name="activity",
            name="is_private",
            field=models.BooleanField(default=False, verbose_name="private"),
        ),
        migrations.RunPython(backfill_is_private, migrations.RunPython.noop),
    ]
