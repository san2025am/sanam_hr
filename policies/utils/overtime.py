from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional, Any, Dict

from django.utils import timezone

from policies.models import PolicyBundle, OvertimeRewardsPolicy
from policies.utils.resolver import resolve_policy
from policies.utils.calendar import is_public_holiday, is_weekly_off


def get_effective_overtime_policy(
    *,
    employee=None,
    location=None,
    shift=None,
    on_date: Optional[date] = None,
) -> Optional[OvertimeRewardsPolicy]:
    role_id = getattr(getattr(employee, 'user', None), 'role_id', None) if employee is not None else None
    bundle = resolve_policy(
        PolicyBundle.PolicyType.OVERTIME_REWARDS,
        role_id=role_id,
        location_id=getattr(location, 'pk', location),
        shift_id=getattr(shift, 'pk', shift),
        on_date=on_date or timezone.localdate(),
    )
    if not bundle:
        return None
    return OvertimeRewardsPolicy.objects.filter(bundle=bundle).first()


def default_rates(policy: Optional[OvertimeRewardsPolicy]) -> Dict[str, Decimal]:
    if policy is None:
        return {
            'normal': Decimal('1.50'),
            'night': Decimal('1.75'),
            'offday': Decimal('2.00'),
            'public_holiday': Decimal('2.50'),
            'cap': None,
        }
    return {
        'normal': Decimal(str(policy.normal_rate or 1.5)),
        'night': Decimal(str(policy.night_rate or 1.75)),
        'offday': Decimal(str(policy.offday_rate or 2.0)),
        'public_holiday': Decimal(str(policy.public_holiday_rate or 2.5)),
        'cap': (Decimal(str(policy.monthly_hours_cap)) if policy.monthly_hours_cap is not None else None),
    }

