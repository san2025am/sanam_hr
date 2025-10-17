
import base64, os
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.contrib import messages
from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone
from weasyprint import HTML, CSS
from django.core.files import File
from django.db import transaction, IntegrityError
from django.contrib.auth import get_user_model

from .forms import JobApplicationForm, EmployeeEducationForm, ContractForm
from .models import JobApplication
from api_guard.models import  Employee, AdditionalQualification, Contract, Role
from core.emailer import send_email_otp
from django.http import JsonResponse, HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt  # سنستخدمه لنداء fetch العام



@require_http_methods(["GET", "POST"])
def job_application_create(request):
    if request.method == "POST":
        form = JobApplicationForm(request.POST, request.FILES)
        if form.is_valid():
            app = form.save()
            from django.contrib import messages
            messages.success(request, "تم استلام طلبك بنجاح. سنقوم بالتواصل معك قريبًا.")
            return redirect("job_application_success")
        else:
            from django.contrib import messages
            messages.error(request, "تعذّر إرسال الطلب. فضلاً راجع البيانات المظللة.")
    else:
        form = JobApplicationForm()
    return render(request, "hr/job_application_form.html", {"form": form})


def job_application_success(request):
    return render(request, "hr/job_application_success.html")


@login_required
@require_http_methods(["GET", "POST"])
def employee_education_update(request, employee_id):
    employee = get_object_or_404(Employee, pk=employee_id)
    if request.method == "POST":
        form = EmployeeEducationForm(request.POST, request.FILES, instance=employee)
        extra_files = request.FILES.getlist("extra_files")
        titles = request.POST.getlist("extra_titles")
        dates = request.POST.getlist("extra_dates")
        if form.is_valid():
            form.save()
            for idx, f in enumerate(extra_files):
                title = (titles[idx] if idx < len(titles) else "مؤهل إضافي") or "مؤهل إضافي"
                date = (dates[idx] if idx < len(dates) else None) or None
                aq = AdditionalQualification(employee=employee, title=title, file=f)
                if date:
                    try:
                        aq.issued_at = date
                    except Exception:
                        pass
                aq.save()
            messages.success(request, "تم تحديث بيانات المؤهل والمرفقات بنجاح.")
            return redirect("employee_education_update", employee_id=employee.id)
    else:
        form = EmployeeEducationForm(instance=employee)
    extras = employee.extra_quals.all()
    return render(request, "hr/employee_education_form.html", {"form": form, "employee": employee, "extras": extras})


@login_required
@require_http_methods(["GET", "POST"])
def contract_create(request):
    if request.method == "POST":
        form = ContractForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            messages.success(request, "تم إنشاء/رفع العقد بنجاح.")
            return redirect("contract_create")
    else:
        form = ContractForm()
    return render(request, "hr/contract_form.html", {"form": form})


@login_required
@require_http_methods(["GET"])
def contract_sign(request, pk):
    contract = get_object_or_404(Contract, pk=pk)
    # لا تسمح بتوقيع الموظف قبل توقيع الإدارة
    if not contract.signed_by_company:
        return HttpResponseForbidden("لم يتم توقيع الإدارة بعد. الرجاء انتظار توقيع الإدارة.")
    return render(request, "hr/contract_sign.html", {"contract": contract})


