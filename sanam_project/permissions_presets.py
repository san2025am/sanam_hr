from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType

# قوائم الموديلات لكل قسم (استخدم نفس التقسيم الوظيفي لديك)
HR_MODELS = [
    ("api_guard", "Contract"),
    ("api_guard", "Employee"),
    ("api_guard", "EmployeeLeaveBalance"),
    ("api_guard", "Role"),
    ("hr", "JobApplication"),
    ("policies", "LeavePolicy"),
    ("policies", "LocalException"),
    ("policies", "PublicHoliday"),
    ("policies", "WeeklyOff"),
]

FINANCE_MODELS = [
    ("api_guard", "Advance"),
    ("api_guard", "Custody"),
    ("api_guard", "Report"),
    ("api_guard", "Salary"),
    ("payroll", "Overtime"),
    ("payroll", "PayrollConfig"),
    ("payroll", "PayrollCycle"),
    ("payroll", "PayrollItem"),
    ("payroll", "Reward"),
]

OPS_MODELS = [
    ("api_guard", "AttendanceRecord"),
    ("api_guard", "DeviceLoginChallenge"),
    ("api_guard", "EmployeeLocationAssignment"),
    ("api_guard", "EmployeeShiftAssignment"),
    ("api_guard", "GeofenceViolationPause"),
    ("api_guard", "Location"),
    ("api_guard", "LocationMonitoringConfig"),
    ("api_guard", "LocationPing"),
    ("api_guard", "Shift"),
    ("api_guard", "Task"),
    ("api_guard", "TrackingIncident"),
    ("api_guard", "TrustedDevice"),
]

LOGISTICS_MODELS = [
    ("api_guard", "LogisticRequest"),
    ("api_guard", "UniformDelivery"),
    ("api_guard", "UniformDeliveryItem"),
    ("api_guard", "UniformItem"),
]

SECTIONS = {
    "HR": HR_MODELS,
    "Finance": FINANCE_MODELS,
    "Operations": OPS_MODELS,
    "Logistics": LOGISTICS_MODELS,
}

# تسميات عربية للأقسام لعرضها في الواجهات
SECTION_LABELS = {
    "HR": "الموارد البشرية",
    "Finance": "الشؤون المالية",
    "Operations": "العمليات",
    "Logistics": "اللوجستيات",
}

def get_section_label(code: str) -> str:
    return SECTION_LABELS.get(code, code)

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
