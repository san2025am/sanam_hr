from datetime import datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from .models import (
    AttendanceRecord,
    Employee,
    EmployeeShiftAssignment,
    Role,
    Salary,
    Shift,
)
from .services.attendance import (
    DEFAULT_AUTO_CLOSE_GRACE_MINUTES,
    close_stale_attendance_for_employee,
)


class AttendanceAutoCloseTests(TestCase):
    def setUp(self):
        role = Role.objects.create(name="guard")
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="guard1",
            password="pass",
        )
        self.user.role = role
        self.user.save(update_fields=["role"])

        self.employee = Employee.objects.create(
            user=self.user,
            full_name="Guard One",
            national_id="1234567890",
            phone_number="1234567890",
        )

        self.shift = Shift.objects.create(
            name="صباحي",
            start_time=time(8, 0),
            end_time=time(16, 0),
        )

        self.assignment = EmployeeShiftAssignment.objects.create(
            employee=self.employee,
            shift=self.shift,
            active=True,
        )

        Salary.objects.create(
            employee=self.employee,
            base_salary=Decimal("3000.00"),
            deductions=Decimal("0.00"),
        )

    def _make_check_in(self, check_in_dt: datetime) -> AttendanceRecord:
        return AttendanceRecord.objects.create(
            employee=self.employee,
            location=None,
            shift=self.shift,
            check_in_time=check_in_dt,
        )

    def test_auto_close_creates_violation_and_deduction(self):
        tz = timezone.get_current_timezone()
        check_in_dt = timezone.make_aware(datetime(2024, 1, 1, 8, 5), tz)
        record = self._make_check_in(check_in_dt)

        shift_duration = timedelta(hours=8, minutes=-5)
        cutoff = check_in_dt + shift_duration
        as_of = cutoff + timedelta(minutes=DEFAULT_AUTO_CLOSE_GRACE_MINUTES + 10)

        actions = close_stale_attendance_for_employee(
            self.employee,
            as_of=as_of,
            notify=False,
        )

        self.assertEqual(len(actions), 1)

        refreshed_salary = Salary.objects.get(employee=self.employee)
        expected_deduction = Decimal("100.00")  # 3000 / 30
        self.assertEqual(refreshed_salary.deductions, expected_deduction)

        violation = self.employee.violations.get()
        self.assertEqual(violation.deduction_value, expected_deduction)
        self.assertEqual(violation.warning_level, 1)

        archived_record = AttendanceRecord.all_objects.get(pk=record.pk)
        self.assertIsNotNone(archived_record.deleted_at)

    def test_auto_close_skips_recent_records(self):
        tz = timezone.get_current_timezone()
        check_in_dt = timezone.make_aware(datetime(2024, 1, 2, 8, 0), tz)
        record = self._make_check_in(check_in_dt)

        as_of = check_in_dt + timedelta(hours=4)
        actions = close_stale_attendance_for_employee(
            self.employee,
            as_of=as_of,
            notify=False,
        )

        self.assertEqual(actions, [])
        self.assertTrue(AttendanceRecord.objects.filter(pk=record.pk).exists())
