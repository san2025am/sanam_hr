# api_guard/admin.py

from django.contrib import admin
try:
    from import_export.admin import ImportExportModelAdmin
except Exception:  # fallback if not installed yet
    class ImportExportModelAdmin(admin.ModelAdmin):
        pass
from django.contrib.admin.models import LogEntry
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.contenttypes.models import ContentType

from .models import (
    EmployeeShiftAssignment, Role, User, Employee, Location, LocationMonitoringConfig, GeofenceViolationPause,
    EmployeeLocationAssignment, Task, Shift,
    AttendanceRecord, LocationPing, Salary, Report, ReportAttachment, Request, EmployeeLeaveBalance,
    ViolationRule, EmployeeViolation,  # <-- الجديد بدل Violation
    Contract, Advance, Custody, LogisticRequest,
    UniformItem, UniformDelivery, UniformDeliveryItem,
    TrustedDevice, DeviceLoginChallenge
)
from .models import ReportMessage, TaskUpdateLog
try:
    from .resources import EmployeeResource, LocationResource, ReportResource, RequestResource
    _HAS_IMPORT_EXPORT = True
except Exception:  # pragma: no cover - optional dependency
    EmployeeResource = LocationResource = ReportResource = RequestResource = None
    _HAS_IMPORT_EXPORT = False
from django import forms
from django.core.exceptions import ValidationError



# =========================
# Inlines
# =========================



class EmployeeInline(admin.StackedInline):
    model = Employee
    can_delete = False
    verbose_name_plural = 'ملف الموظف'
    fk_name = 'user'
    extra = 0
    # يمكنك تحديد الحقول إن رغبت
    # fields = ('full_name','national_id','phone_number','bank_name','bank_account','instructions','supervisor','hire_date','id_image','date_of_birth_gregorian','id_expiry_date')

class ReportAttachmentInline(admin.TabularInline):
    model = ReportAttachment
    extra = 1
    verbose_name = "مرفق"
    verbose_name_plural = "المرفقات"

class ReportMessageInline(admin.TabularInline):
    """إتاحة إضافة تعليمات/ملاحظات للبلاغ من لوحة الإدارة."""
    model = ReportMessage
    extra = 1
    verbose_name = "تعليمات/ملاحظة"
    verbose_name_plural = "سجل التعليمات"
    fields = ("text", "is_instruction", "sender_employee", "sender_user", "sender_role_name", "stage")

class UniformDeliveryItemInline(admin.TabularInline):
    model = UniformDeliveryItem
    extra = 1
    autocomplete_fields = ['item']
    readonly_fields = ('value',)



@admin.register(LogEntry)
class LogEntryAdmin(admin.ModelAdmin):
    list_display = ("action_time", "get_action", "user", "object_id", "object_repr", "get_app_model")
    list_filter = ("action_flag", "content_type")
    search_fields = ("object_repr", "change_message", "user__username", "user__first_name", "user__last_name")
    readonly_fields = ("action_time", "user", "content_type", "object_id", "object_repr", "change_message", "action_flag")
    date_hierarchy = "action_time"

    def get_queryset(self, request):
        # تضمين content_type لتقليل الاستعلامات
        return super().get_queryset(request).select_related("user", "content_type")

    def get_action(self, obj):
        return obj.get_action_flag_display()
    get_action.short_description = "الإجراء"

    def get_app_model(self, obj):
        if obj.content_type_id:
            return obj.content_type.app_label + "." + obj.content_type.model
        return "-"
    get_app_model.short_description = "النموذج"

    # لا نسمح بإضافة/تعديل/حذف يدوي لسجلات التدقيق
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

# =========================
# Users / Roles
# =========================

