from django.db import migrations, models
import django.utils.timezone
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('policies', '0004_rename_policies_lo_date_em_16c24c_idx_policies_lo_date_433bd9_idx_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='LeavePolicy',
            fields=[
                ('created_at', models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('deleted_at', models.DateTimeField(blank=True, editable=False, null=True)),
                ('id', models.UUIDField(editable=False, primary_key=True, serialize=False)),
                ('monthly_accrual_days', models.DecimalField(decimal_places=2, default=0, max_digits=6, verbose_name='الاستحقاق الشهري (أيام)')),
                ('yearly_cap_days', models.DecimalField(decimal_places=2, default=0, max_digits=6, verbose_name='الحد السنوي (أيام)')),
                ('carry_over_max', models.DecimalField(decimal_places=2, default=0, max_digits=6, verbose_name='حد الترحيل السنوي (أيام)')),
                ('bundle', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='leave_policies', to='policies.policybundle', verbose_name='حزمة السياسة (leave)')),
            ],
            options={
                'verbose_name': 'سياسة إجازات (أيام)',
                'verbose_name_plural': 'سياسات إجازات (أيام)',
            },
        ),
        migrations.AddIndex(
            model_name='leavepolicy',
            index=models.Index(fields=['bundle'], name='policies_le_bundle_0c0c28_idx'),
        ),
    ]
