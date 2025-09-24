# api_guard/admin.py

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import (
    EmployeeShiftAssignment, Role, User, Employee, Location, EmployeeLocationAssignment, Task, Shift,
    AttendanceRecord, Salary, Report, ReportAttachment, Request,
    ViolationRule, EmployeeViolation,  # <-- الجديد بدل Violation
    Contract, Advance, Custody, LogisticRequest,
    UniformItem, UniformDelivery, UniformDeliveryItem
)
from django import forms
from django.core.exceptions import ValidationError


from .utils.maps import parse_google_maps_latlng, LatLngNotFound  # لو كنت قد أضفتها سابقًا

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

class UniformDeliveryItemInline(admin.TabularInline):
    model = UniformDeliveryItem
    extra = 1
    autocomplete_fields = ['item']
    readonly_fields = ('value',)

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
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'national_id', 'phone_number', 'bank_name', 'supervisor')
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
class LocationAdmin(admin.ModelAdmin):
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


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ('title', 'assigned_to', 'location', 'status', 'due_date')
    list_filter = ('status', 'location', 'assigned_to')
    search_fields = ('title', 'description', 'assigned_to__full_name')
    autocomplete_fields = ('assigned_by', 'assigned_to', 'location')
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
    list_display = ('employee', 'check_in_time', 'check_out_time', 'shift', 'work_type', 'location')
    list_filter = ('location', 'work_type', 'shift', 'employee')
    search_fields = ('employee__full_name',)
    autocomplete_fields = ('employee', 'location', 'shift')
    ordering = ['-check_in_time']  # ← كانت في مكان خاطئ بنصّك السابق
    
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
class ReportAdmin(admin.ModelAdmin):
    list_display = ('employee', 'report_type', 'location', 'status', 'created_at')
    list_filter = ('status', 'report_type', 'location')
    search_fields = ('employee__full_name', 'description')
    inlines = [ReportAttachmentInline]
    autocomplete_fields = ('employee', 'location')

@admin.register(Request)
class RequestAdmin(admin.ModelAdmin):
    list_display = ('employee', 'request_type', 'status', 'approver', 'created_at')
    list_filter = ('status', 'request_type')
    search_fields = ('employee__full_name', 'description')
    autocomplete_fields = ('employee', 'approver')

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
    list_display = ('employee', 'amount', 'status', 'requested_at')
    list_filter = ('status',)
    search_fields = ('employee__full_name', 'reason')
    autocomplete_fields = ('employee',)

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