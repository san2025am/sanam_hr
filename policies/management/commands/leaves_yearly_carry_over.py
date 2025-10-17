from django.core.management.base import BaseCommand
from django.utils import timezone

from api_guard.models import Employee
from policies.utils.leaves import carry_over_year_for_employee


class Command(BaseCommand):
    help = "Carry over unused leave days at year end up to policy maximum."

    def add_arguments(self, parser):
        parser.add_argument('--year', type=int, help='Base year to carry from (defaults to last year if run in January, otherwise current year)')

    def handle(self, *args, **options):
        today = timezone.localdate()
        year = options.get('year')
        if not year:
            # If running in Jan, carry previous year; else carry current year
            year = today.year - 1 if today.month == 1 else today.year

        total_carried = 0.0
        for emp in Employee.objects.all():
            carried = carry_over_year_for_employee(employee=emp, year=year)
            total_carried += float(carried)
        self.stdout.write(self.style.SUCCESS(f"Carry-over complete for {year}. Total carried days: {total_carried:.2f}"))

