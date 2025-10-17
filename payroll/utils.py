from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from django.db.models import Sum
from django.utils import timezone

from django.conf import settings
from api_guard.models import Employee, Salary, EmployeeLeaveBalance, EmployeeViolation
from .models import PayrollConfig, PayrollCycle, PayrollItem, Reward, Overtime
from policies.utils.overtime import get_effective_overtime_policy, default_rates


def _q2(v: Decimal | float | int) -> Decimal:
    d = v if isinstance(v, Decimal) else Decimal(str(v))
    return d.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def month_bounds(year: int, month: int) -> tuple[datetime, datetime]:
    start = datetime(year, month, 1)
    if month == 12:
        end = datetime(year + 1, 1, 1) - timedelta(microseconds=1)
    else:
        end = datetime(year, month + 1, 1) - timedelta(microseconds=1)
    tz = timezone.get_current_timezone()
    return timezone.make_aware(start, tz), timezone.make_aware(end, tz)


def get_active_config() -> PayrollConfig:
    cfg = PayrollConfig.objects.filter(is_active=True).order_by('-created_at').first()
    if cfg is None:
        cfg = PayrollConfig.objects.create()
    return cfg


def _prev_year_month(year: int, month: int) -> tuple[int, int]:
    if month == 1:
        return year - 1, 12
    return year, month - 1


def build_item_for_employee(*, cycle: PayrollCycle, employee: Employee) -> PayrollItem:
    cfg = cycle.config
    start, end = month_bounds(cycle.year, cycle.month)

    salary = Salary.objects.filter(employee=employee).first()
    base_salary = _q2(getattr(salary, 'base_salary', Decimal('0')) or Decimal('0'))

    if cfg.daily_rate_policy == PayrollConfig.DailyRatePolicy.FIXED:
        daily_rate = _q2(cfg.fixed_daily_rate or 0)
    else:
        # from_base
        default_days = Decimal(cfg.default_working_days or 0)
        daily_rate = _q2(Decimal('0') if default_days <= 0 else (base_salary / default_days))

    # unpaid leave days for this month
    lb = EmployeeLeaveBalance.objects.filter(employee=employee, year=cycle.year, month=cycle.month).first()
    unpaid_leave_days = _q2(getattr(lb, 'used_unpaid_days', Decimal('0')) or Decimal('0'))
    default_days = _q2(cfg.default_working_days or 0)
    payable_days = default_days - unpaid_leave_days
    if payable_days < Decimal('0'):
        payable_days = Decimal('0')

    days_amount = _q2(payable_days * daily_rate)
    # Rewards (approved)
    rewards_sum = (Reward.objects
                   .filter(employee=employee, date__gte=start.date(), date__lte=end.date(), approved=True)
                   .aggregate(s=Sum('amount'))['s'] or Decimal('0'))
    allowances_total = _q2(rewards_sum)

    # Overtime (approved)
    ot_qs = (Overtime.objects
             .filter(employee=employee, date__gte=start.date(), date__lte=end.date(), approved=True))
    # Sum hours by classification
    hour_map = {
        'public_holiday': _q2(ot_qs.filter(classification=Overtime.Classification.PUBLIC_HOLIDAY).aggregate(s=Sum('hours'))['s'] or Decimal('0')),
        'offday': _q2(ot_qs.filter(classification=Overtime.Classification.OFFDAY).aggregate(s=Sum('hours'))['s'] or Decimal('0')),
        'night': _q2(ot_qs.filter(classification=Overtime.Classification.NIGHT).aggregate(s=Sum('hours'))['s'] or Decimal('0')),
        'normal': _q2(ot_qs.filter(classification=Overtime.Classification.NORMAL).aggregate(s=Sum('hours'))['s'] or Decimal('0')),
    }
    total_hours = sum(hour_map.values(), Decimal('0'))

    # Hourly wage from daily_rate / hours_per_day
    hours_per_day = _q2(cfg.hours_per_day or 8)
    hourly_wage = _q2(Decimal('0') if hours_per_day <= 0 else (daily_rate / hours_per_day))

    # Policy
    pol = get_effective_overtime_policy(employee=employee, on_date=start.date())
    rates = default_rates(pol)
    cap = rates.get('cap')  # Decimal or None

    # Apply monthly cap: allocate hours by descending rate priority
    applied_hours = hour_map.copy()
    if cap is not None and cap >= 0:
        remaining = _q2(cap)
        # order by rate desc
        ordered = sorted(['public_holiday','offday','night','normal'], key=lambda k: rates[k], reverse=True)
        # zero all
        for k in applied_hours.keys():
            applied_hours[k] = Decimal('0')
        for k in ordered:
            if remaining <= 0:
                break
            take = hour_map[k]
            if take <= remaining:
                applied_hours[k] = take
                remaining -= take
            else:
                applied_hours[k] = remaining
                remaining = Decimal('0')

    # Compute overtime amount
    ot_amounts = {k: _q2(hourly_wage * applied_hours[k] * rates[k]) for k in ['normal','night','offday','public_holiday']}
    overtime_total = _q2(sum(ot_amounts.values(), Decimal('0')))
    gross = _q2(days_amount + allowances_total + overtime_total)

    # deductions: sum violations in this month + carry_in from previous cycle
    # ملاحظة: إن لم يُحدّد deduction_value في السجل، نحتسب من نسبة القاعدة (rule.default_deduction_percent) من الراتب الأساسي.
    sum_ded = Decimal('0')
    viols = (EmployeeViolation.objects
             .select_related('rule')
             .filter(employee=employee, occurred_at__gte=start, occurred_at__lte=end))
    for v in viols:
        val = getattr(v, 'deduction_value', None)
        if val is not None and Decimal(str(val)) > 0:
            sum_ded += _q2(val)
            continue
        # fallback إلى النسبة الافتراضية من القاعدة
        rule = getattr(v, 'rule', None)
        percent = None
        try:
            percent = Decimal(str(getattr(rule, 'default_deduction_percent', 0) or 0))
        except Exception:
            percent = Decimal('0')
        if percent and percent > 0:
            sum_ded += _q2(base_salary * (percent / Decimal('100')))
    sum_ded = _q2(sum_ded)

    py, pm = _prev_year_month(cycle.year, cycle.month)
    prev = PayrollCycle.objects.filter(year=py, month=pm).first()
    carry_in = Decimal('0')
    if prev:
        prev_item = PayrollItem.objects.filter(cycle=prev, employee=employee).first()
        if prev_item:
            carry_in = _q2(prev_item.deductions_excess_carried or 0)

    requested = _q2(sum_ded + carry_in)

    cap_rate = Decimal(cfg.max_deduction_rate or 0) / Decimal('100')
    cap_amount = _q2(base_salary * cap_rate)
    applied = requested if requested <= cap_amount else cap_amount
    excess = requested - applied if requested > applied else Decimal('0')

    net_pay = _q2(gross - applied)

    item = PayrollItem(
        cycle=cycle,
        employee=employee,
        base_salary=base_salary,
        daily_rate=daily_rate,
        default_working_days=default_days,
        unpaid_leave_days=unpaid_leave_days,
        payable_days=payable_days,
        days_amount=days_amount,
        allowances_total=allowances_total,
        overtime_total=overtime_total,
        gross=gross,
        deductions_requested=requested,
        carry_in_deductions=carry_in,
        deductions_applied=applied,
        deductions_excess_carried=excess,
        net_pay=net_pay,
        detail={
            "period": f"{cycle.year}-{cycle.month:02d}",
            "rewards_total": str(allowances_total),
            "overtime": {
                "hourly_wage": str(hourly_wage),
                "hours": {k: str(hour_map[k]) for k in hour_map},
                "applied_hours": {k: str(applied_hours[k]) for k in applied_hours},
                "rates": {k: str(rates[k]) for k in ['normal','night','offday','public_holiday']},
                "cap": str(cap) if cap is not None else None,
                "amounts": {k: str(ot_amounts[k]) for k in ot_amounts},
                "total": str(overtime_total),
            },
        },
    )
    item.save()
    return item


