from django.contrib import admin, messages
from django.contrib.auth.models import Group, Permission
from django import forms
from django.utils.translation import gettext_lazy as _
from django.db.models import Q

from sanam_project.permissions_presets import get_permissions_for_section, SECTIONS

class GroupForm(forms.ModelForm):
    class Meta:
        model = Group
        fields = ["name", "permissions"]
        widgets = {
            "permissions": forms.SelectMultiple(attrs={"size": "20", "style": "min-width: 480px;"})
        }

class GroupAdminEnhanced(admin.ModelAdmin):
    form = GroupForm
    list_display = ("name", "permissions_count", "sections_hint")
    search_fields = ("name",)
    filter_horizontal = ("permissions",)

    @admin.display(description=_("عدد الصلاحيات"))
    def permissions_count(self, obj):
        return obj.permissions.count()

    @admin.display(description=_("تلميح الأقسام"))
    def sections_hint(self, obj):
        """
        يحاول استنتاج أقرب قسم بناءً على أكثر صلاحيات مطابقة.
        للعرض فقط كتلميح سريع.
        """
        best = None
        best_count = 0
        perm_ids = set(obj.permissions.values_list("id", flat=True))
        for sec, _ in SECTIONS.items():
            sec_perm_ids = set(p.id for p in get_permissions_for_section(sec))
            c = len(perm_ids & sec_perm_ids)
            if c > best_count:
                best = sec
                best_count = c
        return f"{best or '-'} ({best_count})"

    # --- أكشنات تطبيق صلاحيات الأقسام ---
    actions = ("apply_hr_perms", "apply_finance_perms", "apply_ops_perms", "apply_logistics_perms",
               "merge_hr_perms", "merge_finance_perms", "merge_ops_perms", "merge_logistics_perms",
               "remove_section_perms")

    # استبدال كامل لصلاحيات المجموعة بقسم محدد
    def _apply_section(self, request, queryset, section: str):
        new_perms = get_permissions_for_section(section)
        for group in queryset:
            group.permissions.set(new_perms)
        self.message_user(request, f"تم استبدال صلاحيات {queryset.count()} مجموعة بقالب قسم {section}.", messages.SUCCESS)

    # دمج صلاحيات القسم مع الحالية (لا يحذف الموجود)
    def _merge_section(self, request, queryset, section: str):
        add_perms = get_permissions_for_section(section)
        for group in queryset:
            group.permissions.add(*list(add_perms))
        self.message_user(request, f"تم دمج صلاحيات قسم {section} مع {queryset.count()} مجموعة.", messages.SUCCESS)

    # إزالة صلاحيات قسم محدد من المجموعة (لا يحذف الباقي)
    def _remove_section(self, request, queryset, section: str):
        rm_perms = get_permissions_for_section(section)
        for group in queryset:
            group.permissions.remove(*list(rm_perms))
        self.message_user(request, f"تمت إزالة صلاحيات قسم {section} من {queryset.count()} مجموعة.", messages.WARNING)

    # --- أكشنات سريعة ---
    @admin.action(description="استبدال بصلاحيات قسم HR")
    def apply_hr_perms(self, request, queryset): self._apply_section(request, queryset, "HR")

    @admin.action(description="استبدال بصلاحيات قسم Finance")
    def apply_finance_perms(self, request, queryset): self._apply_section(request, queryset, "Finance")

    @admin.action(description="استبدال بصلاحيات قسم Operations")
    def apply_ops_perms(self, request, queryset): self._apply_section(request, queryset, "Operations")

    @admin.action(description="استبدال بصلاحيات قسم Logistics")
    def apply_logistics_perms(self, request, queryset): self._apply_section(request, queryset, "Logistics")

    @admin.action(description="دمج صلاحيات HR")
    def merge_hr_perms(self, request, queryset): self._merge_section(request, queryset, "HR")

    @admin.action(description="دمج صلاحيات Finance")
    def merge_finance_perms(self, request, queryset): self._merge_section(request, queryset, "Finance")

    @admin.action(description="دمج صلاحيات Operations")
    def merge_ops_perms(self, request, queryset): self._merge_section(request, queryset, "Operations")

    @admin.action(description="دمج صلاحيات Logistics")
    def merge_logistics_perms(self, request, queryset): self._merge_section(request, queryset, "Logistics")

    @admin.action(description="إزالة صلاحيات قسم محدد… (أدخل الاسم: HR/Finance/Operations/Logistics)")
    def remove_section_perms(self, request, queryset):
        # استخدم رسالة قصيرة لتوضيح الاستخدام
        self.message_user(request, "استخدم الإجراء 'إزالة صلاحيات قسم محدد…' من خلال دمجه مع واجهة مخصصة لاحقًا، أو عدّل الملف لتثبيت قسم بعينه.", messages.INFO)

# استبدل GroupAdmin الافتراضي
def register_group_admin(admin_site=admin.site):
    try:
        admin_site.unregister(Group)
    except admin.sites.NotRegistered:
        pass
    admin_site.register(Group, GroupAdminEnhanced)

register_group_admin()

