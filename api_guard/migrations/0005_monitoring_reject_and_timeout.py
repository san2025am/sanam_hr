from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api_guard", "0004_tracking_start_mode"),
    ]

    operations = [
        migrations.AddField(
            model_name="locationmonitoringconfig",
            name="reject_outside_geofence",
            field=models.BooleanField(
                default=False,
                verbose_name="رفض النبضات خارج النطاق",
                help_text="إن فُعِّل سيتم رفض أي نبضة خارج الحدود الجغرافية مع كود OUT_OF_GEOFENCE.",
            ),
        ),
        migrations.AddField(
            model_name="locationmonitoringconfig",
            name="heartbeat_timeout_minutes",
            field=models.PositiveIntegerField(
                default=0,
                verbose_name="مهلة انقطاع النبضات (دقائق)",
                help_text="اعتبر التتبع متوقفًا تلقائيًا عند عدم وصول نبضات لهذه المدة (0 = تعطيل)",
            ),
        ),
    ]