@login_required
@require_http_methods(["POST"])
def contract_sign_submit(request, pk):
    contract = get_object_or_404(Contract, pk=pk)
    data_url = request.POST.get("signature_data")
    if not data_url or not data_url.startswith("data:image/png;base64,"):
        return JsonResponse({"ok": False, "detail": "صيغة التوقيع غير صالحة."}, status=400)

    b64 = data_url.split(',', 1)[1]
    raw = base64.b64decode(b64)
    ts = timezone.now().strftime("%Y%m%d%H%M%S")
    sig_name = f"signature_{contract.pk}_{ts}.png"
    sig_dir = os.path.join(settings.MEDIA_ROOT, "contracts", "signatures")
    os.makedirs(sig_dir, exist_ok=True)
    sig_path = os.path.join(sig_dir, sig_name)
    with open(sig_path, "wb") as f:
        f.write(raw)

    with open(sig_path, "rb") as f:
        contract.signature_image.save(sig_name, File(f), save=False)

    contract.mark_signed()

    html_str = render_to_string("hr/contract_pdf_template.html", {
        "contract": contract,
        "company_name": "شركة سنام للأمن",
        "employee_name": getattr(contract.employee, 'full_name', ''),
        "company_signature_url": getattr(contract.company_signature_image, 'url', None),
        "company_signed_at": contract.company_signed_at,
        "company_signer_name": (getattr(getattr(contract, 'company_signed_by', None), 'employee', None).full_name
                                  if getattr(getattr(contract, 'company_signed_by', None), 'employee', None)
                                  else (getattr(getattr(contract, 'company_signed_by', None), 'get_full_name', lambda: '')() or getattr(getattr(contract, 'company_signed_by', None), 'username', None))),
        "employee_signature_url": getattr(contract.signature_image, 'url', None),
        "employee_signed_at": contract.signed_at,
    })

    pdf_name = f"contract_{contract.pk}_signed_{ts}.pdf"
    pdf_dir = os.path.join(settings.MEDIA_ROOT, "contracts", "signed")
    os.makedirs(pdf_dir, exist_ok=True)
    pdf_path = os.path.join(pdf_dir, pdf_name)

    HTML(string=html_str, base_url=request.build_absolute_uri('/')).write_pdf(pdf_path, stylesheets=[
        CSS(string='@page { size: A4; margin: 20mm; } body { font-family: "Tajawal", Arial, sans-serif; }')
    ])

    with open(pdf_path, "rb") as f:
        contract.signed_pdf.save(pdf_name, File(f), save=False)
    contract.save(update_fields=["signature_image", "signed_pdf"])

    # مزامنة الراتب مع جدول الرواتب بعد التوقيع
    try:
        from api_guard.models import Salary
        sal, _ = Salary.objects.get_or_create(employee=contract.employee)
        if contract.salary is not None:
            sal.base_salary = contract.salary
            sal.save(update_fields=["base_salary", "updated_at"]) if hasattr(sal, 'updated_at') else sal.save()
    except Exception:
        pass

    # بعد توقيع العقد: أنشئ/حدّث بيانات دخول تطبيق الحارس + أرسل بريدًا بالبيانات
    try:
        _onboard_employee_for_guard_app(contract.employee)
    except Exception:
        # لا تفشل العملية الأساسية عند فشل البريد/التحديث
        pass

    messages.success(request, "تم توقيع العقد وتوليد نسخة PDF بنجاح.")
    return JsonResponse({"ok": True, "pdf_url": contract.signed_pdf.url})



def _validate_token_or_403(contract: Contract, token: str):
    if not contract.sign_token or not token or token != contract.sign_token:
        return False
    if contract.sign_token_expires_at and timezone.now() > contract.sign_token_expires_at:
        return False
    if contract.signed_by_employee:
        # تم التوقيع مسبقًا – امنع إعادة الاستخدام
        return False
    return True

@require_http_methods(["GET"])
def contract_sign_public(request, pk, token):
    contract = get_object_or_404(Contract, pk=pk)
    if not _validate_token_or_403(contract, token):
        return HttpResponseForbidden("الرابط غير صالح أو منتهي الصلاحية.")
    if not contract.signed_by_company:
        return HttpResponseForbidden("لم يتم توقيع الإدارة بعد. الرجاء انتظار توقيع الإدارة.")
    # نفس القالب المستخدم مع تسجيل الدخول:
    return render(request, "hr/contract_sign.html", {"contract": contract, "public_token": token, "is_public": True})

