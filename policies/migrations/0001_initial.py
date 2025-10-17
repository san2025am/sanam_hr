from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('api_guard', '0013_contract_company_sign_and_overlap'),
    ]

    operations = [
        migrations.CreateModel(
            name='PolicyBundle',
            fields=[
                ('created_at', models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('deleted_at', models.DateTimeField(blank=True, editable=False, null=True)),
                ('id', models.UUIDField(editable=False, primary_key=True, serialize=False)),
                ('policy_type', models.CharField(choices=[('holiday', 'إجازات رسمية'), ('leave', 'إجازات'), ('payroll', 'الرواتب'), ('overtime_rewards', 'مكافآت إضافية'), ('deduction', 'خصومات')], db_index=True, max_length=50, verbose_name='نوع السياسة')),
                ('name', models.CharField(blank=True, max_length=200, null=True, verbose_name='اسم وصفي')),
                ('description', models.TextField(blank=True, null=True, verbose_name='وصف')),
                ('priority', models.PositiveIntegerField(default=100, help_text='الأصغر أقوى', verbose_name='الأولوية')),
                ('start_date', models.DateField(default=django.utils.timezone.now, verbose_name='تاريخ البدء')),
                ('end_date', models.DateField(blank=True, null=True, verbose_name='تاريخ الانتهاء')),
                ('is_active', models.BooleanField(default=True, verbose_name='مفعلة؟')),
                ('config', models.JSONField(blank=True, default=dict, verbose_name='تهيئة (JSON)')),
            ],
            options={
                'verbose_name': 'حزمة سياسة',
                'verbose_name_plural': 'حزم السياسات',
                'ordering': ['policy_type', 'priority', '-start_date'],
            },
        ),
        migrations.CreateModel(
            name='PolicyTarget',
            fields=[
                ('created_at', models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('deleted_at', models.DateTimeField(blank=True, editable=False, null=True)),
                ('id', models.UUIDField(editable=False, primary_key=True, serialize=False)),
                ('scope', models.CharField(choices=[('global', 'عام'), ('role', 'دور'), ('location', 'موقع'), ('shift', 'وردية')], db_index=True, max_length=20, verbose_name='النطاق')),
                ('bundle', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='targets', to='policies.policybundle', verbose_name='الحزمة')),
                ('location', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='api_guard.location', verbose_name='الموقع')),
                ('role', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='api_guard.role', verbose_name='الدور')),
                ('shift', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='api_guard.shift', verbose_name='الوردية')),
            ],
            options={
                'verbose_name': 'هدف سياسة',
                'verbose_name_plural': 'أهداف السياسات',
            },
        ),
        migrations.AddIndex(
            model_name='policybundle',
            index=models.Index(fields=['policy_type', 'priority', 'start_date', 'is_active'], name='policies_po_policy__c0f391_idx'),
        ),
        migrations.AddIndex(
            model_name='policytarget',
            index=models.Index(fields=['scope', 'role'], name='policies_po_scope_r_5b476a_idx'),
        ),
        migrations.AddIndex(
            model_name='policytarget',
            index=models.Index(fields=['scope', 'location'], name='policies_po_scope_l_48abdb_idx'),
        ),
        migrations.AddIndex(
            model_name='policytarget',
            index=models.Index(fields=['scope', 'shift'], name='policies_po_scope_s_1a44b3_idx'),
        ),
        migrations.AddConstraint(
            model_name='policytarget',
            constraint=models.CheckConstraint(
                check=(
                    models.Q(scope='global', role__isnull=True, location__isnull=True, shift__isnull=True)
                    | ~models.Q(scope='global')
                ),
                name='pol_target_global_null_refs',
            ),
        ),
        migrations.AddConstraint(
            model_name='policytarget',
            constraint=models.CheckConstraint(
                check=(
                    models.Q(scope='role', role__isnull=False, location__isnull=True, shift__isnull=True)
                    | ~models.Q(scope='role')
                ),
                name='pol_target_role_only',
            ),
        ),
        migrations.AddConstraint(
            model_name='policytarget',
            constraint=models.CheckConstraint(
                check=(
                    models.Q(scope='location', role__isnull=True, location__isnull=False, shift__isnull=True)
                    | ~models.Q(scope='location')
                ),
                name='pol_target_location_only',
            ),
        ),
        migrations.AddConstraint(
            model_name='policytarget',
            constraint=models.CheckConstraint(
                check=(
                    models.Q(scope='shift', role__isnull=True, location__isnull=True, shift__isnull=False)
                    | ~models.Q(scope='shift')
                ),
                name='pol_target_shift_only',
            ),
        ),
    ]
