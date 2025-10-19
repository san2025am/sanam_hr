from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib import admin
from api_guard.models import Location, Shift
from api_guard.admin import LocationAdmin, ShiftAdmin

User = get_user_model()

class CapacityAdminTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.site = admin.site
        self.location = Location.objects.create(name="L", guard_capacity=5)
        self.shift = Shift.objects.create(name="S", start_at="08:00", end_at="16:00", guard_capacity=5)

        self.superuser = User.objects.create_superuser("admin", "a@a.com", "x")
        self.hr = User.objects.create_user("hr", password="x", is_staff=True)
        self.staff = User.objects.create_user("st", password="x", is_staff=True)

        g, _ = Group.objects.get_or_create(name="HR")
        self.hr.groups.add(g)

    def _req(self, user):
        req = self.factory.get("/")
        req.user = user
        return req

    def test_location_guard_capacity_editable_for_hr(self):
        ma = LocationAdmin(Location, self.site)
        # HR: يجب ألا يكون guard_capacity ضمن readonly
        ro = ma.get_readonly_fields(self._req(self.hr), self.location)
        self.assertNotIn("guard_capacity", ro)

    def test_location_guard_capacity_readonly_for_non_hr(self):
        ma = LocationAdmin(Location, self.site)
        ro = ma.get_readonly_fields(self._req(self.staff), self.location)
        self.assertIn("guard_capacity", ro)

    def test_shift_guard_capacity_editable_for_hr(self):
        ma = ShiftAdmin(Shift, self.site)
        ro = ma.get_readonly_fields(self._req(self.hr), self.shift)
        self.assertNotIn("guard_capacity", ro)

    def test_shift_guard_capacity_readonly_for_non_hr(self):
        ma = ShiftAdmin(Shift, self.site)
        ro = ma.get_readonly_fields(self._req(self.staff), self.shift)
        self.assertIn("guard_capacity", ro)