@admin.register(User)
class CustomUserAdmin(BaseUserAdmin):
    inlines = (EmployeeInline,)
    list_display = ('username', 'get_full_name', 'get_role', 'is_active', 'is_staff')
    list_select_related = ('employee', 'role')
    autocomplete_fields = ('role',)

    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('المعلومات الشخصية', {'fields': ('first_name', 'last_name', 'email')}),
        ('الدور', {'fields': ('role',)}),
        ('الصلاحيات', {
            'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions'),
        }),
        ('تواريخ مهمة', {'fields': ('last_login', 'date_joined')}),
    )

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'password1', 'password2', 'role'),
        }),
    )

    def get_full_name(self, instance):
        if hasattr(instance, 'employee'):
            return instance.employee.full_name
        return "لا يوجد ملف موظف"
    get_full_name.short_description = 'الاسم الكامل'

    def get_role(self, instance):
        if instance.role:
            return instance.role.get_name_display()
        return "-"
    get_role.short_description = 'الدور'

@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ('name_code', 'name_ar', 'description')
    search_fields = ('name', 'description')

    def name_code(self, obj):
        return obj.name
    name_code.short_description = "الرمز"

    def name_ar(self, obj):
        return obj.get_name_display()
    name_ar.short_description = "الاسم"

# =========================
# Employee / Location / Task / Shift
# =========================

@admin.register(Employee)
class EmployeeAdmin(ImportExportModelAdmin):
    if EmployeeResource:
        resource_classes = [EmployeeResource]
    list_display = (
        'full_name', 'national_id', 'phone_number', 'bank_name',
        'monthly_leave_quota_hours', 'supervisor'
    )
    search_fields = ('full_name', 'national_id', 'phone_number', 'bank_account')
    list_filter = ('bank_name', 'supervisor')
    autocomplete_fields = ('supervisor',)

    fieldsets = (
        (None, {'fields': ('user', 'full_name', 'supervisor')}),
        ('الهوية والاتصال', {
            'fields': ('national_id', 'phone_number', 'date_of_birth_gregorian',
                       'id_expiry_date', 'id_image')
        }),
        ('العمل', {'fields': ('hire_date',)}),
        ('البنك والراتب', {'fields': ('bank_name', 'bank_account')}),
        ('الإجازات', {'fields': ('monthly_leave_quota_hours',)}),
        ('تعليمات', {'fields': ('instructions',)}),
    )

# api_guard/admin.py

class LocationAdminForm(forms.ModelForm):
    # حقل نصي مساعد لإدخال المضلّع سطرًا-سطرًا (بدل JSON يدوي)
    polygon_text = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 5}),
        help_text="أدخل كل نقطة في سطر: lat,lng"
    )

    class Meta:
        model = Location
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # عكس JSON إلى نص عند التحرير
        if self.instance and self.instance.polygon_coords:
            lines = []
            for p in self.instance.polygon_coords:
                try:
                    lines.append(f"{float(p[0]):.6f},{float(p[1]):.6f}")
                except Exception:
                    pass
            self.fields["polygon_text"].initial = "\n".join(lines)

    def clean_gps_coordinates(self):
        raw = (self.cleaned_data.get("gps_coordinates") or "").strip()
        if not raw:
            return raw
        # قبول lat,lng مباشرة أو ربط خرائط
        import re
        m = re.match(r"\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$", raw)
        if m:
            lat = float(m.group(1)); lng = float(m.group(2))
            if not (-90 <= lat <= 90 and -180 <= lng <= 180):
                raise forms.ValidationError("lat/lng خارج النطاق.")
            return f"{lat:.5f},{lng:.5f}"
        try:
            res = parse_google_maps_latlng(raw)
            return f"{res['lat']:.5f},{res['lng']:.5f}"
        except Exception:
            raise forms.ValidationError("أدخل lat,lng أو رابط خرائط جوجل صالح.")

    def clean(self):
        cleaned = super().clean()
        use_poly = cleaned.get("use_polygon")
        text = (cleaned.get("polygon_text") or "").strip()
        if use_poly:
            if not text:
                raise forms.ValidationError("فعّلت المضلّع لكن لم تُدخِل نقاطه.")
            pts = []
            for line in text.splitlines():
                if not line.strip():
                    continue
                try:
                    la, ln = [float(x.strip()) for x in line.split(",", 1)]
                except Exception:
                    raise forms.ValidationError(f"سطر مضلّع غير صالح: {line}")
                if not (-90 <= la <= 90 and -180 <= ln <= 180):
                    raise forms.ValidationError(f"lat/lng خارج النطاق: {line}")
                pts.append([la, ln])
            if len(pts) < 3:
                raise forms.ValidationError("المضلّع يحتاج 3 نقاط على الأقل.")
            cleaned["polygon_coords"] = pts
        return cleaned

