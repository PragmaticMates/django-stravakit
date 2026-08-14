from django.db import migrations, models


def forwards(apps, schema_editor):
    Activity = apps.get_model("stravakit", "Activity")
    activity_fields = [
        "moving_time", "elapsed_time", "total_elevation_gain", "average_speed",
        "max_speed", "average_heartrate", "max_heartrate",
        "kudos_count", "total_photo_count", "photo_url", "start_lat", "start_lng",
    ]
    batch = []
    for a in Activity.objects.all().iterator():
        j = a.json or {}
        primary = (j.get("photos") or {}).get("primary") or {}
        urls = primary.get("urls") or {}
        latlng = j.get("start_latlng") or []
        has_gps = len(latlng) == 2 and bool(latlng[0] or latlng[1])
        a.moving_time = j.get("moving_time")
        a.elapsed_time = j.get("elapsed_time")
        a.total_elevation_gain = j.get("total_elevation_gain")
        a.average_speed = j.get("average_speed")
        a.max_speed = j.get("max_speed")
        a.average_heartrate = j.get("average_heartrate")
        a.max_heartrate = j.get("max_heartrate")
        a.kudos_count = j.get("kudos_count", 0) or 0
        a.total_photo_count = j.get("total_photo_count", 0) or 0
        a.photo_url = urls.get("600") or urls.get("100") or ""
        a.start_lat = round(float(latlng[0]), 6) if has_gps else None
        a.start_lng = round(float(latlng[1]), 6) if has_gps else None
        batch.append(a)
    if batch:
        Activity.objects.bulk_update(batch, activity_fields, batch_size=500)

    Gear = apps.get_model("stravakit", "Gear")
    batch = []
    for g in Gear.objects.all().iterator():
        g.gear_type = "bike" if (g.json or {}).get("frame_type") is not None else "shoe"
        batch.append(g)
    if batch:
        Gear.objects.bulk_update(batch, ["gear_type"], batch_size=500)


class Migration(migrations.Migration):

    dependencies = [
        ("stravakit", "0003_activity_distance"),
    ]

    operations = [
        migrations.AddField(
            model_name="activity",
            name="moving_time",
            field=models.PositiveIntegerField(blank=True, null=True, verbose_name="moving time"),
        ),
        migrations.AddField(
            model_name="activity",
            name="elapsed_time",
            field=models.PositiveIntegerField(blank=True, null=True, verbose_name="elapsed time"),
        ),
        migrations.AddField(
            model_name="activity",
            name="total_elevation_gain",
            field=models.FloatField(blank=True, null=True, verbose_name="elevation gain"),
        ),
        migrations.AddField(
            model_name="activity",
            name="average_speed",
            field=models.FloatField(blank=True, null=True, verbose_name="average speed"),
        ),
        migrations.AddField(
            model_name="activity",
            name="max_speed",
            field=models.FloatField(blank=True, null=True, verbose_name="max speed"),
        ),
        migrations.AddField(
            model_name="activity",
            name="average_heartrate",
            field=models.FloatField(blank=True, null=True, verbose_name="average heartrate"),
        ),
        migrations.AddField(
            model_name="activity",
            name="max_heartrate",
            field=models.FloatField(blank=True, null=True, verbose_name="max heartrate"),
        ),
        migrations.AddField(
            model_name="activity",
            name="kudos_count",
            field=models.PositiveIntegerField(default=0, verbose_name="kudos"),
        ),
        migrations.AddField(
            model_name="activity",
            name="total_photo_count",
            field=models.PositiveIntegerField(default=0, verbose_name="photos"),
        ),
        migrations.AddField(
            model_name="activity",
            name="photo_url",
            field=models.URLField(blank=True, default="", max_length=500, verbose_name="photo URL"),
        ),
        migrations.AddField(
            model_name="activity",
            name="start_lat",
            field=models.FloatField(blank=True, null=True, verbose_name="start latitude"),
        ),
        migrations.AddField(
            model_name="activity",
            name="start_lng",
            field=models.FloatField(blank=True, null=True, verbose_name="start longitude"),
        ),
        migrations.AddField(
            model_name="gear",
            name="gear_type",
            field=models.CharField(
                choices=[("bike", "bike"), ("shoe", "shoe")],
                default="shoe", max_length=4, verbose_name="type",
            ),
        ),
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
