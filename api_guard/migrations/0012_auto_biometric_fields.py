from django.db import migrations, models

class Migration(migrations.Migration):

    dependencies = [
        ('api_guard', '0011_merge_20251007_1935'),
    ]

    operations = [
        migrations.AddField(
            model_name='attendancerecord',
            name='biometric_verified',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='attendancerecord',
            name='biometric_method',
            field=models.CharField(max_length=50, null=True, blank=True),
        ),
        migrations.AddField(
            model_name='attendancerecord',
            name='biometric_attempts',
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name='attendancerecord',
            name='check_type',
            field=models.CharField(max_length=20, null=True, blank=True),
        ),
        migrations.AddField(
            model_name='attendancerecord',
            name='is_violation',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='attendancerecord',
            name='timestamp',
            field=models.DateTimeField(null=True, blank=True),
        ),
    ]
