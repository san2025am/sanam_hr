from django.contrib import admin, messages
from django.utils.html import format_html
from django.urls import reverse

from .models import FunctionalSection
from sanam_project.permissions_presets import get_permissions_for_section, SECTIONS, SECTION_LABELS


class SectionCodeFilter(admin.SimpleListFilter):
    title = "القسم"
    parameter_name = "code"

    def lookups(self, request, model_admin):
        return [(k, SECTION_LABELS.get(k, k)) for k in SECTIONS.keys()]

    def queryset(self, request, queryset):
        val = self.value()
        if val:
            return queryset.filter(code=val)
        return queryset


@admin.register(FunctionalSection)
class FunctionalSectionAdmin(admin.ModelAdmin):
    list_display = ("code_ar", "title", "admin_link", "group", "perms_count", "is_active", "order")
    list_filter = (SectionCodeFilter, "is_active", "group")
    search_fields = ("code", "title", "admin_path")
    filter_horizontal = ("permissions",)
    fieldsets = (
        (None, {"fields": ("code", "title", "admin_path", "group", "is_active", "order")}),
        ("الصلاحيات والملاحظات", {"fields": ("permissions", "notes")}),
    )

    @admin.display(description="الرابط")
    def admin_link(self, obj: FunctionalSection):
        url = (obj.admin_path or "").strip() or "#"
        return format_html('<a href="{}" target="_blank">فتح</a>', url)

    @admin.display(description="الرمز")
    def code_ar(self, obj: FunctionalSection):
        return SECTION_LABELS.get(obj.code, obj.code)

    @admin.display(description="عدد الصلاحيات")
    def perms_count(self, obj: FunctionalSection):
        return obj.permissions.count()

    actions = (
        "apply_preset", "merge_preset", "clear_permissions", "apply_to_group", "merge_to_group", "remove_from_group",
    )

    @admin.action(description="استبدال صلاحيات القسم من القالب (حسب code)")
    def apply_preset(self, request, queryset):
        n = 0
        for sec in queryset:
            if sec.code in SECTIONS:
                perms = get_permissions_for_section(sec.code)
                sec.permissions.set(perms)
                n += 1
        self.message_user(request, f"تم استبدال صلاحيات {n} قسمًا من القوالب.", messages.SUCCESS)

    @admin.action(description="دمج صلاحيات القالب مع الحالية (حسب code)")
    def merge_preset(self, request, queryset):
        n = 0
        for sec in queryset:
            if sec.code in SECTIONS:
                perms = get_permissions_for_section(sec.code)
                sec.permissions.add(*list(perms))
                n += 1
        self.message_user(request, f"تم دمج صلاحيات القوالب مع {n} قسمًا.", messages.SUCCESS)

    @admin.action(description="تفريغ الصلاحيات")
    def clear_permissions(self, request, queryset):
        for sec in queryset:
            sec.permissions.clear()
        self.message_user(request, "تم تفريغ الصلاحيات للأقسام المحددة.", messages.WARNING)

    @admin.action(description="استبدال صلاحيات المجموعة المرتبطة")
    def apply_to_group(self, request, queryset):
        n = 0
        for sec in queryset:
            if not sec.group:
                continue
            perms = list(sec.permissions.all())
            sec.group.permissions.set(perms)
            n += 1
        self.message_user(request, f"تم استبدال صلاحيات {n} مجموعة مرتبطة.", messages.SUCCESS)

    @admin.action(description="دمج صلاحيات القسم مع المجموعة المرتبطة")
    def merge_to_group(self, request, queryset):
        n = 0
        for sec in queryset:
            if not sec.group:
                continue
            perms = list(sec.permissions.all())
            sec.group.permissions.add(*perms)
            n += 1
        self.message_user(request, f"تم دمج صلاحيات {n} مجموعة مرتبطة.", messages.SUCCESS)

    @admin.action(description="إزالة صلاحيات هذا القسم من المجموعة المرتبطة")
    def remove_from_group(self, request, queryset):
        n = 0
        for sec in queryset:
            if not sec.group:
                continue
            perms = list(sec.permissions.all())
            sec.group.permissions.remove(*perms)
            n += 1
        self.message_user(request, f"تمت إزالة صلاحيات {n} مجموعة مرتبطة.", messages.WARNING)
