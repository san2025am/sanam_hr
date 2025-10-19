from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from api_guard.models import Location, Shift, Employee, EmployeeLocationAssignment

User = get_user_model()

class CapacityModelTests(TestCase):
    def setUp(self):
        # مستخدمو الاختبار
        self.superuser = User.objects.create_superuser(username="admin", email="a@a.com", password="x")
        self.hr = User.objects.create_user(username="hr", password="x", is_staff=True)
        self.user = User.objects.create_user(username="staff", password="x", is_staff=True)

        # اجعل hr ضمن مجموعة HR إن كانت موجودة
        try:
            from django.contrib.auth.models import Group
            g, _ = Group.objects.get_or_create(name="HR")
            self.hr.groups.add(g)
        except Exception:
            pass

        # بيانات
        self.loc = Location.objects.create(name="Site A", guard_capacity=2)
        self.shift_day = Shift.objects.create(name="Day", start_at="08:00", end_at="16:00", guard_capacity=1)
        self.shift_night = Shift.objects.create(name="Night", start_at="16:00", end_at="00:00", guard_capacity=2)
        self.emp1 = Employee.objects.create(full_name="Emp1", national_id="111")
        self.emp2 = Employee.objects.create(full_name="Emp2", national_id="222")
        self.emp3 = Employee.objects.create(full_name="Emp3", national_id="333")

    def test_site_capacity_blocks_extra_assignments(self):
        # سِعة الموقع = 2
        EmployeeLocationAssignment.objects.create(employee=self.emp1, location=self.loc, shift=self.shift_day)
        EmployeeLocationAssignment.objects.create(employee=self.emp2, location=self.loc, shift=self.shift_night)
        with self.assertRaises(Exception):
            EmployeeLocationAssignment.objects.create(employee=self.emp3, location=self.loc, shift=self.shift_night)

    def test_shift_capacity_blocks_extra_assignments_for_same_site(self):
        # سعة الوردية Day = 1
        EmployeeLocationAssignment.objects.create(employee=self.emp1, location=self.loc, shift=self.shift_day)
        with self.assertRaises(Exception):
            EmployeeLocationAssignment.objects.create(employee=self.emp2, location=self.loc, shift=self.shift_day)

    def test_after_hr_increases_capacity_assignment_is_allowed(self):
        # امتلاء الموقع أولاً
        EmployeeLocationAssignment.objects.create(employee=self.emp1, location=self.loc, shift=self.shift_day)
        EmployeeLocationAssignment.objects.create(employee=self.emp2, location=self.loc, shift=self.shift_night)
        # زيادة السعة بواسطة HR (محاكاة مجردة: تعديل القيمة)
        self.loc.guard_capacity = 3
        self.loc.save()
        # الآن يُسمح بتعيين ثالث
        EmployeeLocationAssignment.objects.create(employee=self.emp3, location=self.loc, shift=self.shift_night)
        self.assertEqual(
            EmployeeLocationAssignment.objects.filter(location=self.loc).count(), 3
        )

    def test_default_capacity_is_five_after_migration_like_behavior(self):
        # إذا كانت المشاريع مهيأة بميجريشن البيانات، السجلات الجديدة تأخذ 5 افترضياً
        l2 = Location.objects.create(name="Site B")  # بدون تحديد
        s2 = Shift.objects.create(name="Late", start_at="00:00", end_at="08:00")  # بدون تحديد
        self.assertEqual(l2.guard_capacity, 5)
        self.assertEqual(s2.guard_capacity, 5)

