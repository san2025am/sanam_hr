from django.core.management.base import BaseCommand
from django.utils import timezone

from api_guard.models import Employee
from policies.utils.leaves import accrue_month_for_employee


class Command(BaseCommand):
    help = "Accrue monthly paid leave days for all employees based on LeavePolicy."

    def add_arguments(self, parser):
        parser.add_argument('--year', type=int, help='Target year (defaults to current)')
        parser.add_argument('--month', type=int, help='Target month 1..12 (defaults to current)')

    def handle(self, *args, **options):
        now = timezone.localdate()
        year = options.get('year') or now.year
        month = options.get('month') or now.month

        total_added = 0.0
        for emp in Employee.objects.all():
            added = accrue_month_for_employee(employee=emp, year=year, month=month)
            total_added += float(added)
        self.stdout.write(self.style.SUCCESS(f"Accrual complete for {year}-{month:02d}. Total added days: {total_added:.2f}"))

