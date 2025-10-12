from datetime import date, timedelta

from django.contrib.admin.views.decorators import staff_member_required
from django.db.models.functions import TruncMonth, TruncDate
from django.db import models
from django.db.models import Count
from django.http import JsonResponse, HttpResponseBadRequest
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from api_guard.models import Employee, Location, Report, Request, AttendanceRecord, EmployeeViolation, ROLE_NAME_CHOICES
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
