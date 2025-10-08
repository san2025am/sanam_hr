import django.db.models.deletion
import django.utils.timezone
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api_guard", "0012_auto_biometric_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="LocationMonitoringConfig",
            fields=[
                (
                    "created_at",
                    models.DateTimeField(default=django.utils.timezone.now, editable=False),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("deleted_at", models.DateTimeField(blank=True, editable=False, null=True)),
                (
                    "is_active",
                    models.BooleanField(default=True, verbose_name="مفعل؟"),
                ),
                (
                    "ping_interval_seconds",
                    models.PositiveIntegerField(
                        default=300,
                        help_text="المدة بين كل إرسال إحداثيات من تطبيق الحارس.",
                        verbose_name="الفاصل الزمني للتتبع (ثواني)",
                    ),
                ),
                (
                    "violation_grace_minutes",
                    models.PositiveIntegerField(
                        default=5,
                        help_text="إذا تجاوز الابتعاد هذه المدة تُنشأ مخالفة تلقائيًا.",
                        verbose_name="مدة السماح قبل تسجيل المخالفة (دقائق)",
                    ),
                ),
                ("notes", models.TextField(blank=True, null=True, verbose_name="ملاحظات")),
                (
                    "location",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="monitoring_config",
                        to="api_guard.location",
                        verbose_name="الموقع",
                    ),
                ),
                (
                    "violation_rule",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="location_monitoring_configs",
                        to="api_guard.violationrule",
                        verbose_name="المخالفة المعتمدة",
                    ),
                ),
            ],
            options={
                "verbose_name": "4.1 ضبط مراقبة موقع",
                "verbose_name_plural": "4.1 ضبط مراقبة المواقع",
                "ordering": ["location__name"],
            },
        ),
    ]
