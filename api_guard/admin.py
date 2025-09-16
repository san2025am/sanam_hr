# api_guard/admin.py

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import (
    Role, User, Employee, Location, EmployeeLocationAssignment, Task, Shift,
    AttendanceRecord, Salary, Report, ReportAttachment, Request, Violation, Contract,
    Advance, Custody, LogisticRequest, UniformItem, UniformDelivery, UniformDeliveryItem
)

# --- Inlines ---
class EmployeeInline(admin.StackedInline):
    model = Employee
    can_delete = False
    verbose_name_plural = 'ملف الموظف'
    fk_name = 'user'

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

# --- ModelAdmins ---
@admin.register(User)
class CustomUserAdmin(BaseUserAdmin):
    inlines = (EmployeeInline,)
    list_display = ('username', 'get_full_name', 'get_role', 'is_active', 'is_staff')
    list_select_related = ('employee', 'role')
    def get_full_name(self, instance):
        if hasattr(instance, 'employee'): return instance.employee.full_name
        return "لا يوجد ملف موظف"
    get_full_name.short_description = 'الاسم الكامل'
    def get_role(self, instance): return instance.role
    get_role.short_description = 'الدور'

@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ('name', 'description'); search_fields = ('name',)

@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'national_id', 'phone_number', 'supervisor')
    search_fields = ('full_name', 'national_id', 'phone_number'); list_filter = ('supervisor',)

@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ('name', 'client_name'); search_fields = ('name', 'client_name')

@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ('title', 'assigned_to', 'location', 'status', 'due_date')
    list_filter = ('status', 'location', 'assigned_to'); search_fields = ('title', 'description', 'assigned_to__full_name')

@admin.register(Shift)
class ShiftAdmin(admin.ModelAdmin):
    list_display = ('name', 'start_time', 'end_time')

@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(admin.ModelAdmin):
    list_display = ('employee', 'check_in_time', 'check_out_time', 'shift', 'work_type', 'location')
    list_filter = ('location', 'work_type', 'shift', 'employee'); search_fields = ('employee__full_name',)

@admin.register(Salary)
class SalaryAdmin(admin.ModelAdmin):
    list_display = ('employee', 'base_salary', 'bonuses', 'deductions', 'overtime', 'total_salary', 'pay_date')
    search_fields = ('employee__full_name',); readonly_fields = ('total_salary',)

@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ('employee', 'report_type', 'location', 'status', 'created_at')
    list_filter = ('status', 'report_type', 'location'); search_fields = ('employee__full_name', 'description')
    inlines = [ReportAttachmentInline]

@admin.register(Request)
class RequestAdmin(admin.ModelAdmin):
    list_display = ('employee', 'request_type', 'status', 'approver', 'created_at')
    list_filter = ('status', 'request_type'); search_fields = ('employee__full_name', 'description')

@admin.register(Violation)
class ViolationAdmin(admin.ModelAdmin):
    list_display = ('employee', 'violation_type', 'reported_by', 'status', 'created_at')
    list_filter = ('status', 'violation_type'); search_fields = ('employee__full_name', 'description')

@admin.register(Contract)
class ContractAdmin(admin.ModelAdmin):
    list_display = ('employee', 'start_date', 'end_date', 'is_signed')
    list_filter = ('is_signed',); search_fields = ('employee__full_name',)

@admin.register(Advance)
class AdvanceAdmin(admin.ModelAdmin):
    list_display = ('employee', 'amount', 'status', 'requested_at')
    list_filter = ('status',); search_fields = ('employee__full_name', 'reason')

@admin.register(Custody)
class CustodyAdmin(admin.ModelAdmin):
    list_display = ('employee', 'item_description', 'status', 'received_at', 'returned_at')
    list_filter = ('status',); search_fields = ('employee__full_name', 'item_description', 'serial_number')

@admin.register(LogisticRequest)
class LogisticRequestAdmin(admin.ModelAdmin):
    list_display = ('supervisor', 'location', 'status', 'created_at')
    list_filter = ('status', 'location', 'supervisor'); search_fields = ('supervisor__full_name', 'location__name', 'description')

@admin.register(UniformItem)
class UniformItemAdmin(admin.ModelAdmin):
    list_display = ('name', 'price'); search_fields = ('name',)

@admin.register(UniformDelivery)
class UniformDeliveryAdmin(admin.ModelAdmin):
    list_display = ('employee', 'delivery_date', 'total_value', 'payment_method', 'is_finalized')
    list_filter = ('payment_method', 'is_finalized', 'location'); search_fields = ('employee__full_name',)
    inlines = [UniformDeliveryItemInline]; readonly_fields = ('total_value',)

admin.site.register(EmployeeLocationAssignment)
