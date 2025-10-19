from django.contrib import admin
from django.utils.html import format_html
from django.http import JsonResponse
from django.urls import path
from .models import (
    Location, Shift, EmployeeLocationAssignment, User, Employee, Role,
    LocationMonitoringConfig, GeofenceViolationPause, Task, AttendanceRecord,
    LocationPing, Salary, Report, ReportAttachment, Request, EmployeeLeaveBalance,
    ViolationRule, EmployeeViolation, Contract, Advance, Custody, LogisticRequest,
    UniformItem, UniformDelivery, UniformDeliveryItem, TrustedDevice, DeviceLoginChallenge,
    TrackingIncident, TaskUpdateLog, ReportMessage, EmployeeShiftAssignment,
    BankAccount, BankChangeRequest,
)


def _user_is_hr(request):
    return request.user.is_superuser or request.user.groups.filter(name="HR").exists()


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "capacity_badge", "remaining_slots_display")
    search_fields = ("name",)

    def capacity_badge(self, obj):
        total = obj.guard_capacity or 0
        rem = obj.remaining_slots()
        is_full = (total > 0 and rem == 0)
        color = "#d9534f" if is_full else "#5cb85c"
        label = "ممتلئ" if is_full else "متاح"
        return format_html(
            '<span style="padding:2px 8px;border-radius:12px;background:{};color:#fff;font-weight:700;">{} ({}/{})</span>',
            color, label, rem, total,
        )

    capacity_badge.short_description = "حالة السعة"

    def remaining_slots_display(self, obj):
        total = obj.guard_capacity or 0
        rem = obj.remaining_slots()
        return f"{rem}/{total}" if total else "-/-"

    remaining_slots_display.short_description = "المتبقّي (موقع)"

    def get_readonly_fields(self, request, obj=None):
        ro = list(super().get_readonly_fields(request, obj))
        if not _user_is_hr(request) and "guard_capacity" not in ro:
            ro.append("guard_capacity")
        return ro


@admin.register(Shift)
class ShiftAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "time_range", "shift_capacity_badge")
    search_fields = ("name",)

    def time_range(self, obj):
        start = getattr(obj, "start_time", getattr(obj, "start_at", "?"))
        end = getattr(obj, "end_time", getattr(obj, "end_at", "?"))
        return f"{start} → {end}"

    time_range.short_description = "الوقت"

    def shift_capacity_badge(self, obj):
        total = obj.guard_capacity or 0
        color = "#6c757d" if total == 0 else "#5bc0de"
        label = f"سِعة الوردية: {total}"
        return format_html(
            '<span style="padding:2px 8px;border-radius:12px;background:{};color:#fff;">{}</span>',
            color, label,
        )

    shift_capacity_badge.short_description = "سِعة"

    def get_readonly_fields(self, request, obj=None):
        ro = list(super().get_readonly_fields(request, obj))
        if not _user_is_hr(request) and "guard_capacity" not in ro:
            ro.append("guard_capacity")
        return ro


