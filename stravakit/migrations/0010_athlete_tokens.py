from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stravakit', '0009_activity_athlete_gear_athlete'),
    ]

    operations = [
        migrations.AddField(
            model_name='athlete',
            name='access_token',
            field=models.CharField(blank=True, default='', max_length=100, verbose_name='access token'),
        ),
        migrations.AddField(
            model_name='athlete',
            name='refresh_token',
            field=models.CharField(blank=True, default='', max_length=100, verbose_name='refresh token'),
        ),
        migrations.AddField(
            model_name='athlete',
            name='token_expires_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='token expires at'),
        ),
        migrations.AddField(
            model_name='athlete',
            name='scope',
            field=models.CharField(blank=True, default='', max_length=200, verbose_name='scope'),
        ),
        migrations.AddField(
            model_name='athlete',
            name='is_default',
            field=models.BooleanField(default=False, verbose_name='default'),
        ),
        migrations.AddConstraint(
            model_name='athlete',
            constraint=models.UniqueConstraint(
                condition=models.Q(('is_default', True)),
                fields=('is_default',),
                name='one_default_athlete',
            ),
        ),
    ]
