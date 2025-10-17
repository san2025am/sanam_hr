from django.contrib import admin
from .models import PolicyBundle, PolicyTarget, WeeklyOff, PublicHoliday, LocalException, LeavePolicy, OvertimeRewardsPolicy


class PolicyTargetInline(admin.TabularInline):
    model = PolicyTarget
    extra = 0
    fields = ("scope", "role", "location", "shift")
    autocomplete_fields = ("role", "location", "shift")


@admin.register(PolicyBundle)
class PolicyBundleAdmin(admin.ModelAdmin):
    list_display = ("policy_type", "name", "priority", "start_date", "end_date", "is_active")
    list_filter = ("policy_type", "is_active")
    search_fields = ("name", "description")
    date_hierarchy = "start_date"
    inlines = [PolicyTargetInline]


@admin.register(PolicyTarget)
class PolicyTargetAdmin(admin.ModelAdmin):
    list_display = ("bundle", "scope", "role", "location", "shift", "created_at")
    list_filter = ("scope", "bundle__policy_type")
    search_fields = ("bundle__name", "role__name", "location__name", "shift__name")
    autocomplete_fields = ("bundle", "role", "location", "shift")


@admin.register(WeeklyOff)
class WeeklyOffAdmin(admin.ModelAdmin):
    list_display = ("scope", "day_of_week", "role", "location", "shift", "priority", "is_active")
    list_filter = ("scope", "day_of_week", "is_active")
    search_fields = ("role__name", "location__name", "shift__name")
    autocomplete_fields = ("role", "location", "shift")


@admin.register(PublicHoliday)
class PublicHolidayAdmin(admin.ModelAdmin):
    list_display = ("name", "date", "repeats_annually", "scope", "role", "location", "shift", "is_active")
    list_filter = ("scope", "repeats_annually", "is_active")
    search_fields = ("name", "role__name", "location__name", "shift__name")
    autocomplete_fields = ("role", "location", "shift")


@admin.register(LocalException)
class LocalExceptionAdmin(admin.ModelAdmin):
    list_display = ("date", "effect", "employee", "location")
    list_filter = ("effect",)
    search_fields = ("employee__full_name", "location__name", "notes")
    autocomplete_fields = ("employee", "location")


@admin.register(LeavePolicy)
class LeavePolicyAdmin(admin.ModelAdmin):
    list_display = ("bundle", "monthly_accrual_days", "yearly_cap_days", "carry_over_max", "created_at")
    search_fields = ("bundle__name",)
    autocomplete_fields = ("bundle",)


@admin.register(OvertimeRewardsPolicy)
class OvertimeRewardsPolicyAdmin(admin.ModelAdmin):
    list_display = ("bundle", "normal_rate", "night_rate", "offday_rate", "public_holiday_rate", "monthly_hours_cap")
    search_fields = ("bundle__name",)
    autocomplete_fields = ("bundle",)