@csrf_exempt   # لأننا لا نعتمد جلسة/CSRF هنا، سنعتمد على التوكن والمهلة
@require_http_methods(["POST"])
def contract_sign_public_submit(request, pk, token):
    contract = get_object_or_404(Contract, pk=pk)
    if not _validate_token_or_403(contract, token):
        return JsonResponse({"ok": False, "detail": "الرابط غير صالح أو منتهي."}, status=403)

    data_url = request.POST.get("signature_data")
    if not data_url or not data_url.startswith("data:image/png;base64,"):
        return JsonResponse({"ok": False, "detail": "صيغة التوقيع غير صالحة."}, status=400)

    # حفظ صورة التوقيع
    b64 = data_url.split(",", 1)[1]
    raw = base64.b64decode(b64)
    ts = timezone.now().strftime("%Y%m%d%H%M%S")
    sig_name = f"signature_{contract.pk}_{ts}.png"
    sig_dir = os.path.join(settings.MEDIA_ROOT, "contracts", "signatures")
    os.makedirs(sig_dir, exist_ok=True)
    sig_path = os.path.join(sig_dir, sig_name)
    with open(sig_path, "wb") as f:
        f.write(raw)
    with open(sig_path, "rb") as f:
        contract.signature_image.save(sig_name, File(f), save=False)

    # علّم العقد موقّع + أبطل الرابط العام حتى لا يُستخدم مجددًا
    contract.mark_signed()
    contract.sign_token = None
    contract.sign_token_expires_at = None

    # توليد PDF
    html_str = render_to_string("hr/contract_pdf_template.html", {
        "contract": contract,
        "company_name": "شركة سنام للأمن",
        "employee_name": getattr(contract.employee, 'full_name', ''),
        "company_signature_url": getattr(contract.company_signature_image, 'url', None),
        "company_signed_at": contract.company_signed_at,
        "company_signer_name": (getattr(getattr(contract, 'company_signed_by', None), 'employee', None).full_name
                                  if getattr(getattr(contract, 'company_signed_by', None), 'employee', None)
                                  else (getattr(getattr(contract, 'company_signed_by', None), 'get_full_name', lambda: '')() or getattr(getattr(contract, 'company_signed_by', None), 'username', None))),
        "employee_signature_url": getattr(contract.signature_image, 'url', None),
        "employee_signed_at": contract.signed_at,
    })
    pdf_name = f"contract_{contract.pk}_signed_{ts}.pdf"
    pdf_dir = os.path.join(settings.MEDIA_ROOT, "contracts", "signed")
    os.makedirs(pdf_dir, exist_ok=True)
    pdf_path = os.path.join(pdf_dir, pdf_name)
    HTML(string=html_str, base_url=request.build_absolute_uri('/')).write_pdf(
        pdf_path,
        stylesheets=[CSS(string='@page { size: A4; margin: 20mm; } body { font-family: "Tajawal", Arial, sans-serif; }')]
    )
    with open(pdf_path, "rb") as f:
        contract.signed_pdf.save(pdf_name, File(f), save=False)
    contract.save(update_fields=["signature_image", "signed_pdf", "sign_token", "sign_token_expires_at"])

    # بعد توقيع العقد: أنشئ/حدّث بيانات دخول تطبيق الحارس + أرسل بريدًا بالبيانات
    try:
        _onboard_employee_for_guard_app(contract.employee)
    except Exception:
        pass

    return JsonResponse({"ok": True, "pdf_url": contract.signed_pdf.url})


# ===== توقيع الإدارة (داخل النظام) =====
@login_required
@require_http_methods(["GET"])
def contract_company_sign(request, pk):
    contract = get_object_or_404(Contract, pk=pk)
    return render(request, "hr/contract_sign.html", {"contract": contract, "is_company": True})


