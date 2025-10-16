from django.contrib import admin, messages
from django.utils.html import format_html
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, path
from django import forms
from django.contrib.auth import get_user_model

from hr.utils.contracts import build_public_sign_url, one_year_period, render_contract_body, send_contract_email
from hr.utils.notifications import send_status_email

from .models import JobApplication
from api_guard.models import Contract, Employee, Role

class JobApplicationAdminForm(forms.ModelForm):
    send_email_now = forms.BooleanField(
        required=False,
        label="إرسال إيميل تحديث الحالة الآن",
        help_text="يرسل رسالة للمتقدم حسب الحالة الجديدة (قيد المراجعة/مقبول/مرفوض)."
    )
    class Meta:
        model = JobApplication
        fields = "__all__"

@admin.register(JobApplication)
class JobApplicationAdmin(admin.ModelAdmin):
    form = JobApplicationAdminForm
    list_display = (
        "full_name", "position", "status", "created_at",
        "email", "employee", "quick_actions",
    )
    list_filter = ("position", "status")
    search_fields = ("full_name", "national_id", "phone", "email")
    actions = [
        "send_status_email_action",
        "create_year_contract_and_send_link",
        "prepare_employee_and_goto_contract",
    ]

    # عمود إجراءات سريعة
    def quick_actions(self, obj):
        # فتح إضافة عقد في تطبيق api_guard وتمرير employee إن كان موجود
        if obj.employee_id:
            add_url = reverse("admin:api_guard_contract_add") + f"?employee={obj.employee_id}"
            return format_html('<a href="{}" class="button" target="_blank">➕ عقد جديد</a>', add_url)
        return "—"
    quick_actions.short_description = "إجراءات سريعة"

    # حفظ النموذج: إنشاء/ربط الموظف عند قبول + إرسال إيميل اختياري
    def save_model(self, request, obj, form, change):
        status_changed = False
        old_status = None
        if change:
            old = JobApplication.objects.get(pk=obj.pk)
            old_status = old.status
            status_changed = (old.status != obj.status)

        super().save_model(request, obj, form, change)

        # عند التحويل إلى "مقبول": اربط الموظف أو أنشئه إذا لم يكن موجودًا
        if status_changed and obj.status == JobApplication.Status.ACCEPTED:
            emp = obj.employee or Employee.objects.filter(national_id=obj.national_id).first()
            if not emp:
                # أنشئ User + Employee من بيانات الطلب
                UserModel = get_user_model()
                # توليد اسم مستخدم بصيغة sa+6 أرقام بشكل فريد
                import secrets, string
                def _gen_username():
                    return 'sa' + ''.join(secrets.choice(string.digits) for _ in range(6))
                username = None
                for _ in range(10):
                    cand = _gen_username()
                    if not UserModel.objects.filter(username__iexact=cand).exists():
                        username = cand
                        break
                if username is None:
                    username = _gen_username()

                user = UserModel.objects.create(
                    username=username,
                    email=(obj.email or '').strip(),
                )
                # عيّن دور الحارس إن وُجد
                try:
                    guard_role = Role.objects.filter(name='guard').first()
                    if guard_role:
                        user.role = guard_role
                        user.save(update_fields=['role'])
                except Exception:
                    pass

                # أنشئ سجل الموظف
                emp = Employee.objects.create(
                    user=user,
                    full_name=obj.full_name,
                    national_id=obj.national_id,
                    phone_number=obj.phone,
                )
                obj.employee = emp
                obj.save(update_fields=["employee"])
            if obj.employee_id:
                add_url = reverse("admin:api_guard_contract_add") + f"?employee={obj.employee.pk}"
                self.message_user(
                    request,
                    format_html(
                        "تم ربط الطلب بالموظف <strong>{}</strong>. "
                        '<a href="{}" target="_blank">⬅️ إضافة عقد جديد لهذا الموظف</a>',
                        obj.employee.full_name, add_url
                    )
                )

        # إرسال إيميل الحالة عند الطلب (المربع)
        if form.cleaned_data.get("send_email_now"):
            ok = send_status_email(obj)
            if ok:
                self.message_user(request, "تم إرسال البريد بنجاح.")
            else:
                self.message_user(request, "تعذّر الإرسال (لا يوجد بريد أو حالة غير مدعومة).")

    # إجراء: إرسال إيميل الحالة للطلبات المحددة
    def send_status_email_action(self, request, queryset):
        sent, skipped = 0, 0
        for app in queryset:
            if send_status_email(app):
                sent += 1
            else:
                skipped += 1
        self.message_user(request, f"تم إرسال {sent} رسالة، وتخطّي {skipped}.")
    send_status_email_action.short_description = "إرسال إيميل تحديث الحالة"

    # إجراء: إنشاء عقد سنة + رابط توقيع + إرسال الرابط
    def create_year_contract_and_send_link(self, request, queryset):
        ok, fail = 0, 0
        for app in queryset:
            try:
                # 1) يجب أن يكون الموظف مرتبطًا مسبقًا
                emp = app.employee or Employee.objects.filter(national_id=app.national_id).first()
                if not emp:
                    self.message_user(request, f"لا يمكن إنشاء عقد: لا يوجد موظف مرتبط/مطابق لطلب {app.pk}", level=messages.ERROR)
                    fail += 1
                    continue
                
                # 2) عقد سنة
                start_date, end_date = one_year_period()
                body = render_contract_body(emp)
                contract = Contract.objects.create(
                    employee=emp,
                    title="عقد عمل - حارس أمن (سنة)",
                    contract_type="سنوي",
                    start_date=start_date,
                    end_date=end_date,
                    salary=0,   # عدّل الراتب لاحقًا أو أضف حقل إدخال
                    body=body,
                )

                # 3) توليد رابط توقيع عام 72 ساعة
                contract.generate_sign_link(hours_valid=72)
                link = build_public_sign_url(contract)

                # 4) إرسال الإيميل باللينك (إن وُجد بريد)
                if app.email:
                    send_contract_email(app.email, emp.full_name, link)

                ok += 1
            except Exception:
                fail += 1
        self.message_user(request, f"تم إنشاء وإرسال {ok} عقد/روابط. فشل {fail}.")
    create_year_contract_and_send_link.short_description = "إنشاء عقد سنة + إرسال رابط التوقيع"

    # إجراء: تهيئة موظف وفتح صفحة إضافة عقد
    def prepare_employee_and_goto_contract(self, request, queryset):
        obj = queryset.first()
        if not obj:
            self.message_user(request, "اختر طلبًا واحدًا.", level="error")
            return
        if queryset.count() > 1:
            self.message_user(request, "اختر طلبًا واحدًا فقط لهذا الإجراء.", level="error")
            return

        emp = obj.employee or Employee.objects.filter(national_id=obj.national_id).first()
        if not emp:
            self.message_user(request, "لا يوجد موظف مرتبط أو مطابق لرقم الهوية. اربط الطلب أولاً.", level="error")
            return
        add_url = reverse("admin:api_guard_contract_add") + f"?employee={emp.pk}"
        self.message_user(request, format_html('جاهز! <a href="{}" target="_blank">فتح صفحة إضافة عقد</a>', add_url))
    prepare_employee_and_goto_contract.short_description = "تهيئة الموظف وفتح صفحة إضافة عقد"
     
