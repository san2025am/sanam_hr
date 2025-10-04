from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('api_guard', '0009_advance_deduction_applied_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='task',
            name='status_note',
            field=models.TextField(blank=True, null=True, verbose_name='ملاحظة الحالة'),
        ),
        migrations.AlterField(
            model_name='task',
            name='status',
            field=models.CharField(choices=[('new', 'جديدة'), ('accepted', 'مقبولة'), ('in_progress', 'قيد التنفيذ'), ('completed', 'مكتملة')], default='new', max_length=20, verbose_name='الحالة'),
        ),
        migrations.AlterField(
            model_name='request',
            name='request_type',
            field=models.CharField(choices=[('coverage', 'تغطية'), ('leave', 'إجازة'), ('transfer', 'نقل'), ('materials', 'طلب مواد'), ('uniform', 'طلب زي')], max_length=20, verbose_name='نوع الطلب'),
        ),
        migrations.AddField(
            model_name='request',
            name='uniform_delivery',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='requests', to='api_guard.uniformdelivery', verbose_name='نموذج الزي المرتبط'),
        ),
    ]
