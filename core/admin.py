from django.contrib import admin, messages
from django.contrib.admin import SimpleListFilter
from django.urls import reverse, re_path
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from django.shortcuts import redirect
from django.utils import timezone
from django.db import models
from urllib.parse import urlencode

class DeletedFilter(SimpleListFilter):
    title = _("الحالة (محذوف؟)"); parameter_name = "deleted"
    def lookups(self, request, model_admin): return (("yes", _("محذوف")), ("no", _("غير محذوف")),)
    def queryset(self, request, qs):
        if not hasattr(qs.model, "is_deleted"): return qs
        if self.value() == "yes": return qs.filter(is_deleted=True)
        if self.value() == "no": return qs.filter(is_deleted=False)
        return qs

class UUIDReadonlyAdminMixin:
    readonly_uuid_fields = ("id", "uuid")
    def get_readonly_fields(self, request, obj=None):
        ro = list(getattr(super(), "get_readonly_fields", lambda *a, **k: [])(request, obj))
        fields = [f.name for f in self.model._meta.fields]
        for f in self.readonly_uuid_fields:
            if f in fields and f not in ro: ro.append(f)
        return ro

class TimeStampedAdminMixin:
    ts_fields = ("created_at", "updated_at", "deleted_at")
    def get_list_display(self, request):
        parent = getattr(super(), "get_list_display", None)
        base = list(parent(request) if parent else ())
        fields = [f.name for f in self.model._meta.fields]
        for f in self.ts_fields:
            if f in fields and f not in base: base.append(f)
        return base
    def get_readonly_fields(self, request, obj=None):
        ro = list(getattr(super(), "get_readonly_fields", lambda *a, **k: [])(request, obj))
        fields = [f.name for f in self.model._meta.fields]
        for f in self.ts_fields:
            if f in fields and f not in ro: ro.append(f)
        return ro

class SoftDeleteAdminMixin:
    actions = ("action_soft_delete", "action_restore", "action_hard_delete")
    list_filter = (DeletedFilter,)
    @admin.action(description="🗃️ أرشفة (حذف منطقي)")
    def action_soft_delete(self, request, qs):
        if not hasattr(qs.model, "is_deleted"): return self.message_user(request,"لا يدعم الحذف المنطقي.",messages.WARNING)
        n=0
        for o in qs:
            if not o.is_deleted:
                o.is_deleted=True
                if hasattr(o,"deleted_at"): o.deleted_at=timezone.now()
                if hasattr(o,"deleted_by") and hasattr(request,"user"): o.deleted_by=request.user
                o.save(update_fields=["is_deleted"]+([ "deleted_at"] if hasattr(o,"deleted_at") else [])+([ "deleted_by"] if hasattr(o,"deleted_by") else [])); n+=1
        self.message_user(request,f"تمت أرشفة {n} عنصرًا.",messages.SUCCESS)
    @admin.action(description="♻️ استرجاع")
    def action_restore(self, request, qs):
        if not hasattr(qs.model, "is_deleted"): return self.message_user(request,"لا يدعم الحذف المنطقي.",messages.WARNING)
        n=0
        for o in qs:
            if o.is_deleted:
                o.is_deleted=False
                if hasattr(o,"deleted_at"): o.deleted_at=None
                if hasattr(o,"deleted_by"): o.deleted_by=None
                o.save(update_fields=["is_deleted"]+([ "deleted_at"] if hasattr(o,"deleted_at") else [])+([ "deleted_by"] if hasattr(o,"deleted_by") else [])); n+=1
        self.message_user(request,f"تم استرجاع {n} عنصرًا.",messages.SUCCESS)
    @admin.action(description="❌ حذف نهائي")
    def action_hard_delete(self, request, qs):
        c=qs.count(); qs.delete(); self.message_user(request,f"تم حذف {c} نهائيًا.",messages.SUCCESS)
    def is_deleted_badge(self, obj):
        if not hasattr(obj,"is_deleted"): return "-"
        color = "#d9534f" if obj.is_deleted else "#5cb85c"; text = "محذوف" if obj.is_deleted else "نشط"
        return format_html('<span style="padding:2px 8px;border-radius:12px;background:{};color:#fff;font-weight:700;">{}</span>', color, text)
    is_deleted_badge.short_description="الحالة"

