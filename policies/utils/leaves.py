from __future__ import annotations

from datetime import datetime, date, timedelta, time
from decimal import Decimal
from typing import Optional, Iterable

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from api_guard.models import Employee, EmployeeLeaveBalance, Shift
from policies.models import LeavePolicy, PolicyBundle
from policies.utils.resolver import resolve_policy


def get_effective_leave_policy(
    *,
    employee: Employee,
    location=None,
    shift: Shift | None = None,
    on_date: Optional[date] = None,
) -> Optional[LeavePolicy]:
    """
    يختار LeavePolicy عبر PolicyBundle(policy_type='leave') وفق الأولوية:
    SHIFT → LOCATION → ROLE → GLOBAL ثم ربط الحزمة بLeavePolicy.
    """
    role_id = getattr(getattr(employee, "user", None), "role_id", None)
    bundle = resolve_policy(
        PolicyBundle.PolicyType.LEAVE,
        role_id=role_id,
        location_id=getattr(location, "pk", location),
        shift_id=getattr(shift, "pk", shift),
        on_date=on_date,
    )
    if bundle is None:
        return None
    return LeavePolicy.objects.filter(bundle=bundle).first()


def _anchored_date(dt: datetime, start_at: time) -> date:
    """
    يحسب تاريخ اليوم اعتمادًا على بداية الوردية.
    إذا كان وقت dt قبل start_at تُنسب لليوم السابق، غير ذلك لنفس اليوم.
    """
    local = timezone.localtime(dt)
    if start_at and local.time() < start_at:
        return (local.date() - timedelta(days=1))
    return local.date()


def _iter_days(start: date, end: date) -> Iterable[date]:
    cur = start
    while cur <= end:
        yield cur
        cur = cur + timedelta(days=1)


def _ensure_month_record(emp: Employee, d: date) -> EmployeeLeaveBalance:
    rec, _ = EmployeeLeaveBalance.objects.get_or_create(
        employee=emp, year=d.year, month=d.month,
        defaults={
            'quota_hours': Decimal('0'),
            'used_hours': Decimal('0'),
            'quota_days': Decimal('0'),
            'used_paid_days': Decimal('0'),
            'used_unpaid_days': Decimal('0'),
            'carry_over_days': Decimal('0'),
        }
    )
    return rec


def accrue_month_for_employee(
    *,
    employee: Employee,
    year: int,
    month: int,
    location=None,
    shift: Shift | None = None,
) -> Decimal:
    """
    يزيد رصيد الشهر المحدد وفق LeavePolicy الفعالة مع احترام الحد السنوي.
    يعيد مقدار الأيام التي تمت إضافتها.
    """
    on_date = date(year, month, 1)
    pol = get_effective_leave_policy(employee=employee, location=location, shift=shift, on_date=on_date)
    if pol is None:
        return Decimal('0')

    monthly = Decimal(pol.monthly_accrual_days or 0)
    cap = Decimal(pol.yearly_cap_days or 0)

    with transaction.atomic():
        # مجموع الاستحقاق حتى هذا الشهر
        total_quota = (EmployeeLeaveBalance.objects
                       .filter(employee=employee, year=year, month__lte=month)
                       .aggregate(s=Sum('quota_days'))['s'] or Decimal('0'))
        add = monthly
        if cap > 0 and (total_quota + add) > cap:
            add = max(Decimal('0'), cap - total_quota)

        rec = _ensure_month_record(employee, on_date)
        if add > 0:
            rec.quota_days = (rec.quota_days or Decimal('0')) + add
            rec.save(update_fields=['quota_days'])
        return add


def carry_over_year_for_employee(
    *,
    employee: Employee,
    year: int,
    location=None,
    shift: Shift | None = None,
) -> Decimal:
    """
    يرحّل الرصيد غير المستخدم من سنة `year` إلى يناير من السنة التالية بحد أقصى carry_over_max.
    طريقة الاحتساب: carry = min(max(sum(quota_days) - sum(used_paid_days), 0), carry_over_max)
    """
    # سياسة نهاية السنة
    pol = get_effective_leave_policy(employee=employee, location=location, shift=shift, on_date=date(year, 12, 31))
    carry_max = Decimal(pol.carry_over_max or 0) if pol else Decimal('0')

    aggr = EmployeeLeaveBalance.objects.filter(employee=employee, year=year).aggregate(
        q=Sum('quota_days'), u=Sum('used_paid_days')
    )
    total_q = aggr['q'] or Decimal('0')
    total_u = aggr['u'] or Decimal('0')
    remaining = total_q - total_u
    if remaining < 0:
        remaining = Decimal('0')
    carry = remaining if carry_max <= 0 else min(remaining, carry_max)

    if carry > 0:
        jan = _ensure_month_record(employee, date(year + 1, 1, 1))
        jan.carry_over_days = carry
        jan.save(update_fields=['carry_over_days'])
    return carry


def record_paid_leave(
    *,
    employee: Employee,
    start: datetime,
    end: datetime,
    shift: Shift,
) -> Decimal:
    """
    يسجل إجازة مدفوعة: تُخصم من الرصيد اليومي فقط.
    يُحسب اليوم بناءً على بداية الوردية.
    يتم توزيع الأيام على شهور السنة حسب تاريخ اليوم المحسوب.
    """
    start_time = getattr(shift, 'start_time', None) or time(0, 0)
    # اجعل نهاية المدة لا تشمل الحد الأعلى لتفادي عد يوم إضافي عند الساعة تمامًا
    end_adj = end - timedelta(microseconds=1)
    s_day = _anchored_date(start, start_time)
    e_day = _anchored_date(end_adj, start_time)
    if e_day < s_day:
        return Decimal('0')

    days = Decimal('0')
    with transaction.atomic():
        for d in _iter_days(s_day, e_day):
            rec = _ensure_month_record(employee, d)
            rec.used_paid_days = (rec.used_paid_days or Decimal('0')) + Decimal('1')
            rec.save(update_fields=['used_paid_days'])
            days += Decimal('1')
    return days


def record_unpaid_leave(
    *,
    employee: Employee,
    start: datetime,
    end: datetime,
    shift: Shift,
) -> Decimal:
    """
    يسجل إجازة غير مدفوعة: لا تخصم من الرصيد، لكنها تزيد used_unpaid_days (تستخدم لاحقًا لتقليل payable_days في الرواتب).
    يتم توزيع الأيام حسب تاريخ بداية الوردية لكل يوم.
    """
    start_time = getattr(shift, 'start_time', None) or time(0, 0)
    end_adj = end - timedelta(microseconds=1)
    s_day = _anchored_date(start, start_time)
    e_day = _anchored_date(end_adj, start_time)
    if e_day < s_day:
        return Decimal('0')

    days = Decimal('0')
    with transaction.atomic():
        for d in _iter_days(s_day, e_day):
            rec = _ensure_month_record(employee, d)
            rec.used_unpaid_days = (rec.used_unpaid_days or Decimal('0')) + Decimal('1')
            rec.save(update_fields=['used_unpaid_days'])
            days += Decimal('1')
    return days

