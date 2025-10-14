from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("api_guard", "0006_report_current_stage_report_last_response_at_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="attendancerecord",
            name="lat",
            field=models.FloatField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name="attendancerecord",
            name="lng",
            field=models.FloatField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name="attendancerecord",
            name="accuracy",
            field=models.FloatField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name="attendancerecord",
            name="location_age_ms",
            field=models.IntegerField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name="attendancerecord",
            name="provider",
            field=models.CharField(max_length=20, null=True, blank=True),
        ),
        migrations.AddField(
            model_name="attendancerecord",
            name="is_mock",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="attendancerecord",
            name="integrity_verdict",
            field=models.CharField(max_length=64, null=True, blank=True),
        ),
        migrations.AddField(
            model_name="attendancerecord",
            name="integrity_details",
            field=models.JSONField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name="attendancerecord",
            name="device_id",
            field=models.CharField(max_length=128, null=True, blank=True),
        ),
        migrations.AddField(
            model_name="attendancerecord",
            name="app_version",
            field=models.CharField(max_length=50, null=True, blank=True),
        ),
        migrations.AddField(
            model_name="attendancerecord",
            name="os_version",
            field=models.CharField(max_length=100, null=True, blank=True),
        ),
        migrations.AddField(
            model_name="attendancerecord",
            name="ip",
            field=models.GenericIPAddressField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name="attendancerecord",
            name="asn",
            field=models.CharField(max_length=50, null=True, blank=True),
        ),
        migrations.AddField(
            model_name="attendancerecord",
            name="vpn_suspected",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="attendancerecord",
            name="confidence_score",
            field=models.FloatField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name="attendancerecord",
            name="reason_code",
            field=models.CharField(max_length=60, null=True, blank=True),
        ),
        migrations.AddField(
            model_name="attendancerecord",
            name="policy_version",
            field=models.CharField(max_length=20, null=True, blank=True),
        ),
        migrations.AddField(
            model_name="attendancerecord",
            name="decision_path",
            field=models.CharField(max_length=255, null=True, blank=True),
        ),
    ]