class RowActionsMixin:
    def row_actions(self, obj):
        a=obj._meta.app_label; m=obj._meta.model_name; pk=obj.pk
        namespace = getattr(self.admin_site, "name", "admin") or "admin"
        change=reverse(f"{namespace}:{a}_{m}_change", args=[pk])
        delete=reverse(f"{namespace}:{a}_{m}_delete", args=[pk])
        soft=reverse(f"{namespace}:{a}_{m}_soft_toggle", args=[pk])
        clone=reverse(f"{namespace}:{a}_{m}_clone", args=[pk])
        parts=[f'<a class="button" href="{change}">تعديل</a>']
        if hasattr(obj,"is_deleted"): parts.append(f'<a class="button" href="{soft}">{"استرجاع" if obj.is_deleted else "أرشفة"}</a>')
        parts.append(f'<a class="button" style="background:#d9534f;color:#fff" href="{delete}">حذف</a>')
        parts.append(f'<a class="button" style="background:#5bc0de;color:#fff" href="{clone}">نسخ</a>')
        return format_html(" ".join(parts))
    row_actions.short_description="إجراءات"
    def get_urls(self):
        urls=super().get_urls()
        def wrap(v): 
            def w(*a,**k): return self.admin_site.admin_view(v)(*a,**k)
            return w
        a=self.model._meta.app_label; m=self.model._meta.model_name
        custom=[
            re_path(rf"^(?P<object_id>.+)/soft-toggle/$", wrap(self._soft_toggle_view), name=f"{a}_{m}_soft_toggle"),
            re_path(rf"^(?P<object_id>.+)/clone/$", wrap(self._clone_view), name=f"{a}_{m}_clone"),
        ]
        return custom+urls
    def _soft_toggle_view(self, request, object_id):
        obj=self.get_object(request, object_id)
        if not obj: return redirect("..")
        if not hasattr(obj,"is_deleted"): return redirect("..")
        obj.is_deleted = not obj.is_deleted
        if hasattr(obj,"deleted_at"): obj.deleted_at = (None if not obj.is_deleted else timezone.now())
        if hasattr(obj,"deleted_by"): obj.deleted_by = (None if not obj.is_deleted else getattr(request,"user",None))
        obj.save()
        return redirect("..")
    def _clone_view(self, request, object_id):
        obj=self.get_object(request, object_id)
        if not obj: return redirect("..")
        # Instead of creating immediately (which may violate unique constraints),
        # redirect to the add form prefilled with current values so the user can adjust.
        params = {}
        for f in obj._meta.get_fields():
            if not getattr(f, "concrete", False):
                continue
            if getattr(f, "primary_key", False) or getattr(f, "many_to_many", False):
                continue
            # Skip auto-managed timestamps and soft-delete flags
            if f.name in {"created_at", "updated_at", "deleted_at", "deleted_by", "is_deleted"}:
                continue
            # Avoid directly pre-filling unique fields to reduce collisions
            if getattr(f, "unique", False):
                continue
            try:
                if isinstance(f, models.ForeignKey):
                    params[f.name] = getattr(obj, f.attname)
                else:
                    val = getattr(obj, f.attname if hasattr(f, "attname") else f.name)
                    if val is not None:
                        params[f.name] = val
            except Exception:
                pass
        namespace = getattr(self.admin_site, "name", "admin") or "admin"
        add_url = reverse(f"{namespace}:{self.model._meta.app_label}_{self.model._meta.model_name}_add")
        if params:
            return redirect(f"{add_url}?{urlencode(params, doseq=True)}")
        return redirect(add_url)

class CoreBaseAdmin(UUIDReadonlyAdminMixin, TimeStampedAdminMixin, RowActionsMixin, admin.ModelAdmin):
    list_per_page=50
    def get_list_display(self, request):
        base=list(super().get_list_display(request))
        if "row_actions" not in base: base.append("row_actions")
        return base

class CoreSoftDeletableAdmin(SoftDeleteAdminMixin, CoreBaseAdmin):
    def get_list_display(self, request):
        base=list(super().get_list_display(request))
        if hasattr(self.model,"is_deleted") and "is_deleted_badge" not in base: base.insert(0,"is_deleted_badge")
        return base

def register_with_core(site, model, *, soft=False, **admin_kwargs):
    Base = CoreSoftDeletableAdmin if soft else CoreBaseAdmin
    AdminCls = type(f"{model.__name__}Admin", (Base,), admin_kwargs)
    site.register(model, AdminCls)

# Register your models here.
