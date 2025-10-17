from __future__ import annotations

from datetime import date

from django.conf import settings
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from payroll.utils import build_and_post_for_employee_on_date
from payroll.models import Reward, Overtime


def _auto_enabled() -> bool:
    try:
        return bool(getattr(settings, 'AUTO_PAYROLL_ON_CHANGE', True))
    except Exception:
        return True


def _safe_build(employee, d: date):
    if not _auto_enabled():
        return
    try:
        if employee and d:
            build_and_post_for_employee_on_date(employee=employee, d=d)
    except Exception:
        # لا تعطل المسار الرئيسي بسبب خطأ ثانوي في الترحيل
        pass


@receiver(post_save, sender=Reward)
def reward_changed(sender, instance: Reward, **kwargs):
    # قم بالتحديث فقط إن كانت المكافأة المعتمدة تؤثر على الشهر
    try:
        if instance.approved:
            _safe_build(instance.employee, instance.date)
    except Exception:
        pass


@receiver(post_delete, sender=Reward)
def reward_deleted(sender, instance: Reward, **kwargs):
    try:
        # عند الحذف، أعد الحساب لنفس الشهر بغض النظر عن حالة الموافقة السابقة
        _safe_build(instance.employee, instance.date)
    except Exception:
        pass


@receiver(post_save, sender=Overtime)
def overtime_changed(sender, instance: Overtime, **kwargs):
    try:
        if instance.approved:
            _safe_build(instance.employee, instance.date)
    except Exception:
        pass


@receiver(post_delete, sender=Overtime)
def overtime_deleted(sender, instance: Overtime, **kwargs):
    try:
        _safe_build(instance.employee, instance.date)
    except Exception:
        pass


# ربط مخالفات الموظفين من تطبيق api_guard بدون الاعتماد على إشارات داخل ذلك التطبيق
try:
    from api_guard.models import EmployeeViolation  # type: ignore

    @receiver(post_save, sender=EmployeeViolation)
    def violation_changed(sender, instance: EmployeeViolation, **kwargs):  # type: ignore[valid-type]
        try:
            d = getattr(instance, 'occurred_at', None)
            d = d.date() if d else None
            _safe_build(instance.employee, d)
        except Exception:
            pass

    @receiver(post_delete, sender=EmployeeViolation)
    def violation_deleted(sender, instance: EmployeeViolation, **kwargs):  # type: ignore[valid-type]
        try:
            d = getattr(instance, 'occurred_at', None)
            d = d.date() if d else None
            _safe_build(instance.employee, d)
        except Exception:
            pass
except Exception:
    # إذا فشل الاستيراد (خلال الهجرات الأولى مثلاً)، تجاهل بأمان
    pass

