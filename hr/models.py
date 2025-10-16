
from __future__ import annotations
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.utils import timezone

from api_guard.models import Employee, Role
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model

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

    def clean(self):
        """
        منع تكرار بيانات التقديم: رقم الهوية، رقم الجوال، البريد الإلكتروني.
        كما نمنع التقديم بنفس البيانات إن كانت موجودة في سجلات الموظفين/المستخدمين.
        """
        super().clean()
        from django.core.exceptions import ValidationError
        from django.contrib.auth import get_user_model
        from api_guard.models import Employee as _Emp

        nid = (self.national_id or "").strip()
        phone = (self.phone or "").strip()
        email = (self.email or "").strip().lower()

        qs = JobApplication.objects.all()
        if self.pk:
            qs = qs.exclude(pk=self.pk)

        errors = {}
        if nid and qs.filter(national_id=nid).exists():
            errors["national_id"] = "رقم الهوية مستخدم في طلب سابق."
        if phone and qs.filter(phone=phone).exists():
            errors["phone"] = "رقم الجوال مستخدم في طلب سابق."
        if email and qs.filter(email__iexact=email).exists():
            errors["email"] = "البريد الإلكتروني مستخدم في طلب سابق."

        # تفادي تعارض مع سجلات الموظفين/الحسابات
        if nid and _Emp.objects.filter(national_id=nid).exists():
            errors.setdefault("national_id", "رقم الهوية مرتبط بموظف قائم.")
        if phone and _Emp.objects.filter(phone_number=phone).exists():
            errors.setdefault("phone", "رقم الجوال مرتبط بموظف قائم.")
        if email:
            User = get_user_model()
            if User.objects.filter(email__iexact=email).exists():
                errors.setdefault("email", "البريد الإلكتروني مرتبط بحساب قائم.")

        if errors:
            raise ValidationError(errors)


# ===== إلحاق الموظف تلقائيًا بعد قبول الطلب =====
@receiver(post_save, sender=JobApplication)
def ensure_employee_on_accept(sender, instance: JobApplication, created: bool, **kwargs):
    try:
        # نفعّل فقط عند حالة "مقبول"
        if (instance.status or '').strip() != JobApplication.Status.ACCEPTED:
            return
        # إن كان مرتبطًا مسبقًا — لا شيء
        if instance.employee_id:
            return
        # ابحث عن موظف موجود عبر رقم الهوية لتجنّب التكرار
        # لا تربط إلا إذا تطابق رقم الهوية ورقم الجوال معًا لتفادي الربط الخاطئ
        emp = Employee.objects.filter(
            national_id=instance.national_id,
            phone_number=instance.phone,
        ).first()
        if not emp:
            # أنشئ User + Employee
            UserModel = get_user_model()
            import secrets, string
            def _gen_username():
                return 'sa' + ''.join(secrets.choice(string.digits) for _ in range(6))
            username = None
            for _ in range(10):
                cand = _gen_username()
                if not UserModel.objects.filter(username__iexact=cand).exists():
                    username = cand
                    break
            username = username or _gen_username()

            user = UserModel.objects.create(
                username=username,
                email=(instance.email or '').strip(),
            )
            # عيّن دور حارس إن وجد
            try:
                guard_role = Role.objects.filter(name='guard').first()
                if guard_role:
                    user.role = guard_role
                    user.save(update_fields=['role'])
            except Exception:
                pass

            emp = Employee.objects.create(
                user=user,
                full_name=instance.full_name,
                national_id=instance.national_id,
                phone_number=instance.phone,
            )
        # اربط الطلب بالموظف
        if not instance.employee_id and emp:
            JobApplication.objects.filter(pk=instance.pk).update(employee=emp)
    except Exception:
        # لا تُعطّل الحفظ لو حدث خطأ — يمكن للإداري إصلاحها يدويًا
        pass
