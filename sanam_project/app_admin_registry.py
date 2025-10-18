from django.apps import apps

from core.admin import register_with_core
from sanam_project.admin_sites import hr_admin, finance_admin, ops_admin, log_admin
from sanam_project.functional_registry import HR_MODELS, FINANCE_MODELS, OPS_MODELS, LOGISTICS_MODELS


MODEL_ADMIN_CONFIG = {
    "api_guard.Employee": {
        "list_display": ("id", "full_name", "national_id", "phone_number", "created_at"),
        "search_fields": ("full_name", "national_id", "phone_number"),
        "list_filter": ("education_level",),
    },
    "api_guard.Contract": {
        "list_display": (
            "id",
            "employee",
            "start_date",
            "end_date",
            "signed_by_employee",
            "signed_by_company",
        ),
        "search_fields": ("employee__full_name", "title"),
    },
    "api_guard.Location": {
        "list_display": ("id", "name", "client_name", "gps_radius", "use_polygon"),
        "search_fields": ("name", "client_name"),
        "list_filter": ("use_polygon",),
    },
    "api_guard.AttendanceRecord": {
        "list_display": (
            "id",
            "employee",
            "location",
            "check_in_time",
            "check_out_time",
            "work_type",
            "is_violation",
        ),
        "search_fields": ("employee__full_name", "location__name"),
        "list_filter": ("work_type", "is_violation"),
    },
    "payroll.PayrollCycle": {
        "list_display": ("id", "year", "month", "status"),
        "list_filter": ("status",),
    },
    "hr.JobApplication": {
        "list_display": ("id", "full_name", "position", "status", "created_at"),
        "search_fields": ("full_name", "national_id", "phone", "email"),
        "list_filter": ("position", "status"),
    },
    "policies.LeavePolicy": {
        "list_display": ("id", "bundle", "monthly_accrual_days", "yearly_cap_days", "carry_over_max"),
    },
}


def _register_group(site, labels):
    for label in labels:
        model = apps.get_model(label)
        config = MODEL_ADMIN_CONFIG.get(label, {})
        soft = config.get("soft")
        if soft is None:
            soft = hasattr(model, "is_deleted")
        admin_kwargs = {k: v for k, v in config.items() if k != "soft"}
        register_with_core(site, model, soft=soft, **admin_kwargs)


_register_group(hr_admin, HR_MODELS)
_register_group(finance_admin, FINANCE_MODELS)
_register_group(ops_admin, OPS_MODELS)
_register_group(log_admin, LOGISTICS_MODELS)
