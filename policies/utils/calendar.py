from __future__ import annotations

from datetime import date, timedelta
from typing import Optional, Any

from django.db.models import Q
from django.utils import timezone

from policies.models import WeeklyOff, PublicHoliday, LocalException


def _pk(v: Any) -> Optional[str]:
    return getattr(v, "pk", v)


def is_public_holiday(
    d: date,
    *,
    employee: Any | None = None,
    location: Any | None = None,
    shift: Any | None = None,
) -> bool:
    """
    يرجع True إذا كان التاريخ عطلة رسمية تنطبق ضمن النطاق.

    الأولوية: SHIFT → LOCATION → ROLE → GLOBAL
    - إذا كانت العطلة "تتكرر سنويًا" تتم المطابقة على (شهر/يوم) فقط.
    - تُؤخذ فقط السجلات المفعلة.
    - أي LocalException من نوع MAKE_WORKING يلغي نتيجة العطلة.
    """
    role = getattr(getattr(employee, "user", None), "role", None) if employee is not None else None
    role_id = _pk(role)
    loc_id = _pk(location)
    shift_id = _pk(shift)

    # Local exception override → make working cancels
    if _has_local_exception(d, employee=employee, location=location, effect=LocalException.Effect.MAKE_WORKING):
        return False

    base = PublicHoliday.objects.filter(is_active=True)
    by_day = Q(date=d) | Q(repeats_annually=True, date__month=d.month, date__day=d.day)
    base = base.filter(by_day)

    if shift_id and base.filter(scope=PublicHoliday.Scope.SHIFT, shift_id=shift_id).exists():
        return True
    if loc_id and base.filter(scope=PublicHoliday.Scope.LOCATION, location_id=loc_id).exists():
        return True
    if role_id and base.filter(scope=PublicHoliday.Scope.ROLE, role_id=role_id).exists():
        return True
    return base.filter(scope=PublicHoliday.Scope.GLOBAL).exists()


def is_weekly_off(
    d: date,
    *,
    employee: Any | None = None,
    location: Any | None = None,
    shift: Any | None = None,
) -> bool:
    """
    يرجع True إذا كان التاريخ يقع في يوم راحة أسبوعية فعال.

    قواعد الاختيار:
    - يتم اختيار سجل WeeklyOff المطابق لليوم الأسبوعي وفق ترتيب النطاق:
      SHIFT → LOCATION → ROLE → GLOBAL
    - داخل النطاق نفسه: الأقل أولوية (priority) يفوز، ثم الأحدث start_date.
    - تُطبق فقط السجلات المفعلة زمنيًا (start_date ≤ d ≤ end_date إن وُجد).
    - LocalException(MAKE_WORKING) يلغي النتيجة، LocalException(MAKE_OFF) يفرض التعطيل حتى لو لم يوجد WeeklyOff.
    """
    # Local exceptions first
    if _has_local_exception(d, employee=employee, location=location, effect=LocalException.Effect.MAKE_OFF):
        return True
    if _has_local_exception(d, employee=employee, location=location, effect=LocalException.Effect.MAKE_WORKING):
        return False

    role = getattr(getattr(employee, "user", None), "role", None) if employee is not None else None
    role_id = _pk(role)
    loc_id = _pk(location)
    shift_id = _pk(shift)

    dow = (d.weekday())  # Monday=0..Sunday=6
    time_q = Q(start_date__lte=d) & (Q(end_date__isnull=True) | Q(end_date__gte=d))
    base = WeeklyOff.objects.filter(is_active=True, day_of_week=dow).filter(time_q)

    def _top(qs):
        return qs.order_by("priority", "-start_date", "-created_at").first()

    if shift_id:
        top = _top(base.filter(scope=WeeklyOff.Scope.SHIFT, shift_id=shift_id))
        if top:
            return True
    if loc_id:
        top = _top(base.filter(scope=WeeklyOff.Scope.LOCATION, location_id=loc_id))
        if top:
            return True
    if role_id:
        top = _top(base.filter(scope=WeeklyOff.Scope.ROLE, role_id=role_id))
        if top:
            return True
    top = _top(base.filter(scope=WeeklyOff.Scope.GLOBAL))
    return bool(top)


def is_day_off(
    d: date,
    *,
    employee: Any | None = None,
    location: Any | None = None,
    shift: Any | None = None,
) -> bool:
    """
    True إذا كان اليوم غير عمل وفق النظام:
    - LocalException: يسبق الجميع (employee ثم location)
    - WeeklyOff: حسب النطاق والأولويات
    - PublicHoliday: حسب النطاق
    """
    # Local exceptions override
    if _has_local_exception(d, employee=employee, location=location, effect=LocalException.Effect.MAKE_OFF):
        return True
    if _has_local_exception(d, employee=employee, location=location, effect=LocalException.Effect.MAKE_WORKING):
        return False

    return is_weekly_off(d, employee=employee, location=location, shift=shift) or \
           is_public_holiday(d, employee=employee, location=location, shift=shift)


def adjust_to_next_working_day(
    d: date,
    *,
    employee: Any | None = None,
    location: Any | None = None,
    shift: Any | None = None,
    max_lookahead_days: int = 14,
) -> date:
    """
    إذا صادف تاريخ الصرف عطلة، ينقل إلى أقرب يوم عمل تالٍ.
    تُستخدم is_day_off للتقرير. يوقف البحث بعد max_lookahead_days للحماية.
    """
    for _ in range(max(1, int(max_lookahead_days))):
        if not is_day_off(d, employee=employee, location=location, shift=shift):
            return d
        d = d + timedelta(days=1)
    return d


def _has_local_exception(d: date, *, employee: Any | None, location: Any | None, effect: str) -> bool:
    # employee-level overrides location-level
    if employee is not None:
        if LocalException.objects.filter(date=d, employee=_pk(employee), effect=effect).exists():
            return True
    if location is not None:
        if LocalException.objects.filter(date=d, location=_pk(location), effect=effect).exists():
            return True
    return False

