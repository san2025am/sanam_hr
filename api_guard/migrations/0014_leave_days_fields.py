from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api_guard', '0013_contract_company_sign_and_overlap'),
    ]

    operations = [
        migrations.AddField(
            model_name='employeeleavebalance',
            name='quota_days',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=6, verbose_name='أيام الإجازة المسموحة (شهريًا)'),
        ),
        migrations.AddField(
            model_name='employeeleavebalance',
            name='used_paid_days',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=6, verbose_name='أيام الإجازة المدفوعة المستخدمة'),
        ),
        migrations.AddField(
            model_name='employeeleavebalance',
            name='used_unpaid_days',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=6, verbose_name='أيام الإجازة غير المدفوعة (لأغراض الرواتب)'),
        ),
        migrations.AddField(
            model_name='employeeleavebalance',
            name='carry_over_days',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=6, verbose_name='أيام مرحّلة من السنة السابقة'),
        ),
    ]

