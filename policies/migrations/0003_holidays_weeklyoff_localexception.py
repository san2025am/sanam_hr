from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('api_guard', '0013_contract_company_sign_and_overlap'),
        ('policies', '0002_rename_policies_po_policy__c0f391_idx_policies_po_policy__60b580_idx_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='WeeklyOff',
            fields=[
                ('created_at', models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('deleted_at', models.DateTimeField(blank=True, editable=False, null=True)),
                ('id', models.UUIDField(editable=False, primary_key=True, serialize=False)),
                ('scope', models.CharField(choices=[('global', 'عام'), ('role', 'دور'), ('location', 'موقع'), ('shift', 'وردية')], db_index=True, max_length=20, verbose_name='النطاق')),
                ('day_of_week', models.IntegerField(choices=[(0, 'الاثنين'), (1, 'الثلاثاء'), (2, 'الأربعاء'), (3, 'الخميس'), (4, 'الجمعة'), (5, 'السبت'), (6, 'الأحد')], db_index=True, verbose_name='اليوم الأسبوعي')),
                ('priority', models.PositiveIntegerField(default=100, help_text='الأصغر أقوى', verbose_name='الأولوية')),
                ('start_date', models.DateField(default=django.utils.timezone.now, verbose_name='تاريخ البدء')),
                ('end_date', models.DateField(blank=True, null=True, verbose_name='تاريخ الانتهاء')),
                ('is_active', models.BooleanField(default=True, verbose_name='مفعلة؟')),
                ('location', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='api_guard.location', verbose_name='الموقع')),
                ('role', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='api_guard.role', verbose_name='الدور')),
                ('shift', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='api_guard.shift', verbose_name='الوردية')),
            ],
            options={
                'verbose_name': 'راحة أسبوعية',
                'verbose_name_plural': 'أيام الراحة الأسبوعية',
            },
        ),
        migrations.CreateModel(
            name='PublicHoliday',
            fields=[
                ('created_at', models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('deleted_at', models.DateTimeField(blank=True, editable=False, null=True)),
                ('id', models.UUIDField(editable=False, primary_key=True, serialize=False)),
                ('name', models.CharField(max_length=200, verbose_name='اسم العطلة')),
                ('date', models.DateField(verbose_name='التاريخ')),
                ('repeats_annually', models.BooleanField(default=True, verbose_name='تكرار سنوي؟')),
                ('scope', models.CharField(choices=[('global', 'عام'), ('role', 'دور'), ('location', 'موقع'), ('shift', 'وردية')], db_index=True, default='global', max_length=20, verbose_name='النطاق')),
                ('is_active', models.BooleanField(default=True, verbose_name='مفعلة؟')),
                ('location', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='api_guard.location', verbose_name='الموقع')),
                ('role', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='api_guard.role', verbose_name='الدور')),
                ('shift', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='api_guard.shift', verbose_name='الوردية')),
            ],
            options={
                'verbose_name': 'عطلة رسمية',
                'verbose_name_plural': 'عطل رسمية',
            },
        ),
        migrations.CreateModel(
            name='LocalException',
            fields=[
                ('created_at', models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('deleted_at', models.DateTimeField(blank=True, editable=False, null=True)),
                ('id', models.UUIDField(editable=False, primary_key=True, serialize=False)),
                ('date', models.DateField(verbose_name='التاريخ')),
                ('effect', models.CharField(choices=[('make_off', 'اجعل عطلة'), ('make_working', 'اجعل عمل')], max_length=20, verbose_name='التأثير')),
                ('notes', models.TextField(blank=True, null=True, verbose_name='ملاحظة')),
                ('employee', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='api_guard.employee', verbose_name='الموظف')),
                ('location', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='api_guard.location', verbose_name='الموقع')),
            ],
            options={
                'verbose_name': 'استثناء محلي',
                'verbose_name_plural': 'استثناءات محلية',
            },
        ),
        migrations.AddIndex(
            model_name='weeklyoff',
            index=models.Index(fields=['scope', 'day_of_week', 'priority', 'start_date', 'is_active'], name='policies_we_scope_d_68fd17_idx'),
        ),
        migrations.AddIndex(
            model_name='publicholiday',
            index=models.Index(fields=['scope', 'date', 'repeats_annually', 'is_active'], name='policies_pu_scope_d_4a60e4_idx'),
        ),
        migrations.AddIndex(
            model_name='localexception',
            index=models.Index(fields=['date', 'employee', 'location'], name='policies_lo_date_em_16c24c_idx'),
        ),
        migrations.AddConstraint(
            model_name='weeklyoff',
            constraint=models.CheckConstraint(
                check=(models.Q(scope='global', role__isnull=True, location__isnull=True, shift__isnull=True) | ~models.Q(scope='global')),
                name='weeklyoff_global_only',
            ),
        ),
        migrations.AddConstraint(
            model_name='weeklyoff',
            constraint=models.CheckConstraint(
                check=(models.Q(scope='role', role__isnull=False, location__isnull=True, shift__isnull=True) | ~models.Q(scope='role')),
                name='weeklyoff_role_only',
            ),
        ),
        migrations.AddConstraint(
            model_name='weeklyoff',
            constraint=models.CheckConstraint(
                check=(models.Q(scope='location', role__isnull=True, location__isnull=False, shift__isnull=True) | ~models.Q(scope='location')),
                name='weeklyoff_location_only',
            ),
        ),
        migrations.AddConstraint(
            model_name='weeklyoff',
            constraint=models.CheckConstraint(
                check=(models.Q(scope='shift', role__isnull=True, location__isnull=True, shift__isnull=False) | ~models.Q(scope='shift')),
                name='weeklyoff_shift_only',
            ),
        ),
        migrations.AddConstraint(
            model_name='publicholiday',
            constraint=models.CheckConstraint(
                check=(models.Q(scope='global', role__isnull=True, location__isnull=True, shift__isnull=True) | ~models.Q(scope='global')),
                name='holiday_scope_global_only',
            ),
        ),
        migrations.AddConstraint(
            model_name='publicholiday',
            constraint=models.CheckConstraint(
                check=(models.Q(scope='role', role__isnull=False, location__isnull=True, shift__isnull=True) | ~models.Q(scope='role')),
                name='holiday_scope_role_only',
            ),
        ),
        migrations.AddConstraint(
            model_name='publicholiday',
            constraint=models.CheckConstraint(
                check=(models.Q(scope='location', role__isnull=True, location__isnull=False, shift__isnull=True) | ~models.Q(scope='location')),
                name='holiday_scope_location_only',
            ),
        ),
        migrations.AddConstraint(
            model_name='publicholiday',
            constraint=models.CheckConstraint(
                check=(models.Q(scope='shift', role__isnull=True, location__isnull=True, shift__isnull=False) | ~models.Q(scope='shift')),
                name='holiday_scope_shift_only',
            ),
        ),
        migrations.AddConstraint(
            model_name='localexception',
            constraint=models.CheckConstraint(
                check=(models.Q(employee__isnull=False, location__isnull=True) | models.Q(employee__isnull=True, location__isnull=False)),
                name='local_exception_one_target',
            ),
        ),
    ]
