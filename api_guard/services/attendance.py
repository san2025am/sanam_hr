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
    ShiftAbsenceLog,
    Salary,
    ViolationRule,
)
from ..sms import send_sms_twilio

logger = logging.getLogger(__name__)

MISSING_CHECKOUT_RULE_TITLE = "عدم تسجيل الانصراف"
MISSING_CHECKOUT_RULE_DESCRIPTION = (
    "مخالفة تلقائية عند عدم تسجيل الانصراف قبل إغلاق الوردية."
)
MISSING_CHECKIN_RULE_TITLE = "عدم تسجيل الحضور"
MISSING_CHECKIN_RULE_DESCRIPTION = (
    "مخالفة تلقائية عند عدم تسجيل الحضور للوردية المجدولة."
)
DEFAULT_AUTO_CLOSE_GRACE_MINUTES = 15
DEFAULT_WARNING_WINDOW_HOURS = 6
ONE_DAY = timedelta(days=1)
ABSENCE_LOOKBACK_DAYS = 2


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


def flag_absent_employees(
    *,
    as_of: Optional[datetime] = None,
    employees: Optional[Iterable[Employee]] = None,
    notify: bool = True,
) -> list[dict]:
    """
    يرصد الورديات التي انتهت بدون تسجيل حضور، ثم يضيف مخالفة غياب ويقوم بالإشعار.
    """
    as_of = as_of or timezone.now()
    local_now = timezone.localtime(as_of)
    actions: list[dict] = []

    assignments = (EmployeeShiftAssignment.objects
                   .select_related(
                        "employee",
                        "employee__user",
                        "employee__supervisor",
                        "shift",
                        "location",
                   )
                   .filter(active=True))
    if employees is not None:
        employee_ids = [emp.id for emp in employees if getattr(emp, "id", None)]
        if not employee_ids:
            return actions
        assignments = assignments.filter(employee_id__in=employee_ids)

    lookback_threshold = as_of - timedelta(days=ABSENCE_LOOKBACK_DAYS)

    for assignment in assignments:
        shift = assignment.shift
        employee = assignment.employee
        if shift is None or employee is None:
            continue

        start_time = assignment.start_time or shift.start_time
        end_time = assignment.end_time or shift.end_time
        if not (start_time and end_time):
            continue

        candidate_dates = []
        if assignment.date:
            candidate_dates = [assignment.date]
        else:
            candidate_dates = [local_now.date(), local_now.date() - ONE_DAY]

        for anchor_date in candidate_dates:
            if anchor_date is None:
                continue
            if assignment.date and anchor_date != assignment.date:
                continue

            window_bounds = _assignment_window_bounds(assignment, anchor_date)
            if window_bounds is None:
                continue
            window_start, window_end, nominal_start, nominal_end = window_bounds

            if window_end is None or window_start is None:
                continue
            if window_end > as_of:
                continue
            if window_end < lookback_threshold:
                continue

            attendance_date = nominal_start.date()
            if ShiftAbsenceLog.objects.filter(
                employee=employee,
                shift=shift,
                date=attendance_date,
                deleted_at__isnull=True,
            ).exists():
                continue

            has_attendance = AttendanceRecord.objects.filter(
                employee=employee,
                check_in_time__gte=window_start,
                check_in_time__lte=window_end,
                deleted_at__isnull=True,
            ).exists()
            if has_attendance:
                continue

            with transaction.atomic():
                deduction = _apply_salary_deduction(employee)
                violation = _create_absence_violation(
                    assignment=assignment,
                    absence_date=attendance_date,
                    deduction=deduction,
                )
                log = ShiftAbsenceLog.objects.create(
                    employee=employee,
                    shift=shift,
                    assignment=assignment,
                    location=assignment.location,
                    date=attendance_date,
                    violation=violation,
                )

            notification_status = None
            if notify:
                notification_status = _notify_absence(
                    employee=employee,
                    absence_date=attendance_date,
                    deduction=deduction,
                    shift=shift,
                    location=assignment.location,
                )
                if notification_status is not None:
                    ShiftAbsenceLog.objects.filter(pk=log.pk).update(notified=bool(notification_status))

            actions.append({
                "employee_id": employee.id,
                "shift_id": shift.id,
                "assignment_id": assignment.id,
                "absence_date": attendance_date,
                "deduction": deduction,
                "violation_id": violation.id if violation else None,
                "notified": notification_status,
            })

    return actions