@login_required
@require_http_methods(["POST"])
def contract_company_sign_submit(request, pk):
    contract = get_object_or_404(Contract, pk=pk)
    data_url = request.POST.get("signature_data")
    if not data_url or not data_url.startswith("data:image/png;base64,"):
        return JsonResponse({"ok": False, "detail": "صيغة التوقيع غير صالحة."}, status=400)

    b64 = data_url.split(',', 1)[1]
    raw = base64.b64decode(b64)
    ts = timezone.now().strftime("%Y%m%d%H%M%S")
    sig_name = f"company_signature_{contract.pk}_{ts}.png"
    sig_dir = os.path.join(settings.MEDIA_ROOT, "contracts", "company_signatures")
    os.makedirs(sig_dir, exist_ok=True)
    sig_path = os.path.join(sig_dir, sig_name)
    with open(sig_path, "wb") as f:
        f.write(raw)
    with open(sig_path, "rb") as f:
        contract.company_signature_image.save(sig_name, File(f), save=False)

    contract.mark_company_signed(user=request.user)
    contract.save(update_fields=["company_signature_image"])  # الحقل حُدّث أعلاه

    # جدد ملف PDF بالعقد ممهورًا بتوقيع الإدارة (قبل توقيع الموظف)
    try:
        html_str = render_to_string(
            "hr/contract_pdf_template.html",
            {
                "contract": contract,
                "company_name": "شركة سنام للأمن",
                "employee_name": getattr(contract.employee, 'full_name', ''),
                "company_signature_url": getattr(contract.company_signature_image, 'url', None),
                "company_signed_at": contract.company_signed_at,
                "company_signer_name": (getattr(getattr(contract, 'company_signed_by', None), 'employee', None).full_name
                                          if getattr(getattr(contract, 'company_signed_by', None), 'employee', None)
                                          else (getattr(getattr(contract, 'company_signed_by', None), 'get_full_name', lambda: '')() or getattr(getattr(contract, 'company_signed_by', None), 'username', None))),
                "employee_signature_url": getattr(contract.signature_image, 'url', None),
                "employee_signed_at": contract.signed_at,
            },
        )
        ts2 = timezone.now().strftime("%Y%m%d%H%M%S")
        pdf_dir2 = os.path.join(settings.MEDIA_ROOT, "contracts", "company_signed")
        os.makedirs(pdf_dir2, exist_ok=True)
        pdf_name2 = f"contract_{contract.pk}_company_signed_{ts2}.pdf"
        pdf_path2 = os.path.join(pdf_dir2, pdf_name2)
        HTML(string=html_str, base_url=request.build_absolute_uri('/')).write_pdf(
            pdf_path2,
            stylesheets=[CSS(string='@page { size: A4; margin: 20mm; } body { font-family: "Tajawal", Arial, sans-serif; }')]
        )
        with open(pdf_path2, "rb") as f:
            contract.file.save(pdf_name2, File(f), save=True)
    except Exception:
        pass

    messages.success(request, "تم توقيع الإدارة على العقد.")
    return JsonResponse({"ok": True, "company_signed": True})


# ===== Onboarding helper: create username/password and email them =====
def _random_password(length: int = 10) -> str:
    import secrets, string
    # مزيج أحرف كبيرة/صغيرة + أرقام لتجاوز محقق كلمات المرور
    alphabet = string.ascii_letters + string.digits
    while True:
        pw = ''.join(secrets.choice(alphabet) for _ in range(max(8, length)))
        # تضمن احتواءها على نوعين على الأقل
        if (any(c.islower() for c in pw) and any(c.isupper() for c in pw) and any(c.isdigit() for c in pw)):
            return pw


