from django.contrib import admin, messages
from django.contrib.auth.models import Group
from django import forms
from django.utils.translation import gettext_lazy as _
from django.urls import path
from django.shortcuts import redirect
from django.template.response import TemplateResponse

from sanam_project.permissions_presets import get_permissions_for_section, SECTIONS, SECTION_LABELS
from admin_extras.models import FunctionalSection

class GroupForm(forms.ModelForm):
    class Meta:
        model = Group
        fields = ["name", "permissions"]
        widgets = {
            "permissions": forms.SelectMultiple(attrs={"size": "20", "style": "min-width: 480px;"})
        }

class GroupAdminEnhanced(admin.ModelAdmin):
    form = GroupForm
    list_display = ("display_name", "permissions_count", "sections_hint")
    list_display_links = ("display_name",)
    search_fields = ("name",)
    filter_horizontal = ("permissions",)
    change_form_template = "admin/auth/group/change_form.html"  # قالب مخصص

    @admin.display(description=_("عدد الصلاحيات"))
    def permissions_count(self, obj):
        return obj.permissions.count()

    @admin.display(description=_("الاسم"))
    def display_name(self, obj):
        # عرض اسم المجموعة بالعربية إن كان من الأقسام القياسية
        return SECTION_LABELS.get(obj.name, obj.name)

    @admin.display(description=_("تلميح الأقسام"))
    def sections_hint(self, obj):
        best = None
        best_count = 0
        perm_ids = set(obj.permissions.values_list("id", flat=True))
        for sec in SECTIONS.keys():
            sec_perm_ids = set(p.id for p in get_permissions_for_section(sec))
            c = len(perm_ids & sec_perm_ids)
            if c > best_count:
                best = sec
                best_count = c
        label = SECTION_LABELS.get(best, best) if best else "-"
        return f"{label} ({best_count})"

    # ----- URLs مخصصة لأزرار الواجهة داخل صفحة المجموعة -----
    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "<path:object_id>/apply-permissions/",
                self.admin_site.admin_view(self.apply_permissions_view),
                name="auth_group_apply_permissions",
            ),
        ]
        return custom + urls

    def apply_permissions_view(self, request, object_id):
        """
        يعالج POST من النموذج المدمج في صفحة المجموعة:
        - section: HR/Finance/Operations/Logistics
        - mode: replace | merge
        """
        group = self.get_object(request, object_id)
        if not group:
            self.message_user(request, "المجموعة غير موجودة.", messages.ERROR)
            return redirect("..")

        if request.method != "POST":
            return redirect("..")

        section = request.POST.get("section")
        mode = request.POST.get("mode")
        new_perms = None
        # أقسام ديناميكية من قاعدة البيانات بقيمة db:<id>
        if isinstance(section, str) and section.startswith("db:"):
            try:
                sec_id = section.split(":", 1)[1]
                s = FunctionalSection.objects.filter(pk=sec_id).first()
                if not s:
                    self.message_user(request, "قسم غير موجود.", messages.ERROR)
                    return redirect("..")
                new_perms = set(s.permissions.all())
            except Exception:
                self.message_user(request, "تعذّر قراءة القسم المحدد.", messages.ERROR)
                return redirect("..")
        else:
            # قوالب قياسية: pre:<code> أو قيمة legacy = code
            code = section.split(":", 1)[1] if (isinstance(section, str) and section.startswith("pre:")) else section
            if code not in SECTIONS.keys():
                self.message_user(request, "قسم غير صالح.", messages.ERROR)
                return redirect("..")
            new_perms = get_permissions_for_section(code)

        if mode == "replace":
            group.permissions.set(new_perms)
            self.message_user(request, f"تم استبدال صلاحيات المجموعة بقالب قسم {section}.", messages.SUCCESS)
        elif mode == "merge":
            group.permissions.add(*list(new_perms))
            self.message_user(request, f"تم دمج صلاحيات قسم {section} مع صلاحيات المجموعة.", messages.SUCCESS)
        else:
            self.message_user(request, "وضع غير صالح. استخدم replace أو merge.", messages.ERROR)

        return redirect(request.META.get("HTTP_REFERER", ".."))

    def render_change_form(self, request, context, add=False, change=False, form_url="", obj=None):
        # مرّر قاموس الأقسام إلى القالب
        context = dict(context)
        context["sections"] = SECTIONS
        context["section_labels"] = SECTION_LABELS
        try:
            dyn = FunctionalSection.objects.filter(is_active=True).order_by("order", "title")
            dyn_choices = [(f"db:{s.pk}", s.title) for s in dyn]
        except Exception:
            dyn_choices = []
        pre_choices = [(f"pre:{k}", SECTION_LABELS.get(k, k)) for k in SECTIONS.keys()]
        context["sections_choices"] = dyn_choices + pre_choices
        try:
            context["object_id"] = getattr(obj, "pk", None)
        except Exception:
            pass
        return super().render_change_form(request, context, add, change, form_url, obj)

# تسجيل/استبدال GroupAdmin الافتراضي
def register_group_admin(admin_site=admin.site):
    from django.contrib.auth.models import Group as _G
    try:
        admin_site.unregister(_G)
    except admin.sites.NotRegistered:
        pass
    admin_site.register(_G, GroupAdminEnhanced)

register_group_admin()
