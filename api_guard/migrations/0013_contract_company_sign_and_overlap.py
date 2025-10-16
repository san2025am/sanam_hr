from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        ('api_guard', '0012_tracking_incident'),
    ]

    operations = [
        migrations.AddField(
            model_name='contract',
            name='company_signature_image',
            field=models.ImageField(blank=True, null=True, upload_to='contracts/company_signatures/', verbose_name='توقيع الإدارة'),
        ),
        migrations.AddField(
            model_name='contract',
            name='company_signed_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='وقت توقيع الإدارة'),
        ),
        migrations.AddField(
            model_name='contract',
            name='company_signed_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='company_signed_contracts', to=settings.AUTH_USER_MODEL, verbose_name='وقّعه من الإدارة'),
        ),
    ]

