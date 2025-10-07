from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('api_guard', '0012_auto_biometric_fields'),
    ]

    operations = [
        migrations.CreateModel(
            name='LocationPing',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('latitude', models.FloatField()),
                ('longitude', models.FloatField()),
                ('accuracy', models.FloatField(blank=True, null=True)),
                ('distance_m', models.FloatField(blank=True, null=True)),
                ('within_radius', models.BooleanField(default=True)),
                ('violation_triggered', models.BooleanField(default=False)),
                ('recorded_at', models.DateTimeField(default=django.utils.timezone.now, verbose_name='وقت التسجيل')),
                ('employee', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='location_pings', to='api_guard.employee', verbose_name='الموظف')),
                ('location', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='location_pings', to='api_guard.location', verbose_name='الموقع')),
            ],
            options={
                'verbose_name': '7.1 تتبع موقع',
                'verbose_name_plural': '7.1 تتبع المواقع',
                'ordering': ['-recorded_at'],
            },
        ),
    ]
