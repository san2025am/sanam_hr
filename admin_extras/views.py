from datetime import date, timedelta

from django.contrib.admin.views.decorators import staff_member_required
from django.db.models.functions import TruncMonth, TruncDate
from django.db import models
from django.db.models import Count
from django.http import JsonResponse, HttpResponseBadRequest
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from api_guard.models import (
    Employee, Location, Report, Request,
    AttendanceRecord, EmployeeViolation, ROLE_NAME_CHOICES, LocationPing,
    GeofenceViolationPause, TrackingIncident,
)
from .models import ChatMessage


@staff_member_required
def dashboard_view(request):
    employees_count = Employee.objects.count()
    locations_count = Location.objects.count()
    reports_count = Report.objects.count()
    requests_count = Request.objects.count()

    # Today stats
    today = timezone.localdate()
    attendance_today = AttendanceRecord.objects.filter(
        models.Q(check_in_time__date=today) | models.Q(timestamp__date=today)
    ).count()
    violations_today = EmployeeViolation.objects.filter(occurred_at__date=today).count()
    # Geofence withdrawals (outside-radius/polygon) captured via LocationPing.violation_triggered
    withdrawals_today = LocationPing.objects.filter(violation_triggered=True, recorded_at__date=today).count()
    # Escalations to absence due to repeated withdrawals (by rule title)
    escalations_rule_title = "غياب بسبب الانسحاب المتكرر"
    escalations_today = EmployeeViolation.objects.filter(occurred_at__date=today, rule__title=escalations_rule_title).count()
    pending_requests_count = Request.objects.filter(status='pending').count()

    # Reports per month (last 6 months)
    now = timezone.now().date()
    start_month = date(now.year - (1 if now.month <= 6 else 0), ((now.month - 6 - 1) % 12) + 1, 1)
    report_series_qs = (
        Report.objects
        .filter(created_at__date__gte=start_month)
        .annotate(month=TruncMonth('created_at'))
        .values('month')
        .annotate(total=Count('id'))
        .order_by('month')
    )
    months = []
    totals = []
    for row in report_series_qs:
        months.append(row['month'].strftime('%Y-%m'))
        totals.append(row['total'])

    # Requests by status
    req_by_status_codes = dict(Request.objects.values_list('status').annotate(c=Count('id')))
    req_by_status = {dict(Request.STATUS_CHOICES).get(k, k): v for k, v in req_by_status_codes.items()}

    # Reports by type (bar/pie)
    reports_by_type_codes = dict(Report.objects.values_list('report_type').annotate(c=Count('id')))
    reports_by_type = {dict(Report.REPORT_TYPE_CHOICES).get(k, k): v for k, v in reports_by_type_codes.items()}

    # Requests by type
    requests_by_type_codes = dict(Request.objects.values_list('request_type').annotate(c=Count('id')))
    requests_by_type = {dict(Request.REQUEST_TYPE_CHOICES).get(k, k): v for k, v in requests_by_type_codes.items()}

    # Employees by role
    roles_map = dict(ROLE_NAME_CHOICES)
    roles_counts = {}
    for code, c in (
        Employee.objects
        .filter(user__role__isnull=False)
        .values_list('user__role__name')
        .annotate(c=Count('id'))
    ):
        roles_counts[roles_map.get(code, code)] = c

    # Attendance last 7 days
    start_day = today - timedelta(days=6)
    att_series_qs = (
        AttendanceRecord.objects
        .filter(models.Q(check_in_time__date__gte=start_day) | models.Q(timestamp__date__gte=start_day))
        .annotate(day=TruncMonth('timestamp'))
    )
    # If timestamp is missing, fallback to check_in_time
    att_series_qs = (
        AttendanceRecord.objects.filter(
            models.Q(check_in_time__date__gte=start_day) | models.Q(timestamp__date__gte=start_day)
        )
        .annotate(day=models.functions.TruncDate(models.Case(
            models.When(timestamp__isnull=False, then='timestamp'),
            default='check_in_time',
        )))
        .values('day').annotate(total=Count('id')).order_by('day')
    )
    att_days = [row['day'].strftime('%Y-%m-%d') for row in att_series_qs]
    att_counts = [row['total'] for row in att_series_qs]

    # Extra charts
    # Reports by status
    reports_by_status_codes = dict(Report.objects.values_list('status').annotate(c=Count('id')))
    reports_by_status = {dict(Report.STATUS_CHOICES).get(k, k): v for k, v in reports_by_status_codes.items()}

    # Violations by rule (top 10)
    violations_by_rule_qs = (
        EmployeeViolation.objects
        .values('rule__title')
        .annotate(c=Count('id'))
        .order_by('-c')[:10]
    )
    violations_by_rule = {row['rule__title'] or 'غير محدد': row['c'] for row in violations_by_rule_qs}

    # Top employees by geofence withdrawals today (top 10)
    top_withdrawals_qs = (
        LocationPing.objects
        .filter(violation_triggered=True, recorded_at__date=today)
        .values('employee__full_name')
        .annotate(c=Count('id'))
        .order_by('-c')[:10]
    )
    top_withdrawals_today = {row['employee__full_name'] or 'غير محدد': row['c'] for row in top_withdrawals_qs}

    # Attendance breakdown (last 30 days)
    last30 = today - timedelta(days=30)
    att_qs = AttendanceRecord.objects.filter(
        models.Q(check_in_time__date__gte=last30) | models.Q(timestamp__date__gte=last30)
    )
    attendance_breakdown = {
        'انتهاكات': att_qs.filter(is_violation=True).count(),
        'طبيعي': att_qs.filter(is_violation=False).count(),
    }

    # Top locations by reports (top 6)
    top_locations_qs = (
        Report.objects.values('location__name').annotate(c=Count('id')).order_by('-c')[:6]
    )
    top_locations_reports = {row['location__name'] or 'غير محدد': row['c'] for row in top_locations_qs}

    context = {
        'employees_count': employees_count,
        'locations_count': locations_count,
        'reports_count': reports_count,
        'requests_count': requests_count,
        'attendance_today': attendance_today,
        'violations_today': violations_today,
        'pending_requests_count': pending_requests_count,
        'withdrawals_today': withdrawals_today,
        'escalations_today': escalations_today,
        'months': months,
        'report_totals': totals,
        'req_by_status': req_by_status,
        'reports_by_type': reports_by_type,
        'requests_by_type': requests_by_type,
        'roles_counts': roles_counts,
        'att_days': att_days,
        'att_counts': att_counts,
        'reports_by_status': reports_by_status,
        'violations_by_rule': violations_by_rule,
        'attendance_breakdown': attendance_breakdown,
        'top_locations_reports': top_locations_reports,
        'top_withdrawals_today': top_withdrawals_today,
        # unified JSON payload for template json_script
        'dashboard_payload': {
            'months': months,
            'report_totals': totals,
            'req_by_status': req_by_status,
            'reports_by_type': reports_by_type,
            'requests_by_type': requests_by_type,
            'roles_counts': roles_counts,
            'att_days': att_days,
            'att_counts': att_counts,
            'reports_by_status': reports_by_status,
            'violations_by_rule': violations_by_rule,
            'attendance_breakdown': attendance_breakdown,
            'top_locations_reports': top_locations_reports,
            'top_withdrawals_today': top_withdrawals_today,
        }
    }
    return render(request, 'admin_extras/dashboard.html', context)


