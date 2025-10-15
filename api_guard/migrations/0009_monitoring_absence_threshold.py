from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api_guard", "0008_employee_photo_badge_code"),
    ]

    operations = [
        migrations.AddField(
            model_name="locationmonitoringconfig",
            name="absence_withdrawals_threshold",
            field=models.PositiveIntegerField(
                default=0,
                verbose_name="حدّ مرات الانسحاب لتسجيل غياب",
                help_text=(
                    "عند تكرار وقائع الانسحاب خلال نفس الوردية بهذا العدد أو أكثر يتم تصعيد الحالة إلى غياب. (0 = تعطيل)"
                ),
            ),
        ),
    ]