def _onboard_employee_for_guard_app(employee: Employee) -> None:
    if not employee or not getattr(employee, 'user', None):
        return
    user = employee.user
    # أنشئ اسم مستخدم بصيغة sa + 6 أرقام عشوائية
    def _random_guard_username() -> str:
        import secrets, string
        digits = string.digits
        return 'sa' + ''.join(secrets.choice(digits) for _ in range(6))

    UserModel = get_user_model()
    desired_username = None
    # حاول عدة مرات لضمان التفرد
    for _ in range(10):
        candidate = _random_guard_username()
        if not UserModel.objects.filter(username__iexact=candidate).exists():
            desired_username = candidate
            break
    if desired_username is None:
        # احتمال نادر جدًا: فشل جميع المحاولات؛ استخدم آخر مرشح (قد يصطدم ونعيد المحاولة في except)
        desired_username = _random_guard_username()

    # حدّث اسم المستخدم إلى رقم التوظيف إن لزم
    try:
        with transaction.atomic():
            if desired_username and user.username != desired_username:
                user.username = desired_username
            # عيّن دور حارس أمن إن لم يكن معيّنًا
            if not getattr(user, 'role_id', None):
                try:
                    guard_role = Role.objects.filter(name='guard').first()
                    if guard_role:
                        user.role = guard_role
                except Exception:
                    pass
            # أنشئ كلمة مرور مؤقتة
            temp_pw = _random_password(12)
            user.set_password(temp_pw)
            user.save()
    except IntegrityError:
        # في حال اصطدام اسم المستخدم، أعِد توليده وجرب مرة إضافية
        with transaction.atomic():
            for _ in range(5):
                alt = _random_guard_username()
                if not UserModel.objects.filter(username__iexact=alt).exists():
                    user.username = alt
                    break
            if not getattr(user, 'role_id', None):
                try:
                    guard_role = Role.objects.filter(name='guard').first()
                    if guard_role:
                        user.role = guard_role
                except Exception:
                    pass
            temp_pw = _random_password(12)
            user.set_password(temp_pw)
            user.save()

    # حضّر نص البريد
    to_email = (user.email or '').strip()
    if not to_email:
        # لا يوجد بريد—لا ترسل شيئًا
        return

    from django.conf import settings
    app_link_lines = []
    if getattr(settings, 'GUARD_APP_DOWNLOAD_URL', ''):
        app_link_lines.append(f"رابط التطبيق: {settings.GUARD_APP_DOWNLOAD_URL}")
    if getattr(settings, 'GUARD_APP_ANDROID_URL', ''):
        app_link_lines.append(f"أندرويد: {settings.GUARD_APP_ANDROID_URL}")
    if getattr(settings, 'GUARD_APP_IOS_URL', ''):
        app_link_lines.append(f"iOS: {settings.GUARD_APP_IOS_URL}")
    if not app_link_lines:
        # كمل بموقع الشركة إن وُجد
        site_url = getattr(settings, 'SITE_URL', '') or ''
        if site_url:
            app_link_lines.append(f"الموقع: {site_url}")

    subject = "بيانات الدخول إلى تطبيق الحارس — سنام الأمن"
    body_lines = [
        f"مرحبًا {employee.full_name},",
        "\nتم توثيق عقد عملك بنجاح.",
        "\nبيانات الدخول إلى تطبيق الحارس:",
        f"اسم المستخدم: {user.username}",
        f"كلمة المرور المؤقتة: {temp_pw}",
        "\nيرجى تغيير كلمة المرور بعد تسجيل الدخول.",
    ]
    if app_link_lines:
        body_lines.extend(["\nروابط التحميل:", *app_link_lines])
    body = "\n".join(body_lines)

    # أرسل البريد (ستتم طباعة المحتوى في السجلات إذا لم تُضبط إعدادات SMTP وكان DEBUG_SMS_ECHO مفعلًا)
    try:
        send_email_otp(to_email, subject, body)
    except Exception:
        # لا ترفع الاستثناء حتى لا تعطل تجربة التوقيع
        pass
    # مزامنة الراتب مع جدول الرواتب بعد التوقيع
    try:
        from api_guard.models import Salary
        sal, _ = Salary.objects.get_or_create(employee=contract.employee)
        if contract.salary is not None:
            sal.base_salary = contract.salary
            sal.save(update_fields=["base_salary", "updated_at"]) if hasattr(sal, 'updated_at') else sal.save()
    except Exception:
        pass