def post_cycle_to_salary(*, year: int, month: int, force: bool = False) -> int:
    """
    يربط بنود الرواتب بدفاتر Salary الشهرية لتحديث: bonuses, overtime, deductions, pay_date.
    ملاحظة: يتم "الاستبدال" لقيم الشهر، وليس الجمع التراكمي. لتفادي التكرار، نضع علامة في detail['posted_to_salary'].
    تعيد عدد العناصر التي تم ترحيلها.
    """
    cycle = PayrollCycle.objects.filter(year=year, month=month).first()
    if not cycle:
        return 0
    _, end = month_bounds(year, month)
    posted_count = 0
    for item in cycle.items.select_related('employee'):
        detail = dict(item.detail or {})
        if detail.get('posted_to_salary') and not force:
            continue
        sal, _ = Salary.objects.get_or_create(employee=item.employee)
        # استبدال قيم الشهر (لا تراكم)
        sal.bonuses = item.allowances_total
        sal.overtime = item.overtime_total
        sal.deductions = item.deductions_applied
        sal.pay_date = end.date()
        sal.save(update_fields=['bonuses', 'overtime', 'deductions', 'pay_date'])

        detail['posted_to_salary'] = True
        item.detail = detail
        item.save(update_fields=['detail'])
        posted_count += 1
    return posted_count


def post_item_to_salary(*, item: PayrollItem, force: bool = True) -> bool:
    """Post a single PayrollItem to Salary."""
    _, end = month_bounds(item.cycle.year, item.cycle.month)
    detail = dict(item.detail or {})
    if detail.get('posted_to_salary') and not force:
        return False
    sal, _ = Salary.objects.get_or_create(employee=item.employee)
    sal.bonuses = item.allowances_total
    sal.overtime = item.overtime_total
    sal.deductions = item.deductions_applied
    sal.pay_date = end.date()
    sal.save(update_fields=['bonuses', 'overtime', 'deductions', 'pay_date'])
    detail['posted_to_salary'] = True
    item.detail = detail
    item.save(update_fields=['detail'])
    return True


def build_and_post_for_employee_on_date(*, employee: Employee, d: date) -> bool:
    """
    Convenience helper used by Admin hooks/signals:
    - Ensures the cycle for (year, month)
    - Rebuilds this employee's item only
    - Optionally posts to Salary depending on settings flags
    Returns True if an item was built and posted.
    """
    year, month = d.year, d.month
    cycle = get_or_create_cycle(year, month)
    # Delete existing item to avoid duplicates
    PayrollItem.objects.filter(cycle=cycle, employee=employee).delete()
    item = build_item_for_employee(cycle=cycle, employee=employee)
    auto_post = getattr(settings, 'AUTO_POST_TO_SALARY', True)
    if auto_post:
        return post_item_to_salary(item=item, force=True)
    return True
def get_or_create_cycle(year: int, month: int) -> PayrollCycle:
    """Fetch a cycle for (year, month) or create one with active config."""
    cycle = PayrollCycle.objects.filter(year=year, month=month).first()
    if cycle:
        return cycle
    cfg = get_active_config()
    cycle = PayrollCycle.objects.create(year=year, month=month, config=cfg)
    return cycle
