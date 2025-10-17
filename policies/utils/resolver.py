from __future__ import annotations

from datetime import date
from typing import Optional, Any

from django.db.models import Q
from django.utils import timezone

from policies.models import PolicyBundle, PolicyTarget


def resolve_policy(
    policy_type: str,
    *,
    role_id: Optional[Any] = None,
    location_id: Optional[Any] = None,
    shift_id: Optional[Any] = None,
    on_date: Optional[date] = None,
) -> Optional[PolicyBundle]:
    """
    Policy Resolver — اختيار السياسة الفعّالة وفق النطاق والأولوية.

    آلية الاختيار:
    1) يتم جلب جميع الحزم من نوع `policy_type` المفعّلة زمنيًا (start_date ≤ اليوم ≤ end_date إن وُجد).
    2) تُرتّب أولوية النطاقات كالتالي: SHIFT → LOCATION → ROLE → GLOBAL.
       - إن وُجدت سياسة على مستوى SHIFT لنفس الورديّة تُفضّل على غيرها.
       - إن لم يوجد، نبحث على مستوى LOCATION، ثم ROLE، ثم GLOBAL.
    3) عند تساوي السياسات داخل نفس النطاق:
       - تُختار الأقل `priority` (الأصغر أقوى).
       - وإن تساوت الأولوية، تُختار الأحدث `start_date`.

    المدخلات:
    - policy_type: سلسلة Choices كما عرّفت في PolicyBundle.PolicyType
    - role_id/location_id/shift_id: معرّفات اختيارية لتقييد النطاق المناسب.
    - on_date: التاريخ المرجعي للتفعيل (افتراضي: اليوم في المنطقة الزمنية للخادم).

    القيمة المعادة:
    - PolicyBundle المختارة أو None إن لم توجد أي سياسة مطابقة.
    """

    ref_date = on_date or timezone.localdate()

    # قاعدة زمنية عامة
    time_q = Q(bundle__start_date__lte=ref_date) & (Q(bundle__end_date__isnull=True) | Q(bundle__end_date__gte=ref_date))

    base = PolicyTarget.objects.select_related("bundle").filter(
        bundle__policy_type=policy_type,
        bundle__is_active=True,
    ).filter(time_q)

    # قبول كائنات موديل أو معرفات
    def _pk(v: Any) -> Optional[str]:
        return getattr(v, "pk", v)

    role_id = _pk(role_id)
    location_id = _pk(location_id)
    shift_id = _pk(shift_id)

    # حسب الترتيب المطلوب: SHIFT → LOCATION → ROLE → GLOBAL
    # SHIFT
    if shift_id:
        qs = base.filter(scope=PolicyTarget.Scope.SHIFT, shift_id=shift_id).order_by("bundle__priority", "-bundle__start_date", "-bundle__created_at")
        top = qs.first()
        if top:
            return top.bundle

    # LOCATION
    if location_id:
        qs = base.filter(scope=PolicyTarget.Scope.LOCATION, location_id=location_id).order_by("bundle__priority", "-bundle__start_date", "-bundle__created_at")
        top = qs.first()
        if top:
            return top.bundle

    # ROLE
    if role_id:
        qs = base.filter(scope=PolicyTarget.Scope.ROLE, role_id=role_id).order_by("bundle__priority", "-bundle__start_date", "-bundle__created_at")
        top = qs.first()
        if top:
            return top.bundle

    # GLOBAL
    qs = base.filter(scope=PolicyTarget.Scope.GLOBAL).order_by("bundle__priority", "-bundle__start_date", "-bundle__created_at")
    top = qs.first()
    return top.bundle if top else None
