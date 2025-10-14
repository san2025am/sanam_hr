from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("api_guard", "0007_attendance_security_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name='employee',
            name='profile_photo',
            field=models.ImageField(blank=True, null=True, upload_to='employee_photos/', verbose_name='صورة الموظف'),
        ),
        migrations.AddField(
            model_name='employee',
            name='badge_code',
            field=models.CharField(blank=True, max_length=8, null=True, unique=True, verbose_name='رقم الموظف (8 خانات)'),
        ),
    ]