@admin.register(Location)
class LocationAdmin(ImportExportModelAdmin):
    if LocationResource:
        resource_classes = [LocationResource]
    form = LocationAdminForm
    list_display = ("name", "client_name", "gps_coordinates", "gps_radius", "use_polygon")
    search_fields = ('employee__full_name',)
    fieldsets = (
        (None, {"fields": ("name", "client_name")}),
        ("الموقع الجغرافي", {
            "fields": ("gps_coordinates", "gps_radius", "use_polygon", "polygon_text"),
            "description": "يمكن لصق رابط Google Maps في gps_coordinates أو إدخال lat,lng مباشرة. لتحديد حدود دقيقة، فعّل المضلّع وأدخل النقاط سطرًا-سطرًا."
        }),
        ("تعليمات", {"fields": ("instructions",)}),
    )


@admin.register(LocationMonitoringConfig)
class LocationMonitoringConfigAdmin(admin.ModelAdmin):
    list_display = (
        "location",
        "is_active",
        "ping_interval_seconds",
        "violation_grace_minutes",
        "reject_outside_geofence",
        "heartbeat_timeout_minutes",
        "tracking_start_mode",
        "violation_rule",
    )
    list_filter = ("is_active", "violation_rule", "reject_outside_geofence")
    search_fields = ("location__name", "location__client_name")
    autocomplete_fields = ("location", "violation_rule")
    fieldsets = (
        (None, {"fields": ("location", "is_active")}),
        ("التتبع", {"fields": (
            "ping_interval_seconds",
            "violation_grace_minutes",
            "reject_outside_geofence",
            "heartbeat_timeout_minutes",
            "tracking_start_mode",
        )}),
        ("المخالفة", {"fields": ("violation_rule", "notes")}),
    )


@admin.register(GeofenceViolationPause)
class GeofenceViolationPauseAdmin(admin.ModelAdmin):
    list_display = (
        "employee",
        "location",
        "pause_started_at",
        "pause_until",
        "duration_minutes",
        "is_active_flag",
    )
    list_filter = ("location", "employee")
    search_fields = ("employee__full_name", "employee__user__username", "location__name")
    autocomplete_fields = ("employee", "location", "created_by")
    readonly_fields = ("is_active_flag",)
    fieldsets = (
        (None, {"fields": ("employee", "location", "reason")}),
        ("الإعدادات", {"fields": ("pause_started_at", "pause_until", "duration_minutes", "resumed_at")}),
        ("بيانات إضافية", {"fields": ("created_by", "is_active_flag")}),
    )

    @admin.display(boolean=True, description="مفعل؟")
    def is_active_flag(self, obj):
        return obj.is_active


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    # عرض اسم الحارس، الموقع، الحالة، وآخر تحديث/ملاحظة
    list_display = ('title', 'assigned_to', 'location', 'status', 'due_date', 'last_update_summary')
    list_filter = ('status', 'location', 'assigned_to', 'due_date')
    search_fields = ('title', 'description', 'assigned_to__full_name')
    autocomplete_fields = ('assigned_by', 'assigned_to', 'location')

    class TaskUpdateLogInline(admin.TabularInline):
        model = TaskUpdateLog
        extra = 0
        readonly_fields = ('created_at',)

    inlines = [TaskUpdateLogInline]

    def last_update_summary(self, obj):
        """آخر تحديث مع ملاحظة مختصرة للعرض السريع."""
        upd = obj.updates.order_by('-created_at').first()
        if not upd:
            return '-'
        who = upd.employee.full_name if upd.employee else '—'
        note = (upd.note or '').strip()
        if len(note) > 30:
            note = note[:27] + '...'
        return f"{upd.created_at:%Y-%m-%d %H:%M} — {who} — {upd.new_status}{(' — ' + note) if note else ''}"
    last_update_summary.short_description = 'آخر تحديث'
# api_guard/admin.py

