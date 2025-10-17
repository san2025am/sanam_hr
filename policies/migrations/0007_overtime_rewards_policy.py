from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('policies', '0006_rename_policies_le_bundle_0c0c28_idx_policies_le_bundle__00090c_idx_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='OvertimeRewardsPolicy',
            fields=[
                ('created_at', models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('deleted_at', models.DateTimeField(blank=True, editable=False, null=True)),
                ('id', models.UUIDField(editable=False, primary_key=True, serialize=False)),
                ('normal_rate', models.DecimalField(decimal_places=2, default=1.5, max_digits=5, verbose_name='معامل العادي')),
                ('night_rate', models.DecimalField(decimal_places=2, default=1.75, max_digits=5, verbose_name='معامل الليلي')),
                ('offday_rate', models.DecimalField(decimal_places=2, default=2.0, max_digits=5, verbose_name='معامل يوم الراحة')),
                ('public_holiday_rate', models.DecimalField(decimal_places=2, default=2.5, max_digits=5, verbose_name='معامل العطلة الرسمية')),
                ('night_window_start', models.TimeField(default=django.utils.timezone.datetime(2000, 1, 1, 22, 0, tzinfo=None).time(), verbose_name='بداية الليلي')),
                ('night_window_end', models.TimeField(default=django.utils.timezone.datetime(2000, 1, 1, 6, 0, tzinfo=None).time(), verbose_name='نهاية الليلي')),
                ('monthly_hours_cap', models.DecimalField(blank=True, decimal_places=2, max_digits=6, null=True, verbose_name='سقف ساعات شهري')),
                ('bundle', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='overtime_policies', to='policies.policybundle', verbose_name='حزمة السياسة (overtime_rewards)')),
            ],
            options={
                'verbose_name': 'سياسة إضافي ومكافآت',
                'verbose_name_plural': 'سياسات إضافي ومكافآت',
            },
        ),
        migrations.AddIndex(
            model_name='overtimerewardspolicy',
            index=models.Index(fields=['bundle'], name='policies_ov_bundle_bfa191_idx'),
        ),
    ]

