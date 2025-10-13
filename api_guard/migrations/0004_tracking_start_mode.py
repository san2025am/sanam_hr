from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api_guard", "0003_rename_geo_pause_emp_until_idx_api_guard_g_employe_97f277_idx_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="locationmonitoringconfig",
            name="tracking_start_mode",
            field=models.CharField(
                default="check_in",
                max_length=20,
                choices=[("check_in", "يبدأ من تسجيل الحضور"), ("shift_start", "يبدأ من بداية الوردية")],
                verbose_name="متى يبدأ التتبّع",
                help_text="اختر ما إذا كان التتبّع يبدأ من بداية الوردية أو بعد تسجيل الحضور.",
            ),
        ),
    ]