@admin.register(Shift)
class ShiftAdmin(admin.ModelAdmin):
    list_display = ('name', 'start_time', 'end_time')
    search_fields = ('name',)  # <-- إضافة لازمة للـ autocomplete
    


@admin.register(EmployeeShiftAssignment)
class EmployeeShiftAssignmentAdmin(admin.ModelAdmin):
    list_display = ("employee", "shift", "date", "location", "active")
    list_filter  = ("shift", "active", "location", "date")
    search_fields = ("employee__full_name", "employee__user__username", "shift__name")

# =========================
# Attendance / Salary
# =========================

@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(admin.ModelAdmin):
    list_display = ('employee', 'check_in_time', 'check_out_time', 'shift', 'work_type', 'location','check_type', 'timestamp',
        'biometric_method', 'biometric_verified', 'biometric_attempts',
        'is_violation',)
    list_filter = ('location', 'work_type', 'shift', 'employee','biometric_method', 'biometric_verified', 'is_violation')
    search_fields = ('employee__full_name',)
    autocomplete_fields = ('employee', 'location', 'shift')
    ordering = ['-check_in_time']  # ← كانت في مكان خاطئ بنصّك السابق


@admin.register(LocationPing)
class LocationPingAdmin(admin.ModelAdmin):
    list_display = ('employee', 'location', 'recorded_at', 'within_radius', 'distance_m', 'violation_triggered')
    list_filter = ('within_radius', 'violation_triggered', 'location')
    search_fields = ('employee__full_name', 'location__name')
    autocomplete_fields = ('employee', 'location')
    ordering = ['-recorded_at']
    
@admin.register(Salary)
class SalaryAdmin(admin.ModelAdmin):
    list_display = ('employee', 'base_salary', 'bonuses', 'deductions', 'overtime', 'total_salary', 'pay_date')
    search_fields = ('employee__full_name',)
    readonly_fields = ('total_salary',)
    autocomplete_fields = ('employee',)

# =========================
# Reports / Requests
# =========================

@admin.register(Report)
class ReportAdmin(ImportExportModelAdmin):
    if ReportResource:
        resource_classes = [ReportResource]
    list_display = ('employee', 'report_type', 'location', 'status', 'created_at')
    list_filter = ('status', 'report_type', 'location')
    search_fields = ('employee__full_name', 'description')
    # إظهار المرفقات وسجل التعليمات ضمن التقرير
    inlines = [ReportAttachmentInline, ReportMessageInline]
    autocomplete_fields = ('employee', 'location')

@admin.register(Request)
class RequestAdmin(ImportExportModelAdmin):
    if RequestResource:
        resource_classes = [RequestResource]
    list_display = (
        'employee', 'request_type', 'status', 'approver', 'created_at',
        'leave_start', 'leave_end', 'leave_hours', 'leave_deducted'
    )
    list_filter = ('status', 'request_type', 'leave_deducted')
    search_fields = ('employee__full_name', 'description')
    autocomplete_fields = ('employee', 'approver')
    readonly_fields = ('leave_hours', 'leave_deducted')

# =========================
# Violations (الجديد)
# =========================

@admin.register(ViolationRule)
class ViolationRuleAdmin(admin.ModelAdmin):
    list_display = ('title', 'default_action', 'default_deduction_percent')
    list_filter = ('default_action',)
    search_fields = ('title', 'description')

@admin.register(EmployeeViolation)
class EmployeeViolationAdmin(admin.ModelAdmin):
    list_display = ('employee', 'rule', 'reported_by', 'location',
                    'status', 'warning_level', 'deduction_value', 'occurred_at')
    list_filter = ('status', 'rule', 'location', 'warning_level')
    search_fields = ('employee__full_name', 'description', 'rule__title')
    autocomplete_fields = ('employee', 'reported_by', 'rule', 'location')

# =========================
# Contracts / Finance / Logistics
# =========================

@admin.register(Contract)
class ContractAdmin(admin.ModelAdmin):
    list_display = ('employee', 'start_date', 'end_date', 'is_signed')
    list_filter = ('is_signed',)
    search_fields = ('employee__full_name',)
    autocomplete_fields = ('employee',)

