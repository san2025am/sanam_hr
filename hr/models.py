
from __future__ import annotations
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.utils import timezone

from api_guard.models import Employee

# في حال لديك Employee جاهز في تطبيق آخر، استبدل هذا النموذج بربط ForeignKey/N:1 لنموذجك.

class JobApplication(models.Model):
    class Position(models.TextChoices):
        GUARD = "guard", _("حارس أمن")
        SUPERVISOR = "supervisor", _("مشرف")
        HR = "hr", _("موارد بشرية")

    full_name = models.CharField(max_length=200, verbose_name="الاسم الرباعي")
    national_id = models.CharField(max_length=20, verbose_name="رقم الهوية")
    phone = models.CharField(max_length=20, verbose_name="رقم الجوال")
    email = models.EmailField(verbose_name="الإيميل", blank=True)
    position = models.CharField(max_length=20, choices=Position.choices, verbose_name="الوظيفة المتقدم لها")

    resume = models.FileField(upload_to="applications/resumes/", verbose_name="السيرة الذاتية", blank=True, null=True)
    qualification_document = models.FileField(upload_to="applications/qualifications/", verbose_name="المؤهل العلمي", blank=True, null=True)
    cover_letter = models.TextField(verbose_name="رسالة توضيحية", blank=True)

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="تاريخ التقديم")

    class Status(models.TextChoices):
        NEW = "new", _("جديد")
        UNDER_REVIEW = "under_review", _("قيد المراجعة")
        ACCEPTED = "accepted", _("مقبول")
        REJECTED = "rejected", _("مرفوض")

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NEW, verbose_name="الحالة")
    notes = models.TextField(verbose_name="ملاحظات الموارد البشرية", blank=True)

    employee = models.ForeignKey(Employee, on_delete=models.SET_NULL, blank=True, null=True, verbose_name="الموظف المرتبط")

    def __str__(self):
        return f"{self.full_name} – {self.get_position_display()}"

