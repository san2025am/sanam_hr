from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('api_guard', '0014_leave_days_fields'),
        ('payroll', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='Reward',
            fields=[
                ('created_at', models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('deleted_at', models.DateTimeField(blank=True, editable=False, null=True)),
                ('id', models.UUIDField(editable=False, primary_key=True, serialize=False)),
                ('date', models.DateField(verbose_name='التاريخ')),
                ('amount', models.DecimalField(decimal_places=2, max_digits=10, verbose_name='المبلغ')),
                ('reason', models.CharField(blank=True, max_length=255, null=True, verbose_name='السبب')),
                ('approved', models.BooleanField(default=False, verbose_name='معتمد؟')),
                ('employee', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='rewards', to='api_guard.employee', verbose_name='الموظف')),
            ],
            options={
                'verbose_name': 'مكافأة',
                'verbose_name_plural': 'مكافآت',
            },
        ),
        migrations.CreateModel(
            name='Overtime',
            fields=[
                ('created_at', models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('deleted_at', models.DateTimeField(blank=True, editable=False, null=True)),
                ('id', models.UUIDField(editable=False, primary_key=True, serialize=False)),
                ('date', models.DateField(verbose_name='التاريخ')),
                ('hours', models.DecimalField(decimal_places=2, max_digits=6, verbose_name='الساعات')),
                ('classification', models.CharField(choices=[('normal', 'عادي'), ('night', 'ليلي'), ('offday', 'يوم راحة'), ('public_holiday', 'عطلة رسمية')], default='normal', max_length=20, verbose_name='التصنيف')),
                ('approved', models.BooleanField(default=False, verbose_name='معتمد؟')),
                ('note', models.CharField(blank=True, max_length=255, null=True, verbose_name='ملاحظة')),
                ('employee', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='overtimes', to='api_guard.employee', verbose_name='الموظف')),
            ],
            options={
                'verbose_name': 'عمل إضافي',
                'verbose_name_plural': 'أعمال إضافية',
            },
        ),
        migrations.AddIndex(
            model_name='reward',
            index=models.Index(fields=['employee', 'date'], name='payroll_rew_employee_37cfe6_idx'),
        ),
        migrations.AddIndex(
            model_name='overtime',
            index=models.Index(fields=['employee', 'date'], name='payroll_ove_employee_e8f8d7_idx'),
        ),
    ]