@admin.register(Advance)
class AdvanceAdmin(admin.ModelAdmin):
    list_display = ('employee', 'amount', 'status', 'requested_at', 'approved_at', 'deduction_applied')
    list_filter = ('status', 'deduction_applied')
    search_fields = ('employee__full_name', 'reason')
    autocomplete_fields = ('employee',)
    readonly_fields = ('approved_at', 'deduction_applied')


@admin.register(EmployeeLeaveBalance)
class EmployeeLeaveBalanceAdmin(admin.ModelAdmin):
    list_display = ('employee', 'year', 'month', 'quota_hours', 'used_hours', 'remaining_hours_display')
    list_filter = ('year', 'month')
    search_fields = ('employee__full_name',)
    autocomplete_fields = ('employee',)
    readonly_fields = ('remaining_hours_display',)

    def remaining_hours_display(self, obj):
        return obj.remaining_hours
    remaining_hours_display.short_description = 'الرصيد المتبقي'

@admin.register(Custody)
class CustodyAdmin(admin.ModelAdmin):
    list_display = ('employee', 'item_description', 'status', 'received_at', 'returned_at')
    list_filter = ('status',)
    search_fields = ('employee__full_name', 'item_description', 'serial_number')
    autocomplete_fields = ('employee',)

@admin.register(LogisticRequest)
class LogisticRequestAdmin(admin.ModelAdmin):
    list_display = ('supervisor', 'location', 'status', 'created_at')
    list_filter = ('status', 'location', 'supervisor')
    search_fields = ('supervisor__full_name', 'location__name', 'description')
    autocomplete_fields = ('supervisor', 'location')

# =========================
# Uniforms
# =========================

@admin.register(UniformItem)
class UniformItemAdmin(admin.ModelAdmin):
    list_display = ('name', 'price')
    search_fields = ('name',)

@admin.register(UniformDelivery)
class UniformDeliveryAdmin(admin.ModelAdmin):
    list_display = ('employee', 'delivery_date', 'total_value', 'payment_method', 'is_finalized')
    list_filter = ('payment_method', 'is_finalized', 'location')
    search_fields = ('employee__full_name',)
    inlines = [UniformDeliveryItemInline]
    readonly_fields = ('total_value',)
    autocomplete_fields = ('employee', 'location',
                           'operations_manager_signature', 'operations_assistant_signature')


# =========================
# Device Security
# =========================

@admin.register(TrustedDevice)
class TrustedDeviceAdmin(admin.ModelAdmin):
    list_display = ('user', 'device_name', 'device_hash', 'first_seen_at', 'last_seen_at')
    search_fields = ('user__username', 'user__employee__full_name', 'device_name', 'device_hash')
    list_filter = ('first_seen_at', 'last_seen_at')
    autocomplete_fields = ('user',)
    readonly_fields = ('first_seen_at', 'last_seen_at')
    ordering = ('-last_seen_at',)


@admin.register(DeviceLoginChallenge)
class DeviceLoginChallengeAdmin(admin.ModelAdmin):
    list_display = ('user', 'device_name', 'device_hash', 'expires_at', 'attempts', 'verified_at')
    search_fields = ('user__username', 'user__employee__full_name', 'device_name', 'device_hash')
    list_filter = ('verified_at', 'expires_at')
    autocomplete_fields = ('user',)
    readonly_fields = ('verified_at',)
    ordering = ('-expires_at',)


class EmployeeLocationAssignmentForm(forms.ModelForm):
    class Meta:
        model  = EmployeeLocationAssignment
        fields = "__all__"

    def clean(self):
        cleaned = super().clean()
        emp = cleaned.get("employee")
        loc = cleaned.get("location")

        if emp and loc:
            qs = EmployeeLocationAssignment.objects.filter(employee=emp, location=loc)
            # عند التعديل، استبعد السجل الحالي
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                # منع التكرار برسالة واضحة بدل IntegrityError
                raise ValidationError("هذا الموظف مرتبط بهذا الموقع بالفعل.")
        return cleaned


@admin.register(EmployeeLocationAssignment)
class EmployeeLocationAssignmentAdmin(admin.ModelAdmin):
    form = EmployeeLocationAssignmentForm
    # مافيه حاجة نعمل 
