from django.db import migrations, models
import django.db.models.deletion
import uuid
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ("api_guard", "0017_shift_assignment_buffers"),
    ]

    operations = [
        migrations.CreateModel(
            name="ShiftAbsenceLog",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, editable=False, null=True)),
                ("date", models.DateField(verbose_name="تاريخ الوردية")),
                ("notified", models.BooleanField(default=False, verbose_name="تم إرسال الإشعار؟")),
                ("assignment", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="absence_logs", to="api_guard.employeeshiftassignment", verbose_name="تعيين الوردية")),
                ("employee", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="shift_absence_logs", to="api_guard.employee", verbose_name="الموظف")),
                ("location", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="absence_logs", to="api_guard.location", verbose_name="الموقع")),
                ("shift", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="absence_logs", to="api_guard.shift", verbose_name="الوردية")),
                ("violation", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="absence_logs", to="api_guard.employeeviolation", verbose_name="المخالفة المرتبطة")),
            ],
            options={
                "verbose_name": "7.2 سجل غياب وردية",
                "verbose_name_plural": "7.2 سجلات غياب الورديات",
            },
        ),
        migrations.AddConstraint(
            model_name="shiftabsencelog",
            constraint=models.UniqueConstraint(fields=("employee", "shift", "date"), name="uniq_employee_shift_absence_day"),
        ),
    ]
