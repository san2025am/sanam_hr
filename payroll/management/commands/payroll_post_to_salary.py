from django.core.management.base import BaseCommand
from django.utils import timezone

from payroll.utils import post_cycle_to_salary


class Command(BaseCommand):
    help = "Post payroll cycle amounts to Salary model (bonuses, overtime, deductions, pay_date)."

    def add_arguments(self, parser):
        parser.add_argument('--year', type=int)
        parser.add_argument('--month', type=int)
        parser.add_argument('--force', action='store_true', help='Override already posted items')

    def handle(self, *args, **opts):
        today = timezone.localdate()
        year = opts.get('year') or today.year
        month = opts.get('month') or today.month
        force = bool(opts.get('force'))
        n = post_cycle_to_salary(year=year, month=month, force=force)
        self.stdout.write(self.style.SUCCESS(f"Posted {n} payroll items to Salary for {year}-{month:02d}."))

