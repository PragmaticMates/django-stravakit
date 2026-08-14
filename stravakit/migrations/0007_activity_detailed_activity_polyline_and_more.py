from django.db import migrations, models

# Scalar DetailedActivity-only fields (kept inline so the migration is self-contained
# and doesn't drift if the model constant later changes).
DETAIL_MARKER_FIELDS = ("embed_token", "calories", "description", "device_name")


def backfill_promoted_fields(apps, schema_editor):
    """Populate the newly promoted `polyline` / `is_detailed` columns from each activity's
    stored JSON, so existing rows match what read_json now writes on import."""
    Activity = apps.get_model("stravakit", "Activity")
    batch = []
    for a in Activity.objects.all().iterator():
        j = a.json or {}
        route = j.get("map") or {}
        a.polyline = route.get("polyline") or route.get("summary_polyline") or ""
        a.is_detailed = any(j.get(field) is not None for field in DETAIL_MARKER_FIELDS)
        batch.append(a)
    if batch:
        Activity.objects.bulk_update(batch, ["polyline", "is_detailed"], batch_size=500)


class Migration(migrations.Migration):

    dependencies = [
        ('stravakit', '0006_activity_achievement_count_activity_comment_count_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='activity',
            name='is_detailed',
            field=models.BooleanField(default=False, verbose_name='detailed'),
        ),
        migrations.AddField(
            model_name='activity',
            name='polyline',
            field=models.TextField(blank=True, default='', verbose_name='polyline'),
        ),
        migrations.AlterField(
            model_name='activity',
            name='distance',
            field=models.FloatField(verbose_name='distance'),
        ),
        migrations.RunPython(backfill_promoted_fields, migrations.RunPython.noop),
    ]