@staff_member_required
def chat_view(request):
    return render(request, 'admin_extras/chat.html')


@staff_member_required
@require_GET
def chat_messages_json(request):
    """
    Returns recent messages (optionally after `since` iso dt).
    """
    since = request.GET.get('since')
    # Always return messages in ascending order
    if since:
        try:
            ref = timezone.datetime.fromisoformat(since)
            if timezone.is_naive(ref):
                ref = timezone.make_aware(ref, timezone.get_current_timezone())
            qs = (
                ChatMessage.objects
                .filter(created_at__gt=ref)
                .select_related('user')
                .order_by('created_at')[:50]
            )
        except Exception:
            return HttpResponseBadRequest('invalid since')
        iterable = qs
    else:
        # last 50 then sort ascending in python
        latest = list(ChatMessage.objects.select_related('user').order_by('-created_at')[:50])
        iterable = reversed(latest)

    data = [
        {
            'id': str(m.id),
            'user': getattr(m.user, 'username', 'unknown'),
            'message': m.message,
            'created_at': m.created_at.isoformat(),
        }
        for m in iterable
    ]
    return JsonResponse({'messages': data})


@staff_member_required
@require_POST
def chat_send(request):
    msg = (request.POST.get('message') or '').strip()
    if not msg:
        return HttpResponseBadRequest('empty message')
    ChatMessage.objects.create(user=request.user, message=msg)
    return JsonResponse({'ok': True})


