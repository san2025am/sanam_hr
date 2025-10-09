from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api_guard", "0016_trusteddevice_refactor"),
    ]

    operations = [
        migrations.AddField(
            model_name="employeeshiftassignment",
            name="post_shift_buffer_minutes",
            field=models.PositiveIntegerField(
                default=0,
                help_text="يبقي التتبع فعالًا بعد الوردية الرسمية قبل تسجيل المخالفات.",
                verbose_name="مدة السماح بعد الوردية (دقائق)",
            ),
        ),
        migrations.AddField(
            model_name="employeeshiftassignment",
            name="pre_shift_buffer_minutes",
            field=models.PositiveIntegerField(
                default=0,
                help_text="يسمح للحارس بالتجهيز وتسجيل الحضور قبل بدء الوردية الرسمية.",
                verbose_name="مدة السماح قبل الوردية (دقائق)",
            ),
        ),
    ]
