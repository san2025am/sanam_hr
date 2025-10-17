from django.contrib import admin

from .models import PayrollConfig, PayrollCycle, PayrollItem, Reward, Overtime
from . import utils as payroll_utils
from django.contrib import messages


@admin.register(PayrollConfig)
class PayrollConfigAdmin(admin.ModelAdmin):
    list_display = ("daily_rate_policy", "fixed_daily_rate", "default_working_days", "hours_per_day", "max_deduction_rate", "is_active")
    list_filter = ("daily_rate_policy", "is_active")


class PayrollItemInline(admin.TabularInline):
    model = PayrollItem
    extra = 0
    readonly_fields = (
        "employee", "base_salary", "daily_rate", "default_working_days", "unpaid_leave_days", "payable_days",
        "days_amount", "allowances_total", "overtime_total", "gross",
        "deductions_requested", "carry_in_deductions", "deductions_applied", "deductions_excess_carried", "net_pay",
    )


@admin.register(PayrollCycle)
class PayrollCycleAdmin(admin.ModelAdmin):
    list_display = ("year", "month", "status", "config")
    list_filter = ("status",)
    inlines = [PayrollItemInline]
    actions = ("rebuild_cycle_items", "post_cycle_to_salary",)

    def save_model(self, request, obj, form, change):
        """
        تعامل لطيف مع محاولة إنشاء دورة مكررة لنفس (السنة/الشهر):
        - عند الإضافة، إن وُجدت دورة قائمة لنفس الشهر، حدّثها (وأعد تفعيلها إن كانت محذوفة منطقيًا) بدل إنشاء صف جديد.
        - يمنع IntegrityError ويُبقي تجربة الـ Admin سلسة.
        """
        try:
            if not change:
                all_qs = getattr(PayrollCycle, 'all_objects', PayrollCycle.objects)
                existing = (all_qs.filter(year=obj.year, month=obj.month)
                                   .order_by('-updated_at').first())
                if existing:
                    # حدّث الإعداد والحالة، واستعد السجل إن كان محذوفًا منطقيًا
                    fields = []
                    if obj.config_id and obj.config_id != existing.config_id:
                        existing.config = obj.config
                        fields.append('config')
                    if obj.status and obj.status != existing.status:
                        existing.status = obj.status
                        fields.append('status')
                    if getattr(existing, 'deleted_at', None) is not None:
                        existing.deleted_at = None
                        fields.append('deleted_at')
                    existing.save(update_fields=list(set(fields + ['updated_at'])) or None)
                    messages.success(request, 'تم تحديث دورة الراتب القائمة لهذا الشهر بدلاً من إنشاء دورة مكررة.')
                    return
        except Exception:
            pass
        return super().save_model(request, obj, form, change)

    def rebuild_cycle_items(self, request, queryset):
        """أعد بناء بنود الدورة المحددة (يحذف البنود ويعيد حسابها لجميع الموظفين)."""
        total_cycles = 0
        total_items = 0
        for cycle in queryset:
            cycle.items.all().delete()
            count = 0
            for emp in payroll_utils.Employee.objects.all():
                payroll_utils.build_item_for_employee(cycle=cycle, employee=emp)
                count += 1
            total_cycles += 1
            total_items += count
        self.message_user(request, f"تمت إعادة بناء {total_items} بند عبر {total_cycles} دورة.")
    rebuild_cycle_items.short_description = "إعادة بناء بنود الدورة"

    def post_cycle_to_salary(self, request, queryset):
        """رحّل القيم من الدورة إلى جدول الرواتب Salary."""
        total = 0
        for cycle in queryset:
            total += payroll_utils.post_cycle_to_salary(year=cycle.year, month=cycle.month, force=True)
        self.message_user(request, f"تم ترحيل {total} بند إلى جدول الرواتب.")
    post_cycle_to_salary.short_description = "ترحيل الدورة إلى Salary"


@admin.register(PayrollItem)
class PayrollItemAdmin(admin.ModelAdmin):
    list_display = ("cycle", "employee", "net_pay", "gross", "deductions_applied", "deductions_excess_carried")
    search_fields = ("employee__full_name",)
    list_filter = ("cycle__year", "cycle__month")
    actions = ("recalculate_items",)

    def recalculate_items(self, request, queryset):
        """إعادة احتساب البنود المحددة من جديد من مصادرها (مكافآت/إضافي/مخالفات)."""
        count = 0
        for item in queryset.select_related("cycle", "employee"):
            cycle = item.cycle
            employee = item.employee
            # أعد إنشاء السجل بالحذف ثم البناء لضمان القيم الصحيحة
            item.delete()
            payroll_utils.build_item_for_employee(cycle=cycle, employee=employee)
            count += 1
        self.message_user(request, f"تمت إعادة احتساب {count} بند.")
    recalculate_items.short_description = "إعادة احتساب البنود"


@admin.register(Reward)
class RewardAdmin(admin.ModelAdmin):
    list_display = ("employee", "date", "amount", "approved")
    list_filter = ("approved",)
    search_fields = ("employee__full_name", "reason")
    autocomplete_fields = ("employee",)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        # Auto recalc + post only if approved
        try:
            auto = getattr(settings, 'AUTO_PAYROLL_ON_CHANGE', True)
        except Exception:
            auto = True
        if auto and obj.approved and obj.employee and obj.date:
            try:
                payroll_utils.build_and_post_for_employee_on_date(employee=obj.employee, d=obj.date)
            except Exception:
                pass


@admin.register(Overtime)
class OvertimeAdmin(admin.ModelAdmin):
    list_display = ("employee", "date", "hours", "classification", "approved")
    list_filter = ("approved", "classification")
    search_fields = ("employee__full_name", "note")
    autocomplete_fields = ("employee",)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        try:
            auto = getattr(settings, 'AUTO_PAYROLL_ON_CHANGE', True)
        except Exception:
            auto = True
        if auto and obj.approved and obj.employee and obj.date:
            try:
                payroll_utils.build_and_post_for_employee_on_date(employee=obj.employee, d=obj.date)
            except Exception:
                pass