@admin.register(EmployeeLocationAssignment)
class EmployeeLocationAssignmentAdmin(admin.ModelAdmin):
    change_form_template = "admin/api_guard/assignment/change_form.html"

    def get_list_display(self, request):
        cols = ["id", "employee", "location"]
        field_names = {f.name for f in self.model._meta.get_fields()}
        if "shift" in field_names:
            cols.append("shift")
        # دعم start_at / start_date
        if "start_at" in field_names:
            cols += ["start_at", "end_at"]
        else:
            cols += ["start_date", "end_date"]
        return cols

    def get_autocomplete_fields(self, request):
        field_names = {f.name for f in self.model._meta.get_fields()}
        base = ["employee", "location"]
        if "shift" in field_names:
            base.append("shift")
        return tuple(base)

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "capacity-info/",
                self.admin_site.admin_view(self.capacity_info_view),
                name="api_guard_assignment_capacity_info",
            ),
        ]
        return custom + urls

    def capacity_info_view(self, request):
        loc_id = request.GET.get("location")
        shf_id = request.GET.get("shift")
        site_total = site_used = site_remaining = 0
        pair_total = pair_used = pair_remaining = 0

        try:
            if loc_id:
                loc = Location.objects.get(pk=loc_id)
                site_total = int(loc.guard_capacity or 0)
                qs_site = EmployeeLocationAssignment.objects.filter(location_id=loc_id)
                # إن وُجد end_date، اعتبر النشط فقط
                if "end_date" in {f.name for f in EmployeeLocationAssignment._meta.get_fields()}:
                    qs_site = qs_site.filter(end_date__isnull=True)
                if hasattr(EmployeeLocationAssignment, "is_deleted"):
                    qs_site = qs_site.filter(is_deleted=False)
                site_used = qs_site.count()
                site_remaining = max(site_total - site_used, 0)

            if loc_id and shf_id:
                # إن كان الحقل shift موجودًا في ELA استخدمه، وإلا fallback إلى EmployeeShiftAssignment
                if "shift" in {f.name for f in EmployeeLocationAssignment._meta.get_fields()}:
                    qs_pair = EmployeeLocationAssignment.objects.filter(location_id=loc_id, shift_id=shf_id)
                    if hasattr(EmployeeLocationAssignment, "is_deleted"):
                        qs_pair = qs_pair.filter(is_deleted=False)
                    pair_used = qs_pair.count()
                else:
                    pair_used = EmployeeShiftAssignment.objects.filter(location_id=loc_id, shift_id=shf_id).count()
                shf = Shift.objects.get(pk=shf_id)
                pair_total = int(getattr(shf, "guard_capacity", 0) or 0)
                pair_remaining = max(pair_total - pair_used, 0)
        except Exception:
            pass

        return JsonResponse({
            "site_total": site_total,
            "site_used": site_used,
            "site_remaining": site_remaining,
            "pair_total": pair_total,
            "pair_used": pair_used,
            "pair_remaining": pair_remaining,
        })

    def save_model(self, request, obj, form, change):
        obj.save()


# Register remaining models with default admins to restore visibility
_MODELS_TO_REGISTER = [
    LocationMonitoringConfig, GeofenceViolationPause, Task, AttendanceRecord,
    LocationPing, Salary, Report, ReportAttachment, Request, EmployeeLeaveBalance,
    ViolationRule, EmployeeViolation, Contract, Advance, Custody, LogisticRequest,
    UniformItem, UniformDelivery, UniformDeliveryItem, TrustedDevice, DeviceLoginChallenge,
    TrackingIncident, TaskUpdateLog, ReportMessage, EmployeeShiftAssignment,
]

for _m in _MODELS_TO_REGISTER:
    try:
        if _m not in admin.site._registry:
            admin.site.register(_m)
    except admin.sites.AlreadyRegistered:
        pass


# Registrations to satisfy autocomplete_fields in other admins
@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("username", "is_active", "is_staff")
    search_fields = ("username", "email")


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ("full_name", "national_id")
    search_fields = ("full_name", "national_id")


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)


@admin.register(BankAccount)
class BankAccountAdmin(admin.ModelAdmin):
    list_display = ("employee", "bank_name", "masked_iban", "updated_at")
    search_fields = ("employee__full_name", "iban", "bank_name")

    def masked_iban(self, obj):
        try:
            s = str(obj.iban or '')
            tail = s.replace(' ', '')[-4:]
            return f"XXXX...{tail}" if tail else ''
        except Exception:
            return ''


@admin.register(BankChangeRequest)
class BankChangeRequestAdmin(admin.ModelAdmin):
    list_display = ("employee", "status", "requested_bank_name", "requested_iban", "created_at", "decided_at")
    list_filter = ("status", "created_at")
    search_fields = ("employee__full_name", "requested_iban", "current_iban")
    readonly_fields = ("created_at", "decided_at", "hr_reviewer")

    actions = ("action_approve", "action_reject")

    def action_approve(self, request, queryset):
        from .services.bank_account import approve_bank_change
        for obj in queryset:
            try:
                approve_bank_change(request_id=obj.id, reviewer=request.user, comment="Approved via admin action")
            except Exception:
                pass
        self.message_user(request, "تمت الموافقة على الطلبات المحددة")

    def action_reject(self, request, queryset):
        from .services.bank_account import reject_bank_change
        for obj in queryset:
            try:
                reject_bank_change(request_id=obj.id, reviewer=request.user, comment="Rejected via admin action")
            except Exception:
                pass
        self.message_user(request, "تم رفض الطلبات المحددة")
