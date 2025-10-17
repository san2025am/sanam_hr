from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from api_guard.models import Employee
from payroll.models import PayrollCycle
from payroll.utils import get_active_config, build_item_for_employee


class Command(BaseCommand):
    help = "Build monthly payroll cycle and items."

    def add_arguments(self, parser):
        parser.add_argument('--year', type=int)
        parser.add_argument('--month', type=int)
        parser.add_argument('--close', action='store_true', help='Mark cycle as closed after building')

    def handle(self, *args, **opts):
        today = timezone.localdate()
        year = opts.get('year') or today.year
        month = opts.get('month') or today.month
        if not (1 <= int(month) <= 12):
            raise CommandError('Invalid month')

        cfg = get_active_config()
        with transaction.atomic():
            cycle, created = PayrollCycle.objects.get_or_create(year=year, month=month, defaults={'config': cfg})
            if not created and cycle.config_id != cfg.id:
                cycle.config = cfg
                cycle.save(update_fields=['config'])

            # wipe old items if rebuilding
            cycle.items.all().delete()

            count = 0
            for emp in Employee.objects.all():
                build_item_for_employee(cycle=cycle, employee=emp)
                count += 1

            if opts.get('close'):
                cycle.status = PayrollCycle.Status.CLOSED
                cycle.save(update_fields=['status'])

        self.stdout.write(self.style.SUCCESS(f"Built payroll cycle {year}-{month:02d} with {count} items."))

