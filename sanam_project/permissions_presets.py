from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType

# قوائم الموديلات لكل قسم (استخدم نفس التقسيم الوظيفي لديك)
HR_MODELS = [
    ("api_guard","Employee"), ("api_guard","Role"), ("api_guard","Contract"),
    ("api_guard","MonthlyLeaveBalance"), ("hr","JobApplication"),
    ("policies","PolicyGoal"), ("policies","WeeklyRestDay"), ("policies","PolicyException"),
    ("policies","PolicyBundle"), ("policies","DailyLeavePolicy"),
]

FINANCE_MODELS = [
    ("payroll","PayrollConfig"), ("payroll","DailyRatePolicy"), ("payroll","PayrollCycle"),
    ("payroll","DailyPayroll"), ("payroll","PayrollItem"), ("payroll","Bonus"),
    ("api_guard","Salary"), ("api_guard","Advance"), ("api_guard","Custody"), ("api_guard","Report"),
]

OPS_MODELS = [
    ("api_guard","Location"), ("api_guard","LocationMonitoringConfig"), ("api_guard","GeofenceViolationPause"),
    ("api_guard","EmployeeLocationAssignment"), ("api_guard","Shift"), ("api_guard","AttendanceRecord"),
    ("api_guard","TrackingEvent"), ("api_guard","ViolationPolicy"), ("api_guard","EmployeeViolation"),
    ("api_guard","Task"), ("api_guard","TrustedDevice"), ("api_guard","DeviceVerificationRequest"),
]

LOGISTICS_MODELS = [
    ("api_guard","LogisticsRequest"), ("api_guard","UniformItem"), ("api_guard","UniformReceipt"),
]

SECTIONS = {
    "HR": HR_MODELS,
    "Finance": FINANCE_MODELS,
    "Operations": OPS_MODELS,
    "Logistics": LOGISTICS_MODELS,
}

# أنواع الصلاحيات القياسية لكل موديل
PERM_CODES = ("view", "add", "change", "delete")

def queryset_for_section(section: str):
    """
    يرجع QuerySet بصلاحيات القسم المحدد (جميع add/change/delete/view على موديلات القسم).
    """
    models = SECTIONS.get(section, [])
    # ابحث عن ContentType لكل (app_label, model_name)
    cts = []
    for app_label, model_name in models:
        try:
            ct = ContentType.objects.get(app_label=app_label, model=model_name.lower())
            cts.append(ct)
        except ContentType.DoesNotExist:
            continue
    return Permission.objects.filter(
        content_type__in=cts,
        codename__regex=r"^(%s)_" % "|".join(PERM_CODES)
    )

def get_permissions_for_section(section: str):
    """
    يرجع set(Permission) لصلاحيات القسم.
    """
    return set(queryset_for_section(section))