def flag_absent_assignments_for_employee(
    employee: Employee,
    *,
    as_of: Optional[datetime] = None,
    notify: bool = True,
) -> list[dict]:
    if employee is None:
        return []
    return flag_absent_employees(as_of=as_of, employees=[employee], notify=notify)


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

    # اليوم المرجعي للوردية: يوم البداية دائمًا
    # إن كانت الوردية ليلية (تعبر منتصف الليل) وكان وقت الحضور في ساعات الصباح قبل end_time
    # فاجعل اليوم المرجعي هو اليوم السابق
    anchor_date = getattr(assignment, "date", None)
    if anchor_date is None:
        anchor_date = local_check_in.date()
        if end_time <= start_time:
            try:
                current_t = local_check_in.timetz() if hasattr(local_check_in, 'timetz') else local_check_in.time()
            except Exception:
                current_t = local_check_in.time()
            if current_t < end_time:
                anchor_date = anchor_date - timedelta(days=1)

    start_dt = _make_aware(datetime.combine(anchor_date, start_time))
    end_dt = _make_aware(datetime.combine(anchor_date, end_time))
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


def _assignment_window_bounds(
    assignment: EmployeeShiftAssignment,
    anchor_date,
) -> Optional[tuple[datetime, datetime, datetime, datetime]]:
    shift = assignment.shift
    if shift is None or anchor_date is None:
        return None

    start_time = assignment.start_time or shift.start_time
    end_time = assignment.end_time or shift.end_time
    if not (start_time and end_time):
        return None

    start_naive = datetime.combine(anchor_date, start_time)
    end_naive = datetime.combine(anchor_date, end_time)
    if end_time <= start_time:
        end_naive += ONE_DAY

    start_dt = _make_aware(start_naive)
    end_dt = _make_aware(end_naive)

    pre_minutes = int(getattr(assignment, "pre_shift_buffer_minutes", 0) or 0)
    post_minutes = int(getattr(assignment, "post_shift_buffer_minutes", 0) or 0)

    window_start = start_dt - timedelta(minutes=pre_minutes)
    window_end = end_dt + timedelta(minutes=post_minutes)

    return window_start, window_end, start_dt, end_dt


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


def _create_absence_violation(
    *,
    assignment: EmployeeShiftAssignment,
    absence_date,
    deduction: Decimal,
) -> Optional[EmployeeViolation]:
    employee = assignment.employee
    shift = assignment.shift
    try:
        rule = ViolationRule.objects.get(title=MISSING_CHECKIN_RULE_TITLE)
    except ViolationRule.DoesNotExist:
        rule = ViolationRule.objects.create(
            title=MISSING_CHECKIN_RULE_TITLE,
            description=MISSING_CHECKIN_RULE_DESCRIPTION,
            default_action="deduct",
            default_deduction_percent=Decimal("0"),
        )

    warning_level = (
        EmployeeViolation.objects.filter(employee=employee, rule=rule).count() + 1
    )

    shift_name = getattr(shift, "name", "")
    description = (
        f"تسجيل غياب ليوم {absence_date.isoformat()} بسبب عدم تسجيل الحضور"
        f"{f' للوردية {shift_name}' if shift_name else ''}."
    )

    violation = EmployeeViolation.objects.create(
        employee=employee,
        rule=rule,
        reported_by=employee.supervisor,
        location=assignment.location,
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
    return _dispatch_notification(
        employee=employee,
        subject="تنبيه عدم تسجيل انصراف",
        message=message,
    )


def _notify_absence(
    *,
    employee: Employee,
    absence_date,
    deduction: Decimal,
    shift,
    location,
) -> Optional[bool]:
    shift_part = f" للوردية {getattr(shift, 'name', '')}" if getattr(shift, "name", "") else ""
    location_part = f" في موقع {getattr(location, 'name', '')}" if getattr(location, "name", "") else ""
    deduction_part = f" وتم تطبيق خصم بقيمة {deduction}." if deduction and deduction > 0 else "."
    message = (
        f"عزيزي {employee.full_name}، لم يتم تسجيل حضورك{shift_part}{location_part} ليوم {absence_date}. "
        f"تم تسجيل مخالفة غياب{deduction_part}"
    )
    return _dispatch_notification(
        employee=employee,
        subject="تنبيه غياب بدون تسجيل حضور",
        message=message,
    )


def _dispatch_notification(
    *,
    employee: Employee,
    subject: str,
    message: str,
) -> Optional[bool]:
    phone = getattr(employee, "phone_number", None)
    email = getattr(getattr(employee, "user", None), "email", None)

    results: list[bool] = []

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
                subject=subject,
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
