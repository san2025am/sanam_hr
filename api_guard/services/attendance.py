from __future__ import annotations

import logging
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable, Optional

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from ..models import (
    AttendanceRecord,
    Employee,
    EmployeeShiftAssignment,
    EmployeeViolation,
    Salary,
    ViolationRule,
)
from ..sms import send_sms_twilio

logger = logging.getLogger(__name__)

MISSING_CHECKOUT_RULE_TITLE = "عدم تسجيل الانصراف"
MISSING_CHECKOUT_RULE_DESCRIPTION = (
    "مخالفة تلقائية عند عدم تسجيل الانصراف قبل إغلاق الوردية."
)
DEFAULT_AUTO_CLOSE_GRACE_MINUTES = 15
DEFAULT_WARNING_WINDOW_HOURS = 6
ONE_DAY = timedelta(days=1)


def close_stale_attendance_records(
    *,
    as_of: Optional[datetime] = None,
    employees: Optional[Iterable[Employee]] = None,
    notify: bool = True,
) -> list[dict]:
    """Close stale open attendance records and issue violations/deductions.

    Returns a list of dictionaries describing the actions taken for auditing/testing.
    """

    as_of = as_of or timezone.now()
    actions: list[dict] = []

    if employees is None:
        qs = AttendanceRecord.objects.filter(check_out_time__isnull=True, deleted_at__isnull=True)
    else:
        employee_ids = [emp.id for emp in employees]
        if not employee_ids:
            return actions
        qs = AttendanceRecord.objects.filter(
            check_out_time__isnull=True,
            deleted_at__isnull=True,
            employee_id__in=employee_ids,
        )

    for record in qs.select_related("employee", "employee__supervisor", "location", "shift"):
        outcome = _handle_single_record(record, as_of=as_of, notify=notify)
        if outcome:
            actions.append(outcome)

    return actions


def close_stale_attendance_for_employee(
    employee: Employee,
    *,
    as_of: Optional[datetime] = None,
    notify: bool = True,
) -> list[dict]:
    """Shortcut to close stale records for a single employee."""

    if employee is None:
        return []
    return close_stale_attendance_records(as_of=as_of, employees=[employee], notify=notify)


def _handle_single_record(record: AttendanceRecord, *, as_of: datetime, notify: bool) -> Optional[dict]:
    expected_end = _expected_checkout(record)
    if expected_end is None:
        logger.debug("Skipped auto-closing attendance %s: could not infer shift end", record.pk)
        return None

    grace = timedelta(minutes=DEFAULT_AUTO_CLOSE_GRACE_MINUTES)
    if as_of < expected_end + grace:
        return None

    absence_date = timezone.localtime(expected_end).date()

    with transaction.atomic():
        deduction = _apply_salary_deduction(record.employee)
        violation = _create_violation(record, absence_date, deduction)
        _soft_delete_record(record)

    notification_status = None
    if notify:
        notification_status = _notify_employee(record.employee, absence_date, deduction)

    logger.info(
        "Auto-closed attendance %s for employee %s on %s (deduction=%s, notified=%s)",
        record.pk,
        record.employee_id,
        absence_date,
        deduction,
        notification_status,
    )

    return {
        "record_id": record.pk,
        "employee_id": record.employee_id,
        "absence_date": absence_date,
        "deduction": deduction,
        "violation_id": violation.id if violation else None,
        "notified": notification_status,
    }


def _expected_checkout(record: AttendanceRecord) -> Optional[datetime]:
    shift = record.shift
    if not shift:
        return None

    local_check_in = timezone.localtime(record.check_in_time)
    assignment = _find_relevant_assignment(record, local_check_in)

    start_time = getattr(assignment, "start_time", None) or shift.start_time
    end_time = getattr(assignment, "end_time", None) or shift.end_time
    if not (start_time and end_time):
        return None

    anchor_date = getattr(assignment, "date", None) or local_check_in.date()

    start_dt = _make_aware(datetime.combine(anchor_date, start_time))
    end_dt = _make_aware(datetime.combine(anchor_date, end_time))
    if end_time <= start_time:
        end_dt += ONE_DAY

    if local_check_in < start_dt and (start_dt - local_check_in) > timedelta(hours=DEFAULT_WARNING_WINDOW_HOURS):
        start_dt -= ONE_DAY
        end_dt -= ONE_DAY
        if end_time <= start_time:
            end_dt += ONE_DAY

    # Incorporate custom grace periods from assignment
    if assignment:
        if assignment.checkout_grace_hours is not None:
            end_dt += timedelta(hours=float(assignment.checkout_grace_hours))
        elif assignment.checkout_grace is not None:
            end_dt += timedelta(minutes=int(assignment.checkout_grace))

    return end_dt