@staff_member_required
@require_GET
def daily_window_report_view(request):
    """
    تقرير مبسّط للإدارة عن فترة زمنية محددة.
    GET params:
      - from: ISO datetime (محلي/UTC)
      - to:   ISO datetime (محلي/UTC) — افتراضي الآن
      - format=json | html  (افتراضي html)
    الافتراضي للفترة: اليوم 21:00 (محلي) → الآن.
    """
    fmt = (request.GET.get('format') or 'html').strip().lower()
    raw_from = request.GET.get('from')
    raw_to = request.GET.get('to')

    now = timezone.now()
    local_now = timezone.localtime(now)
    default_start_local = local_now.replace(hour=21, minute=0, second=0, microsecond=0)
    if default_start_local > local_now:
        # لو كانت 21:00 لم تأتِ بعد اليوم، استخدم 21:00 لليوم السابق
        default_start_local = default_start_local - timedelta(days=1)

    def _parse_dt(value, fallback):
        if not value:
            return fallback
        try:
            dt = timezone.datetime.fromisoformat(value)
            if timezone.is_naive(dt):
                dt = timezone.make_aware(dt, timezone.get_current_timezone())
            return dt
        except Exception:
            return fallback

    start_dt = _parse_dt(raw_from, default_start_local)
    end_dt = _parse_dt(raw_to, local_now)

    # جمع البيانات
    att_q = AttendanceRecord.objects.filter(
        models.Q(check_in_time__gte=start_dt, check_in_time__lte=end_dt) |
        models.Q(check_out_time__isnull=False, check_out_time__gte=start_dt, check_out_time__lte=end_dt) |
        models.Q(timestamp__gte=start_dt, timestamp__lte=end_dt)
    )
    att_total = att_q.count()
    att_by_type = {
        'check_in': att_q.filter(check_type='check_in').count(),
        'check_out': att_q.filter(check_type='check_out').count(),
        'early_check_out': att_q.filter(check_type='early_check_out').count(),
    }
    att_violations = att_q.filter(is_violation=True).count()

    # آخر إجراء حضور لكل موظف خلال النافذة
    latest_att = (
        att_q.select_related('employee', 'location')
            .order_by('employee_id', '-timestamp', '-check_in_time')
    )
    last_per_employee = {}
    for r in latest_att:
        key = r.employee_id
        if key in last_per_employee:
            continue
        last_per_employee[key] = {
            'employee': r.employee.full_name,
            'action': r.check_type,
            'at': timezone.localtime(r.timestamp or r.check_in_time).strftime('%Y-%m-%d %H:%M'),
            'location': getattr(r.location, 'name', None),
            'violation': bool(r.is_violation),
        }

    # التتبع الجغرافي
    ping_q = LocationPing.objects.filter(recorded_at__gte=start_dt, recorded_at__lte=end_dt)
    ping_total = ping_q.count()
    ping_inside = ping_q.filter(within_radius=True).count()
    ping_outside = ping_total - ping_inside
    ping_violations = ping_q.filter(violation_triggered=True).count()

    # Pauses خلال النافذة
    pause_q = GeofenceViolationPause.objects.filter(
        pause_started_at__lte=end_dt,
        pause_until__gte=start_dt,
        resumed_at__isnull=True,
    ).select_related('employee', 'location')
    pauses = [
        {
            'employee': p.employee.full_name,
            'location': getattr(p.location, 'name', 'جميع المواقع') if p.location else 'جميع المواقع',
            'from': timezone.localtime(p.pause_started_at).strftime('%Y-%m-%d %H:%M'),
            'until': timezone.localtime(p.pause_until).strftime('%Y-%m-%d %H:%M'),
            'reason': p.reason,
        }
        for p in pause_q[:50]
    ]

    # مخالفات
    vio_q = EmployeeViolation.objects.filter(occurred_at__gte=start_dt, occurred_at__lte=end_dt)
    vio_by_rule = dict(
        vio_q.values_list('rule__title').annotate(c=Count('id'))
    )

    # Incidents (انقطاع نبضات)
    inc_q = TrackingIncident.objects.filter(recorded_at__gte=start_dt, recorded_at__lte=end_dt)
    incidents_by_type = dict(inc_q.values_list('incident_type').annotate(c=Count('id')))

    payload = {
        'window': {
            'start': timezone.localtime(start_dt).strftime('%Y-%m-%d %H:%M'),
            'end': timezone.localtime(end_dt).strftime('%Y-%m-%d %H:%M'),
        },
        'attendance': {
            'total': att_total,
            'by_type': att_by_type,
            'violations': att_violations,
            'latest_per_employee': list(last_per_employee.values())[:100],
        },
        'tracking': {
            'pings_total': ping_total,
            'inside': ping_inside,
            'outside': ping_outside,
            'withdrawal_violations': ping_violations,
            'pauses_active': len(pauses),
            'pauses': pauses,
            'incidents': incidents_by_type,
        },
        'violations_by_rule': vio_by_rule,
        'logical_checks': [
            'منع العمل خارج نافذة الوردية إلا إذا كانت سماحات غير محددة',
            'اشتراط التحقق البيومتري (fingerprint/face/pin)',
            'رفض المواقع الوهمية (Mock) عند توفرها',
            'تفعيل reject_outside_geofence عند ضبط الموقع',
            'تسجيل انقطاع نبضات (Heartbeat timeout) عند تجاوزه المهلة',
            'إيقاف المخالفات عبر GeofenceViolationPause عند الإطلاق',
        ],
    }

    if fmt == 'json':
        return JsonResponse(payload, json_dumps_params={'ensure_ascii': False})

    return render(request, 'admin_extras/daily_window_report.html', {'data': payload})
