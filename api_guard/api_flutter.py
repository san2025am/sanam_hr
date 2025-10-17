from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal

from django.utils import timezone
from django.shortcuts import get_object_or_404

from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status, serializers

from policies.utils.calendar import is_day_off, is_public_holiday, is_weekly_off
from policies.models import PublicHoliday
from api_guard.models import Employee, Request, EmployeeLeaveBalance
from payroll.models import PayrollItem, Reward, Overtime
from payroll.utils import get_or_create_cycle, build_item_for_employee


def _user_employee(request) -> Employee:
    emp = getattr(request.user, 'employee', None)
    if emp is None:
        raise serializers.ValidationError({"detail": "الحساب غير مرتبط بموظف"})
    return emp


class TodayHolidayView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        emp = _user_employee(request)
        today = timezone.localdate()
        off = is_day_off(today, employee=emp)
        reason = None
        title = None
        if off:
            # سبب العطلة: عطلة رسمية أو راحة أسبوعية أو استثناء محلي
            if is_public_holiday(today, employee=emp):
                reason = 'public_holiday'
                hol = PublicHoliday.objects.filter(date=today).first() or \
                      PublicHoliday.objects.filter(repeats_annually=True, date__month=today.month, date__day=today.day).first()
                title = getattr(hol, 'name', None) or 'عطلة رسمية'
            elif is_weekly_off(today, employee=emp):
                reason = 'weekly_off'
                title = today.strftime('%A')
            else:
                reason = 'local_exception'
                title = 'استثناء محلي'
        return Response({
            'date': str(today),
            'is_day_off': off,
            'reason': reason,
            'title': title,
        })


class LeaveBalanceView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        emp = _user_employee(request)
        today = timezone.localdate()
        qs = EmployeeLeaveBalance.objects.filter(employee=emp, year=today.year)
        accrued = Decimal('0')
        taken = Decimal('0')
        for b in qs:
            accrued += (b.quota_days or Decimal('0')) + (b.carry_over_days or Decimal('0'))
            taken += (b.used_paid_days or Decimal('0'))
        remaining = accrued - taken
        if remaining < 0:
            remaining = Decimal('0')
        return Response({
            'unit': 'days',
            'accrued': float(accrued),
            'taken': float(taken),
            'remaining': float(remaining),
        })


class LeaveApplySerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=[('paid', 'مدفوعة'), ('unpaid', 'غير مدفوعة')])
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    reason = serializers.CharField(allow_blank=True, required=False)


class LeaveApplyView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        emp = _user_employee(request)
        ser = LeaveApplySerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        # نخزن نوع الإجازة ضمن الوصف لعدم وجود حقل مستقل الآن
        desc = (data.get('reason') or '').strip()
        desc = f"[type={data['type']}]\n{desc}" if desc else f"[type={data['type']}]"
        # حدد أوقات البداية والنهاية كاليوم الكامل
        sd = datetime.combine(data['start_date'], time(0, 0))
        ed = datetime.combine(data['end_date'], time(23, 59, 59))
        sd = timezone.make_aware(sd, timezone.get_current_timezone())
        ed = timezone.make_aware(ed, timezone.get_current_timezone())

        req = Request.objects.create(
            employee=emp,
            request_type='leave',
            description=desc,
            status='pending',
            leave_start=sd,
            leave_end=ed,
        )
        return Response({
            'ok': True,
            'request_id': str(req.id),
            'status': req.status,
        }, status=status.HTTP_201_CREATED)


class PayslipView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, y: int, m: int):
        emp = _user_employee(request)
        cycle = get_or_create_cycle(y, m)
        item = PayrollItem.objects.filter(cycle=cycle, employee=emp).first()
        if item is None:
            item = build_item_for_employee(cycle=cycle, employee=emp)
        payload = {
            'year': y,
            'month': m,
            'status': cycle.status,
            'base_salary': float(item.base_salary or 0),
            'daily_rate': float(item.daily_rate or 0),
            'default_working_days': float(item.default_working_days or 0),
            'payable_days': float(item.payable_days or 0),
            'days_amount': float(item.days_amount or 0),
            'allowances_total': float(item.allowances_total or 0),
            'overtime_total': float(item.overtime_total or 0),
            'gross': float(item.gross or 0),
            'deductions_applied': float(item.deductions_applied or 0),
            'deductions_excess_carried': float(item.deductions_excess_carried or 0),
            'net_pay': float(item.net_pay or 0),
            'detail': item.detail or {},
            'item_id': str(item.id),
        }
        return Response(payload)


class MonthHolidaysView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, y: int, m: int):
        emp = _user_employee(request)
        # ابني قائمة الأيام 1..N مع حالة يوم العطلة + سبب مختصر
        tz = timezone.get_current_timezone()
        # حدد عدد الأيام في الشهر
        from calendar import monthrange
        _, days_in_month = monthrange(y, m)
        results = []
        for d in range(1, days_in_month + 1):
            dt = date(y, m, d)
            off = is_day_off(dt, employee=emp)
            reason = None
            if off:
                if is_public_holiday(dt, employee=emp):
                    reason = 'public_holiday'
                elif is_weekly_off(dt, employee=emp):
                    reason = 'weekly_off'
                else:
                    reason = 'local_exception'
            results.append({'day': d, 'is_day_off': bool(off), 'reason': reason})
        return Response({'year': y, 'month': m, 'days': results})


class RewardsListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        emp = _user_employee(request)
        try:
            y = int(request.query_params.get('year') or 0)
            m = int(request.query_params.get('month') or 0)
        except Exception:
            y = m = 0
        qs = Reward.objects.filter(employee=emp)
        if y and m:
            qs = qs.filter(date__year=y, date__month=m)
        qs = qs.order_by('-date')
        data = [
            {
                'id': str(r.id),
                'date': str(r.date),
                'amount': float(r.amount or 0),
                'reason': r.reason,
                'approved': bool(r.approved),
            }
            for r in qs
        ]
        return Response({'results': data})


class OvertimeListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        emp = _user_employee(request)
        try:
            y = int(request.query_params.get('year') or 0)
            m = int(request.query_params.get('month') or 0)
        except Exception:
            y = m = 0
        qs = Overtime.objects.filter(employee=emp)
        if y and m:
            qs = qs.filter(date__year=y, date__month=m)
        qs = qs.order_by('-date')
        data = [
            {
                'id': str(o.id),
                'date': str(o.date),
                'hours': float(o.hours or 0),
                'classification': o.classification,
                'approved': bool(o.approved),
                'note': o.note,
            }
            for o in qs
        ]
        return Response({'results': data})


class MarkItemPaidView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        emp = _user_employee(request)
        item = get_object_or_404(PayrollItem, pk=pk, employee=emp)
        detail = dict(item.detail or {})
        detail['paid'] = True
        detail['paid_at'] = timezone.now().isoformat()
        item.detail = detail
        item.save(update_fields=['detail'])
        return Response({'ok': True, 'paid': True, 'paid_at': detail['paid_at']})
