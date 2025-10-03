# Generated manually for trusted device support

import uuid
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('api_guard', '0007_attendancerecord_early_attachment_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='TrustedDevice',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('deleted_at', models.DateTimeField(blank=True, editable=False, null=True)),
                ('device_hash', models.CharField(max_length=128, verbose_name='بصمة الجهاز')),
                ('device_name', models.CharField(blank=True, max_length=200, verbose_name='اسم الجهاز')),
                ('first_seen_at', models.DateTimeField(auto_now_add=True, verbose_name='أول ظهور')),
                ('last_seen_at', models.DateTimeField(auto_now=True, verbose_name='آخر ظهور')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='trusted_devices', to=settings.AUTH_USER_MODEL, verbose_name='المستخدم')),
            ],
            options={
                'verbose_name': 'جهاز موثوق',
                'verbose_name_plural': 'الأجهزة الموثوقة',
                'unique_together': {('user', 'device_hash')},
            },
        ),
        migrations.CreateModel(
            name='DeviceLoginChallenge',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('deleted_at', models.DateTimeField(blank=True, editable=False, null=True)),
                ('device_hash', models.CharField(max_length=128, verbose_name='بصمة الجهاز')),
                ('device_name', models.CharField(blank=True, max_length=200, verbose_name='اسم الجهاز')),
                ('code_hash', models.CharField(max_length=128, verbose_name='هاش رمز التحقق')),
                ('expires_at', models.DateTimeField(verbose_name='ينتهي في')),
                ('attempts', models.PositiveSmallIntegerField(default=0, verbose_name='عدد المحاولات')),
                ('verified_at', models.DateTimeField(blank=True, null=True, verbose_name='وقت التوثيق')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='device_login_challenges', to=settings.AUTH_USER_MODEL, verbose_name='المستخدم')),
            ],
            options={
                'verbose_name': 'طلب توثيق جهاز',
                'verbose_name_plural': 'طلبات توثيق الأجهزة',
            },
        ),
        migrations.AddIndex(
            model_name='deviceloginchallenge',
            index=models.Index(fields=['user', 'device_hash'], name='api_guard_d_user_id_6ed861_idx'),
        ),
        migrations.AddIndex(
            model_name='deviceloginchallenge',
            index=models.Index(fields=['expires_at'], name='api_guard_d_expires_5c3ed4_idx'),
        ),
    ]