def _find_relevant_assignment(record: AttendanceRecord, local_check_in: datetime) -> Optional[EmployeeShiftAssignment]:
    if not record.shift_id:
        return None

    qs = EmployeeShiftAssignment.objects.filter(
        employee=record.employee,
        shift=record.shift,
        active=True,
    )
    if record.location_id:
        qs = qs.filter(Q(location=record.location) | Q(location__isnull=True))

    check_in_date = local_check_in.date()
    qs = qs.filter(Q(date__isnull=True) | Q(date__lte=check_in_date))
    qs = qs.order_by("-date", "-created_at")

    return qs.first()


def _apply_salary_deduction(employee: Employee) -> Decimal:
    salary, _ = Salary.objects.get_or_create(employee=employee)
    base = salary.base_salary or Decimal("0")
    deduction = (base / Decimal("30")) if base else Decimal("0")
    deduction = deduction.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    if deduction > 0:
        Salary.objects.filter(pk=salary.pk).update(deductions=F("deductions") + deduction)

    return deduction


def _create_violation(
    record: AttendanceRecord,
    absence_date,
    deduction: Decimal,
) -> Optional[EmployeeViolation]:
    try:
        rule = ViolationRule.objects.get(title=MISSING_CHECKOUT_RULE_TITLE)
    except ViolationRule.DoesNotExist:
        rule = ViolationRule.objects.create(
            title=MISSING_CHECKOUT_RULE_TITLE,
            description=MISSING_CHECKOUT_RULE_DESCRIPTION,
            default_action="deduct",
            default_deduction_percent=Decimal("0"),
        )

    warning_level = (
        EmployeeViolation.objects.filter(employee=record.employee, rule=rule).count() + 1
    )

    description = (
        f"تسجيل غياب ليوم {absence_date.isoformat()} بسبب عدم تسجيل الانصراف للوردية "
        f"التي بدأ الحضور لها عند {timezone.localtime(record.check_in_time):%Y-%m-%d %H:%M}."
    )

    violation = EmployeeViolation.objects.create(
        employee=record.employee,
        rule=rule,
        reported_by=record.employee.supervisor,
        location=record.location,
        description=description,
        warning_level=warning_level,
        deduction_value=deduction,
    )
    return violation


def _soft_delete_record(record: AttendanceRecord) -> None:
    notes_suffix = "[AUTO-CLOSED: missing checkout]"
    if record.notes:
        record.notes = f"{record.notes} {notes_suffix}"
    else:
        record.notes = notes_suffix
    record.save(update_fields=["notes"])
    record.delete()


def _notify_employee(employee: Employee, absence_date, deduction: Decimal) -> Optional[bool]:
    message = (
        f"عزيزي {employee.full_name}، لم يتم تسجيل انصرافك ليوم {absence_date}. "
        f"تم تسجيل غياب وخصم بقيمة {deduction} من راتبك."
    )

    phone = getattr(employee, "phone_number", None)
    email = getattr(getattr(employee, "user", None), "email", None)

    results = []

    if phone:
        try:
            send_sms_twilio(phone, message)
            results.append(True)
        except Exception as exc:  # pragma: no cover - depends on external service
            logger.warning("Failed to send SMS notification to %s: %s", phone, exc)
            results.append(False)

    if email:
        try:
            send_mail(
                subject="تنبيه عدم تسجيل انصراف",
                message=message,
                from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
                recipient_list=[email],
                fail_silently=False,
            )
            results.append(True)
        except Exception as exc:  # pragma: no cover - depends on email backend
            logger.warning("Failed to send email notification to %s: %s", email, exc)
            results.append(False)

    if not results:
        return None

    return all(results)


def _make_aware(dt: datetime) -> datetime:
    tz = timezone.get_current_timezone()
    if timezone.is_naive(dt):
        return timezone.make_aware(dt, tz)
    return dt.astimezone(tz)
